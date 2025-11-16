import datetime
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.orm import relationship, declarative_base

# Base model for all tables
Base = declarative_base()

# -----------------------------
# USER MODEL
# -----------------------------
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    username = Column(String, nullable=True)
    referral_count = Column(Integer, default=0)
    referred_by = Column(Integer, ForeignKey("users.telegram_id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    ticket_code = Column(String, nullable=False, unique=True)
    free_ticket = Column(Boolean, default=False)

    # Relationship to raffle entries
    tickets = relationship("RaffleEntry", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"

# -----------------------------
# RAFFLE ENTRY MODEL
# -----------------------------
class RaffleEntry(Base):
    __tablename__ = "raffle_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    payment_ref = Column(String, unique=True, nullable=True)
    free_ticket = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationship to user
    user = relationship("User", back_populates="tickets")

    def __repr__(self):
        return f"<RaffleEntry(id={self.id}, user_id={self.user_id}, free_ticket={self.free_ticket})>"
