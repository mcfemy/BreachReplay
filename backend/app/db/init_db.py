from app.db.session import Base, engine
from app.models import *
from app.core.logging import get_logger
import asyncio


logger = get_logger(__name__)


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created.")


if __name__ == "__main__":
    asyncio.run(init_db())
