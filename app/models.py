from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(Integer, unique=True, index=True)
    username = Column(String)
    balance = Column(Integer, default=0)
    referral_count = Column(Integer, default=0)
    affiliate_earnings = Column(Integer, default=0)
    referral_code = Column(String, unique=True, index=True)

class RaffleEntry(Base):
    __tablename__ = "raffle_entries"
    id = Column(Integer, primary_key=True, index=True)
    ticket_code = Column(String, unique=True, index=True)
    free_ticket = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey("users.id"))
    user = relationship("User", back_populates="tickets")

User.tickets = relationship("RaffleEntry", back_populates="user")
