from fastapi import APIRouter, Depends
from sqlalchemy import text

from ..config import get_settings
from ..db import get_conn
from ..deps import current_user
from ..services import linking

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


@router.post("/link-code")
async def link_code(user=Depends(current_user), conn=Depends(get_conn)):
    code, exp = await linking.create_link_code(conn, user["id"])
    s = get_settings()
    return {
        "code": code, "expires_at": exp.isoformat(), "ttl_seconds": s.link_code_ttl_min * 60,
        "command": f"/start {code}",
        "deep_link": f"https://t.me/{s.bot_username}?start={code}" if s.bot_username else None,
    }


@router.get("/status")
async def status(user=Depends(current_user), conn=Depends(get_conn)):
    r = (await conn.execute(text(
        "SELECT username, linked_at FROM telegram_links WHERE user_id=:u"), {"u": user["id"]})).mappings().first()
    return {"linked": bool(r), "username": r["username"] if r else None, "linked_at": r["linked_at"].isoformat() if r else None}


@router.delete("", status_code=204)
async def unlink(user=Depends(current_user), conn=Depends(get_conn)):
    await conn.execute(text("DELETE FROM telegram_links WHERE user_id=:u"), {"u": user["id"]})
    await conn.execute(text("INSERT INTO audit_log(user_id,action) VALUES (:u,'telegram_unlinked')"), {"u": user["id"]})
