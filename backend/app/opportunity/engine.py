"""
engine.py — Imkoniyat-aniqlash: real-vaqt (NewMessage oqimiga ulanadi, polling YO'Q)
+ ishga tushgandagi bir martalik "tiklash" (catch_up, min_id bilan).

Mos topilganda Message(channel='opportunity') yoziladi, WebSocket orqali
broadcast qilinadi va (Stage 6) tasdiqlangan guruhlarga yuboriladi
(`delivery.deliver`, `_save_match` ichida — xato Message'ni yo'qotmaydi).
"""
import asyncio
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import select

from ..database import async_session_factory
from ..models import Message, Source, SourceType, utc_now
from . import delivery, store
from .formatting import _opp_hash, format_opportunity
from .gemini_analyzer import analyze_opportunity
from .matcher import Profile, evaluate
from .parser import parse_post
from .resolve import resolve_target

try:
    from telethon.errors import FloodWaitError
except Exception:  # pragma: no cover — telethon yo'q muhitda ham import ishlasin
    class FloodWaitError(Exception):
        seconds = 0

logger = logging.getLogger("opportunity.engine")

Broadcast = Callable[[dict[str, Any]], Awaitable[None]]

# Eski monitor.py dagi cheklovlar (o'zgarishsiz):
_MAX_FLOOD_WAIT = 300
_MAX_NEW_PER_CHANNEL = 200
_MIN_TEXT_LEN = 40

# AI (Gemini) qo'shimcha tekshiruvi: regex-filtrdan o'tgan postlar shu chegaradan
# past ball olsa yuborilmaydi. GEMINI_API_KEY sozlanmagan bo'lsa AI bosqichi
# butunlay o'tkazib yuboriladi (faqat regex/matcher natijasiga tayaniladi).
_AI_MIN_SCORE = 70


async def _ai_confirms(opp) -> bool:
    """Gemini orqali qo'shimcha tekshiruv (havola bo'lsa — saytga kirib o'qib).
    Kalit yo'q yoki AI xato bersa — bloklamaydi (regex natijasiga ishoniladi)."""
    try:
        urls = [opp.link] if opp.link else None
        # Sync/Async xavfsiz chaqiruv
        import inspect
        _res = analyze_opportunity(opp.raw_text, urls[0] if isinstance(urls, list) and urls else urls)
        result = await _res if inspect.isawaitable(_res) else _res
    except Exception:
        logger.exception("AI tahlilida kutilmagan xato — regex natijasiga tayanildi")
        return True
    if result is None:
        # Kalit yo'q yoki AI javob bermadi — AI bosqichisiz davom etiladi.
        return True
    score = result.get("match_score", 0) or 0
    is_relevant = result.get("is_relevant", True)
    if not is_relevant or score < _AI_MIN_SCORE:
        logger.info(
            "AI rad etdi [ball %s]: %s", score, (result.get("title") or opp.title)[:50]
        )
        return False
    return True


def _profile_from_dict(d: dict) -> Profile:
    return Profile(
        age=d.get("age", 16),
        grade=d.get("grade"),
        ielts=d.get("ielts"),
        knows_english=d.get("knows_english", True),
        is_student=d.get("is_student", False),
        is_pupil=d.get("is_pupil", True),
        interests=d.get("interests", []),
        only_free=d.get("only_free", True),
    )


async def _get_or_create_source(session, channel_id: int, name: str) -> Source:
    identifier = f"opportunity:{channel_id}"
    result = await session.execute(
        select(Source).where(Source.identifier == identifier, Source.kind == "opportunity")
    )
    source = result.scalar_one_or_none()
    if source is None:
        source = Source(
            identifier=identifier,
            display_name=name,
            type=SourceType.CHANNEL,
            is_active=True,
            kind="opportunity",
        )
        session.add(source)
        await session.flush()
    elif source.display_name != name:
        source.display_name = name
    return source


async def _save_match(
    channel_id: int,
    channel_name: str,
    opp,
    telegram_msg_id: int,
    broadcast: Optional[Broadcast],
    userbot_client=None,
) -> None:
    """Mos topilgan imkoniyatni Message jadvaliga yozadi, broadcast qiladi va guruhlarga yuboradi."""
    text = format_opportunity(opp, channel_name)
    links = [opp.link] if opp.link else []

    async with async_session_factory() as session:
        source = await _get_or_create_source(session, channel_id, channel_name)
        record = Message(
            source_id=source.id,
            sender_name=channel_name[:255],
            text=text,
            media_type=None,
            telegram_message_id=telegram_msg_id,
            received_at=utc_now(),
            is_read=False,
            chat_id=channel_id,
            direction="in",
            has_media_file=False,
            link_urls=json.dumps(links, ensure_ascii=False) if links else None,
            channel="opportunity",
            opp_score=opp.score,
        )
        session.add(record)
        await session.commit()
        await session.refresh(record)

        payload = {
            "id": record.id,
            "source_id": source.id,
            "source_display_name": source.display_name,
            "sender_name": record.sender_name,
            "text": record.text,
            "media_type": None,
            "media_path": None,
            "telegram_message_id": record.telegram_message_id,
            "received_at": record.received_at.isoformat(),
            "is_read": False,
            "is_archived": False,
            "archived_at": None,
            "reply_to_message_id": None,
            "chat_id": record.chat_id,
            "direction": "in",
            "has_media_file": False,
            "media_mime": None,
            "media_name": None,
            "link_urls": links or None,
            "channel": "opportunity",
            "opp_score": opp.score,
            "deadline": opp.deadline.isoformat() if opp.deadline else None,
            "link": opp.link or None,
        }
    if broadcast is not None:
        try:
            await broadcast(payload)
        except Exception:
            logger.exception("Opportunity broadcast xatosi")

    # Stage 6: tasdiqlangan guruhlarga yuborish. Message allaqachon DB'da — yuborish
    # xatosi hech narsani yo'qotmaydi; deliver() istisno ko'tarmaydi, lekin baribir himoya.
    try:
        await delivery.deliver(text, userbot_client=userbot_client)
    except Exception:
        logger.exception("Guruhga yuborishda kutilmagan xato (Message saqlangan)")


async def handle_incoming(
    chat_id: int,
    chat_name: str,
    message_text: str,
    message_date: Optional[datetime],
    telegram_msg_id: int,
    broadcast: Optional[Broadcast] = None,
    userbot_client=None,
) -> bool:
    """
    Bitta yangi (real-vaqt) xabarni tekshiradi. Mos kelsa Message yozadi va
    broadcast qiladi. Qaytaradi: mos topilib yuborilgan bo'lsa True.

    Faqat opp_channels ichidagi kanallar va enabled=True bo'lsa ishlaydi.
    """
    settings = await store.get_settings()
    if not settings.get("enabled"):
        return False

    channel = await store.get_channel(chat_id)
    if channel is None:
        return False

    # last_seen'ni har doim yangilaymiz (real-vaqt xabari — catch_up buni qayta ko'rmasin).
    if telegram_msg_id > channel.last_seen:
        await store.set_last_seen(chat_id, telegram_msg_id)

    text = (message_text or "").strip()
    if len(text) < _MIN_TEXT_LEN:
        return False

    profile = _profile_from_dict(await store.get_profile())
    today = date.today()
    post_date = message_date.date() if message_date else today

    opp = parse_post(text, post_date, chat_name)
    evaluate(opp, profile, today)

    min_score = settings.get("min_score", 40)
    if opp.score < min_score or opp.reject_reasons:
        return False

    h = _opp_hash(opp)
    if await store.is_sent(h):
        return False

    # AI (Gemini) qo'shimcha tekshiruvi: havola bo'lsa saytga kirib o'qib baholaydi.
    if not await _ai_confirms(opp):
        return False

    await store.mark_sent(h)

    await _save_match(chat_id, chat_name, opp, telegram_msg_id, broadcast, userbot_client)
    await store.record_match()
    logger.info("Yangi imkoniyat [%s]: %s", opp.score, opp.title[:50])
    return True


async def _handle_flood(e, label: str) -> None:
    wait = int(getattr(e, "seconds", 0) or 0)
    wait = min(wait, _MAX_FLOOD_WAIT)
    logger.warning("%s: FloodWait — %ss kutilmoqda (Telegram limiti)", label, wait)
    await asyncio.sleep(wait + 1)


async def catch_up(client, broadcast: Optional[Broadcast] = None) -> int:
    """
    Ilova ishga tushganda (enabled bo'lsa): har kanal uchun min_id=last_seen dan
    boshlab eskidan-yangiga (reverse=True) yangi xabarlarni o'qiydi va tekshiradi.
    Yangi qo'shilgan kanal uchun (last_seen=0) faqat baseline o'rnatiladi — eski
    postlar yuborilmaydi (eski init_baseline mantig'i).

    Qaytaradi: topilgan (yuborilgan) imkoniyatlar soni.
    """
    settings = await store.get_settings()
    if not settings.get("enabled"):
        return 0

    channels = await store.list_channels()
    found_total = 0

    for channel in channels:
        try:
            entity = await resolve_target(client, str(channel.channel_id))
            if entity is None:
                logger.warning("Catch-up: kanal topilmadi %s (%s)", channel.channel_id, channel.name)
                continue

            if channel.last_seen == 0:
                # Yangi kanal: eski postlar yuborilmasin — faqat baseline.
                async for msg in client.iter_messages(entity, limit=1):
                    await store.set_last_seen(channel.channel_id, msg.id)
                    logger.info("Baseline: %s #%s", channel.name, msg.id)
                    break
                await asyncio.sleep(1)
                continue

            new_max_id = channel.last_seen
            new_messages = []
            async for msg in client.iter_messages(
                entity, min_id=channel.last_seen, reverse=True, limit=_MAX_NEW_PER_CHANNEL,
            ):
                new_messages.append(msg)
                if msg.id > new_max_id:
                    new_max_id = msg.id

            channel_found = 0
            for msg in new_messages:
                text = (getattr(msg, "text", None) or getattr(msg, "message", None) or "").strip()
                msg_date = getattr(msg, "date", None)
                matched = await handle_incoming(
                    channel.channel_id, channel.name, text, msg_date, msg.id, broadcast, client,
                )
                if matched:
                    channel_found += 1
                    found_total += 1

            if new_max_id > channel.last_seen:
                await store.set_last_seen(channel.channel_id, new_max_id)

            await store.record_check(channel_found)
            await asyncio.sleep(2)

        except FloodWaitError as e:
            await _handle_flood(e, f"Catch-up {channel.name}")
        except Exception as e:
            logger.warning("Catch-up xatosi %s: %s", channel.name, e)
            await asyncio.sleep(2)

    return found_total
