import os
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base

# ============================================================
#                      DATABASE CONFIG
# ============================================================
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./raffle.db"
)

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

async_session = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

Base = declarative_base()


# ============================================================
#                   INIT DB (STARTUP)
# ============================================================
async def init_db():
    """
    Create tables if they don't exist
    """
    from app import models  # ⬅ lazy import avoids circular errors

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
