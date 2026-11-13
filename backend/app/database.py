from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


_settings = get_settings()

# Neon's pooled endpoint ("-pooler" in the host) is PgBouncer in transaction mode, which cannot keep asyncpg's
# prepared statements. Turn the statement caches off there; the direct endpoint is unaffected.
_connect_args: dict[str, int] = (
    {"statement_cache_size": 0, "prepared_statement_cache_size": 0} if "-pooler" in _settings.DATABASE_URL else {}
)

engine = create_async_engine(
    _settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_recycle=300,  # serverless Postgres (Neon) drops idle connections
    connect_args=_connect_args,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Callers commit explicitly; session is closed (rolled back) on exit."""
    async with async_session_factory() as session:
        yield session


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


def get_session_factory() -> SessionFactory:
    """FastAPI dependency: opens independent sessions (streaming responses and background tasks outlive the request session)."""
    return async_session_factory
