"""Форматирование сообщений (HTML). Без зависимости от aiogram — тестируется отдельно."""
from html import escape

STATUS_RU = {"plan": "В планах", "watching": "В процессе", "watched": "Просмотрено", "dropped": "Брошено", "later": "Отложено"}
TYPE_RU = {"movie": "Фильм", "series": "Сериал", "documentary": "Документальный", "cartoon": "Мультфильм", "anime": "Аниме"}


def stars(n: int | None) -> str:
    return "★" * n + "☆" * (5 - n) if n else ""


def title_line(c: dict) -> str:
    t = escape(c["title"])
    return f"<b>{t}</b> ({c['year']})" if c.get("year") else f"<b>{t}</b>"


def card_text(c: dict, *, mine_status: str | None = None, stars_n: int | None = None) -> str:
    lines = [title_line(c)]
    if c.get("original_title"):
        lines.append(f"<i>{escape(c['original_title'])}</i>")
    meta = [TYPE_RU.get(c.get("type_code"), "Фильм")]
    if c.get("rating_kp"):
        meta.append(f"Кинопоиск {c['rating_kp']}")
    if c.get("duration_min"):
        meta.append(f"{c['duration_min']} мин")
    if c.get("is_serial") and c.get("total_episodes"):
        meta.append(f"{c['total_episodes']} серий")
    lines.append(" · ".join(meta))
    if c.get("genres"):
        lines.append(escape(", ".join(c["genres"][:4])))
    if c.get("directors"):
        lines.append("Режиссёр: " + escape(", ".join(c["directors"])))
    if c.get("actors"):
        lines.append("В ролях: " + escape(", ".join(c["actors"])))
    d = c.get("description") or c.get("short")
    if d:
        lines.append("\n" + escape(d[:350]) + ("…" if len(d) > 350 else ""))
    if mine_status:
        lines.append(f"\nСтатус: <b>{STATUS_RU.get(mine_status, mine_status)}</b>" + (f" · {stars(stars_n)}" if stars_n else ""))
    return "\n".join(lines)[:1000]       # лимит подписи к фото — 1024


def candidates_text(items: list[dict], note: str = "") -> str:
    out = [note] if note else []
    for i, c in enumerate(items, 1):
        r = f" · ★{c['rating_kp']}" if c.get("rating_kp") else ""
        g = f" · {escape(', '.join(c['genres'][:2]))}" if c.get("genres") else ""
        out.append(f"{i}. {title_line(c)}{r}{g}")
    return "\n".join(out)


def stats_text(s: dict) -> str:
    if not s["total"]:
        return "Пока пусто. Пришлите название или ссылку на фильм — я добавлю его в вашу медиатеку."
    st = s["by_status"]
    lines = [
        "<b>Ваша статистика</b>",
        f"Записей: {s['total']} · просмотрено: {st.get('watched', 0)} · в процессе: {st.get('watching', 0)} · в планах: {st.get('plan', 0)}",
        f"Часов просмотра: {s['hours']} · серий: {s['episodes_watched']}"
        + (f" · средняя оценка: {s['avg_stars']}" if s.get("avg_stars") else ""),
    ]
    if s["top_genres"]:
        lines.append("Жанры: " + escape(", ".join(f"{g['name']} ({g['n']})" for g in s["top_genres"][:5])))
    if s["top_directors"]:
        lines.append("Режиссёры: " + escape(", ".join(f"{p['name']} ({p['n']})" for p in s["top_directors"][:3])))
    if s["unfinished"]:
        lines.append("\n<b>Недосмотрено:</b>")
        for u in s["unfinished"][:5]:
            tot = u["total_episodes"] or "?"
            lines.append(f"• {escape(u['title'])} — {u['watched_eps']}/{tot}, {u['days_idle']} дн. назад")
    return "\n".join(lines)


def link_result_text(status: str, name: str | None = None) -> str:
    return {
        "linked": f"✅ Готово, {escape(name or '')}! Аккаунт привязан. Созданы статусы и коллекции: «Хочу посмотреть», «Смотрю», «Просмотрено», «Избранное».\n\nПришлите название или ссылку на фильм — добавлю в вашу медиатеку. /help — все команды.",
        "invalid": "Код не найден. Проверьте, что скопировали его полностью, или создайте новый на сайте.",
        "expired": "Срок действия кода истёк (10 минут). Создайте новый на сайте: «Подключить Telegram».",
        "used": "Этот код уже использован. Создайте новый на сайте.",
        "rate_limited": "Слишком много неверных попыток. Повторите через 15 минут.",
    }.get(status, "Не удалось привязать аккаунт.")


HELP = (
    "<b>Команды</b>\n"
    "/add название или ссылка — добавить фильм или сериал (Кинопоиск, IMDb, стриминги)\n"
    "/search запрос — поиск в вашей медиатеке и в Кинопоиске\n"
    "/random — случайный фильм из «В планах»\n"
    "/stats — статистика и недосмотренное\n"
    "/mood — подбор по настроению (скоро)\n"
    "/remind [дни] — напоминать о недосмотренных сериалах через N дней\n\n"
    "Можно просто прислать название или ссылку без команды."
)
NOT_LINKED = ("Аккаунт не привязан. Откройте сайт → «Подключить Telegram», скопируйте код "
              "и отправьте мне: <code>/start LINK-XXXXXXXX</code>")
