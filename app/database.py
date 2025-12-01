import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Float, DateTime
from sqlalchemy.orm import relationship
from datetime import datetime

DATABASE_URL = os.getenv("DATABASE_URL")

# Provide a sensible local default when env var is not set
if not DATABASE_URL:
    DATABASE_URL = "sqlite+aiosqlite:///./test.db"

# Force async URL for Railway PostgreSQL
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
# 🧩 MODELS
# ======================================================

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=True)
    email = Column(String, unique=True, nullable=True)
    tickets = relationship("Ticket", back_populates="user", cascade="all, delete-orphan")


class RaffleEntry(Base):
    __tablename__ = "raffle_entries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    tickets = Column(Integer, default=0)
    amount = Column(Float)
    reference = Column(String, unique=True)

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    code = Column(String, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="tickets")


async def get_db():
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()



# ======================================================
# 🧩 init_db()
# ======================================================

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
