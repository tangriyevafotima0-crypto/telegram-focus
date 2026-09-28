import asyncio
import inspect
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from dotenv import load_dotenv
from sqlalchemy import select
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl import types

from .database import async_session_factory
from .media import MAX_UPLOAD_MB, safe_media_path
from .models import Message, Source


logger = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

SESSION_PATH = str(BACKEND_DIR / "telegram_focus")
MessageCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

_client: Optional[TelegramClient] = None
_stop_event = asyncio.Event()


def _settings() -> tuple[int, str, str]:
    raw_api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    phone = os.getenv("TELEGRAM_PHONE", "").strip()
    if not raw_api_id or not api_hash or not phone:
        raise RuntimeError(
            "TELEGRAM_API_ID, TELEGRAM_API_HASH va TELEGRAM_PHONE backend/.env da "
            "to‘ldirilishi kerak."
        )
    try:
        api_id = int(raw_api_id)
    except ValueError as exc:
        raise RuntimeError("TELEGRAM_API_ID faqat raqam bo‘lishi kerak.") from exc
    return api_id, api_hash, phone


def _normalize_identifier(value: str) -> str:
    return value.strip().lstrip("@").casefold()


def _display_name(entity: Any) -> str:
    if isinstance(entity, types.User):
        name = " ".join(
            part for part in (entity.first_name, entity.last_name) if part
        ).strip()
        return name or entity.username or str(entity.id)
    return (
        getattr(entity, "title", None)
        or getattr(entity, "username", None)
        or str(getattr(entity, "id", "Noma’lum"))
    )


def _media_type(message: Any) -> Optional[str]:
    if not message or not message.media:
        return None
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.voice:
        return "voice"
    if message.audio:
        return "audio"
    if message.document:
        return "document"
    if message.sticker:
        return "sticker"
    return "media"


_URL_RE = re.compile(r"https?://\S+")


def _extract_links(text: str) -> list[str]:
    if not text:
        return []
    return _URL_RE.findall(text)


def _media_mime(message: Any) -> Optional[str]:
    document = getattr(message, "document", None)
    if document is not None and getattr(document, "mime_type", None):
        return document.mime_type
    if getattr(message, "photo", None):
        return "image/jpeg"
    return None


def _media_extension(mime: Optional[str], media_type_hint: Optional[str]) -> str:
    if mime and "/" in mime:
        ext = mime.split("/")[-1].split(";")[0]
        if ext:
            return ext
    return media_type_hint or "bin"


async def _maybe_download_media(
    message: Any,
    media_type: Optional[str],
    source_id: int,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Download small media to data/media/. Never blocks message saving on failure.

    Returns (has_media_file, media_mime, media_name).
    """
    if media_type is None or not message.media:
        return False, None, None

    mime = _media_mime(message)
    try:
        size = getattr(message.file, "size", None) if message.file else None
        if size is not None and size > MAX_UPLOAD_MB * 1024 * 1024:
            return False, mime, None

        ext = _media_extension(mime, media_type)
        file_name = f"{source_id}_{message.id}.{ext}"
        target_path = safe_media_path(file_name)
        await message.download_media(file=str(target_path))
        return True, mime, file_name
    except Exception:
        logger.exception("Media yuklab olishda xato (xabar baribir saqlanadi)")
        return False, mime, None


async def _maybe_analyze_media(
    media_type: Optional[str],
    media_name: str,
    original_text: str,
) -> tuple[str, Optional[str]]:
    """Stage 1: yuklab olingan media ustida OCR/audio/PDF tahlili.

    Hech qachon exception otmaydi va asosiy oqimni to'xtatmaydi (try/except +
    logger.exception naqshi, mavjud kod uslubiga mos). Muvaffaqiyatsiz bo'lsa
    (masalan Gemini 429/500), original_text va None qaytaradi.

    Qaytaradi: (yangi_text, media_analysis_json | None)
    """
    try:
        from .media import safe_media_path
        from .opportunity import dashboard_formatter, media_analyzer

        path = safe_media_path(media_name)

        if media_type == "photo":
            result = await media_analyzer.analyze_image(path)
            dashboard = dashboard_formatter.format_media_analysis("photo", result)
            dashboard_json = json.dumps(dashboard, ensure_ascii=False) if dashboard else None
            if result.get("ok") and result.get("text"):
                return result["text"], dashboard_json
            return original_text, dashboard_json

        if media_type in ("voice", "audio"):
            result = await media_analyzer.analyze_audio(path)
            dashboard = dashboard_formatter.format_media_analysis(media_type, result)
            dashboard_json = json.dumps(dashboard, ensure_ascii=False) if dashboard else None
            if result.get("ok") and result.get("text"):
                return result["text"], dashboard_json
            return original_text, dashboard_json

        if media_type == "document" and path.suffix.lower() == ".pdf":
            result = await media_analyzer.analyze_document(path)
            if result.get("ok"):
                dashboard = dashboard_formatter.format_media_analysis("document", result)
                dashboard_json = json.dumps(dashboard, ensure_ascii=False) if dashboard else None
                return result.get("text") or original_text, dashboard_json
            return original_text, None

        return original_text, None
    except Exception:
        logger.exception("Media tahlilida xato (xabar baribir saqlanadi, o'zgarishsiz)")
        return original_text, None


def _entity_type(entity: Any) -> str:
    if isinstance(entity, types.User):
        return "user"
    if isinstance(entity, types.Channel):
        return "channel" if entity.broadcast else "group"
    return "group"


async def _maybe_call(callback: Optional[MessageCallback], payload: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(payload)
    if inspect.isawaitable(result):
        await result


async def _handle_new_message(
    event: events.NewMessage.Event,
    callback: Optional[MessageCallback],
) -> None:
    try:
        entity = await event.get_chat()
        sender = await event.get_sender()
        chat_id = event.chat_id
        if entity is None or chat_id is None:
            return

        try:
            from .opportunity.engine import handle_incoming
            from .routers.messages import message_manager

            await handle_incoming(
                chat_id,
                _display_name(entity),
                event.message.message or "",
                event.message.date,
                event.message.id,
                message_manager.broadcast,
                event.client,
            )
        except Exception:
            logger.exception("Imkoniyat-aniqlashda xato (asosiy oqimga ta'sir qilmaydi)")

        identifiers = {
            _normalize_identifier(str(chat_id)),
            _normalize_identifier(str(getattr(entity, "id", chat_id))),
        }
        username = getattr(entity, "username", None)
        if username:
            identifiers.add(_normalize_identifier(username))

        async with async_session_factory() as session:
            result = await session.execute(
                select(Source).where(Source.is_active.is_(True), Source.kind == "telegram")
            )
            sources = result.scalars().all()
            matched_source = next(
                (
                    source
                    for source in sources
                    if _normalize_identifier(source.identifier) in identifiers
                ),
                None,
            )
            if matched_source is None:
                if event.is_private:
                    res = await session.execute(
                        select(Source).where(Source.identifier == "dm_unmonitored")
                    )
                    matched_source = res.scalars().first()
                    if matched_source is None:
                        return
                else:
                    return

            message = event.message
            received_at = datetime.now(timezone.utc)
            media_type = _media_type(message)
            has_media_file, media_mime, media_name = await _maybe_download_media(
                message, media_type, matched_source.id
            )
            links = _extract_links(message.message or "")
            reply_to_message_id = getattr(message, "reply_to_msg_id", None)

            record_text = message.message or ""
            media_analysis_json = None
            if has_media_file and media_name:
                record_text, media_analysis_json = await _maybe_analyze_media(
                    media_type, media_name, record_text
                )

            record = Message(
                source_id=matched_source.id,
                sender_name=_display_name(sender or entity),
                text=record_text,
                media_type=media_type,
                telegram_message_id=message.id,
                received_at=received_at,
                is_read=False,
                reply_to_message_id=reply_to_message_id,
                chat_id=chat_id,
                direction="in",
                has_media_file=has_media_file,
                media_mime=media_mime,
                media_name=media_name,
                link_urls=json.dumps(links) if links else None,
                channel="telegram",
                media_analysis_json=media_analysis_json,
            )
            if matched_source and matched_source.identifier == 'dm_unmonitored':
                record.is_archived = True
            session.add(record)
            await session.commit()
            await session.refresh(record)

            record_id = record.id
            source_id = matched_source.id
            source_display_name = matched_source.display_name
            source_identifier = matched_source.identifier

            payload = {
                "id": record.id,
                "source_id": matched_source.id,
                "source_display_name": matched_source.display_name,
                "sender_name": record.sender_name,
                "text": record.text,
                "media_type": record.media_type,
                "media_path": record.media_path,
                "telegram_message_id": record.telegram_message_id,
                "received_at": record.received_at.isoformat(),
                "is_read": record.is_read,
                "is_archived": record.is_archived,
                "archived_at": None,
                "reply_to_message_id": record.reply_to_message_id,
                "chat_id": record.chat_id,
                "direction": record.direction,
                "has_media_file": record.has_media_file,
                "media_mime": record.media_mime,
                "media_name": record.media_name,
                "link_urls": links,
                "channel": record.channel,
                "triage_level": record.triage_level,
                "triage_reason": record.triage_reason,
                "triage_auto_reply": record.triage_auto_reply,
                "triage_dashboard": (
                    json.loads(record.triage_dashboard_json) if record.triage_dashboard_json else None
                ),
                "media_analysis": (
                    json.loads(record.media_analysis_json) if record.media_analysis_json else None
                ),
            }

        await _maybe_call(callback, payload)

        asyncio.create_task(
            _process_message_stages(record_id, source_id, source_identifier, callback)
        )

    except Exception:
        logger.exception("_handle_new_message xatoligi")


async def _process_message_stages(
    record_id: int,
    source_id: int,
    source_identifier: str,
    callback: Optional[MessageCallback],
) -> None:
    try:
        async with async_session_factory() as session:
            record = await session.get(Message, record_id)
            if record is None:
                return

            try:
                from .opportunity.triage import classify_message

                triage_result = await classify_message(record)
                record.triage_level = triage_result.level
                record.triage_reason = triage_result.reason
                record.triage_auto_reply = triage_result.auto_reply_text
                if triage_result.level == 3:
                    from .opportunity import dashboard_formatter

                    dashboard = dashboard_formatter.format_triage_emergency(
                        record.text, triage_result.reason
                    )
                    record.triage_dashboard_json = json.dumps(dashboard, ensure_ascii=False)
                await session.commit()
                await session.refresh(record)
            except Exception:
                logger.exception("Triage klassifikatsiyasida xato (xabar baribir saqlangan)")

            try:
                is_unmonitored = source_identifier == "dm_unmonitored"
                if is_unmonitored or (record.triage_level in (1, 2)):
                    from .opportunity.auto_responder import send_executive_reply
                    await send_executive_reply(record)
            except Exception:
                logger.exception("Executive auto-reply yuborishda xato")

            update_payload = {
                "id": record.id,
                "triage_level": record.triage_level,
                "triage_reason": record.triage_reason,
                "triage_auto_reply": record.triage_auto_reply,
                "triage_dashboard": (
                    json.loads(record.triage_dashboard_json) if record.triage_dashboard_json else None
                ),
            }
        await _maybe_call(callback, update_payload)
    except Exception:
        logger.exception("_process_message_stages xatoligi (record_id=%s)", record_id)
    except Exception:
        logger.exception("Filtrlangan Telegram xabarini saqlashda xato")


async def run_telegram_client(
    on_new_filtered_message: Optional[MessageCallback] = None,
    *,
    interactive: bool = False,
) -> None:
    """Run the Telethon userbot until shutdown.

    The first login is intentionally interactive and should be run from a terminal:
    `python -m app.telethon_client`. The FastAPI process uses interactive=False so
    a missing session never blocks a systemd service waiting for stdin.
    """
    global _client
    try:
        api_id, api_hash, phone = _settings()
    except RuntimeError as exc:
        logger.warning("Telethon ishga tushmadi: %s", exc)
        return

    _stop_event.clear()
    client = TelegramClient(SESSION_PATH, api_id, api_hash)
    _client = client
    client.add_event_handler(
        lambda event: _handle_new_message(event, on_new_filtered_message),
        events.NewMessage,
    )

    try:
        while not _stop_event.is_set():
            try:
                if not client.is_connected():
                    await client.connect()
                if not await client.is_user_authorized():
                    if not interactive:
                        logger.error(
                            "Telethon session topilmadi. Avval terminalda "
                            "`python -m app.telethon_client` bilan bir marta login qiling."
                        )
                        return
                    # Telethon asks for the SMS/Telegram code and optional 2FA password here.
                    await client.start(phone=phone)

                logger.info("Telethon ulandi; filtrlangan xabarlar tinglanmoqda.")
                await client.run_until_disconnected()
            except FloodWaitError as exc:
                logger.warning("Flood wait: %s soniya kutilyapti.", exc.seconds)
                await asyncio.sleep(exc.seconds)
            except (ConnectionError, OSError) as exc:
                logger.warning("Telegram ulanishi uzildi: %s", exc)
                if not _stop_event.is_set():
                    await asyncio.sleep(5)
            else:
                if not _stop_event.is_set():
                    logger.warning("Telegram ulanishi uzildi; 5 soniyadan keyin qayta ulanadi.")
                    await asyncio.sleep(5)
    except (asyncio.CancelledError, KeyboardInterrupt):
        raise
    except Exception:
        logger.exception("Telethon client xatosi")
    finally:
        if client.is_connected():
            await client.disconnect()
        if _client is client:
            _client = None


def get_client() -> TelegramClient:
    """Return the running Telethon client, or raise if it isn't connected."""
    if _client is None:
        raise RuntimeError("Telegram mijozi ulanmagan.")
    return _client


async def stop_telegram_client() -> None:
    _stop_event.set()
    if _client is not None and _client.is_connected():
        await _client.disconnect()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_telegram_client(interactive=True))