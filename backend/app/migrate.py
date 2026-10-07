"""Минимальный раннер миграций: применяет migrations/*.sql по порядку и помнит применённые.
Запуск: python -m app.migrate   (позже можно заменить на Alembic)."""
import asyncio
from pathlib import Path

import asyncpg

from .config import get_settings

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


async def run() -> None:
    conn = await asyncpg.connect(get_settings().asyncpg_dsn)
    try:
        await conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())")
        done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name in done:
                continue
            print("apply", f.name)
            async with conn.transaction():
                await conn.execute(f.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO schema_migrations(name) VALUES ($1)", f.name)
        print("migrations up to date")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run())
