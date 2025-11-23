# app/database.py

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func

import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///raffle.db")

# Async engine
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True
)

# Async session
async_session = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


# -----------------------
#       MODELS
# -----------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(String, unique=True, index=True)
    referrals = Column(Integer, default=0)
    affiliate_earnings = Column(Integer, default=0)
    joined_at = Column(DateTime(timezone=True), server_default=func.now())


class RaffleEntry(Base):
    __tablename__ = "raffle_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    ticket_code = Column(String, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


# -----------------------
#   INIT DB
# -----------------------

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
