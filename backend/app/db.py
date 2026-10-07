from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from .config import get_settings

engine = create_async_engine(get_settings().database_url, pool_size=10, max_overflow=10, pool_pre_ping=True)


async def get_conn() -> AsyncIterator[AsyncConnection]:
    """Одна транзакция на запрос: commit при успехе, rollback при исключении."""
    async with engine.begin() as conn:
        yield conn
