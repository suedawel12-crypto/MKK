from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean, DateTime, JSON, ForeignKey, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime
import json

from config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_size=20,
    max_overflow=40,
    pool_pre_ping=True
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(String, unique=True, nullable=False, index=True)
    username = Column(String)
    first_name = Column(String)
    last_name = Column(String)
    wallet_balance = Column(Float, default=0.0)
    is_blocked = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    ip_addresses = Column(JSONB, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    
    cards = relationship("Card", back_populates="user")
    transactions = relationship("Transaction", back_populates="user")

class Room(Base):
    __tablename__ = "rooms"
    
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(String)
    card_price = Column(Float, default=1.0)
    max_players = Column(Integer, default=100)
    status = Column(String, default="active")  # active, inactive
    created_at = Column(DateTime, default=datetime.utcnow)
    
    rounds = relationship("Round", back_populates="room")

class Round(Base):
    __tablename__ = "rounds"
    
    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), index=True)
    status = Column(String, default="waiting")  # waiting, active, completed, jackpot
    total_pool = Column(Float, default=0.0)
    jackpot_pool = Column(Float, default=0.0)
    winner_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    winner_amount = Column(Float, default=0.0)
    numbers_called = Column(JSONB, default=list)
    start_time = Column(DateTime, nullable=True)
    end_time = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    room = relationship("Room", back_populates="rounds")
    cards = relationship("Card", back_populates="round")
    called_numbers = relationship("CalledNumber", back_populates="round")
    winner = relationship("User", foreign_keys=[winner_id])

class Card(Base):
    __tablename__ = "cards"
    __table_args__ = (
        Index('idx_round_user', 'round_id', 'user_id'),
        Index('idx_unique_card', 'round_id', 'user_id', unique=True),
    )
    
    id = Column(Integer, primary_key=True)
    round_id = Column(Integer, ForeignKey("rounds.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    numbers = Column(JSONB, nullable=False)  # 3x9 grid for 75-ball
    marked_numbers = Column(JSONB, default=list)
    claimed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    round = relationship("Round", back_populates="cards")
    user = relationship("User", back_populates="cards")

class CalledNumber(Base):
    __tablename__ = "called_numbers"
    
    id = Column(Integer, primary_key=True)
    round_id = Column(Integer, ForeignKey("rounds.id"), index=True)
    number = Column(Integer, nullable=False)
    called_at = Column(DateTime, default=datetime.utcnow)
    
    round = relationship("Round", back_populates="called_numbers")

class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index('idx_user_timestamp', 'user_id', 'timestamp'),
    )
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    amount = Column(Float, nullable=False)
    type = Column(String, nullable=False)  # deposit, buy_card, win, jackpot, commission
    reference_id = Column(String, nullable=True)
    status = Column(String, default="completed")  # pending, completed, failed
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="transactions")

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True)
    action = Column(String, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    details = Column(JSONB, default=dict)
    ip_address = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User")

# Create tables
def init_db():
    Base.metadata.create_all(bind=engine)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()