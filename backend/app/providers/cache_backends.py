import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text


class RedisCache:
    def __init__(self, client, prefix: str = "cinemate:"):
        self.r = client
        self.prefix = prefix

    async def get(self, key):
        raw = await self.r.get(self.prefix + key)
        return json.loads(raw) if raw else None

    async def set(self, key, value, ttl):
        await self.r.set(self.prefix + key, json.dumps(value, ensure_ascii=False), ex=ttl)


class PgCache:
    """Таблица api_cache: переживает перезапуск Redis и помогает не упираться в квоту Кинопоиска."""

    def __init__(self, engine):
        self.engine = engine

    async def get(self, key):
        async with self.engine.connect() as c:
            row = (await c.execute(
                text("SELECT value FROM api_cache WHERE cache_key=:k AND expires_at>now()"), {"k": key}
            )).first()
        return row[0] if row else None

    async def set(self, key, value, ttl):
        exp = datetime.now(timezone.utc) + timedelta(seconds=ttl)
        async with self.engine.begin() as c:
            await c.execute(
                text("""INSERT INTO api_cache(cache_key,value,expires_at) VALUES (:k, CAST(:v AS jsonb), :e)
                        ON CONFLICT (cache_key) DO UPDATE SET value=EXCLUDED.value, expires_at=EXCLUDED.expires_at"""),
                {"k": key, "v": json.dumps(value, ensure_ascii=False), "e": exp},
            )
