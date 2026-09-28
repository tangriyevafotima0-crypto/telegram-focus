"""
delivery.py — Mos topilgan imkoniyatni Telegram guruh(lar)iga yuborish (Stage 6).

Ikki rejim:
  (B) "bot"     — .env da BOT_TOKEN bo'lsa: Telethon'da ikkinchi klient
                  (TelegramClient(...).start(bot_token=...)); xabar bot nomidan,
                  guruhda bot ADMIN bo'lishi shart (eski bot.py xatti-harakati).
  (A) "userbot" — BOT_TOKEN yo'q bo'lsa: asosiy userbot yuboradi (xabar
                  foydalanuvchi akkaunti nomidan); admin shart emas, lekin
                  yuborish huquqi tekshiriladi.

BOT_TOKEN hech qachon log/javobga chiqarilmaydi.
"""
import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from . import store

try:
    from telethon import TelegramClient
    from telethon.errors import FloodWaitError
except Exception:  # pragma: no cover — telethon yo'q muhitda ham import ishlasin
    TelegramClient = None  # type: ignore[assignment]

    class FloodWaitError(Exception):  # type: ignore[no-redef]
        seconds = 0

logger = logging.getLogger("opportunity.delivery")

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")

# Eski monitor.py dagi chegara (o'zgarishsiz):
_MAX_FLOOD_WAIT = 300

CONFIRMED_TEXT = "✅ Bu guruh imkoniyatlar yuborish uchun tasdiqlandi."

_bot_client: Optional[Any] = None


# ── Rejim ─────────────────────────────────────────────

def bot_token() -> str:
    """BOT_TOKEN (bo'sh bo'lishi mumkin). Faqat ichki foydalanish — hech qachon log qilinmaydi."""
    return os.getenv("BOT_TOKEN", "").strip()


def bot_configured() -> bool:
    return bool(bot_token())


def owner_id() -> Optional[int]:
    raw = os.getenv("OWNER_ID", "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


def get_bot_client() -> Optional[Any]:
    """Ishga tushgan bot klienti (bot rejimida), aks holda None."""
    return _bot_client


def delivery_mode() -> str:
    """'bot' — BOT_TOKEN sozlangan va bot klienti ishlayapti; aks holda 'userbot'."""
    if bot_configured() and _bot_client is not None:
        return "bot"
    return "userbot"


def mode_info() -> dict:
    mode = delivery_mode()
    return {
        "mode": mode,
        "bot_configured": bot_configured(),
        "warning": (
            "Xabarlar sizning akkauntingiz nomidan yuboriladi."
            if mode == "userbot"
            else None
        ),
    }


# ── Bot klientni yuritish ─────────────────────────────

async def start_bot_client() -> Optional[Any]:
    """
    BOT_TOKEN bo'lsa bot klientini ishga tushiradi (session — alohida fayl).
    Bo'lmasa yoki xato bo'lsa None (userbot rejimida qolinadi). Token logga chiqmaydi.
    """
    global _bot_client
    token = bot_token()
    if not token:
        return None
    if TelegramClient is None:
        logger.warning("Bot rejimi: telethon o'rnatilmagan.")
        return None
    try:
        api_id = int(os.getenv("TELEGRAM_API_ID", "").strip())
        api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
        if not api_hash:
            raise ValueError("TELEGRAM_API_HASH bo'sh")
    except (ValueError, TypeError):
        logger.warning("Bot rejimi: TELEGRAM_API_ID/TELEGRAM_API_HASH noto'g'ri — userbot rejimida.")
        return None
    try:
        client = TelegramClient(str(BACKEND_DIR / "telegram_focus_bot"), api_id, api_hash)
        await client.start(bot_token=token)
        _bot_client = client
        logger.info("Bot klienti ishga tushdi (bot rejimi).")
        return client
    except Exception as exc:
        # str(exc) tokenni o'z ichiga olmaydi, lekin ehtiyot uchun turini yozamiz.
        logger.error("Bot klienti ishga tushmadi (%s) — userbot rejimida.", type(exc).__name__)
        _bot_client = None
        return None


async def stop_bot_client() -> None:
    global _bot_client
    client, _bot_client = _bot_client, None
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            logger.warning("Bot klientini uzishda xato.")


# ── Huquqlarni tekshirish ─────────────────────────────

async def _is_bot_admin(bot, entity) -> bool:
    """Bot guruhda administrator/creator ekanini tekshiradi (eski xatti-harakat)."""
    try:
        me = await bot.get_me()
        perms = await bot.get_permissions(entity, me)
        return bool(getattr(perms, "is_admin", False) or getattr(perms, "is_creator", False))
    except Exception as exc:
        logger.warning("Admin tekshiruvida xato: %s", type(exc).__name__)
        return False


async def _userbot_can_send(client, entity) -> bool:
    """Userbot guruhga yoza olishini tekshiradi."""
    try:
        me = await client.get_me()
        perms = await client.get_permissions(entity, me)
        if perms is None:
            return False
        if getattr(perms, "is_admin", False) or getattr(perms, "is_creator", False):
            return True
        return bool(getattr(perms, "send_messages", True))
    except Exception as exc:
        logger.warning("Yuborish huquqini tekshirishda xato: %s", type(exc).__name__)
        return False


async def check_group_ready(userbot_client, chat_id: int) -> tuple[bool, str]:
    """
    Guruh tasdiqlash/yuborish uchun tayyormi. Qaytaradi: (ok, sabab).
    Bot rejimi: bot guruhda admin bo'lishi shart. Userbot rejimi: yozish huquqi.
    """
    mode = delivery_mode()
    if mode == "bot":
        bot = get_bot_client()
        try:
            entity = await bot.get_entity(chat_id)
        except Exception:
            return False, (
                "Bot bu guruhni topa olmadi. Botni guruhga qo'shib, administrator qiling."
            )
        if not await _is_bot_admin(bot, entity):
            return False, "Bot guruhda administrator emas. Botga admin huquqi bering."
        return True, ""

    if userbot_client is None:
        return False, "Telegram mijozi ulanmagan."
    try:
        entity = await userbot_client.get_entity(chat_id)
    except Exception:
        return False, "Akkauntingiz bu guruhni topa olmadi (a'zo ekanligingizni tekshiring)."
    if not await _userbot_can_send(userbot_client, entity):
        return False, "Akkauntingizda bu guruhga xabar yuborish huquqi yo'q."
    return True, ""


# ── Yuborish ──────────────────────────────────────────

async def _send_with_retry(sender, chat_id: int, text: str) -> None:
    """
    FloodWait ≤300s kutib 1 marta qayta urinadi. `sender(chat_id, text, parse_mode)` —
    bir xabarni yuboradigan korutina. Formatlash (markdown) xatosi bo'lsa `**` ni
    olib tashlab oddiy matn bilan qayta yuboradi (eski fallback).
    """
    async def _attempt(msg: str, parse_mode: Optional[str]) -> None:
        await sender(chat_id, msg, parse_mode)

    async def _with_flood_retry(msg: str, parse_mode: Optional[str]) -> None:
        try:
            await _attempt(msg, parse_mode)
        except FloodWaitError as exc:
            wait = min(int(getattr(exc, "seconds", 0) or 0), _MAX_FLOOD_WAIT)
            logger.warning("Yuborish: FloodWait — %ss kutilmoqda", wait)
            await asyncio.sleep(wait + 1)
            await _attempt(msg, parse_mode)

    try:
        await _with_flood_retry(text, "md")
    except FloodWaitError:
        raise
    except Exception as exc:
        logger.info("Markdown yuborish xatosi (%s) — oddiy matn bilan qayta urinilmoqda.", type(exc).__name__)
        await _with_flood_retry(text.replace("**", ""), None)


def _make_sender(client):
    async def _send(chat_id: int, msg: str, parse_mode: Optional[str]) -> None:
        await client.send_message(chat_id, msg, parse_mode=parse_mode, link_preview=False)

    return _send


async def send_to_chat(client, chat_id: int, text: str) -> None:
    """Berilgan klient orqali bitta chatga yuboradi (FloodWait + markdown fallback bilan)."""
    await _send_with_retry(_make_sender(client), chat_id, text)


async def deliver(text: str, userbot_client=None) -> int:
    """
    Tasdiqlangan HAR guruhga yuboradi. Bitta guruh xatosi boshqalarni to'xtatmaydi;
    hech qachon istisno ko'tarmaydi (Message DB'da baribir qoladi). Qaytaradi: muvaffaqiyatli
    yuborilgan guruhlar soni.

    Bot rejimida yuborishdan oldin admin qayta tekshiriladi (eski xatti-harakat).
    """
    try:
        groups = await store.list_groups("confirmed")
    except Exception:
        logger.exception("Guruhlar ro'yxatini o'qishda xato — yuborish o'tkazib yuborildi.")
        return 0
    if not groups:
        return 0

    mode = delivery_mode()
    sender_client = get_bot_client() if mode == "bot" else userbot_client
    if sender_client is None:
        logger.warning("Yuborish: klient mavjud emas (%s rejimi) — o'tkazib yuborildi.", mode)
        return 0

    sent = 0
    for group in groups:
        try:
            if mode == "bot":
                try:
                    entity = await sender_client.get_entity(group.chat_id)
                except Exception:
                    logger.warning("Guruh topilmadi (%s) — o'tkazib yuborildi.", group.title)
                    continue
                if not await _is_bot_admin(sender_client, entity):
                    logger.warning("Bot '%s' guruhida admin emas — yuborilmadi.", group.title)
                    continue
            await send_to_chat(sender_client, group.chat_id, text)
            sent += 1
        except FloodWaitError as exc:
            logger.warning("Guruh '%s': FloodWait davom etdi (%ss) — o'tkazildi.", group.title, getattr(exc, "seconds", "?"))
        except Exception as exc:
            logger.warning("Guruhga yuborishda xato '%s': %s", group.title, type(exc).__name__)
    return sent


async def send_confirmation(userbot_client, chat_id: int) -> bool:
    """Guruh tasdiqlangach '✅ tasdiqlandi' xabarini yuboradi (eski matn). Xato bo'lsa False."""
    client = get_bot_client() if delivery_mode() == "bot" else userbot_client
    if client is None:
        return False
    try:
        await send_to_chat(client, chat_id, CONFIRMED_TEXT)
        return True
    except Exception as exc:
        logger.warning("Tasdiqlash xabari yuborilmadi: %s", type(exc).__name__)
        return False
