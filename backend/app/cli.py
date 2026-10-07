"""python -m app.cli create_superuser --email you@example.com --name Admin"""
import argparse
import asyncio
import getpass

from sqlalchemy import text

from .db import engine
from .security import hash_password


async def create_superuser(email: str, name: str, password: str) -> None:
    async with engine.begin() as c:
        uid = (await c.execute(text("""
            INSERT INTO users(name,email,password_hash,role) VALUES (:n,:e,:p,'admin')
            ON CONFLICT ((lower(email))) DO UPDATE SET role='admin', password_hash=EXCLUDED.password_hash
            RETURNING id"""), {"n": name, "e": email.lower(), "p": hash_password(password)})).scalar_one()
        await c.execute(text("SELECT bootstrap_user(:u)"), {"u": uid})
    await engine.dispose()
    print(f"Суперпользователь {email} готов (id={uid})")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create_superuser")
    p.add_argument("--email", required=True)
    p.add_argument("--name", default="Admin")
    p.add_argument("--password", help="если не указан — будет запрошен")
    a = ap.parse_args()
    if a.cmd == "create_superuser":
        pw = a.password or getpass.getpass("Пароль (мин. 8 символов): ")
        if len(pw) < 8:
            raise SystemExit("Пароль слишком короткий")
        asyncio.run(create_superuser(a.email, a.name, pw))


if __name__ == "__main__":
    main()
