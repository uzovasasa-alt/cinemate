import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from .api import Api
from .config import load
from .handlers import router

COMMANDS = [
    BotCommand(command="add", description="Добавить фильм или сериал"),
    BotCommand(command="search", description="Поиск"),
    BotCommand(command="random", description="Случайный фильм из планов"),
    BotCommand(command="stats", description="Статистика"),
    BotCommand(command="mood", description="Подбор по настроению"),
    BotCommand(command="remind", description="Напоминания"),
    BotCommand(command="help", description="Помощь"),
]


def build(cfg):
    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    api = Api(cfg.api_url, cfg.internal_token)
    dp["api"] = api
    return bot, dp, api


async def run_polling(cfg):
    bot, dp, api = build(cfg)
    await bot.delete_webhook(drop_pending_updates=False)
    await bot.set_my_commands(COMMANDS)
    try:
        await dp.start_polling(bot)
    finally:
        await api.close()


def run_webhook(cfg):
    bot, dp, api = build(cfg)

    async def on_startup(bot: Bot):
        await bot.set_my_commands(COMMANDS)
        await bot.set_webhook(cfg.webhook_url, secret_token=cfg.webhook_secret,
                              allowed_updates=dp.resolve_used_update_types())

    async def on_shutdown(bot: Bot):
        await api.close()

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)
    app = web.Application()
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=cfg.webhook_secret).register(app, path=cfg.webhook_path)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host=cfg.host, port=cfg.port)


def main():
    logging.basicConfig(level=logging.INFO)
    cfg = load()
    if cfg.mode == "webhook":
        run_webhook(cfg)
    else:
        asyncio.run(run_polling(cfg))


if __name__ == "__main__":
    main()
