"""Внутренний API для Telegram-бота. Доступен только по сервисному токену (заголовок X-Internal-Token)."""
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..db import get_conn
from ..deps import get_provider, internal_auth, provider_http_error
from ..linkparse import parse_input
from ..providers.base import ProviderError, ProviderNotFound
from ..services import content as content_svc
from ..services import library as lib
from ..services import linking

router = APIRouter(prefix="/api/internal", tags=["internal"], dependencies=[Depends(internal_auth)])


class LinkIn(BaseModel):
    code: str = Field(max_length=64)
    telegram_id: int
    chat_id: int
    username: str | None = None


class TgIn(BaseModel):
    telegram_id: int


class ResolveIn(TgIn):
    text: str = Field(max_length=500)


class AddIn(TgIn):
    kinopoisk_id: int = Field(gt=0)
    service: str | None = Field(default=None, max_length=80)


class StatusIn(TgIn):
    content_id: int
    status: str


class ContentIn(TgIn):
    content_id: int


class RateIn(TgIn):
    content_id: int
    stars: int = Field(ge=1, le=5)


class ReviewIn(TgIn):
    content_id: int
    text: str = Field(max_length=5000)


class SearchIn(TgIn):
    q: str = Field(max_length=200)


class SettingsIn(TgIn):
    remind_inactive_days: int | None = Field(default=None, ge=1, le=365)
    notify_telegram: bool | None = None


async def _uid(conn, telegram_id: int) -> int:
    uid = await linking.user_by_telegram(conn, telegram_id)
    if not uid:
        raise HTTPException(403, "not_linked")
    return uid


def _err(e: lib.LibraryError):
    return HTTPException(400, {"code": e.code, "message": e.message})


@router.post("/telegram/link")
async def link(body: LinkIn, conn=Depends(get_conn)):
    r = await linking.consume_link_code(conn, body.code, body.telegram_id, body.chat_id, body.username)
    return {"status": r.status, "name": r.name}


@router.post("/bot/resolve")
async def resolve(body: ResolveIn, conn=Depends(get_conn), provider=Depends(get_provider)):
    await _uid(conn, body.telegram_id)
    p = parse_input(body.text)
    if not p:
        return {"candidates": [], "exact": False, "service": None, "guessed": False, "hint": "no_title"}
    try:
        if p.kind == "kp_id":
            items, exact = [await provider.by_kinopoisk_id(int(p.value))], True
        elif p.kind == "imdb":
            d = await provider.by_imdb_id(p.value)
            items, exact = ([d] if d else []), True
        else:
            items, exact = await provider.search(p.value, limit=5), False
    except ProviderError as e:
        if p.kind == "kp_id" and isinstance(e, ProviderNotFound):
            return {"candidates": [], "exact": True, "service": None, "guessed": False, "hint": "not_found"}
        raise provider_http_error(e)
    return {"candidates": [content_svc.dto_summary(i) for i in items], "exact": exact,
            "service": p.service, "guessed": p.guessed, "query": p.value}


def _card_for_bot(c: dict) -> dict:
    return {
        "title": c["title"], "original_title": c["original_title"], "year": c["year"], "type_code": c["type_code"],
        "poster_url": c["poster_url"], "rating_kp": float(c["rating_kp"]) if c["rating_kp"] is not None else None,
        "genres": c["genres"], "directors": [d["name"] for d in c["directors"]][:3],
        "actors": [a["name"] for a in c["actors"]][:5], "description": (c["description"] or "")[:600],
        "duration_min": c["duration_min"], "is_serial": c["is_serial"], "total_episodes": c["total_episodes"],
        "seasons": len(c["seasons"]), "status": (c.get("mine") or {}).get("status_code"),
    }


@router.post("/bot/add")
async def add(body: AddIn, conn=Depends(get_conn), provider=Depends(get_provider)):
    uid = await _uid(conn, body.telegram_id)
    try:
        cid = await content_svc.get_or_fetch(conn, provider, body.kinopoisk_id)
        source = {"source_type": "streaming", "service_name": body.service} if body.service else None
        created = await lib.add_to_library(conn, uid, cid, status="plan", via="telegram", source=source)
    except ProviderError as e:
        raise provider_http_error(e)
    card = await content_svc.get_card(conn, cid, uid)
    return {"created": created, "content_id": cid, "card": _card_for_bot(card)}


@router.post("/bot/status")
async def status(body: StatusIn, conn=Depends(get_conn)):
    uid = await _uid(conn, body.telegram_id)
    try:
        return await lib.set_status(conn, uid, body.content_id, body.status)
    except lib.LibraryError as e:
        raise _err(e)


@router.post("/bot/episode")
async def episode(body: ContentIn, conn=Depends(get_conn)):
    uid = await _uid(conn, body.telegram_id)
    try:
        return await lib.bump_episode(conn, uid, body.content_id)
    except lib.LibraryError as e:
        raise _err(e)


@router.post("/bot/rate")
async def rate(body: RateIn, conn=Depends(get_conn)):
    uid = await _uid(conn, body.telegram_id)
    try:
        await lib.set_rating(conn, uid, body.content_id, body.stars)
    except lib.LibraryError as e:
        raise _err(e)
    return {"ok": True}


@router.post("/bot/review")
async def review(body: ReviewIn, conn=Depends(get_conn)):
    uid = await _uid(conn, body.telegram_id)
    try:
        await lib.set_review(conn, uid, body.content_id, body.text)
    except lib.LibraryError as e:
        raise _err(e)
    return {"ok": True}


@router.post("/bot/library")
async def library(body: SearchIn, conn=Depends(get_conn)):
    uid = await _uid(conn, body.telegram_id)
    return await lib.list_library(conn, uid, q=body.q, limit=5)


@router.post("/bot/random")
async def random_pick(body: TgIn, conn=Depends(get_conn)):
    uid = await _uid(conn, body.telegram_id)
    return {"item": await lib.random_pick(conn, uid)}


@router.post("/bot/stats")
async def stats(body: TgIn, conn=Depends(get_conn)):
    uid = await _uid(conn, body.telegram_id)
    return await lib.stats(conn, uid)


@router.post("/bot/settings")
async def settings(body: SettingsIn, conn=Depends(get_conn)):
    uid = await _uid(conn, body.telegram_id)
    patch = {k: v for k, v in {"remind_inactive_days": body.remind_inactive_days,
                               "notify_telegram": body.notify_telegram}.items() if v is not None}
    if patch:
        await conn.execute(text("UPDATE user_profiles SET settings = settings || CAST(:p AS jsonb) WHERE user_id=:u"),
                           {"p": json.dumps(patch), "u": uid})
    s = (await conn.execute(text("SELECT settings FROM user_profiles WHERE user_id=:u"), {"u": uid})).scalar_one()
    pending = (await conn.execute(text(
        "SELECT count(*) FROM notifications WHERE user_id=:u AND status='pending'"), {"u": uid})).scalar_one()
    return {"settings": s, "pending_reminders": pending}
