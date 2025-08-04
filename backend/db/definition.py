

from sqlalchemy import create_engine, insert, ForeignKey, Column, Integer, String, Text, Float, DateTime, Boolean, Enum
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.declarative import declarative_base
import os 
from datetime import datetime
from sqlalchemy.dialects.postgresql import UUID
import uuid


ASYNC_DATABASE_URL = f"postgresql+asyncpg://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT','5432')}/{os.getenv('POSTGRES_DB')}?sslmode=require"

DATABASE_URL = f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT','5432')}/{os.getenv('POSTGRES_DB')}?sslmode=require"
# Set up the async database engine and session
async_engine = create_async_engine(ASYNC_DATABASE_URL, echo=True, pool_size=10, max_overflow=20, pool_timeout=5, pool_recycle=1800,pool_pre_ping=True)
engine = create_engine(DATABASE_URL, echo=True, pool_size=10, max_overflow=20, pool_timeout=5, pool_recycle=1800,pool_pre_ping=True)
Base = declarative_base()
DEFAULT_ELO = 1000


class Agents(Base):
    __tablename__ = "agents"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now)
    elo = Column(Integer, nullable=False, default=DEFAULT_ELO)


class Matches(Base):
    __tablename__ = "matches"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    agent1_id = Column(UUID, ForeignKey("agents.id"), nullable=False)
    agent2_id = Column(UUID, ForeignKey("agents.id"), nullable=False)
    agent1_default = Column(Boolean, nullable=False, default=False)
    agent2_default = Column(Boolean, nullable=False, default=False)
    result = Column(Integer, nullable=False) # 0: draw, 1: agent1 wins, 2: agent2 wins
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class Transcripts(Base):
    __tablename__ = "transcripts"
    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    match_id = Column(UUID, ForeignKey("matches.id"), nullable=False)
    message = Column(Text, nullable=False)
    agent_id = Column(Integer, nullable=False) # 1: agent1, 2: agent2
    created_at = Column(DateTime, nullable=False, default=datetime.now)
