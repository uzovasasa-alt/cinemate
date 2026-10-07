#!/usr/bin/env python3
"""Перенос данных CineVault (MySQL) → Cinemate (PostgreSQL).

Идемпотентен: во всех таблицах используются legacy_*_id и UPSERT, повторный запуск ничего не дублирует.
Всё выполняется в одной транзакции PostgreSQL — при ошибке откатывается целиком.

Запуск:
  pip install pymysql "psycopg[binary]"
  MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306 MYSQL_DB=cinevault MYSQL_USER=root MYSQL_PASS=root \
  PG_DSN="postgresql://cinemate:cinemate@localhost:5432/cinemate" \
  python scripts/migrate_mysql_to_pg.py [--dry-run]

[Предположение] Время в MySQL хранилось в UTC. Оценка 1–10 переводится в 1–5 как int(x/2+0.5),
исходное значение сохраняется в ratings.legacy_rating10. Теги CineVault в новой схеме не переносятся
(в отчёте указано, сколько связей пропущено).
"""
import argparse
import os
import re
from datetime import datetime, timezone

import psycopg
import pymysql
import pymysql.cursors

SRC_MAP = {"stream": "streaming", "file": "local", "disc": "physical", "other": "other"}


def utc(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if isinstance(dt, datetime) and dt.tzinfo is None else dt


def split_list(s, seps=r"[,;]+"):
    return [x.strip() for x in re.split(seps, s or "") if x.strip()]


def stars_from10(r):
    if r is None:
        return None
    return max(1, min(5, int(float(r) / 2 + 0.5)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="выполнить всё и откатить")
    args = ap.parse_args()

    my = pymysql.connect(host=os.getenv("MYSQL_HOST", "127.0.0.1"), port=int(os.getenv("MYSQL_PORT", "3306")),
                         user=os.getenv("MYSQL_USER", "root"), password=os.getenv("MYSQL_PASS", ""),
                         database=os.getenv("MYSQL_DB", "cinevault"), charset="utf8mb4",
                         cursorclass=pymysql.cursors.DictCursor)
    pg = psycopg.connect(os.environ["PG_DSN"])
    mc = my.cursor()

    def q(sql, *p):
        mc.execute(sql, p)
        return mc.fetchall()

    stats = {}
    with pg.transaction():
        cur = pg.cursor()

        umap = {}
        for u in q("SELECT * FROM users ORDER BY id"):
            cur.execute("""INSERT INTO users(legacy_user_id,name,email,password_hash,role,created_at)
                           VALUES (%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (legacy_user_id) DO UPDATE SET name=EXCLUDED.name, role=EXCLUDED.role
                           RETURNING id""",
                        (u["id"], u["name"], u["email"].lower(), u["password_hash"], u["role"], utc(u["created_at"])))
            umap[u["id"]] = cur.fetchone()[0]
            cur.execute("SELECT bootstrap_user(%s)", (umap[u["id"]],))
        stats["users"] = len(umap)

        cmap, ucmap = {}, {}
        for t in q("SELECT * FROM titles ORDER BY id"):
            owner = umap[t["owner_id"]]
            genres = split_list(t["genres"])
            type_code = "documentary" if any("документ" in g.lower() for g in genres) else (
                "series" if t["type"] == "series" else "movie")
            cur.execute("""
                INSERT INTO content_items(legacy_title_id,type_code,is_serial,title,original_title,year,countries,
                    duration_min,total_episodes,poster_url,created_by,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (legacy_title_id) DO UPDATE SET title=EXCLUDED.title, year=EXCLUDED.year,
                    duration_min=EXCLUDED.duration_min, total_episodes=EXCLUDED.total_episodes, updated_at=now()
                RETURNING id""",
                        (t["id"], type_code, t["type"] == "series", t["name"], t["original_name"] or None, t["year"],
                         split_list(t["country"]), t["duration"] or None, t["total_eps"] or 0, t["poster"] or None,
                         owner, utc(t["created_at"]), utc(t["updated_at"])))
            cid = cur.fetchone()[0]
            cmap[t["id"]] = cid

            cur.execute("DELETE FROM content_genres WHERE content_id=%s", (cid,))
            for g in genres:
                cur.execute("INSERT INTO genres(name) VALUES (%s) ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING id", (g,))
                cur.execute("INSERT INTO content_genres VALUES (%s,%s) ON CONFLICT DO NOTHING", (cid, cur.fetchone()[0]))

            cur.execute("DELETE FROM content_people WHERE content_id=%s", (cid,))
            for role, raw in (("director", t["director"]), ("actor", t["actors"])):
                for i, name in enumerate(split_list(raw), 1):
                    cur.execute("""INSERT INTO people(name) VALUES (%s)
                                   ON CONFLICT (lower(name)) WHERE kinopoisk_id IS NULL DO UPDATE SET name=people.name
                                   RETURNING id""", (name[:200],))
                    cur.execute("INSERT INTO content_people(content_id,person_id,role,sort_order) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                                (cid, cur.fetchone()[0], role, i))

            cur.execute("""
                INSERT INTO user_content(user_id,content_id,status_code,watched_eps,plan_date,visibility,added_via,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,'migration',%s,%s)
                ON CONFLICT (user_id,content_id) DO UPDATE SET status_code=EXCLUDED.status_code,
                    watched_eps=EXCLUDED.watched_eps, plan_date=EXCLUDED.plan_date, visibility=EXCLUDED.visibility
                RETURNING id""",
                        (owner, cid, t["status"], t["done_eps"] or 0, t["plan_date"], t["visibility"],
                         utc(t["created_at"]), utc(t["updated_at"])))
            ucid = cur.fetchone()[0]
            ucmap[t["id"]] = ucid

            cur.execute("DELETE FROM content_sources WHERE user_content_id=%s", (ucid,))
            loc = (t["location"] or "").strip()
            stype = SRC_MAP.get(t["source"], "other")
            cur.execute("""INSERT INTO content_sources(user_content_id,source_type,url,file_path,storage_place,note)
                           VALUES (%s,%s,%s,%s,%s,%s)""",
                        (ucid, stype,
                         loc if stype == "streaming" and loc.lower().startswith("http") else None,
                         loc if stype == "local" else None,
                         loc if stype == "physical" else None,
                         loc if stype in ("streaming", "other") and not loc.lower().startswith("http") and loc else None))

            if t["rating"] is not None:
                cur.execute("""INSERT INTO ratings(user_id,content_id,stars,legacy_rating10) VALUES (%s,%s,%s,%s)
                               ON CONFLICT (user_id,content_id) DO UPDATE SET stars=EXCLUDED.stars, legacy_rating10=EXCLUDED.legacy_rating10""",
                            (owner, cid, stars_from10(t["rating"]), t["rating"]))
            if (t["review"] or "").strip():
                cur.execute("""INSERT INTO reviews(user_id,content_id,body) VALUES (%s,%s,%s)
                               ON CONFLICT (user_id,content_id) DO UPDATE SET body=EXCLUDED.body""",
                            (owner, cid, t["review"].strip()))
        stats["titles"] = len(cmap)
        stats["legacy_tags_skipped"] = q("SELECT count(*) c FROM title_tags")[0]["c"]

        smap, emap = {}, {}
        for s in q("SELECT * FROM seasons ORDER BY id"):
            if s["title_id"] not in cmap:
                continue
            cur.execute("""INSERT INTO seasons(content_id,number,episodes_count,legacy_season_id) VALUES (%s,%s,%s,%s)
                           ON CONFLICT (legacy_season_id) DO UPDATE SET episodes_count=EXCLUDED.episodes_count RETURNING id""",
                        (cmap[s["title_id"]], s["season_no"], s["total_eps"], s["id"]))
            smap[s["id"]] = cur.fetchone()[0]
        owner_of_season = {s["id"]: s["title_id"] for s in q("SELECT id,title_id FROM seasons")}
        title_owner = {t["id"]: t["owner_id"] for t in q("SELECT id,owner_id FROM titles")}
        for e in q("SELECT * FROM episodes ORDER BY id"):
            if e["season_id"] not in smap:
                continue
            cur.execute("""INSERT INTO episodes(season_id,number,name,duration_min,legacy_episode_id) VALUES (%s,%s,%s,%s,%s)
                           ON CONFLICT (legacy_episode_id) DO UPDATE SET name=EXCLUDED.name RETURNING id""",
                        (smap[e["season_id"]], e["episode_no"], e["name"], e["duration"] or None, e["id"]))
            emap[e["id"]] = cur.fetchone()[0]
            if e["watched"]:
                owner = umap[title_owner[owner_of_season[e["season_id"]]]]
                cur.execute("INSERT INTO user_episodes(user_id,episode_id,watched_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                            (owner, emap[e["id"]], utc(e["watched_at"]) or datetime.now(timezone.utc)))
        stats["episodes"] = len(emap)

        colmap = {}
        for c in q("SELECT * FROM collections ORDER BY id"):
            cur.execute("""INSERT INTO collections(legacy_collection_id,owner_id,name,description,visibility,created_at,updated_at)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (legacy_collection_id) DO UPDATE SET name=EXCLUDED.name,
                               description=EXCLUDED.description, visibility=EXCLUDED.visibility RETURNING id""",
                        (c["id"], umap[c["owner_id"]], c["name"], c["description"], c["visibility"],
                         utc(c["created_at"]), utc(c["updated_at"])))
            colmap[c["id"]] = cur.fetchone()[0]
        for m in q("SELECT * FROM collection_members"):
            cur.execute("""INSERT INTO collection_members(collection_id,user_id,member_role) VALUES (%s,%s,%s)
                           ON CONFLICT (collection_id,user_id) DO UPDATE SET member_role=EXCLUDED.member_role""",
                        (colmap[m["collection_id"]], umap[m["user_id"]], m["member_role"]))
        for ct in q("SELECT * FROM collection_titles"):
            if ct["title_id"] in cmap:
                cur.execute("INSERT INTO collection_items(collection_id,content_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                            (colmap[ct["collection_id"]], cmap[ct["title_id"]]))
        stats["collections"] = len(colmap)

        nfav = 0
        for f in q("SELECT * FROM favorites"):
            if f["title_id"] in cmap:
                cur.execute("""INSERT INTO collection_items(collection_id,content_id)
                               SELECT id,%s FROM collections WHERE owner_id=%s AND system_code='favorites'
                               ON CONFLICT DO NOTHING""", (cmap[f["title_id"]], umap[f["user_id"]]))
                nfav += 1
        stats["favorites"] = nfav

        for uid in umap.values():
            cur.execute("SELECT sync_status_collections(%s)", (uid,))

        nh = 0
        for h in q("SELECT * FROM watch_history ORDER BY id"):
            if h["title_id"] not in cmap:
                continue
            cur.execute("""INSERT INTO viewing_history(legacy_history_id,user_id,content_id,episode_id,watched_at,minutes)
                           VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (legacy_history_id) DO NOTHING""",
                        (h["id"], umap[h["user_id"]], cmap[h["title_id"]], emap.get(h["episode_id"]),
                         utc(h["watched_at"]) or datetime.now(timezone.utc), h["duration"] or 0))
            nh += 1
        stats["history"] = nh

        nr = 0
        for r in q("SELECT * FROM reminders ORDER BY id"):
            if r["title_id"] not in cmap:
                continue
            cur.execute("""INSERT INTO notifications(legacy_reminder_id,user_id,kind,content_id,scheduled_at,status)
                           VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (legacy_reminder_id) DO NOTHING""",
                        (r["id"], umap[r["user_id"]], r["kind"], cmap[r["title_id"]],
                         datetime.combine(r["remind_date"], datetime.min.time(), tzinfo=timezone.utc),
                         "done" if r["done"] else "pending"))
            nr += 1
        stats["reminders"] = nr

        checks = [("users", "SELECT count(*) FROM users WHERE legacy_user_id IS NOT NULL", "SELECT count(*) c FROM users"),
                  ("titles", "SELECT count(*) FROM content_items WHERE legacy_title_id IS NOT NULL", "SELECT count(*) c FROM titles"),
                  ("collections", "SELECT count(*) FROM collections WHERE legacy_collection_id IS NOT NULL", "SELECT count(*) c FROM collections")]
        ok = True
        for name, pg_sql, my_sql in checks:
            cur.execute(pg_sql)
            a, b = cur.fetchone()[0], q(my_sql)[0]["c"]
            ok &= a == b
            print(("OK " if a == b else "ОШИБКА"), f"{name}: MySQL={b} PG={a}")
        if not ok:
            raise SystemExit("Сверка не прошла — транзакция откатана")
        if args.dry_run:
            print("--dry-run: откат")
            raise psycopg.Rollback

    print("Готово:", stats)


if __name__ == "__main__":
    try:
        main()
    except psycopg.Rollback:
        pass
