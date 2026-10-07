"""Настройки читаются из переменных окружения. Секреты в репозиторий не попадают."""
import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    redis_url: str
    secret_key: str
    internal_token: str
    cookie_secure: bool
    session_days: int
    admin_email: str
    bot_username: str
    link_code_ttl_min: int
    kinopoisk_api_key: str
    kinopoisk_base_url: str
    kinopoisk_max_rps: float
    cache_ttl_search: int
    cache_ttl_card: int
    public_url: str

    @property
    def is_prod(self) -> bool:
        return self.env == "production"

    @property
    def asyncpg_dsn(self) -> str:
        return self.database_url.replace("postgresql+asyncpg://", "postgresql://")


@lru_cache
def get_settings() -> Settings:
    s = Settings(
        env=os.getenv("APP_ENV", "development"),
        database_url=os.getenv("DATABASE_URL", "postgresql+asyncpg://cinemate:cinemate@localhost:5432/cinemate"),
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"),
        internal_token=os.getenv("INTERNAL_API_TOKEN", "dev-internal-token"),
        cookie_secure=_bool("COOKIE_SECURE", False),
        session_days=int(os.getenv("SESSION_DAYS", "7")),
        admin_email=os.getenv("ADMIN_EMAIL", "").strip().lower(),
        bot_username=os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@"),
        link_code_ttl_min=int(os.getenv("LINK_CODE_TTL_MIN", "10")),
        kinopoisk_api_key=os.getenv("KINOPOISK_API_KEY", ""),
        kinopoisk_base_url=os.getenv("KINOPOISK_API_BASE", "https://api.kinopoisk.dev").rstrip("/"),
        kinopoisk_max_rps=float(os.getenv("KINOPOISK_MAX_RPS", "5")),
        cache_ttl_search=int(os.getenv("CACHE_TTL_SEARCH", str(24 * 3600))),
        cache_ttl_card=int(os.getenv("CACHE_TTL_CARD", str(7 * 24 * 3600))),
        public_url=os.getenv("PUBLIC_URL", "http://localhost:8000").rstrip("/"),
    )
    if s.is_prod:
        weak = []
        if s.secret_key.startswith("dev-") or len(s.secret_key) < 32:
            weak.append("SECRET_KEY")
        if s.internal_token.startswith("dev-") or len(s.internal_token) < 24:
            weak.append("INTERNAL_API_TOKEN")
        if weak:
            raise RuntimeError("Небезопасные значения в production: " + ", ".join(weak))
    return s
