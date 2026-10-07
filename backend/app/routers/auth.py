import hashlib
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from ..config import get_settings
from ..db import get_conn
from ..deps import COOKIE, current_user
from ..security import create_session_token, hash_password, verify_password
from ..services import throttle

router = APIRouter(prefix="/api", tags=["auth"])
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")


class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    email: str = Field(max_length=120)
    password: str = Field(min_length=8, max_length=72)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Некорректный email")
        return v


class LoginIn(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=72)


def _set_cookie(resp: Response, user_id: int) -> None:
    s = get_settings()
    resp.set_cookie(COOKIE, create_session_token(user_id), httponly=True, secure=s.cookie_secure,
                    samesite="lax", max_age=s.session_days * 86400, path="/")


def _ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@router.post("/auth/register", status_code=201)
async def register(body: RegisterIn, request: Request, response: Response, conn=Depends(get_conn)):
    rk = "reg:" + _ip(request)
    if await throttle.blocked(conn, rk, 10):
        raise HTTPException(429, "Слишком много попыток. Повторите позже.")
    await throttle.hit(conn, rk)
    exists = (await conn.execute(text("SELECT 1 FROM users WHERE lower(email)=:e"), {"e": body.email})).first()
    if exists:
        raise HTTPException(409, "Этот email уже зарегистрирован")
    s = get_settings()
    role = "admin" if s.admin_email and body.email == s.admin_email else "user"
    uid = (await conn.execute(text(
        "INSERT INTO users(name,email,password_hash,role) VALUES (:n,:e,:p,:r) RETURNING id"),
        {"n": body.name.strip(), "e": body.email, "p": hash_password(body.password), "r": role})).scalar_one()
    await conn.execute(text("SELECT bootstrap_user(:u)"), {"u": uid})
    _set_cookie(response, uid)
    return {"id": uid, "name": body.name.strip(), "email": body.email, "role": role}


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, response: Response, conn=Depends(get_conn)):
    email = body.email.strip().lower()
    ip = _ip(request)
    k1, k2 = "lg:" + hashlib.sha1(f"{ip}|{email}".encode()).hexdigest(), "lgip:" + ip
    if await throttle.blocked(conn, k1, 5) or await throttle.blocked(conn, k2, 30):
        raise HTTPException(429, "Слишком много попыток входа. Повторите через 15 минут.")
    u = (await conn.execute(text(
        "SELECT id,name,email,role,password_hash FROM users WHERE lower(email)=:e AND is_active"), {"e": email})).mappings().first()
    if not u or not verify_password(body.password, u["password_hash"]):
        await throttle.hit(conn, k1)
        await throttle.hit(conn, k2)
        # коммит обязателен, иначе счётчик попыток откатится: поэтому возвращаем ответ, а не бросаем исключение
        response.status_code = 401
        return {"detail": "Неверный email или пароль"}
    _set_cookie(response, u["id"])
    return {"id": u["id"], "name": u["name"], "email": u["email"], "role": u["role"]}


@router.post("/auth/logout", status_code=204)
async def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")


@router.get("/me")
async def me(user=Depends(current_user)):
    return user
