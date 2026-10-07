"""KinopoiskProvider: поиск и карточки через API Кинопоиска (api.kinopoisk.dev, v1.4).

[Предположение] Формат ответа описан по публичной документации; парсер написан защитно
(любое поле может отсутствовать). Базовый URL настраивается через KINOPOISK_API_BASE.
Ключ — только из переменной окружения KINOPOISK_API_KEY.
"""
import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from .base import (ContentDTO, EpisodeDTO, PersonDTO, ProviderAuthError, ProviderError, ProviderNotFound,
                   ProviderRateLimited, ProviderUnavailable, SeasonDTO)
from .cache import Cache

SERIAL_TYPES = {"tv-series", "animated-series", "tv-show"}
ROLE_MAP = {"director": "director", "actor": "actor", "writer": "writer", "producer": "producer"}
MAX_PEOPLE = {"director": 5, "actor": 20, "writer": 5, "producer": 3}


@dataclass
class HttpResponse:
    status: int
    headers: dict
    data: Any


class HttpTransport(Protocol):
    async def get(self, url: str, params: dict, headers: dict, timeout: float) -> HttpResponse: ...


class HttpxTransport:
    def __init__(self):
        import httpx
        self._c = httpx.AsyncClient()

    async def get(self, url, params, headers, timeout):
        r = await self._c.get(url, params=params, headers=headers, timeout=timeout)
        try:
            data = r.json()
        except ValueError:
            data = None
        return HttpResponse(r.status_code, {k.lower(): v for k, v in r.headers.items()}, data)

    async def aclose(self):
        await self._c.aclose()


def _num(v, lo=0.0) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return round(f, 1) if f > lo else None


def _int(v) -> int | None:
    try:
        i = int(v)
    except (TypeError, ValueError):
        return None
    return i if i > 0 else None


def _date(v) -> date | None:
    if not v or not isinstance(v, str):
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        return None


def parse_movie(doc: dict) -> ContentDTO:
    genres = [g["name"].strip().lower() for g in (doc.get("genres") or []) if g.get("name")]
    kp_type = (doc.get("type") or "movie").lower()
    is_serial = kp_type in SERIAL_TYPES or bool(doc.get("isSeries"))
    if "документальный" in genres:
        type_code = "documentary"
    elif kp_type == "anime":
        type_code = "anime"
    elif kp_type in ("cartoon", "animated-series"):
        type_code = "cartoon"
    elif is_serial:
        type_code = "series"
    else:
        type_code = "movie"

    title = doc.get("name") or doc.get("alternativeName") or doc.get("enName") or ""
    original = doc.get("alternativeName") or doc.get("enName")
    if original == title:
        original = None
    year = _int(doc.get("year"))
    if year and not 1888 <= year <= 2100:
        year = None

    ext = doc.get("externalId") or {}
    rating = doc.get("rating") or {}
    poster = (doc.get("poster") or {}).get("url") or (doc.get("poster") or {}).get("previewUrl")

    counters: dict[str, int] = {}
    people: list[PersonDTO] = []
    for p in doc.get("persons") or []:
        role = ROLE_MAP.get((p.get("enProfession") or "").lower())
        name = p.get("name") or p.get("enName")
        if not role or not name:
            continue
        counters[role] = counters.get(role, 0) + 1
        if counters[role] > MAX_PEOPLE[role]:
            continue
        people.append(PersonDTO(_int(p.get("id")), name, p.get("enName"), p.get("photo"), role, counters[role]))

    seasons_info = []
    for s in doc.get("seasonsInfo") or []:
        n, c = _int(s.get("number")), _int(s.get("episodesCount"))
        if n and c:
            seasons_info.append((n, c))

    watch = []
    for it in ((doc.get("watchability") or {}).get("items") or []):
        if it.get("url") and it.get("name"):
            watch.append({"name": it["name"], "url": it["url"], "logo": (it.get("logo") or {}).get("url")})

    duration = _int(doc.get("seriesLength") if is_serial else doc.get("movieLength")) \
        or _int(doc.get("movieLength")) or _int(doc.get("seriesLength"))

    return ContentDTO(
        kinopoisk_id=_int(doc.get("id")),
        imdb_id=(ext.get("imdb") or None),
        tmdb_id=_int(ext.get("tmdb")),
        type_code=type_code,
        is_serial=is_serial,
        title=title.strip(),
        original_title=(original or None),
        year=year,
        description=doc.get("description") or None,
        short_description=doc.get("shortDescription") or None,
        poster_url=poster,
        rating_kp=_num(rating.get("kp")),
        rating_imdb=_num(rating.get("imdb")),
        duration_min=duration,
        countries=[c["name"] for c in (doc.get("countries") or []) if c.get("name")],
        genres=genres,
        age_rating=_int(doc.get("ageRating")),
        people=people,
        watchability=watch,
        total_episodes=sum(c for _, c in seasons_info),
        seasons_info=seasons_info,
    )


def parse_seasons(docs: list[dict]) -> list[SeasonDTO]:
    out = []
    for d in docs or []:
        n = _int(d.get("number"))
        if not n:                       # сезон 0 — спецвыпуски, пропускаем
            continue
        eps = []
        for e in d.get("episodes") or []:
            en = _int(e.get("number"))
            if en:
                eps.append(EpisodeDTO(en, (e.get("name") or e.get("enName") or "")[:300],
                                      _date(e.get("airDate")), _int(e.get("duration"))))
        out.append(SeasonDTO(n, _int(d.get("episodesCount")) or len(eps), eps))
    return sorted(out, key=lambda s: s.number)


class KinopoiskProvider:
    MAX_ATTEMPTS = 3

    def __init__(self, api_key: str, base_url: str, cache: Cache, transport: HttpTransport,
                 ttl_search: int = 86400, ttl_card: int = 604800, max_rps: float = 5.0,
                 timeout: float = 10.0, sleep=asyncio.sleep, clock=time.monotonic):
        self.api_key = api_key
        self.base = base_url.rstrip("/")
        self.cache = cache
        self.transport = transport
        self.ttl_search, self.ttl_card = ttl_search, ttl_card
        self.timeout = timeout
        self._sleep, self._clock = sleep, clock
        self._interval = 1.0 / max_rps if max_rps > 0 else 0.0
        self._next_at = 0.0
        self._lock = asyncio.Lock()
        self.requests_made = 0          # для проверки лимитов в тестах и метриках

    async def _throttle(self):
        async with self._lock:
            now = self._clock()
            wait = self._next_at - now
            self._next_at = max(now, self._next_at) + self._interval
        if wait > 0:
            await self._sleep(wait)

    async def _get(self, path: str, params: dict, ttl: int) -> Any:
        if not self.api_key:
            raise ProviderAuthError("KINOPOISK_API_KEY не задан")
        key = "kp:" + hashlib.sha1((path + json.dumps(params, sort_keys=True)).encode()).hexdigest()
        cached = await self.cache.get(key)
        if cached is not None:
            return cached
        url = self.base + path
        headers = {"X-API-KEY": self.api_key, "Accept": "application/json"}
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            await self._throttle()
            self.requests_made += 1
            try:
                r = await self.transport.get(url, params, headers, self.timeout)
            except (asyncio.TimeoutError, OSError) as e:
                if attempt == self.MAX_ATTEMPTS:
                    raise ProviderUnavailable(f"Кинопоиск недоступен: {e}") from e
                await self._sleep(0.5 * 2 ** (attempt - 1))
                continue
            if r.status == 200 and r.data is not None:
                await self.cache.set(key, r.data, ttl)
                return r.data
            if r.status in (401, 403):
                raise ProviderAuthError("Ключ Кинопоиска отклонён или исчерпана квота")
            if r.status == 404:
                raise ProviderNotFound(path)
            if r.status == 429 or r.status >= 500:
                if attempt == self.MAX_ATTEMPTS:
                    exc = ProviderRateLimited if r.status == 429 else ProviderUnavailable
                    raise exc(f"Кинопоиск ответил {r.status}")
                try:
                    delay = float(r.headers.get("retry-after", ""))
                except ValueError:
                    delay = 0.5 * 2 ** (attempt - 1)
                await self._sleep(min(delay, 10.0))
                continue
            raise ProviderError(f"Неожиданный ответ Кинопоиска: {r.status}")
        raise ProviderUnavailable("unreachable")

    async def search(self, query: str, limit: int = 10) -> list[ContentDTO]:
        q = " ".join(query.split()).lower()
        if not q:
            return []
        data = await self._get("/v1.4/movie/search", {"query": q, "page": 1, "limit": limit}, self.ttl_search)
        items = [parse_movie(d) for d in (data.get("docs") or [])]
        return [i for i in items if i.kinopoisk_id and i.title]

    async def by_kinopoisk_id(self, kp_id: int) -> ContentDTO:
        data = await self._get(f"/v1.4/movie/{int(kp_id)}", {}, self.ttl_card)
        dto = parse_movie(data)
        if not dto.kinopoisk_id or not dto.title:
            raise ProviderNotFound(str(kp_id))
        return dto

    async def by_imdb_id(self, imdb_id: str) -> ContentDTO | None:
        data = await self._get("/v1.4/movie", {"externalId.imdb": imdb_id, "limit": 1}, self.ttl_card)
        docs = data.get("docs") or []
        return parse_movie(docs[0]) if docs else None

    async def seasons(self, kp_id: int) -> list[SeasonDTO]:
        data = await self._get("/v1.4/season", {"movieId": int(kp_id), "limit": 100}, self.ttl_card)
        return parse_seasons(data.get("docs") or [])
