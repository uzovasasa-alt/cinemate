"""Кэш ответов внешнего API. Здесь протокол, память и цепочка; Redis и PG — в cache_backends.py."""
import time
from typing import Any, Protocol


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...


class MemoryCache:
    def __init__(self, clock=time.monotonic):
        self._d: dict[str, tuple[float, Any]] = {}
        self._clock = clock

    async def get(self, key):
        item = self._d.get(key)
        if not item:
            return None
        exp, val = item
        if exp < self._clock():
            self._d.pop(key, None)
            return None
        return val

    async def set(self, key, value, ttl):
        self._d[key] = (self._clock() + ttl, value)


class ChainCache:
    """Быстрый кэш первым (Redis), надёжный вторым (PostgreSQL). Попадание во второй прогревает первый."""

    def __init__(self, *backends: Cache, backfill_ttl: int = 3600):
        self.backends = backends
        self.backfill_ttl = backfill_ttl

    async def get(self, key):
        for i, b in enumerate(self.backends):
            try:
                val = await b.get(key)
            except Exception:       # упавший кэш не должен ронять запрос
                continue
            if val is not None:
                for earlier in self.backends[:i]:
                    try:
                        await earlier.set(key, val, self.backfill_ttl)
                    except Exception:
                        pass
                return val
        return None

    async def set(self, key, value, ttl):
        for b in self.backends:
            try:
                await b.set(key, value, ttl)
            except Exception:
                pass
