from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from .config import get_settings
from .db import engine
from .providers.cache import ChainCache
from .providers.cache_backends import PgCache, RedisCache
from .providers.kinopoisk import HttpxTransport, KinopoiskProvider
from .routers import auth, internal, library, telegram


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    backends = []
    redis_client = None
    try:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(s.redis_url, decode_responses=True)
        backends.append(RedisCache(redis_client))
    except Exception:
        pass
    backends.append(PgCache(engine))
    transport = HttpxTransport()
    app.state.provider = KinopoiskProvider(
        s.kinopoisk_api_key, s.kinopoisk_base_url, ChainCache(*backends), transport,
        ttl_search=s.cache_ttl_search, ttl_card=s.cache_ttl_card, max_rps=s.kinopoisk_max_rps)
    yield
    await transport.aclose()
    if redis_client:
        await redis_client.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="Cinemate API", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    for r in (auth.router, telegram.router, library.router, internal.router):
        app.include_router(r)

    @app.get("/api/health", tags=["system"])
    async def health():
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
        return {"status": "ok", "kinopoisk_key": bool(s.kinopoisk_api_key)}

    return app


app = create_app()
