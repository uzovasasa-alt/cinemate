from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import get_conn
from ..deps import current_user, get_provider, provider_http_error
from ..providers.base import ProviderError
from ..services import content as content_svc
from ..services import library as lib

router = APIRouter(prefix="/api", tags=["library"])


class AddIn(BaseModel):
    kinopoisk_id: int = Field(gt=0)
    status: str = "plan"
    source: dict | None = None


class PatchIn(BaseModel):
    status: str | None = None
    stars: int | None = Field(default=None, ge=1, le=5)
    review: str | None = Field(default=None, max_length=5000)
    bump_episode: bool = False


def _lib_err(e: lib.LibraryError) -> HTTPException:
    return HTTPException(400, {"code": e.code, "message": e.message})


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=200), provider=Depends(get_provider), user=Depends(current_user)):
    try:
        return [content_svc.dto_summary(d) for d in await provider.search(q, limit=10)]
    except ProviderError as e:
        raise provider_http_error(e)


@router.post("/library", status_code=201)
async def add(body: AddIn, provider=Depends(get_provider), user=Depends(current_user), conn=Depends(get_conn)):
    try:
        cid = await content_svc.get_or_fetch(conn, provider, body.kinopoisk_id)
        created = await lib.add_to_library(conn, user["id"], cid, status=body.status, via="web", source=body.source)
    except ProviderError as e:
        raise provider_http_error(e)
    except lib.LibraryError as e:
        raise _lib_err(e)
    return {"content_id": cid, "created": created}


@router.get("/library")
async def library(status: str | None = None, type_code: str | None = None, q: str | None = None,
                  limit: int = 50, offset: int = 0, user=Depends(current_user), conn=Depends(get_conn)):
    return await lib.list_library(conn, user["id"], status=status, type_code=type_code, q=q, limit=limit, offset=offset)


@router.patch("/library/{content_id}")
async def patch(content_id: int, body: PatchIn, user=Depends(current_user), conn=Depends(get_conn)):
    try:
        out = {}
        if body.status:
            out.update(await lib.set_status(conn, user["id"], content_id, body.status))
        if body.bump_episode:
            out.update(await lib.bump_episode(conn, user["id"], content_id))
        if body.stars is not None:
            await lib.set_rating(conn, user["id"], content_id, body.stars)
        if body.review is not None:
            await lib.set_review(conn, user["id"], content_id, body.review)
        return {"ok": True, **out}
    except lib.LibraryError as e:
        raise _lib_err(e)


@router.get("/content/{content_id}")
async def card(content_id: int, user=Depends(current_user), conn=Depends(get_conn)):
    c = await content_svc.get_card(conn, content_id, user["id"])
    if not c:
        raise HTTPException(404, "Не найдено")
    return c


@router.get("/stats")
async def stats(user=Depends(current_user), conn=Depends(get_conn)):
    return await lib.stats(conn, user["id"])
