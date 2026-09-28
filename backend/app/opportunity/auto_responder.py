"""auto_responder.py — Stage 3: Executive Auto-Responder.

Daraja 2 (NOTIFICATION REQUIRED) xabarlarga Zafar nomidan emas, balki uning
"shaxsiy AI assistenti" sifatida ochiq javob yuboradi. Shablon matnlari
so'zma-so'z, o'zgartirmasdan ishlatiladi (STAGE_3_PROMPT.md talabi).

Xavfsizlik: standart holatda o'chirilgan (`auto_reply_enabled=False`,
settings.json). Yoqilmagan bo'lsa, bu modul hech narsa yubormaydi — chaqiruvchi
(telethon_client) buni faqat log/UI uchun belgilab qo'yadi, qo'lda tasdiqlash
Notification Center orqali amalga oshiriladi (routers/messages.py dagi
/api/messages/{id}/confirm-auto-reply va /cancel-auto-reply endpointlari).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Message
from ..sender import send_reply
from ..settings_store import read_auto_responder_settings

logger = logging.getLogger(__name__)

# Zafar so'ragan shablonlar — AYNAN MATN, o'zgartirmasdan.
TEXT_TEMPLATE = (
    "Assalomu alaykum! Men Zafarning shaxsiy AI assistentiman. Ushbu xabarni "
    "Zafarga yetkazdim. Bo'shashlari bilan o'zlari sizga bog'lanadilar."
)

MEDIA_TEMPLATE = (
    "Assalomu alaykum! Yuborgan hujjatingiz/rasmingiz qabul qilindi va "
    "Zafarning diqqat markaziga kiritildi. O'zlari ko'rib chiqib javob "
    "yozadilar."
)

# Auto-reply orqali yuborilgan chiquvchi xabarlarni ajratish uchun belgi
# (yangi ustun ochilmadi — mavjud media_type ustunidan foydalanildi).
AUTO_REPLY_MARKER = "auto_reply"

RATE_LIMIT_WINDOW = timedelta(hours=24)


@dataclass
class AutoResponderResult:
    sent: bool
    reason: str  # "sent" | "disabled" | "rate_limited" | "wrong_level" | "no_chat" | "error"


def _select_template(has_media_file: bool) -> str:
    return MEDIA_TEMPLATE if has_media_file else TEXT_TEMPLATE


async def _was_recently_auto_replied(chat_id: int) -> bool:
    """Oxirgi 24 soatda shu chatga auto-reply yuborilganmi tekshiradi."""
    cutoff = datetime.now(timezone.utc) - RATE_LIMIT_WINDOW
    async with async_session_factory() as session:
        query = (
            select(Message.id)
            .where(Message.chat_id == chat_id)
            .where(Message.direction == "out")
            .where(Message.media_type == AUTO_REPLY_MARKER)
            .where(Message.received_at >= cutoff)
            .limit(1)
        )
        result = await session.execute(query)
        return result.scalar_one_or_none() is not None


async def send_executive_reply(
    message: Message,
    triage_level: Optional[int] = None,
    *,
    force: bool = False,
) -> AutoResponderResult:
    """Daraja 2 xabarga standart shablonni Zafar nomidan emas, AI assistent
    sifatida yuboradi.

    `force=True` — Notification Center'da qo'lda "Yubordim" bosilganda,
    `auto_reply_enabled` o'chirilgan bo'lsa ham yuborish uchun ishlatiladi
    (rate-limit baribir tekshiriladi).
    """
    level = triage_level if triage_level is not None else message.triage_level
    is_unmonitored_dm = message.source_id == 14
    if not is_unmonitored_dm and level != 2:
        return AutoResponderResult(sent=False, reason="wrong_level")

    if not force and not read_auto_responder_settings().get("auto_reply_enabled"):
        return AutoResponderResult(sent=False, reason="disabled")

    chat_id = message.chat_id
    if chat_id is None:
        return AutoResponderResult(sent=False, reason="no_chat")

    if await _was_recently_auto_replied(chat_id):
        logger.info(
            "Auto-reply rate-limit: chat_id=%s uchun oxirgi 24 soatda allaqachon yuborilgan.",
            chat_id,
        )
        return AutoResponderResult(sent=False, reason="rate_limited")

    template_text = _select_template(message.has_media_file)

    try:
        sent_record = await send_reply(
            message_db_id=message.id,
            text=template_text,
            file_paths=None,
            force_document=False,
        )
    except Exception:
        logger.exception("Executive auto-reply yuborishda xato (message_id=%s)", message.id)
        return AutoResponderResult(sent=False, reason="error")

    # send_reply umumiy "media" media_type qo'yadi (file_paths yo'q bo'lgani
    # uchun bu yerda hech qachon ishlamaydi) — auto-reply belgisi bilan qayta
    # yozamiz, keyingi rate-limit tekshiruvlari buni topa olishi uchun.
    async with async_session_factory() as session:
        row = await session.get(Message, sent_record.id)
        if row is not None:
            row.media_type = AUTO_REPLY_MARKER
            await session.commit()

    logger.info("Executive auto-reply yuborildi: chat_id=%s, message_id=%s", chat_id, message.id)
    return AutoResponderResult(sent=True, reason="sent")
