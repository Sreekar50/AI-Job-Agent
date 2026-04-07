"""
Initialize the database — creates all tables.
Run once: python scripts/init_db.py
"""
import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.db.database import engine, Base
from backend.db import models  # noqa
from loguru import logger


async def init():
    logger.info("Creating database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("All tables created successfully.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(init())
