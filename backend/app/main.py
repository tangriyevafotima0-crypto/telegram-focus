import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
from fastapi import FastAPI
from app.routers import briefing

from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .database import close_db, init_db
from .database import async_session_factory
from .email_worker import email_worker_loop
from .opportunity import bot_commands as opportunity_bot_commands
from .opportunity import delivery as opportunity_delivery
from .opportunity.engine import catch_up as opportunity_catch_up
from .opportunity import store as opportunity_store
from .routers.email import router as email_router
from .routers.messages import message_manager, run_auto_archive_once
from .routers.messages import router as messages_router
from .routers.opportunity import router as opportunity_router
from .routers.sources import router as sources_router
from app.routers.ai_chat import router as ai_chat_router
from .settings_store import read_archive_settings
from .telethon_client import get_client, run_telegram_client, stop_telegram_client


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")

AUTO_ARCHIVE_INTERVAL_SECONDS = 6 * 60 * 60


async def _auto_archive_loop() -> None:
    while True:
        try:
            await asyncio.sleep(AUTO_ARCHIVE_INTERVAL_SECONDS)
            settings = read_archive_settings()
            if settings.get("auto_archive_days", 0) > 0:
                async with async_session_factory() as session:
                    count = await run_auto_archive_once(session)
                    if count:
                        logger.info("Avtomatik arxiv: %s ta xabar arxivlandi.", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Avtomatik arxiv siklida xato")


async def _opportunity_catchup_once() -> None:
    """Ishga tushganda: enabled bo'lsa, Telethon ulanishini kutib bir marta tiklaydi."""
    for _ in range(30):  # ~60s gacha kutadi (Telethon login/ulanish uchun)
        try:
            client = get_client()
            break
        except RuntimeError:
            await asyncio.sleep(2)
    else:
        logger.warning("Imkoniyat tiklash: Telegram mijozi ulanmadi (timeout).")
        return
    try:
        settings = await opportunity_store.get_settings()
        if not settings.get("enabled"):
            return
        found = await opportunity_catch_up(client, message_manager.broadcast)
        if found:
            logger.info("Imkoniyat tiklash (catch_up): %s ta topildi.", found)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Imkoniyat tiklash (catch_up) xatosi")


async def _guarded(name: str, coro_factory) -> None:
    """Fon vazifa o'z himoya o'rami ichida: yiqilsa faqat log yoziladi, boshqalarga tegmaydi."""
    try:
        await coro_factory()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Fon vazifa '%s' to'xtadi (boshqalari ishlashda davom etadi)", name)


async def _bot_startup() -> None:
    """BOT_TOKEN bo'lsa bot klientini ishga tushiradi va (OWNER_ID bilan) buyruqlarni ulaydi."""
    client = await opportunity_delivery.start_bot_client()
    if client is not None:
        opportunity_bot_commands.register(client, message_manager.broadcast)


def _start_task(app: FastAPI, name: str, coro_factory) -> asyncio.Task:
    task = asyncio.create_task(_guarded(name, coro_factory), name=name)
    app.state.background_tasks[name] = task
    return task


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    app.state.background_tasks = {}
    # Har biri bir-biriga bog'liq bo'lmagan: bittasi yiqilsa qolganlari ishlaydi.
    _start_task(
        app,
        "telethon",
        lambda: run_telegram_client(on_new_filtered_message=message_manager.broadcast, interactive=False),
    )
    _start_task(app, "auto_archive", _auto_archive_loop)
    _start_task(app, "email_worker", lambda: email_worker_loop(message_manager.broadcast))
    _start_task(app, "opportunity_catchup", _opportunity_catchup_once)
    _start_task(app, "bot_commands", _bot_startup)
    # Eski nomlar (regressiya: boshqa kod app.state.*_task ni o'qisa)
    app.state.telegram_task = app.state.background_tasks["telethon"]
    app.state.auto_archive_task = app.state.background_tasks["auto_archive"]
    app.state.email_task = app.state.background_tasks["email_worker"]
    app.state.opportunity_catchup_task = app.state.background_tasks["opportunity_catchup"]
    try:
        yield
    finally:
        # To'xtatish: har bir qadam mustaqil — birining xatosi qolganini to'xtatmasin.
        for step_name, step in (
            ("telegram_client", stop_telegram_client),
            ("bot_client", opportunity_delivery.stop_bot_client),
        ):
            try:
                await step()
            except Exception:
                logger.exception("To'xtatishda xato: %s", step_name)
        tasks = list(app.state.background_tasks.values())
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Vazifa tugashida xato: %s", task.get_name())
        try:
            await close_db()
        except Exception:
            logger.exception("close_db xatosi")


app = FastAPI(
    title="Telegram Focus API",
    description="Tanlangan Telegram manbalaridan xabarlarni ko‘rsatish API'si.",
    version="1.0.0",
    lifespan=lifespan,
)

allowed_origins = [
    item.strip()
    for item in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_origin_regex=".*",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sources_router)
app.include_router(messages_router)
app.include_router(email_router)
app.include_router(opportunity_router)
app.include_router(briefing.router, prefix='/api')
app.include_router(ai_chat_router)


@app.get("/api/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}


frontend_dir = PROJECT_DIR / "frontend"
if frontend_dir.is_dir():
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

# --- AI CHIEF OF STAFF INTERAKTIV CHAT ROUTERI ---
