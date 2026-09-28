import base64
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..database import get_db
from ..media import MAX_UPLOAD_MB, MEDIA_DIR, is_allowed_mime, safe_tmp_media_path
from ..models import Message
from ..schemas import MessageCountsOut, MessageOut
from ..sender import send_reply
from ..settings_store import (
    DEFAULT_ARCHIVE_SETTINGS,
    read_archive_settings,
    read_auto_responder_settings,
    write_archive_settings,
    write_auto_responder_settings,
)
from ..opportunity.auto_responder import AutoResponderResult, send_executive_reply


router = APIRouter(tags=["messages"])


class MessageConnectionManager:
    def __init__(self) -> None:
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        disconnected: list[WebSocket] = []
        for websocket in tuple(self.connections):
            try:
                await websocket.send_json(payload)
            except Exception:
                disconnected.append(websocket)
        for websocket in disconnected:
            self.disconnect(websocket)


message_manager = MessageConnectionManager()


def to_message_out(message: Message) -> MessageOut:
    link_urls = None
    if message.link_urls:
        try:
            link_urls = json.loads(message.link_urls)
        except (TypeError, ValueError):
            link_urls = None
    return MessageOut(
        id=message.id,
        source_id=message.source_id,
        source_display_name=(message.source.display_name if message.source else 'Noma\'lum'),
        sender_name=message.sender_name,
        text=message.text,
        media_type=message.media_type,
        media_path=message.media_path,
        telegram_message_id=message.telegram_message_id,
        received_at=message.received_at,
        is_read=message.is_read,
        is_archived=message.is_archived,
        archived_at=message.archived_at,
        reply_to_message_id=message.reply_to_message_id,
        chat_id=message.chat_id,
        direction=message.direction,
        has_media_file=message.has_media_file,
        media_mime=message.media_mime,
        media_name=message.media_name,
        link_urls=link_urls,
        channel=message.channel,
        triage_level=message.triage_level,
        triage_reason=message.triage_reason,
        triage_auto_reply=message.triage_auto_reply,
        triage_dashboard=message.triage_dashboard_json,
        media_analysis=message.media_analysis_json,
    )


@router.get("/api/messages", response_model=list[MessageOut])
async def list_messages(
    source_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
    archived: bool = False,
    channel: Optional[str] = None,
    unread_only: bool = False,
    search: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    query = (
        select(Message)
        .options(selectinload(Message.source))
        .order_by(Message.received_at.desc(), Message.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if source_id is not None:
        query = query.where(Message.source_id == source_id)
    # Default behavior unchanged: non-archived messages only.
    query = query.where(Message.is_archived == archived)
    if channel is not None:
        query = query.where(Message.channel == channel)
    if unread_only:
        query = query.where(Message.is_read.is_(False))
    if search:
        term = search.strip()[:100]
        if term:
            like = f"%{term}%"
            query = query.where(or_(Message.text.like(like), Message.sender_name.like(like)))
    result = await db.execute(query)
    return [to_message_out(item) for item in result.scalars().all()]


@router.get("/api/messages/counts", response_model=MessageCountsOut)
async def message_counts(db: AsyncSession = Depends(get_db)) -> MessageCountsOut:
    async def _count(*conditions) -> int:
        query = select(func.count()).select_from(Message).where(*conditions)
        result = await db.execute(query)
        return int(result.scalar_one())

    telegram_unread = await _count(
        Message.channel == "telegram",
        Message.is_read.is_(False),
        Message.is_archived.is_(False),
    )
    email_unread = await _count(
        Message.channel == "email",
        Message.is_read.is_(False),
        Message.is_archived.is_(False),
    )
    opportunity_unread = await _count(
        Message.channel == "opportunity",
        Message.is_read.is_(False),
        Message.is_archived.is_(False),
    )
    archived_count = await _count(Message.is_archived.is_(True))

    return MessageCountsOut(
        telegram_unread=telegram_unread,
        email_unread=email_unread,
        archived=archived_count,
        opportunity_unread=opportunity_unread,
    )


@router.get("/api/notifications", response_model=list[MessageOut])
async def list_notifications(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    """Stage 2: Notification Center — Daraja 2 va Daraja 3 xabarlar (arxivlanmagan)."""
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    query = (
        select(Message)
        .options(selectinload(Message.source))
        .where(Message.triage_level.in_([2, 3]))
        .where(Message.is_archived.is_(False))
        .order_by(Message.triage_level.desc(), Message.received_at.desc(), Message.id.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(query)
    return [to_message_out(item) for item in result.scalars().all()]


@router.get("/api/media/{message_id}")
async def get_media(message_id: int, db: AsyncSession = Depends(get_db)) -> FileResponse:
    message = await db.get(Message, message_id)
    if message is None or not message.has_media_file or not message.media_name:
        raise HTTPException(status_code=404, detail="Media topilmadi.")

    file_path = (MEDIA_DIR / message.media_name).resolve()
    if MEDIA_DIR.resolve() not in file_path.parents or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Media topilmadi.")

    return FileResponse(
        path=file_path,
        media_type=message.media_mime or "application/octet-stream",
        filename=message.media_name,
    )


class ReplyFileIn(BaseModel):
    """One file for a reply, sent as base64 JSON (python-multipart not in requirements.txt)."""

    name: str = Field(min_length=1, max_length=255)
    mime: str = Field(min_length=1, max_length=100)
    data_b64: str


class ReplyIn(BaseModel):
    text: Optional[str] = None
    files: Optional[list[ReplyFileIn]] = None
    as_document: bool = False


@router.post("/api/messages/{message_id}/reply", response_model=MessageOut)
async def reply_to_message(
    message_id: int,
    payload: ReplyIn,
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    text = (payload.text or "").strip()
    files = payload.files or []
    if not text and not files:
        raise HTTPException(status_code=422, detail="Matn yoki fayl kerak.")

    original = await db.get(Message, message_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Xabar topilmadi.")
    if original.channel != "telegram":
        # Email xatlarida chat_id = email hisob ID'si (Telegram chat emas): javob YUBORILMAYDI.
        raise HTTPException(status_code=422, detail="Bu kanal uchun javob yuborish qo'llab-quvvatlanmaydi.")

    max_bytes = MAX_UPLOAD_MB * 1024 * 1024
    tmp_dir = MEDIA_DIR / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    saved_paths: list[str] = []

    try:
        for item in files:
            if not is_allowed_mime(item.mime):
                raise HTTPException(status_code=415, detail=f"Ruxsat etilmagan fayl turi: {item.mime}")
            try:
                raw = base64.b64decode(item.data_b64, validate=True)
            except Exception as exc:
                raise HTTPException(status_code=422, detail="Fayl ma'lumoti noto‘g‘ri (base64).") from exc
            if len(raw) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=f"Fayl {MAX_UPLOAD_MB}MB dan katta bo‘lishi mumkin emas.",
                )
            tmp_name = f"{uuid.uuid4().hex}_{item.name}"
            tmp_path = safe_tmp_media_path(tmp_name)
            tmp_path.write_bytes(raw)
            saved_paths.append(str(tmp_path))

        record = await send_reply(
            message_db_id=message_id,
            text=text,
            file_paths=saved_paths,
            force_document=payload.as_document,
        )
        result = to_message_out(record)
        await message_manager.broadcast(result.model_dump(mode="json"))
        return result
    finally:
        for path in saved_paths:
            try:
                import os

                os.remove(path)
            except OSError:
                pass


@router.patch("/api/messages/{message_id}/read", response_model=MessageOut)
async def mark_message_read(
    message_id: int,
    archive: bool = False,
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    query = (
        select(Message)
        .options(selectinload(Message.source))
        .where(Message.id == message_id)
    )
    result = await db.execute(query)
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="Xabar topilmadi.")
    message.is_read = True
    if archive and not message.is_archived:
        message.is_archived = True
        message.archived_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(message)
    return to_message_out(message)


@router.patch("/api/messages/{message_id}/archive", response_model=MessageOut)
async def archive_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    query = (
        select(Message)
        .options(selectinload(Message.source))
        .where(Message.id == message_id)
    )
    result = await db.execute(query)
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="Xabar topilmadi.")
    if not message.is_archived:
        message.is_archived = True
        message.archived_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(message)
    return to_message_out(message)


@router.patch("/api/messages/{message_id}/unarchive", response_model=MessageOut)
async def unarchive_message(
    message_id: int,
    db: AsyncSession = Depends(get_db),
) -> MessageOut:
    query = (
        select(Message)
        .options(selectinload(Message.source))
        .where(Message.id == message_id)
    )
    result = await db.execute(query)
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="Xabar topilmadi.")
    if message.is_archived:
        message.is_archived = False
        message.archived_at = None
        await db.commit()
        await db.refresh(message)
    return to_message_out(message)


class ArchiveBulkIn(BaseModel):
    ids: Optional[list[int]] = None
    source_id: Optional[int] = None
    only_read: bool = False


class ArchiveBulkOut(BaseModel):
    archived: int


@router.post("/api/messages/archive-bulk", response_model=ArchiveBulkOut)
async def archive_bulk(
    payload: ArchiveBulkIn,
    db: AsyncSession = Depends(get_db),
) -> ArchiveBulkOut:
    if payload.ids is not None:
        if len(payload.ids) > 500:
            raise HTTPException(status_code=422, detail="Bir vaqtda 500 tadan ortiq ID yubormang.")
        if not payload.ids:
            return ArchiveBulkOut(archived=0)
        query = select(Message).where(
            Message.id.in_(payload.ids), Message.is_archived.is_(False)
        )
    elif payload.source_id is not None:
        query = select(Message).where(
            Message.source_id == payload.source_id, Message.is_archived.is_(False)
        )
        if payload.only_read:
            query = query.where(Message.is_read.is_(True))
    else:
        raise HTTPException(status_code=422, detail="ids yoki source_id kerak.")

    result = await db.execute(query)
    messages = result.scalars().all()
    now = datetime.now(timezone.utc)
    for message in messages:
        message.is_archived = True
        message.archived_at = now
    await db.commit()
    return ArchiveBulkOut(archived=len(messages))


class ArchiveSettingsOut(BaseModel):
    archive_on_read: bool
    archive_on_reply: bool
    auto_archive_days: int


class ArchiveSettingsIn(BaseModel):
    archive_on_read: Optional[bool] = None
    archive_on_reply: Optional[bool] = None
    auto_archive_days: Optional[int] = Field(default=None, ge=0)


@router.get("/api/settings/archive", response_model=ArchiveSettingsOut)
async def get_archive_settings() -> ArchiveSettingsOut:
    return ArchiveSettingsOut(**read_archive_settings())


@router.put("/api/settings/archive", response_model=ArchiveSettingsOut)
async def put_archive_settings(payload: ArchiveSettingsIn) -> ArchiveSettingsOut:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    merged = write_archive_settings(updates)
    return ArchiveSettingsOut(**merged)


class AutoResponderSettingsOut(BaseModel):
    auto_reply_enabled: bool


class AutoResponderSettingsIn(BaseModel):
    auto_reply_enabled: Optional[bool] = None


@router.get("/api/settings/auto-responder", response_model=AutoResponderSettingsOut)
async def get_auto_responder_settings() -> AutoResponderSettingsOut:
    return AutoResponderSettingsOut(**read_auto_responder_settings())


@router.put("/api/settings/auto-responder", response_model=AutoResponderSettingsOut)
async def put_auto_responder_settings(payload: AutoResponderSettingsIn) -> AutoResponderSettingsOut:
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    merged = write_auto_responder_settings(updates)
    return AutoResponderSettingsOut(**merged)


class AutoReplyActionOut(BaseModel):
    sent: bool
    reason: str


@router.post("/api/messages/{message_id}/confirm-auto-reply", response_model=AutoReplyActionOut)
async def confirm_auto_reply(message_id: int, db: AsyncSession = Depends(get_db)) -> AutoReplyActionOut:
    """Notification Center'da qo'lda 'Yubordim' bosilganda (auto-reply o'chirilgan bo'lsa)."""
    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Xabar topilmadi.")
    if message.triage_level != 2:
        raise HTTPException(status_code=422, detail="Faqat Daraja 2 xabarlar uchun.")

    result: AutoResponderResult = await send_executive_reply(message, force=True)
    if result.reason == "error":
        raise HTTPException(status_code=502, detail="Telegram'ga yuborishda xato yuz berdi.")
    if result.reason == "no_chat":
        raise HTTPException(status_code=404, detail="Chat topilmadi.")
    return AutoReplyActionOut(sent=result.sent, reason=result.reason)


@router.post("/api/messages/{message_id}/cancel-auto-reply", response_model=AutoReplyActionOut)
async def cancel_auto_reply(message_id: int, db: AsyncSession = Depends(get_db)) -> AutoReplyActionOut:
    """Notification Center'da 'Bekor qilish' bosilganda — xabarni arxivlaydi,
    hech narsa yubormaydi."""
    message = await db.get(Message, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Xabar topilmadi.")
    if message.triage_level != 2:
        raise HTTPException(status_code=422, detail="Faqat Daraja 2 xabarlar uchun.")

    message.is_archived = True
    message.archived_at = datetime.now(timezone.utc)
    await db.commit()
    return AutoReplyActionOut(sent=False, reason="cancelled")


async def run_auto_archive_once(db: AsyncSession) -> int:
    """Archive read messages older than auto_archive_days. Returns count archived."""
    settings = read_archive_settings()
    days = settings.get("auto_archive_days", 0)
    if not days or days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = select(Message).where(
        Message.is_archived.is_(False),
        Message.is_read.is_(True),
        Message.received_at < cutoff,
    )
    result = await db.execute(query)
    messages = result.scalars().all()
    now = datetime.now(timezone.utc)
    for message in messages:
        message.is_archived = True
        message.archived_at = now
    if messages:
        await db.commit()
    return len(messages)


@router.websocket("/ws/messages")
async def messages_websocket(websocket: WebSocket) -> None:
    await message_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        message_manager.disconnect(websocket)
    except Exception:
        message_manager.disconnect(websocket)