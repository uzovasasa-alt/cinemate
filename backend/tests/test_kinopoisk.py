import asyncio
import unittest

from app.providers.base import (ProviderAuthError, ProviderNotFound, ProviderRateLimited, ProviderUnavailable)
from app.providers.cache import ChainCache, MemoryCache
from app.providers.kinopoisk import HttpResponse, KinopoiskProvider, parse_movie, parse_seasons
from tests import fixtures as fx


class Parse(unittest.TestCase):
    def test_movie(self):
        d = parse_movie(fx.MATRIX)
        self.assertEqual((d.kinopoisk_id, d.title, d.original_title, d.year), (301, "Матрица", "The Matrix", 1999))
        self.assertEqual((d.type_code, d.is_serial), ("movie", False))
        self.assertEqual((d.rating_kp, d.rating_imdb, d.duration_min, d.imdb_id, d.tmdb_id), (8.5, 8.7, 136, "tt0133093", 603))
        self.assertEqual(d.genres, ["фантастика", "боевик"])
        self.assertEqual(d.poster_url, "https://img/matrix.jpg")
        self.assertEqual([(p.role, p.name) for p in d.people],
                         [("director", "Лана Вачовски"), ("actor", "Киану Ривз"), ("actor", "Кэрри-Энн Мосс")])
        self.assertEqual(len(d.watchability), 1)        # без url не берём

    def test_series(self):
        d = parse_movie(fx.SERIES)
        self.assertEqual((d.type_code, d.is_serial, d.total_episodes, d.duration_min), ("series", True, 16, 55))
        self.assertIsNone(d.rating_imdb)                 # 0 = нет оценки

    def test_documentary_by_genre(self):
        self.assertEqual(parse_movie(fx.DOC).type_code, "documentary")
        self.assertTrue(parse_movie(fx.DOC).is_serial)

    def test_missing_fields_do_not_crash(self):
        d = parse_movie({"id": 5, "name": "X"})
        self.assertEqual((d.title, d.year, d.people, d.genres, d.poster_url), ("X", None, [], [], None))

    def test_bad_year_dropped(self):
        self.assertIsNone(parse_movie({"id": 1, "name": "X", "year": 1500}).year)

    def test_people_limit(self):
        doc = {"id": 1, "name": "X", "persons": [{"id": i, "name": f"A{i}", "enProfession": "actor"} for i in range(1, 40)]}
        self.assertEqual(len(parse_movie(doc).people), 20)

    def test_seasons(self):
        s = parse_seasons(fx.SEASONS["docs"])
        self.assertEqual([x.number for x in s], [1, 2])    # сезон 0 отброшен, порядок восстановлен
        self.assertEqual(s[0].episodes[0].duration_min, 50)
        self.assertEqual(str(s[1].episodes[0].air_date), "2022-01-02")
        self.assertIsNone(s[1].episodes[1].air_date)


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, params, headers, timeout):
        self.calls.append((url, params, headers))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def make(*responses, cache=None, key="SECRET"):
    sleeps = []

    async def fake_sleep(x):
        sleeps.append(x)

    t = FakeTransport(*responses)
    p = KinopoiskProvider(key, "https://api.test", cache or MemoryCache(), t, max_rps=0, sleep=fake_sleep)
    return p, t, sleeps


def ok(data):
    return HttpResponse(200, {}, data)


class Provider(unittest.IsolatedAsyncioTestCase):
    async def test_search_sends_key_and_caches(self):
        p, t, _ = make(ok({"docs": [fx.MATRIX]}))
        r1 = await p.search("  Матрица  ")
        r2 = await p.search("матрица")
        self.assertEqual(r1[0].kinopoisk_id, 301)
        self.assertEqual(len(r2), 1)
        self.assertEqual(len(t.calls), 1, "второй запрос должен прийти из кэша")
        self.assertEqual(t.calls[0][2]["X-API-KEY"], "SECRET")
        self.assertEqual(t.calls[0][0], "https://api.test/v1.4/movie/search")

    async def test_by_id_and_imdb(self):
        p, t, _ = make(ok(fx.MATRIX))
        self.assertEqual((await p.by_kinopoisk_id(301)).title, "Матрица")
        self.assertTrue(t.calls[0][0].endswith("/v1.4/movie/301"))
        p, t, _ = make(ok({"docs": [fx.MATRIX]}))
        self.assertEqual((await p.by_imdb_id("tt0133093")).kinopoisk_id, 301)
        self.assertEqual(t.calls[0][1]["externalId.imdb"], "tt0133093")
        p, t, _ = make(ok({"docs": []}))
        self.assertIsNone(await p.by_imdb_id("tt0000000"))

    async def test_seasons(self):
        p, t, _ = make(ok(fx.SEASONS))
        self.assertEqual(len(await p.seasons(5)), 2)
        self.assertEqual(t.calls[0][1]["movieId"], 5)

    async def test_retry_on_429_with_retry_after(self):
        p, t, sleeps = make(HttpResponse(429, {"retry-after": "2"}, None), ok({"docs": [fx.MATRIX]}))
        self.assertEqual(len((await p.search("матрица"))), 1)
        self.assertEqual(len(t.calls), 2)
        self.assertIn(2.0, sleeps)

    async def test_gives_up_after_max_attempts(self):
        p, t, _ = make(HttpResponse(429, {}, None))
        with self.assertRaises(ProviderRateLimited):
            await p.search("x1")
        self.assertEqual(len(t.calls), 3)
        p, t, _ = make(HttpResponse(503, {}, None))
        with self.assertRaises(ProviderUnavailable):
            await p.search("x1")

    async def test_network_error_retried(self):
        p, t, _ = make(asyncio.TimeoutError(), ok({"docs": []}))
        self.assertEqual(await p.search("zz"), [])
        self.assertEqual(len(t.calls), 2)

    async def test_auth_not_found_and_missing_key(self):
        p, _, _ = make(HttpResponse(401, {}, None))
        with self.assertRaises(ProviderAuthError):
            await p.search("zz")
        p, _, _ = make(HttpResponse(404, {}, None))
        with self.assertRaises(ProviderNotFound):
            await p.by_kinopoisk_id(1)
        p, t, _ = make(ok({}), key="")
        with self.assertRaises(ProviderAuthError):
            await p.search("zz")
        self.assertEqual(t.calls, [])

    async def test_rate_limiter_spaces_requests(self):
        now = [0.0]
        sleeps = []

        async def fake_sleep(x):
            sleeps.append(x)
            now[0] += x

        t = FakeTransport(ok({"docs": []}))
        p = KinopoiskProvider("k", "https://api.test", MemoryCache(), t, max_rps=2, sleep=fake_sleep, clock=lambda: now[0])
        for i in range(3):
            await p.search(f"query {i}")
        self.assertAlmostEqual(sum(sleeps), 1.0, places=2)    # 3 запроса при 2 rps: 0 + 0.5 + 0.5

    async def test_chain_cache_backfills_and_survives_failures(self):
        fast, slow = MemoryCache(), MemoryCache()
        await slow.set("a", {"v": 1}, 100)

        class Broken:
            async def get(self, k): raise RuntimeError
            async def set(self, k, v, ttl): raise RuntimeError

        c = ChainCache(Broken(), fast, slow)
        self.assertEqual(await c.get("a"), {"v": 1})
        self.assertEqual(await fast.get("a"), {"v": 1})
        await c.set("b", 2, 10)
        self.assertEqual(await slow.get("b"), 2)


if __name__ == "__main__":
    unittest.main()
