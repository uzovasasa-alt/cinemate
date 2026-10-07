from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text

from .db import get_conn
from .providers.base import (ProviderAuthError, ProviderError, ProviderNotFound, ProviderRateLimited,
                             ProviderUnavailable)
from .security import check_internal_token, read_session_token

COOKIE = "cv_session"


async def current_user(request: Request, conn=Depends(get_conn)) -> dict:
    uid = read_session_token(request.cookies.get(COOKIE, ""))
    if uid:
        u = (await conn.execute(text(
            "SELECT id,name,email,role FROM users WHERE id=:i AND is_active"), {"i": uid})).mappings().first()
        if u:
            return dict(u)
    raise HTTPException(401, "Требуется вход")


async def internal_auth(x_internal_token: str | None = Header(default=None)) -> None:
    if not check_internal_token(x_internal_token):
        raise HTTPException(403, "forbidden")


def get_provider(request: Request):
    return request.app.state.provider


def provider_http_error(e: ProviderError) -> HTTPException:
    if isinstance(e, ProviderNotFound):
        return HTTPException(404, "Не найдено в Кинопоиске")
    if isinstance(e, ProviderRateLimited):
        return HTTPException(429, "Кинопоиск просит подождать, повторите через минуту")
    if isinstance(e, ProviderAuthError):
        return HTTPException(503, "Каталог Кинопоиска временно недоступен (ключ/квота)")
    if isinstance(e, ProviderUnavailable):
        return HTTPException(503, "Кинопоиск недоступен")
    return HTTPException(502, "Ошибка каталога")
