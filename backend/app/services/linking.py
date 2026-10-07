"""Привязка Telegram по одноразовому коду."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ..config import get_settings
from ..security import generate_link_code, hash_link_code, normalize_link_code
from . import throttle

MAX_BAD_ATTEMPTS = 10   # на один telegram_id за 15 минут


@dataclass
class LinkResult:
    status: str                 # linked | invalid | expired | used | rate_limited
    user_id: int | None = None
    name: str | None = None


async def create_link_code(conn, user_id: int) -> tuple[str, datetime]:
    ttl = get_settings().link_code_ttl_min
    await conn.execute(text(
        "UPDATE link_codes SET expires_at=now() WHERE user_id=:u AND used_at IS NULL AND expires_at>now()"), {"u": user_id})
    code = generate_link_code()
    exp = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    await conn.execute(text("INSERT INTO link_codes(user_id,code_hash,expires_at) VALUES (:u,:h,:e)"),
                       {"u": user_id, "h": hash_link_code(code), "e": exp})
    return code, exp


async def consume_link_code(conn, raw_code: str, telegram_id: int, chat_id: int, username: str | None) -> LinkResult:
    key = f"tg:{telegram_id}"
    if await throttle.blocked(conn, key, MAX_BAD_ATTEMPTS):
        return LinkResult("rate_limited")
    code = normalize_link_code(raw_code)
    if not code:
        await throttle.hit(conn, key)
        return LinkResult("invalid")
    h = hash_link_code(code)
    # Атомарно: погасить можно только неиспользованный и непросроченный код — гонки исключены.
    row = (await conn.execute(text("""
        UPDATE link_codes SET used_at=now(), used_by_telegram_id=:t
        WHERE code_hash=:h AND used_at IS NULL AND expires_at>now() RETURNING user_id"""),
        {"h": h, "t": telegram_id})).first()
    if not row:
        await throttle.hit(conn, key)
        info = (await conn.execute(text("SELECT used_at FROM link_codes WHERE code_hash=:h"), {"h": h})).first()
        if not info:
            return LinkResult("invalid")
        return LinkResult("used" if info[0] else "expired")
    user_id = row[0]
    # Один Telegram — один аккаунт и наоборот: старые связки заменяются.
    await conn.execute(text("DELETE FROM telegram_links WHERE user_id=:u OR telegram_id=:t"), {"u": user_id, "t": telegram_id})
    await conn.execute(text(
        "INSERT INTO telegram_links(user_id,telegram_id,chat_id,username) VALUES (:u,:t,:c,:n)"),
        {"u": user_id, "t": telegram_id, "c": chat_id, "n": (username or None)})
    await conn.execute(text("SELECT bootstrap_user(:u)"), {"u": user_id})
    await conn.execute(text("INSERT INTO audit_log(user_id,action,entity,entity_id) VALUES (:u,'telegram_linked','user',:u)"),
                       {"u": user_id})
    name = (await conn.execute(text("SELECT name FROM users WHERE id=:u"), {"u": user_id})).scalar_one()
    return LinkResult("linked", user_id, name)


async def user_by_telegram(conn, telegram_id: int) -> int | None:
    return (await conn.execute(text("SELECT user_id FROM telegram_links WHERE telegram_id=:t"), {"t": telegram_id})).scalar()
