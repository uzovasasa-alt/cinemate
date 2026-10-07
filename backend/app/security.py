"""Пароли, сессионные JWT и одноразовые коды привязки Telegram."""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt

from .config import get_settings

# Без похожих символов (0/O, 1/I/L). 31 символ ^ 8 ≈ 2^39.6 вариантов.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
CODE_RE = re.compile(r"^LINK-[" + CODE_ALPHABET + r"]{" + str(CODE_LEN) + r"}$")


def hash_password(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, hashed: str) -> bool:
    import bcrypt
    # PHP-хэши начинаются с $2y$ — это тот же bcrypt, библиотека принимает $2b$
    h = hashed.replace("$2y$", "$2b$", 1)
    try:
        return bcrypt.checkpw(password.encode()[:72], h.encode())
    except ValueError:
        return False


def create_session_token(user_id: int) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(days=s.session_days)}
    return jwt.encode(payload, s.secret_key, algorithm="HS256")


def read_session_token(token: str) -> int | None:
    try:
        data = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
        return int(data["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def generate_link_code() -> str:
    return "LINK-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def normalize_link_code(raw: str) -> str | None:
    """'link-7f3a9c2k ' → 'LINK-7F3A9C2K'. Возвращает None, если формат неверный."""
    code = (raw or "").strip().upper().replace(" ", "")
    if code and not code.startswith("LINK-") and len(code) == CODE_LEN:
        code = "LINK-" + code
    return code if CODE_RE.match(code) else None


def hash_link_code(code: str) -> str:
    key = get_settings().secret_key.encode()
    return hmac.new(key, code.encode(), hashlib.sha256).hexdigest()


def check_internal_token(provided: str | None) -> bool:
    expected = get_settings().internal_token
    return bool(provided) and hmac.compare_digest(provided, expected)
