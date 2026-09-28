"""Send Telegram replies to a source chat (Stage 2, Checkpoint 1)."""
import asyncio
import logging
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from telethon.errors import FloodWaitError

from .database import async_session_factory
from .models import Message, Source
from .settings_store import read_archive_settings
from .telethon_client import get_client

logger = logging.getLogger(__name__)

MAX_AUTO_RETRY_WAIT_SECONDS = 60


async def _get_message_with_source(message_db_id: int) -> Message:
    async with async_session_factory() as session:
        query = (
            select(Message)
            .options(selectinload(Message.source))
            .where(Message.id == message_db_id)
        )
        result = await session.execute(query)
        message = result.scalar_one_or_none()
        if message is None:
            raise HTTPException(status_code=404, detail="Xabar topilmadi.")
        if message.chat_id is None:
            raise HTTPException(
                status_code=404,
                detail="Bu xabar uchun manba chat topilmadi (chat_id yo‘q).",
            )
        return message


async def _telegram_send(coro_factory):
    """Run a Telethon send coroutine, retrying once on a short FloodWaitError."""
    try:
        return await coro_factory()
    except FloodWaitError as exc:
        if exc.seconds <= MAX_AUTO_RETRY_WAIT_SECONDS:
            logger.warning("FloodWaitError: %s soniya kutib, qayta urinilmoqda.", exc.seconds)
            await asyncio.sleep(exc.seconds)
            try:
                return await coro_factory()
            except FloodWaitError as exc2:
                raise HTTPException(
                    status_code=429,
                    detail=f"Telegram cheklovi: {exc2.seconds} soniyadan keyin urinib ko‘ring.",
                ) from exc2
        raise HTTPException(
            status_code=429,
            detail=f"Telegram cheklovi: {exc.seconds} soniyadan keyin urinib ko‘ring.",
        ) from exc


async def send_reply(
    message_db_id: int,
    text: Optional[str],
    file_paths: Optional[list[str]] = None,
    force_document: bool = False,
) -> Message:
    """Send a reply into the source chat of an existing incoming message.

    Returns the newly created outgoing Message row (direction='out').
    """
    try:
        client = get_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Telegram ulanmagan.") from exc

    original = await _get_message_with_source(message_db_id)
    chat_id = original.chat_id
    reply_to = original.telegram_message_id
    text = text or ""
    file_paths = file_paths or []

    try:
        if file_paths:
            if len(file_paths) > 1:
                sent = await _telegram_send(
                    lambda: client.send_file(
                        chat_id,
                        file_paths,
                        caption=text or None,
                        reply_to=reply_to,
                        force_document=force_document,
                        supports_streaming=True,
                    )
                )
            else:
                sent = await _telegram_send(
                    lambda: client.send_file(
                        chat_id,
                        file_paths[0],
                        caption=text or None,
                        reply_to=reply_to,
                        force_document=force_document,
                        supports_streaming=True,
                    )
                )
            sent_message = sent[0] if isinstance(sent, list) else sent
        else:
            sent_message = await _telegram_send(
                lambda: client.send_message(
                    chat_id,
                    text,
                    reply_to=reply_to,
                    link_preview=True,
                )
            )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Chat topilmadi.") from exc
    except Exception as exc:
        logger.exception("Telegram javob yuborishda xato")
        raise HTTPException(status_code=502, detail="Telegram'ga yuborishda xato yuz berdi.") from exc

    async with async_session_factory() as session:
        record = Message(
            source_id=original.source_id,
            sender_name="Siz",
            text=text,
            media_type=_out_media_type(file_paths, force_document),
            telegram_message_id=getattr(sent_message, "id", 0),
            is_read=True,
            direction="out",
            reply_to_message_id=reply_to,
            chat_id=chat_id,
            channel=original.channel,
            has_media_file=bool(file_paths),
        )
        session.add(record)

        # archive_on_reply: mark the original incoming message archived too.
        if read_archive_settings().get("archive_on_reply"):
            from datetime import datetime, timezone

            original_row = await session.get(Message, original.id)
            if original_row is not None and not original_row.is_archived:
                original_row.is_archived = True
                original_row.archived_at = datetime.now(timezone.utc)

        await session.commit()
        await session.refresh(record)
        # source relationship needed by callers building MessageOut
        record.source = original.source
        return record


def _out_media_type(file_paths: list[str], force_document: bool) -> Optional[str]:
    if not file_paths:
        return None
    if force_document:
        return "document"
    return "media"
