from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    func,
)
from sqlalchemy.orm import relationship

from app.database import Base


# ============================================================
#                           USER
# ============================================================
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, default="")
    email = Column(String, default="")
    balance = Column(Integer, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tickets = relationship("Ticket", back_populates="user")
    entries = relationship("RaffleEntry", back_populates="user")


# ============================================================
#                          TICKET
# ============================================================
class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True)
    code = Column(String, unique=True, index=True, nullable=False)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="tickets")


# ============================================================
#                       RAFFLE ENTRY
# ============================================================
class RaffleEntry(Base):
    __tablename__ = "raffle_entries"

    id = Column(Integer, primary_key=True)

    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    reference = Column(String, unique=True, index=True, nullable=False)

    amount = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)

    confirmed = Column(Boolean, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="entries")


# ============================================================
#                       TRANSACTION
# ============================================================
class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True)

    reference = Column(String, index=True)
    amount = Column(Integer)
    status = Column(String, default="pending")

    user_id = Column(Integer, ForeignKey("users.id"))

    created_at = Column(DateTime(timezone=True), server_default=func.now())


# ============================================================
#                          WINNER
# ============================================================
class Winner(Base):
    __tablename__ = "winners"

    id = Column(Integer, primary_key=True)

    ticket_code = Column(String, index=True)
    user_id = Column(Integer)

    announced_by = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
