# app/database.py
import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import os

# ---------------------------------
# Database Configuration
# ---------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///raffle.db")

# Base model
Base = declarative_base()

# ---------------------------------
# Models
# ---------------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    referral_count = Column(Integer, default=0)
    referred_by = Column(Integer, ForeignKey("users.telegram_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    affiliate_code = Column(String, unique=True, nullable=True)
    commission_balance = Column(Integer, default=0)

    tickets = relationship("RaffleEntry", back_populates="user", cascade="all, delete-orphan")


class RaffleEntry(Base):
    __tablename__ = "raffle_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    payment_ref = Column(String, unique=True, nullable=True)
    free_ticket = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="tickets")

# ---------------------------------
# Async Database Engine + Session
# ---------------------------------
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# ---------------------------------
# Utility to Initialize DB
# ---------------------------------
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
