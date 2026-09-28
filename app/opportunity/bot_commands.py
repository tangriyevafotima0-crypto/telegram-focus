"""
bot_commands.py — Eski bot.py buyruqlarini Telegram orqali saqlash (IXTIYORIY, Stage 6).

Faqat `.env` da BOT_TOKEN va OWNER_ID bo'lsa yuklanadi (`register()` aks holda hech
narsa qilmaydi). Har buyruq store/service/engine funksiyalarini chaqiradi — mantiq
ikkilanmaydi (HTTP router ham xuddi shularni chaqiradi).

Buyruqlar: /start, /monitor_add|remove|list|on|off|status, /scan_now, /refresh,
/group_add|confirm|list|remove, /profile, /profile_set.

Dekoratorlar (eski bot.py dan): owner_only (faqat egasi, shaxsiy chatda),
owner_in_group (egasi guruhda — guruhda /group_confirm ishlatish uchun).
"""
import functools
import logging
from typing import Any, Awaitable, Callable, Optional

from . import delivery, service, store
from .engine import catch_up
from .resolve import _load_dialog_cache

try:
    from telethon import events
except Exception:  # pragma: no cover
    events = None  # type: ignore[assignment]

logger = logging.getLogger("opportunity.bot_commands")

START_TEXT = (
    "👋 Imkoniyat monitori\n\n"
    "Kanallarni kuzatib, sizga mos imkoniyatlarni topaman.\n\n"
    "📡 Kanallar:\n"
    "/monitor_add <@kanal | link | ID> — kanal qo'shish\n"
    "/monitor_remove <ID> — kanalni o'chirish\n"
    "/monitor_list — kanallar ro'yxati\n"
    "/monitor_on, /monitor_off — yoqish / o'chirish\n"
    "/monitor_status — holat\n"
    "/scan_now — hozir tekshirish\n"
    "/refresh — dialoglarni yangilash\n\n"
    "👥 Guruhlar:\n"
    "/group_add <@guruh | link | ID> — guruh qo'shish\n"
    "/group_confirm <ID> — tasdiqlash\n"
    "/group_list — ro'yxat\n"
    "/group_remove <ID> — o'chirish\n\n"
    "👤 Profil:\n"
    "/profile — ko'rish\n"
    "/profile_set <maydon> <qiymat> — o'zgartirish"
)

# /profile_set uchun ruxsat etilgan maydonlar va ularning turlari.
_PROFILE_FIELDS: dict[str, str] = {
    "age": "int",
    "grade": "int?",
    "ielts": "float?",
    "knows_english": "bool",
    "is_student": "bool",
    "is_pupil": "bool",
    "only_free": "bool",
    "interests": "list",
}
_VALID_INTERESTS = ["IT", "Til", "Fan", "Biznes", "Debat", "Liderlik", "Madaniyat", "San'at"]

Handler = Callable[[Any], Awaitable[None]]


# ── Dekoratorlar (eski bot.py dan) ────────────────────

def owner_only(func: Handler) -> Handler:
    """Faqat egasi (OWNER_ID) va faqat shaxsiy chatda."""

    @functools.wraps(func)
    async def wrapper(event) -> None:
        owner = delivery.owner_id()
        if owner is None or event.sender_id != owner:
            return  # begonalarga javob berilmaydi
        if not getattr(event, "is_private", True):
            return
        await func(event)

    return wrapper


def owner_in_group(func: Handler) -> Handler:
    """Egasi (OWNER_ID) — shaxsiy chatda ham, guruhda ham."""

    @functools.wraps(func)
    async def wrapper(event) -> None:
        owner = delivery.owner_id()
        if owner is None or event.sender_id != owner:
            return
        await func(event)

    return wrapper


def _args(event) -> str:
    """'/cmd arg1 arg2' -> 'arg1 arg2'."""
    text = (getattr(event, "raw_text", None) or getattr(event, "text", "") or "").strip()
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _userbot():
    """Asosiy userbot klienti (kanal/guruhni topish uchun) yoki None."""
    from ..telethon_client import get_client

    try:
        return get_client()
    except RuntimeError:
        return None


def _parse_bool(value: str) -> bool:
    v = value.strip().lower()
    if v in ("1", "true", "ha", "yes", "on", "y"):
        return True
    if v in ("0", "false", "yo'q", "yoq", "no", "off", "n"):
        return False
    raise ValueError("ha/yo'q (yoki true/false) deb yozing")


def parse_profile_value(field: str, raw: str) -> Any:
    """/profile_set qiymatini turga o'giradi; noto'g'ri bo'lsa ValueError."""
    kind = _PROFILE_FIELDS[field]
    raw = raw.strip()
    if kind.endswith("?") and raw.lower() in ("", "none", "yo'q", "yoq", "-", "null"):
        return None
    if kind.startswith("int"):
        value = int(raw)
        bounds = {"age": (5, 100), "grade": (1, 11)}[field]
        if not bounds[0] <= value <= bounds[1]:
            raise ValueError(f"{field}: {bounds[0]}–{bounds[1]} oralig'ida bo'lishi kerak")
        return value
    if kind.startswith("float"):
        value = float(raw.replace(",", "."))
        if not 0 <= value <= 9:
            raise ValueError("ielts: 0–9 oralig'ida bo'lishi kerak")
        return value
    if kind == "bool":
        return _parse_bool(raw)
    if kind == "list":
        items = [x.strip() for x in raw.replace(";", ",").split(",") if x.strip()]
        bad = [x for x in items if x not in _VALID_INTERESTS]
        if bad:
            raise ValueError(f"Noto'g'ri qiziqish: {', '.join(bad)}. Mumkin: {', '.join(_VALID_INTERESTS)}")
        return items
    raise ValueError("noma'lum maydon")


# ── Buyruq amallari (event'ga bog'liq emas — testlash oson) ──

async def do_start() -> str:
    return START_TEXT


async def do_monitor_add(arg: str) -> str:
    if not arg:
        return "Ishlatish: /monitor_add <@kanal | t.me link | ID>"
    client = _userbot()
    if client is None:
        return "❌ Telegram mijozi ulanmagan."
    try:
        row = await service.add_channel_by_identifier(client, arg)
    except service.ServiceError as exc:
        return f"❌ {exc.detail}"
    return f"✅ Qo'shildi: {row.name} (ID: {row.channel_id})"


async def do_monitor_remove(arg: str) -> str:
    if not arg:
        return "Ishlatish: /monitor_remove <ID>  (ID — /monitor_list dagi raqam)"
    try:
        db_id = int(arg)
    except ValueError:
        return "❌ ID raqam bo'lishi kerak."
    return "✅ O'chirildi." if await store.remove_channel_by_db_id(db_id) else "❌ Kanal topilmadi."


async def do_monitor_list() -> str:
    rows = await store.list_channels()
    if not rows:
        return "Kanallar yo'q. /monitor_add bilan qo'shing."
    return "📡 Kuzatilayotgan kanallar:\n" + "\n".join(f"{r.id}. {r.name} ({r.channel_id})" for r in rows)


async def do_monitor_toggle(enabled: bool) -> str:
    current = await store.get_settings()
    await store.update_settings(
        enabled=enabled, min_score=current["min_score"], check_interval=current["check_interval"]
    )
    return "✅ Monitor yoqildi." if enabled else "⏸ Monitor o'chirildi."


async def do_monitor_status() -> str:
    st = await service.build_status()
    return (
        f"📊 Monitor: {'yoqilgan' if st['enabled'] else 'o‘chirilgan'}\n"
        f"Kanallar: {st['channels_count']}\n"
        f"Min. ball: {st['min_score']}\n"
        f"Tekshiruvlar: {st['total_checks']}, topilgan: {st['total_found']}\n"
        f"Oxirgi: {st['last_check'] or '—'}"
    )


async def do_scan_now(broadcast: Optional[Callable] = None) -> str:
    client = _userbot()
    if client is None:
        return "❌ Telegram mijozi ulanmagan."
    found = await catch_up(client, broadcast)
    return f"🔍 Tekshiruv tugadi: {found} ta yangi imkoniyat."


async def do_refresh() -> str:
    client = _userbot()
    if client is None:
        return "❌ Telegram mijozi ulanmagan."
    return f"🔄 Dialoglar yangilandi: {await _load_dialog_cache(client)} ta."


async def do_group_add(arg: str) -> str:
    if not arg:
        return "Ishlatish: /group_add <@guruh | t.me link | ID>"
    client = _userbot()
    if client is None:
        return "❌ Telegram mijozi ulanmagan."
    try:
        row = await service.add_group_by_identifier(client, arg)
    except service.ServiceError as exc:
        return f"❌ {exc.detail}"
    return f"➕ Guruh qo'shildi (kutilmoqda): {row.title}\nTasdiqlash: /group_confirm {row.id}"


async def do_group_confirm(arg: str) -> str:
    try:
        db_id = int(arg)
    except ValueError:
        return "Ishlatish: /group_confirm <ID>  (ID — /group_list dagi raqam)"
    group = await store.get_group_by_db_id(db_id)
    if group is None:
        return "❌ Guruh topilmadi."
    client = _userbot()
    ok, reason = await delivery.check_group_ready(client, group.chat_id)
    if not ok:
        return f"❌ {reason}"
    await store.confirm_group(db_id)
    await delivery.send_confirmation(client, group.chat_id)
    return f"✅ Tasdiqlandi: {group.title}"


async def do_group_list() -> str:
    rows = await store.list_groups()
    if not rows:
        return "Guruhlar yo'q. /group_add bilan qo'shing."
    mark = {"confirmed": "✓", "pending": "●"}
    return "👥 Guruhlar:\n" + "\n".join(f"{r.id}. {mark.get(r.status, '?')} {r.title} ({r.chat_id})" for r in rows)


async def do_group_remove(arg: str) -> str:
    try:
        db_id = int(arg)
    except ValueError:
        return "Ishlatish: /group_remove <ID>"
    return "✅ O'chirildi." if await store.remove_group_by_db_id(db_id) else "❌ Guruh topilmadi."


async def do_profile() -> str:
    p = await store.get_profile()
    return (
        "👤 Profil:\n"
        f"Yosh: {p['age']}\nSinf: {p['grade'] if p['grade'] is not None else '—'}\n"
        f"IELTS: {p['ielts'] if p['ielts'] is not None else '—'}\n"
        f"Ingliz tili: {'ha' if p['knows_english'] else 'yo‘q'}\n"
        f"O'quvchi: {'ha' if p['is_pupil'] else 'yo‘q'}, talaba: {'ha' if p['is_student'] else 'yo‘q'}\n"
        f"Faqat bepul: {'ha' if p['only_free'] else 'yo‘q'}\n"
        f"Qiziqishlar: {', '.join(p['interests']) or '—'}\n\n"
        "O'zgartirish: /profile_set <maydon> <qiymat>\n"
        f"Maydonlar: {', '.join(_PROFILE_FIELDS)}"
    )


async def do_profile_set(arg: str) -> str:
    parts = arg.split(maxsplit=1)
    if len(parts) < 2 or parts[0] not in _PROFILE_FIELDS:
        return f"Ishlatish: /profile_set <maydon> <qiymat>\nMaydonlar: {', '.join(_PROFILE_FIELDS)}"
    field, raw = parts
    try:
        value = parse_profile_value(field, raw)
    except ValueError as exc:
        return f"❌ {exc}"
    current = await store.get_profile()
    current[field] = value
    await store.update_profile(**current)
    return f"✅ {field} yangilandi."


# ── Ro'yxatdan o'tkazish ──────────────────────────────

def _build_routes(broadcast: Optional[Callable]) -> list[tuple[str, Handler, bool]]:
    """(buyruq, handler, guruhda_ruxsat) ro'yxati. Handler event'ni oladi va javob beradi."""

    def simple(fn):
        async def handler(event):
            await event.respond(await fn())
        return handler

    def with_arg(fn):
        async def handler(event):
            await event.respond(await fn(_args(event)))
        return handler

    async def scan(event):
        await event.respond("🔍 Tekshirilmoqda...")
        await event.respond(await do_scan_now(broadcast))

    async def on(event):
        await event.respond(await do_monitor_toggle(True))

    async def off(event):
        await event.respond(await do_monitor_toggle(False))

    return [
        ("start", simple(do_start), False),
        ("monitor_add", with_arg(do_monitor_add), False),
        ("monitor_remove", with_arg(do_monitor_remove), False),
        ("monitor_list", simple(do_monitor_list), False),
        ("monitor_on", on, False),
        ("monitor_off", off, False),
        ("monitor_status", simple(do_monitor_status), False),
        ("scan_now", scan, False),
        ("refresh", simple(do_refresh), False),
        ("group_add", with_arg(do_group_add), False),
        ("group_confirm", with_arg(do_group_confirm), True),  # guruhda ham egasi tasdiqlay oladi
        ("group_list", simple(do_group_list), False),
        ("group_remove", with_arg(do_group_remove), False),
        ("profile", simple(do_profile), False),
        ("profile_set", with_arg(do_profile_set), False),
    ]


def register(bot_client, broadcast: Optional[Callable] = None) -> int:
    """
    Bot klientiga buyruqlarni ro'yxatdan o'tkazadi. BOT_TOKEN/OWNER_ID yo'q bo'lsa
    yoki bot klienti None bo'lsa — hech narsa qilmaydi (0 qaytaradi), xatosiz.
    """
    if bot_client is None or not delivery.bot_configured() or delivery.owner_id() is None:
        return 0
    if events is None:
        logger.warning("Bot buyruqlari: telethon o'rnatilmagan.")
        return 0
    count = 0
    for name, handler, in_group in _build_routes(broadcast):
        wrapped = owner_in_group(handler) if in_group else owner_only(handler)
        pattern = rf"^/{name}(?:@\w+)?(?:\s|$)"
        bot_client.add_event_handler(wrapped, events.NewMessage(pattern=pattern))
        count += 1
    logger.info("Bot buyruqlari ro'yxatdan o'tdi: %s ta.", count)
    return count
