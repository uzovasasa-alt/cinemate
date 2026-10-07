from sqlalchemy import text


async def blocked(conn, key: str, max_attempts: int, minutes: int = 15) -> bool:
    n = (await conn.execute(
        text("SELECT count(*) FROM login_attempts WHERE k=:k AND created_at > now() - make_interval(mins => :m)"),
        {"k": key, "m": minutes})).scalar_one()
    return n >= max_attempts


async def hit(conn, key: str) -> None:
    await conn.execute(text("INSERT INTO login_attempts(k) VALUES (:k)"), {"k": key})
    await conn.execute(text("DELETE FROM login_attempts WHERE created_at < now() - interval '1 day' AND random() < 0.02"))
