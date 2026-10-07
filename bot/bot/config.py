import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    token: str
    api_url: str
    internal_token: str
    mode: str                 # polling | webhook
    webhook_url: str          # https://example.com/telegram/webhook
    webhook_secret: str
    webhook_path: str
    host: str
    port: int
    site_url: str


def load() -> Config:
    c = Config(
        token=os.environ["TELEGRAM_BOT_TOKEN"],        # серверный секрет, пользователь его никогда не вводит
        api_url=os.getenv("API_INTERNAL_URL", "http://api:8000").rstrip("/"),
        internal_token=os.environ["INTERNAL_API_TOKEN"],
        mode=os.getenv("BOT_MODE", "polling"),
        webhook_url=os.getenv("TELEGRAM_WEBHOOK_URL", ""),
        webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
        webhook_path=os.getenv("TELEGRAM_WEBHOOK_PATH", "/telegram/webhook"),
        host=os.getenv("BOT_HOST", "0.0.0.0"),
        port=int(os.getenv("BOT_PORT", "8081")),
        site_url=os.getenv("PUBLIC_URL", "").rstrip("/"),
    )
    if c.mode == "webhook" and not (c.webhook_url.startswith("https://") and len(c.webhook_secret) >= 16):
        raise RuntimeError("Для webhook нужны HTTPS-адрес TELEGRAM_WEBHOOK_URL и TELEGRAM_WEBHOOK_SECRET (от 16 символов)")
    return c
