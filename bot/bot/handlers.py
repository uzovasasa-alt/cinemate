import re
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .api import Api, BotApiError
from .format import (HELP, NOT_LINKED, STATUS_RU, candidates_text, card_text, link_result_text, stats_text,
                     title_line)

router = Router()
CODE_IN_TEXT = re.compile(r"^\s*(?:/start\s+)?(LINK-[A-Za-z0-9]{8})\s*$", re.I)


class ReviewState(StatesGroup):
    waiting = State()


def _tg(m: Message | CallbackQuery) -> int:
    return m.from_user.id


async def _call(api: Api, target: Message, path: str, **payload):
    """Вызов API с единообразной обработкой ошибок. Возвращает None, если ответ пользователю уже отправлен."""
    try:
        return await api.post(path, **payload)
    except BotApiError as e:
        if e.not_linked:
            await target.answer(NOT_LINKED)
        elif e.status in (429, 503, 502):
            await target.answer("⏳ " + escape(e.message))
        elif e.status == 400:
            await target.answer("⚠️ " + escape(e.message))
        else:
            await target.answer("Что-то пошло не так, попробуйте ещё раз чуть позже.")
        return None


def status_keyboard(content_id: int, is_serial: bool):
    kb = InlineKeyboardBuilder()
    for code in ("plan", "watching", "watched", "later", "dropped"):
        kb.button(text=STATUS_RU[code], callback_data=f"st:{content_id}:{code}")
    for n in range(1, 6):
        kb.button(text="★" * n, callback_data=f"rt:{content_id}:{n}")
    kb.button(text="✍️ Рецензия", callback_data=f"rv:{content_id}")
    rows = [3, 2, 5, 1]
    if is_serial:
        kb.button(text="+1 серия", callback_data=f"ep:{content_id}")
        rows = [3, 2, 5, 2]
    kb.adjust(*rows)
    return kb.as_markup()


async def send_card(target: Message, card: dict, content_id: int, prefix: str = ""):
    text = prefix + card_text(card, mine_status=card.get("status"))
    kb = status_keyboard(content_id, bool(card.get("is_serial")))
    if card.get("poster_url"):
        try:
            await target.answer_photo(card["poster_url"], caption=text[:1024], reply_markup=kb)
            return
        except TelegramBadRequest:
            pass          # CDN постера недоступен для Telegram — отправим текстом
    await target.answer(text, reply_markup=kb)


# ---------- привязка ----------

async def _link(message: Message, api: Api, code: str):
    r = await _call(api, message, "/telegram/link", code=code, telegram_id=_tg(message),
                    chat_id=message.chat.id, username=message.from_user.username)
    if r:
        await message.answer(link_result_text(r["status"], r.get("name")))


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, api: Api):
    if command.args:
        return await _link(message, api, command.args.strip())
    await message.answer("Привет! Я Cinemate — помогаю вести каталог фильмов и сериалов.\n\n"
                         "Чтобы начать, откройте сайт → «Подключить Telegram», скопируйте код и отправьте мне:\n"
                         "<code>/start LINK-XXXXXXXX</code>")


@router.message(F.text.regexp(CODE_IN_TEXT))
async def bare_code(message: Message, api: Api):
    await _link(message, api, CODE_IN_TEXT.match(message.text).group(1))


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(HELP)


# ---------- добавление и поиск ----------

async def _resolve_and_show(message: Message, api: Api, text: str):
    r = await _call(api, message, "/bot/resolve", telegram_id=_tg(message), text=text)
    if r is None:
        return
    items = r["candidates"]
    if not items:
        await message.answer("Не смог вытащить название из ссылки. Пришлите название текстом или ссылку на Кинопоиск."
                             if r.get("hint") == "no_title"
                             else "Не нашёл такой фильм в Кинопоиске. Попробуйте точнее: название и год.")
        return
    svc = (r.get("service") or "")[:30]
    suffix = f":{svc}" if svc else ""
    kb = InlineKeyboardBuilder()
    if r["exact"] and len(items) == 1:
        c = items[0]
        kb.button(text="➕ Добавить", callback_data=f"add:{c['kinopoisk_id']}{suffix}")
        kb.button(text="Отмена", callback_data="cancel")
        kb.adjust(2)
        txt = card_text(c)
        if c.get("poster_url"):
            try:
                await message.answer_photo(c["poster_url"], caption=txt[:1024], reply_markup=kb.as_markup())
                return
            except TelegramBadRequest:
                pass
        await message.answer(txt, reply_markup=kb.as_markup())
        return
    note = "Нашёл по ссылке похожее, выберите нужное:" if r.get("guessed") else "Нашёл, выберите нужное:"
    for i, c in enumerate(items, 1):
        label = f"➕ {i}. {c['title'][:28]}" + (f" ({c['year']})" if c.get("year") else "")
        kb.button(text=label, callback_data=f"add:{c['kinopoisk_id']}{suffix}")
    kb.adjust(1)
    await message.answer(candidates_text(items, note), reply_markup=kb.as_markup())


@router.message(Command("add"))
async def add_cmd(message: Message, command: CommandObject, api: Api):
    if not command.args:
        return await message.answer("Пришлите название или ссылку: <code>/add Матрица</code>")
    await _resolve_and_show(message, api, command.args)


@router.message(Command("search"))
async def search_cmd(message: Message, command: CommandObject, api: Api):
    if not command.args:
        return await message.answer("Что искать? <code>/search матрица</code>")
    mine = await _call(api, message, "/bot/library", telegram_id=_tg(message), q=command.args)
    if mine is None:
        return
    if mine:
        lines = ["<b>В вашей медиатеке:</b>"] + [
            f"• {title_line(m)} — {STATUS_RU.get(m['status_code'], '')}" for m in mine]
        await message.answer("\n".join(lines))
    await _resolve_and_show(message, api, command.args)


@router.callback_query(F.data.startswith("add:"))
async def add_cb(cb: CallbackQuery, api: Api):
    parts = cb.data.split(":", 2)
    await cb.answer("Добавляю…")
    r = await _call(api, cb.message, "/bot/add", telegram_id=_tg(cb), kinopoisk_id=int(parts[1]),
                    service=parts[2] if len(parts) > 2 else None)
    if r is None:
        return
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    prefix = "✅ Добавлено\n\n" if r["created"] else "ℹ️ Уже в вашей медиатеке\n\n"
    await send_card(cb.message, r["card"], r["content_id"], prefix)


@router.callback_query(F.data == "cancel")
async def cancel_cb(cb: CallbackQuery):
    await cb.answer("Отменено")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass


# ---------- статус, оценка, серия, рецензия ----------

@router.callback_query(F.data.startswith("st:"))
async def status_cb(cb: CallbackQuery, api: Api):
    _, cid, code = cb.data.split(":")
    r = await _call(api, cb.message, "/bot/status", telegram_id=_tg(cb), content_id=int(cid), status=code)
    await cb.answer(f"Статус: {STATUS_RU[code]}" if r else "Не получилось")


@router.callback_query(F.data.startswith("rt:"))
async def rate_cb(cb: CallbackQuery, api: Api):
    _, cid, n = cb.data.split(":")
    r = await _call(api, cb.message, "/bot/rate", telegram_id=_tg(cb), content_id=int(cid), stars=int(n))
    await cb.answer("Оценка " + "★" * int(n) if r else "Не получилось")


@router.callback_query(F.data.startswith("ep:"))
async def episode_cb(cb: CallbackQuery, api: Api):
    r = await _call(api, cb.message, "/bot/episode", telegram_id=_tg(cb), content_id=int(cb.data.split(":")[1]))
    if r:
        tot = r["total_episodes"] or "?"
        await cb.answer(f"Серия {r['watched_eps']} из {tot}" + (" — досмотрели!" if r["status"] == "watched" else ""))
    else:
        await cb.answer("Не получилось")


@router.callback_query(F.data.startswith("rv:"))
async def review_cb(cb: CallbackQuery, state: FSMContext):
    await state.set_state(ReviewState.waiting)
    await state.update_data(content_id=int(cb.data.split(":")[1]))
    await cb.answer()
    await cb.message.answer("Напишите рецензию одним сообщением (или /cancel).")


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")


@router.message(ReviewState.waiting, F.text, ~F.text.startswith("/"))
async def review_text(message: Message, state: FSMContext, api: Api):
    cid = (await state.get_data()).get("content_id")
    await state.clear()
    r = await _call(api, message, "/bot/review", telegram_id=_tg(message), content_id=cid, text=message.text)
    if r:
        await message.answer("Рецензия сохранена ✍️")


# ---------- прочее ----------

@router.message(Command("stats"))
async def stats_cmd(message: Message, api: Api):
    s = await _call(api, message, "/bot/stats", telegram_id=_tg(message))
    if s is not None:
        await message.answer(stats_text(s))


@router.message(Command("random"))
async def random_cmd(message: Message, api: Api):
    r = await _call(api, message, "/bot/random", telegram_id=_tg(message))
    if r is None:
        return
    it = r["item"]
    if not it:
        return await message.answer("В «Планах» пока пусто — добавьте что-нибудь!")
    await message.answer("🎲 Сегодня можно посмотреть:\n" + title_line(it) + (f" · ★{it['rating_kp']}" if it.get("rating_kp") else ""))


@router.message(Command("mood"))
async def mood_cmd(message: Message):
    await message.answer("Подбор по настроению (AI) подключается на следующем этапе. "
                         "Пока можно воспользоваться /random.")


@router.message(Command("remind"))
async def remind_cmd(message: Message, command: CommandObject, api: Api):
    days = None
    if command.args:
        if not command.args.strip().isdigit() or not 1 <= int(command.args) <= 365:
            return await message.answer("Укажите число дней от 1 до 365: <code>/remind 14</code>")
        days = int(command.args)
    r = await _call(api, message, "/bot/settings", telegram_id=_tg(message), remind_inactive_days=days)
    if r:
        d = r["settings"].get("remind_inactive_days", 14)
        await message.answer(f"Напоминаю о недосмотренных сериалах, если вы не смотрели их {d} дн. "
                             f"Изменить: <code>/remind 7</code>.\nЗапланированных напоминаний: {r['pending_reminders']}.")


@router.message(F.text & ~F.text.startswith("/"))
async def free_text(message: Message, api: Api):
    await _resolve_and_show(message, api, message.text)
