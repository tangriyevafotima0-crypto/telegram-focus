"""
service.py — HTTP router (routers/opportunity.py) va Telegram bot buyruqlari
(bot_commands.py) UMUMIY ishlatadigan yuqori darajali amallar. Mantiq bir joyda:
ikkalasi ham shu funksiyalarni chaqiradi.
"""
import logging
from typing import Any, Optional

from telethon.tl.types import Channel, Chat

from . import store
from .resolve import resolve_target

logger = logging.getLogger("opportunity.service")

NOT_FOUND_CHANNEL = "Kanal topilmadi. Akkauntingiz shu kanalga a'zoligini tekshiring."
NOT_FOUND_GROUP = "Guruh topilmadi. Akkauntingiz shu guruhga a'zoligini tekshiring."


class ServiceError(Exception):
    """Foydalanuvchiga ko'rsatiladigan xato (HTTP status bilan)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def normalize_target(identifier: str) -> str:
    """@username | t.me link | ID -> resolve_target uchun target string."""
    value = identifier.strip()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    return value.strip()


def full_chat_id(entity) -> int:
    """Telethon entity -> to'liq chat ID (Channel: -100..., Chat: -id)."""
    cid = entity.id
    if isinstance(entity, Channel):
        return int(f"-100{cid}")
    if isinstance(entity, Chat):
        return -cid
    return cid


async def resolve_entity(client, identifier: str, not_found: str):
    """identifier -> entity yoki ServiceError(404)."""
    target = normalize_target(identifier)
    try:
        entity = await resolve_target(client, target)
    except Exception as exc:
        logger.warning("Topishda xato %s: %s", target, type(exc).__name__)
        entity = None
    if entity is None:
        raise ServiceError(404, not_found)
    return entity


async def add_channel_by_identifier(client, identifier: str):
    entity = await resolve_entity(client, identifier, NOT_FOUND_CHANNEL)
    name = getattr(entity, "title", str(entity.id))
    return await store.add_channel(full_chat_id(entity), name)


async def add_group_by_identifier(client, identifier: str, title: Optional[str] = None):
    entity = await resolve_entity(client, identifier, NOT_FOUND_GROUP)
    full_id = full_chat_id(entity)
    name = (title or "").strip() or getattr(entity, "title", None) or str(full_id)
    return await store.add_group(full_id, name[:255])


async def build_status() -> dict[str, Any]:
    settings = await store.get_settings()
    channels = await store.list_channels()
    stats = await store.get_stats()
    return {
        "enabled": settings["enabled"],
        "channels_count": len(channels),
        "min_score": settings["min_score"],
        "check_interval": settings["check_interval"],
        "total_checks": stats["total_checks"],
        "total_found": stats["total_found"],
        "last_check": stats["last_check"],
    }
