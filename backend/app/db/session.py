from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

engine_kwargs = {"echo": settings.DEBUG, "pool_pre_ping": True, "pool_recycle": 1800}
if not settings.DATABASE_URL.startswith("sqlite"):
    engine_kwargs.update({"pool_size": 10, "max_overflow": 20})

engine = create_async_engine(
    settings.DATABASE_URL,
    **engine_kwargs,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Synchronous engine for Celery workers (avoids asyncio.run overhead)
_sync_engine_kwargs: dict = {"pool_pre_ping": True, "pool_recycle": 1800}
if not settings.SYNC_DATABASE_URL.startswith("sqlite"):
    _sync_engine_kwargs.update({"pool_size": 5, "max_overflow": 10})

sync_engine = create_engine(settings.SYNC_DATABASE_URL, **_sync_engine_kwargs)
SyncSessionLocal = sessionmaker(bind=sync_engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
