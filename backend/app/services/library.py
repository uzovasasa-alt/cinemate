"""Личная медиатека: статусы, оценки, рецензии, прогресс, статистика. Общая логика для Web API и бота."""
import re

from sqlalchemy import text

STATUSES = ("plan", "watching", "watched", "dropped", "later")
STATUS_RU = {"plan": "В планах", "watching": "В процессе", "watched": "Просмотрено", "dropped": "Брошено", "later": "Отложено"}


class LibraryError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def _like(q: str) -> str:
    return "%" + re.sub(r"([\\%_])", r"\\\1", q.strip()) + "%"


async def add_to_library(conn, user_id: int, content_id: int, *, status: str = "plan", via: str = "web",
                         source: dict | None = None) -> bool:
    """True — запись создана, False — уже была в медиатеке."""
    if status not in STATUSES:
        raise LibraryError("bad_status", "Неизвестный статус")
    row = (await conn.execute(text("""
        INSERT INTO user_content(user_id,content_id,status_code,added_via) VALUES (:u,:c,:s,:v)
        ON CONFLICT (user_id,content_id) DO NOTHING RETURNING id"""),
        {"u": user_id, "c": content_id, "s": status, "v": via})).first()
    if not row:
        return False
    if source:
        await conn.execute(text("""
            INSERT INTO content_sources(user_content_id,source_type,service_name,url,file_path,file_size_bytes,
              file_format,media_kind,storage_place,note)
            VALUES (:uc,:t,:svc,:url,:fp,:fs,:ff,:mk,:sp,:note)"""), {
            "uc": row[0], "t": source.get("source_type", "streaming"), "svc": source.get("service_name"),
            "url": source.get("url"), "fp": source.get("file_path"), "fs": source.get("file_size_bytes"),
            "ff": source.get("file_format"), "mk": source.get("media_kind"), "sp": source.get("storage_place"),
            "note": source.get("note")})
    await conn.execute(text("SELECT sync_status_collections(:u,:c)"), {"u": user_id, "c": content_id})
    return True


async def _item(conn, user_id: int, content_id: int):
    r = (await conn.execute(text("""
        SELECT uc.id, uc.status_code, uc.watched_eps, ci.is_serial, ci.total_episodes, ci.duration_min, ci.title
        FROM user_content uc JOIN content_items ci ON ci.id=uc.content_id
        WHERE uc.user_id=:u AND uc.content_id=:c"""), {"u": user_id, "c": content_id})).mappings().first()
    if not r:
        raise LibraryError("not_in_library", "Сначала добавьте запись в медиатеку")
    return r


async def _history(conn, user_id, content_id, minutes, episode_id=None):
    await conn.execute(text(
        "INSERT INTO viewing_history(user_id,content_id,episode_id,minutes) VALUES (:u,:c,:e,:m)"),
        {"u": user_id, "c": content_id, "e": episode_id, "m": max(0, int(minutes or 0))})


async def set_status(conn, user_id: int, content_id: int, status: str) -> dict:
    if status not in STATUSES:
        raise LibraryError("bad_status", "Неизвестный статус")
    it = await _item(conn, user_id, content_id)
    prev, eps = it["status_code"], it["watched_eps"]
    if status == "watched" and prev != "watched":
        dur = it["duration_min"] or 0
        if it["is_serial"] and it["total_episodes"]:
            remaining = max(0, it["total_episodes"] - eps)
            eps = it["total_episodes"]
            await _history(conn, user_id, content_id, remaining * dur)
        elif not it["is_serial"]:
            await _history(conn, user_id, content_id, dur)
    await conn.execute(text(
        "UPDATE user_content SET status_code=:s, watched_eps=:e, updated_at=now() WHERE id=:i"),
        {"s": status, "e": eps, "i": it["id"]})
    await conn.execute(text("SELECT sync_status_collections(:u,:c)"), {"u": user_id, "c": content_id})
    return {"status": status, "watched_eps": eps, "title": it["title"]}


async def bump_episode(conn, user_id: int, content_id: int) -> dict:
    """«+1 серия»: двигает счётчик, отмечает следующую серию (если известны эпизоды) и пишет историю."""
    it = await _item(conn, user_id, content_id)
    if not it["is_serial"]:
        raise LibraryError("not_serial", "Это не сериал")
    total = it["total_episodes"]
    if total and it["watched_eps"] >= total:
        raise LibraryError("already_done", "Все серии уже просмотрены")
    new = it["watched_eps"] + 1
    ep = (await conn.execute(text("""
        SELECT e.id FROM episodes e JOIN seasons s ON s.id=e.season_id
        WHERE s.content_id=:c AND NOT EXISTS (SELECT 1 FROM user_episodes ue WHERE ue.user_id=:u AND ue.episode_id=e.id)
        ORDER BY s.number, e.number LIMIT 1"""), {"c": content_id, "u": user_id})).scalar()
    if ep:
        await conn.execute(text("INSERT INTO user_episodes(user_id,episode_id) VALUES (:u,:e) ON CONFLICT DO NOTHING"),
                           {"u": user_id, "e": ep})
    await _history(conn, user_id, content_id, it["duration_min"], ep)
    status = "watched" if total and new >= total else "watching"
    await conn.execute(text("UPDATE user_content SET watched_eps=:n, status_code=:s, updated_at=now() WHERE id=:i"),
                       {"n": new, "s": status, "i": it["id"]})
    await conn.execute(text("SELECT sync_status_collections(:u,:c)"), {"u": user_id, "c": content_id})
    return {"watched_eps": new, "total_episodes": total, "status": status, "title": it["title"]}


async def set_rating(conn, user_id: int, content_id: int, stars: int) -> None:
    if not 1 <= stars <= 5:
        raise LibraryError("bad_rating", "Оценка — от 1 до 5")
    await _item(conn, user_id, content_id)
    await conn.execute(text("""
        INSERT INTO ratings(user_id,content_id,stars) VALUES (:u,:c,:s)
        ON CONFLICT (user_id,content_id) DO UPDATE SET stars=EXCLUDED.stars, updated_at=now()"""),
        {"u": user_id, "c": content_id, "s": stars})


async def set_review(conn, user_id: int, content_id: int, body: str) -> None:
    body = (body or "").strip()[:5000]
    await _item(conn, user_id, content_id)
    if not body:
        await conn.execute(text("DELETE FROM reviews WHERE user_id=:u AND content_id=:c"), {"u": user_id, "c": content_id})
        return
    await conn.execute(text("""
        INSERT INTO reviews(user_id,content_id,body) VALUES (:u,:c,:b)
        ON CONFLICT (user_id,content_id) DO UPDATE SET body=EXCLUDED.body, updated_at=now()"""),
        {"u": user_id, "c": content_id, "b": body})


async def list_library(conn, user_id: int, *, status: str | None = None, type_code: str | None = None,
                       q: str | None = None, limit: int = 50, offset: int = 0) -> list[dict]:
    rows = (await conn.execute(text("""
        SELECT ci.id AS content_id, ci.kinopoisk_id, ci.title, ci.original_title, ci.year, ci.type_code, ci.is_serial,
               ci.poster_url, ci.rating_kp, ci.total_episodes, uc.status_code, uc.watched_eps, uc.updated_at, r.stars,
               (SELECT string_agg(g.name, ', ' ORDER BY g.name) FROM content_genres cg
                  JOIN genres g ON g.id=cg.genre_id WHERE cg.content_id=ci.id) AS genres
        FROM user_content uc
        JOIN content_items ci ON ci.id=uc.content_id
        LEFT JOIN ratings r ON r.user_id=uc.user_id AND r.content_id=ci.id
        WHERE uc.user_id=:u
          AND (CAST(:st AS text) IS NULL OR uc.status_code = CAST(:st AS text))
          AND (CAST(:ty AS text) IS NULL OR ci.type_code = CAST(:ty AS text))
          AND (CAST(:q AS text) IS NULL OR ci.title ILIKE CAST(:q AS text) OR ci.original_title ILIKE CAST(:q AS text))
        ORDER BY uc.updated_at DESC LIMIT :lim OFFSET :off"""),
        {"u": user_id, "st": status, "ty": type_code, "q": _like(q) if q and q.strip() else None,
         "lim": min(max(limit, 1), 100), "off": max(offset, 0)})).mappings().all()
    return [dict(r) for r in rows]


async def random_pick(conn, user_id: int) -> dict | None:
    r = (await conn.execute(text("""
        SELECT ci.id AS content_id, ci.title, ci.year, ci.poster_url, ci.rating_kp, ci.short_description
        FROM user_content uc JOIN content_items ci ON ci.id=uc.content_id
        WHERE uc.user_id=:u AND uc.status_code IN ('plan','later') ORDER BY random() LIMIT 1"""), {"u": user_id})).mappings().first()
    return dict(r) if r else None


async def stats(conn, user_id: int) -> dict:
    def rows(sql, **p):
        return conn.execute(text(sql), {"u": user_id, **p})

    by_status = {r[0]: r[1] for r in (await rows(
        "SELECT status_code, count(*) FROM user_content WHERE user_id=:u GROUP BY 1")).all()}
    minutes = (await rows("SELECT COALESCE(sum(minutes),0) FROM viewing_history WHERE user_id=:u")).scalar_one()
    eps = (await rows("""SELECT COALESCE(sum(uc.watched_eps),0) FROM user_content uc
                         JOIN content_items ci ON ci.id=uc.content_id WHERE uc.user_id=:u AND ci.is_serial""")).scalar_one()
    avg = (await rows("SELECT round(avg(stars)::numeric,1) FROM ratings WHERE user_id=:u")).scalar_one()
    genres = [dict(r) for r in (await rows("""
        SELECT g.name, count(*) AS n FROM user_content uc JOIN content_genres cg ON cg.content_id=uc.content_id
        JOIN genres g ON g.id=cg.genre_id WHERE uc.user_id=:u GROUP BY 1 ORDER BY n DESC, 1 LIMIT 8""")).mappings().all()]

    async def people(role):
        return [dict(r) for r in (await rows("""
            SELECT p.name, count(*) AS n FROM user_content uc JOIN content_people cp ON cp.content_id=uc.content_id
            JOIN people p ON p.id=cp.person_id WHERE uc.user_id=:u AND cp.role=:r
            GROUP BY p.id, p.name ORDER BY n DESC, p.name LIMIT 5""", r=role)).mappings().all()]

    unfinished = [dict(r) for r in (await rows("""
        SELECT ci.id AS content_id, ci.title, uc.watched_eps, ci.total_episodes,
               (now()::date - uc.updated_at::date) AS days_idle
        FROM user_content uc JOIN content_items ci ON ci.id=uc.content_id
        WHERE uc.user_id=:u AND ci.is_serial AND uc.status_code IN ('watching','plan','later')
          AND uc.watched_eps > 0 AND (ci.total_episodes = 0 OR uc.watched_eps < ci.total_episodes)
        ORDER BY uc.updated_at ASC LIMIT 20""")).mappings().all()]
    monthly = [dict(r) for r in (await rows("""
        SELECT to_char(date_trunc('month', watched_at),'YYYY-MM') AS month, round(sum(minutes)/60.0,1) AS hours, count(*) AS events
        FROM viewing_history WHERE user_id=:u GROUP BY 1 ORDER BY 1 DESC LIMIT 12""")).mappings().all()]
    dups = [dict(r) for r in (await rows("""
        SELECT lower(ci.title) AS title, ci.year, count(*) AS n FROM user_content uc JOIN content_items ci ON ci.id=uc.content_id
        WHERE uc.user_id=:u GROUP BY 1,2 HAVING count(*) > 1""")).mappings().all()]
    return {
        "total": sum(by_status.values()), "by_status": by_status,
        "hours": round(minutes / 60, 1), "episodes_watched": int(eps),
        "avg_stars": float(avg) if avg is not None else None,
        "top_genres": genres, "top_directors": await people("director"), "top_actors": await people("actor"),
        "unfinished": unfinished, "monthly": monthly, "possible_duplicates": dups,
    }
