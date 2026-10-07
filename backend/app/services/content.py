"""Глобальный каталог: сохранение карточек из провайдера в content_items и связанные таблицы."""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from ..providers.base import ContentDTO, ProviderError, SeasonDTO

CARD_TTL = timedelta(days=7)


def dto_summary(d: ContentDTO) -> dict:
    return {
        "kinopoisk_id": d.kinopoisk_id, "title": d.title, "original_title": d.original_title,
        "year": d.year, "type_code": d.type_code, "is_serial": d.is_serial,
        "poster_url": d.poster_url, "rating_kp": d.rating_kp, "genres": d.genres[:4],
        "short": (d.short_description or d.description or "")[:300],
    }


async def upsert_content(conn, d: ContentDTO) -> int:
    cid = (await conn.execute(text("""
        INSERT INTO content_items(kinopoisk_id,imdb_id,tmdb_id,type_code,is_serial,title,original_title,year,
          description,short_description,poster_url,rating_kp,rating_imdb,duration_min,total_episodes,countries,
          age_rating,watchability,fetched_at)
        VALUES (:kp,:imdb,:tmdb,:type,:serial,:title,:orig,:year,:descr,:short,:poster,:rkp,:rimdb,:dur,:eps,
          CAST(:countries AS text[]),:age,CAST(:watch AS jsonb),now())
        ON CONFLICT (kinopoisk_id) DO UPDATE SET
          imdb_id=COALESCE(EXCLUDED.imdb_id,content_items.imdb_id),
          tmdb_id=COALESCE(EXCLUDED.tmdb_id,content_items.tmdb_id),
          type_code=EXCLUDED.type_code, is_serial=EXCLUDED.is_serial, title=EXCLUDED.title,
          original_title=COALESCE(EXCLUDED.original_title,content_items.original_title),
          year=COALESCE(EXCLUDED.year,content_items.year),
          description=COALESCE(EXCLUDED.description,content_items.description),
          short_description=COALESCE(EXCLUDED.short_description,content_items.short_description),
          poster_url=COALESCE(EXCLUDED.poster_url,content_items.poster_url),
          rating_kp=COALESCE(EXCLUDED.rating_kp,content_items.rating_kp),
          rating_imdb=COALESCE(EXCLUDED.rating_imdb,content_items.rating_imdb),
          duration_min=COALESCE(EXCLUDED.duration_min,content_items.duration_min),
          total_episodes=CASE WHEN EXCLUDED.total_episodes>0 THEN EXCLUDED.total_episodes ELSE content_items.total_episodes END,
          countries=CASE WHEN cardinality(EXCLUDED.countries)>0 THEN EXCLUDED.countries ELSE content_items.countries END,
          age_rating=COALESCE(EXCLUDED.age_rating,content_items.age_rating),
          watchability=CASE WHEN jsonb_array_length(EXCLUDED.watchability)>0 THEN EXCLUDED.watchability ELSE content_items.watchability END,
          fetched_at=now(), updated_at=now()
        RETURNING id"""), {
        "kp": d.kinopoisk_id, "imdb": d.imdb_id, "tmdb": d.tmdb_id, "type": d.type_code, "serial": d.is_serial,
        "title": d.title[:300], "orig": (d.original_title or None) and d.original_title[:300], "year": d.year,
        "descr": d.description, "short": d.short_description, "poster": d.poster_url, "rkp": d.rating_kp,
        "rimdb": d.rating_imdb, "dur": d.duration_min, "eps": d.total_episodes, "countries": d.countries,
        "age": d.age_rating, "watch": json.dumps(d.watchability, ensure_ascii=False),
    })).scalar_one()

    if d.genres:
        await conn.execute(text("DELETE FROM content_genres WHERE content_id=:c"), {"c": cid})
        for g in d.genres:
            gid = (await conn.execute(text(
                "INSERT INTO genres(name) VALUES (:n) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id"),
                {"n": g[:80]})).scalar_one()
            await conn.execute(text(
                "INSERT INTO content_genres(content_id,genre_id) VALUES (:c,:g) ON CONFLICT DO NOTHING"), {"c": cid, "g": gid})

    if d.people:
        await conn.execute(text("DELETE FROM content_people WHERE content_id=:c"), {"c": cid})
        for p in d.people:
            if p.kinopoisk_id:
                pid = (await conn.execute(text("""
                    INSERT INTO people(kinopoisk_id,name,en_name,photo_url) VALUES (:k,:n,:e,:p)
                    ON CONFLICT (kinopoisk_id) DO UPDATE SET name=EXCLUDED.name, en_name=EXCLUDED.en_name,
                      photo_url=COALESCE(EXCLUDED.photo_url,people.photo_url) RETURNING id"""),
                    {"k": p.kinopoisk_id, "n": p.name[:200], "e": p.en_name, "p": p.photo_url})).scalar_one()
            else:
                pid = (await conn.execute(text("""
                    INSERT INTO people(name) VALUES (:n)
                    ON CONFLICT (lower(name)) WHERE kinopoisk_id IS NULL DO UPDATE SET name=people.name RETURNING id"""),
                    {"n": p.name[:200]})).scalar_one()
            await conn.execute(text("""
                INSERT INTO content_people(content_id,person_id,role,sort_order) VALUES (:c,:p,:r,:s)
                ON CONFLICT (content_id,person_id,role) DO UPDATE SET sort_order=EXCLUDED.sort_order"""),
                {"c": cid, "p": pid, "r": p.role, "s": p.sort_order})
    return cid


async def save_seasons(conn, content_id: int, seasons: list[SeasonDTO]) -> None:
    for s in seasons:
        sid = (await conn.execute(text("""
            INSERT INTO seasons(content_id,number,episodes_count) VALUES (:c,:n,:k)
            ON CONFLICT (content_id,number) DO UPDATE SET episodes_count=EXCLUDED.episodes_count RETURNING id"""),
            {"c": content_id, "n": s.number, "k": s.episodes_count})).scalar_one()
        if s.episodes:
            await conn.execute(text("""
                INSERT INTO episodes(season_id,number,name,air_date,duration_min) VALUES (:s,:n,:name,:air,:dur)
                ON CONFLICT (season_id,number) DO UPDATE SET name=EXCLUDED.name, air_date=EXCLUDED.air_date,
                  duration_min=EXCLUDED.duration_min"""),
                [{"s": sid, "n": e.number, "name": e.name, "air": e.air_date, "dur": e.duration_min} for e in s.episodes])
    total = sum(s.episodes_count for s in seasons)
    if total:
        await conn.execute(text("UPDATE content_items SET total_episodes=:t WHERE id=:c"), {"t": total, "c": content_id})


async def get_or_fetch(conn, provider, kp_id: int, with_seasons: bool = True) -> int:
    """Возвращает content_id; если карточки нет или она старая — берёт из провайдера (с кэшем)."""
    row = (await conn.execute(text(
        "SELECT id, fetched_at, is_serial, total_episodes FROM content_items WHERE kinopoisk_id=:k"), {"k": kp_id})).mappings().first()
    fresh = (row and row["fetched_at"] and
             datetime.now(timezone.utc) - row["fetched_at"] < CARD_TTL and
             (not row["is_serial"] or row["total_episodes"] > 0))
    if fresh:
        return row["id"]
    dto = await provider.by_kinopoisk_id(kp_id)
    cid = await upsert_content(conn, dto)
    if dto.is_serial and with_seasons:
        try:
            await save_seasons(conn, cid, await provider.seasons(kp_id))
        except ProviderError:       # сезоны — приятный бонус, их сбой не должен ломать добавление
            pass
    return cid


async def get_card(conn, content_id: int, user_id: int | None = None) -> dict | None:
    c = (await conn.execute(text("SELECT * FROM content_items WHERE id=:i"), {"i": content_id})).mappings().first()
    if not c:
        return None
    c = dict(c)
    if c["kinopoisk_id"] is None and c["created_by"] != user_id:      # ручная запись видна автору и если она публична
        pub = (await conn.execute(text(
            "SELECT 1 FROM user_content WHERE content_id=:c AND visibility='public' LIMIT 1"), {"c": content_id})).first()
        if not pub:
            return None
    c["genres"] = [r[0] for r in (await conn.execute(text(
        "SELECT g.name FROM content_genres cg JOIN genres g ON g.id=cg.genre_id WHERE cg.content_id=:c ORDER BY g.name"),
        {"c": content_id})).all()]
    people = (await conn.execute(text(
        "SELECT p.id,p.name,p.photo_url,cp.role FROM content_people cp JOIN people p ON p.id=cp.person_id "
        "WHERE cp.content_id=:c ORDER BY cp.role, cp.sort_order"), {"c": content_id})).mappings().all()
    c["directors"] = [dict(p) for p in people if p["role"] == "director"]
    c["actors"] = [dict(p) for p in people if p["role"] == "actor"]
    c["seasons"] = [dict(r) for r in (await conn.execute(text(
        "SELECT number, episodes_count FROM seasons WHERE content_id=:c ORDER BY number"), {"c": content_id})).mappings().all()]
    if user_id:
        st = (await conn.execute(text("""
            SELECT uc.status_code, uc.watched_eps, uc.visibility, r.stars, rv.body AS review
            FROM user_content uc
            LEFT JOIN ratings r ON r.user_id=uc.user_id AND r.content_id=uc.content_id
            LEFT JOIN reviews rv ON rv.user_id=uc.user_id AND rv.content_id=uc.content_id
            WHERE uc.user_id=:u AND uc.content_id=:c"""), {"u": user_id, "c": content_id})).mappings().first()
        c["mine"] = dict(st) if st else None
    return c
