import os
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import event
from sqlalchemy.engine import Engine

logger = logging.getLogger("telegram_focus.database")

BACKEND_DIR = Path(__file__).resolve().parents[1]
DB_DIR = str(BACKEND_DIR / "data")
os.makedirs(DB_DIR, exist_ok=True)
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite+aiosqlite:///{DB_DIR}/focus.db"

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=60000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 60.0}
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)

async_session_factory = async_session_maker
AsyncSessionLocal = async_session_maker
Base = declarative_base()

async def init_db():
    logger.info("[Database] Bazaga ulanish tekshirildi.")

async def close_db():
    await engine.dispose()
    logger.info("[Database] Bazaga ulanish yopildi.")

async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session

get_db = get_session
