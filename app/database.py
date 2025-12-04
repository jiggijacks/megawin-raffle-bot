import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import (
    Column, Integer, String, Boolean, ForeignKey, Float, DateTime, func
)
from sqlalchemy.orm import relationship
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

# sensible default for local dev
if not DATABASE_URL:
    DATABASE_URL = "sqlite+aiosqlite:///raffle.db"

# force async URL if Heroku-style postgres url
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://")

engine = create_async_engine(DATABASE_URL, echo=False)

async_session = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    class_=AsyncSession,
)

Base = declarative_base()


# ======================================================
# MODELS
# ======================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    email = Column(String, unique=True, nullable=True)
    balance = Column(Float, default=0.0)
    created_at = Column(DateTime, default=func.now())

    tickets = relationship("Ticket", back_populates="user", cascade="all, delete-orphan")
    raffle_entries = relationship("RaffleEntry", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")


class RaffleEntry(Base):
    __tablename__ = "raffle_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    quantity = Column(Integer, default=0)
    amount = Column(Float, default=0.0)
    reference = Column(String, unique=True, nullable=False, index=True)
    confirmed = Column(Boolean, default=False)  # becomes True when payment is verified
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="raffle_entries")


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    code = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="tickets")


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Float, nullable=False)
    reference = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="transactions")


class Winner(Base):
    __tablename__ = "winners"

    id = Column(Integer, primary_key=True)
    ticket_code = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    announced_by = Column(String, nullable=True)
    notes = Column(String, nullable=True)
    announced_at = Column(DateTime, default=func.now())


# ======================================================
# DB helpers
# ======================================================

async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
