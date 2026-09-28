import os
import logging
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy import event, text
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

# Ustunlar/jadvallar shu ro'yxatga qo'shiladi: (jadval, ustun, DDL turi).
# Idempotent: har bir ustun PRAGMA table_info orqali tekshiriladi, mavjud
# bo'lsa o'tkazib yuboriladi — hech qanday mavjud ma'lumot yo'qolmaydi.
_COLUMN_MIGRATIONS: list[tuple[str, str, str]] = [
    # (Stage 1, media tahlili) — mavjud `text` ustuni OCR/transkripsiya natijasini
    # o'zida saqlaydi; bu ustun faqat qo'shimcha struktura (deadline/summa/talablar
    # va boshqa metama'lumotlar) uchun.
    ("messages", "media_analysis_json", "TEXT"),
    # (Stage 2, triage) — 4-darajali klassifikatsiya natijasi.
    ("messages", "triage_level", "INTEGER"),
    ("messages", "triage_reason", "TEXT"),
    ("messages", "triage_auto_reply", "TEXT"),
    # (Stage 4, dashboard format) — Daraja 3 xabarlar uchun tayyor
    # {xulosa, holat, tavsiya, tahlil} JSON.
    ("messages", "triage_dashboard_json", "TEXT"),
]


async def run_migrations() -> None:
    """Barcha jadvallarni (agar yo'q bo'lsa) yaratadi, so'ng idempotent
    ALTER TABLE ADD COLUMN orqali yetishmayotgan ustunlarni qo'shadi.

    Xavfsiz: mavjud ma'lumotlarga tegmaydi, faqat yo'q narsani qo'shadi.
    """
    from . import models  # noqa: F401  (Base.metadata to'ldirilishi uchun import)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        for table, column, ddl_type in _COLUMN_MIGRATIONS:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing_columns = {row[1] for row in result.fetchall()}
            if column not in existing_columns:
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
                )
                logger.info("[Migratsiya] %s.%s ustuni qo'shildi.", table, column)


async def init_db():
    await run_migrations()
    logger.info("[Database] Bazaga ulanish tekshirildi.")

async def close_db():
    await engine.dispose()
    logger.info("[Database] Bazaga ulanish yopildi.")

async def get_session() -> AsyncSession:
    async with async_session_maker() as session:
        yield session

get_db = get_session

# NOTA BENE (Stage 0 fix, 2026-09-26):
# Bu faylda avval "get_sync_db()" nomli funksiya bor edi — u sync SQLAlchemy
# Session ochib, hardcoded "/home/ubuntu/..." yo'liga ulanardi. Bu butun ilova
# async (aiosqlite) ekanligiga zid edi: bir vaqtda ikkita mustaqil ulanish bitta
# SQLite faylga tegib, "database is locked" xatolarini keltirib chiqarardi va
# boshqa yo'lga o'rnatilgan har qanday serverda darhol ishlamas edi.
# Yechim: barcha chaqiruvchi kod (routers/briefing.py, routers/ai_chat.py,
# opportunity/store.py, opportunity/briefing_service.py) yuqoridagi mavjud
# get_session/get_db async funksiyasidan foydalanadigan qilib qayta yozildi.
# get_sync_db() endi mavjud emas — uni import qilishga urinish ImportError beradi,
# bu ataylab shunday: eski xato pattern qaytarilib qolmasligi uchun.
