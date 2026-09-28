"""
store.py — Imkoniyat-motor holati, endi SQLite'da (eski storage.BotState JSON o'rniga).
Xatti-harakat bir xil: add_channel, remove_channel, get_last_seen, set_last_seen,
is_sent, mark_sent, record_check, profile, settings — endi async DB funksiyalari.

Guruhlar (Stage 6): opp_groups — add_group / confirm_group / list_groups / remove_group.
"""
import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, func, select

from ..database import async_session_factory
from ..models import OppChannel, OppGroup, OppProfile, OppSent, OppSettings, OppStats

DEFAULT_PROFILE: dict[str, Any] = {
    "age": 16,
    "grade": 11,
    "ielts": 6.0,
    "knows_english": True,
    "is_student": False,
    "is_pupil": True,
    "interests": ["IT", "Biznes", "Debat", "Til", "Liderlik"],
    "only_free": True,
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,
    "min_score": 40,
    "check_interval": 600,
}

_MAX_SENT_HASHES = 5000


async def _get_or_create_profile(session) -> OppProfile:
    row = await session.get(OppProfile, 1)
    if row is None:
        row = OppProfile(
            id=1,
            age=DEFAULT_PROFILE["age"],
            grade=DEFAULT_PROFILE["grade"],
            ielts=DEFAULT_PROFILE["ielts"],
            knows_english=DEFAULT_PROFILE["knows_english"],
            is_student=DEFAULT_PROFILE["is_student"],
            is_pupil=DEFAULT_PROFILE["is_pupil"],
            interests=json.dumps(DEFAULT_PROFILE["interests"], ensure_ascii=False),
            only_free=DEFAULT_PROFILE["only_free"],
        )
        session.add(row)
        await session.flush()
    return row


async def _get_or_create_settings(session) -> OppSettings:
    row = await session.get(OppSettings, 1)
    if row is None:
        row = OppSettings(id=1, **DEFAULT_SETTINGS)
        session.add(row)
        await session.flush()
    return row


async def _get_or_create_stats(session) -> OppStats:
    row = await session.get(OppStats, 1)
    if row is None:
        row = OppStats(id=1, total_checks=0, total_found=0, last_check="")
        session.add(row)
        await session.flush()
    return row


def _profile_to_dict(row: OppProfile) -> dict[str, Any]:
    try:
        interests = json.loads(row.interests) if row.interests else []
    except (TypeError, ValueError):
        interests = []
    return {
        "age": row.age,
        "grade": row.grade,
        "ielts": row.ielts,
        "knows_english": row.knows_english,
        "is_student": row.is_student,
        "is_pupil": row.is_pupil,
        "interests": interests,
        "only_free": row.only_free,
    }


def _settings_to_dict(row: OppSettings) -> dict[str, Any]:
    return {
        "enabled": row.enabled,
        "min_score": row.min_score,
        "check_interval": row.check_interval,
    }


# ── Profil ────────────────────────────────────────────

async def get_profile() -> dict[str, Any]:
    async with async_session_factory() as session:
        row = await _get_or_create_profile(session)
        await session.commit()
        return _profile_to_dict(row)


async def update_profile(**fields: Any) -> dict[str, Any]:
    async with async_session_factory() as session:
        row = await _get_or_create_profile(session)
        for key, value in fields.items():
            if value is None and key not in ("grade", "ielts"):
                continue
            if key == "interests":
                row.interests = json.dumps(value, ensure_ascii=False)
            elif hasattr(row, key):
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return _profile_to_dict(row)


# ── Sozlamalar ────────────────────────────────────────

async def get_settings() -> dict[str, Any]:
    async with async_session_factory() as session:
        row = await _get_or_create_settings(session)
        await session.commit()
        return _settings_to_dict(row)


async def update_settings(**fields: Any) -> dict[str, Any]:
    async with async_session_factory() as session:
        row = await _get_or_create_settings(session)
        for key, value in fields.items():
            if value is None:
                continue
            if hasattr(row, key):
                setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return _settings_to_dict(row)


# ── Kanallar ──────────────────────────────────────────

async def add_channel(channel_id: int, name: str) -> OppChannel:
    async with async_session_factory() as session:
        existing = (
            await session.execute(select(OppChannel).where(OppChannel.channel_id == channel_id))
        ).scalar_one_or_none()
        if existing is not None:
            existing.name = name
            await session.commit()
            await session.refresh(existing)
            return existing
        row = OppChannel(channel_id=channel_id, name=name, last_seen=0)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def remove_channel(channel_id: int) -> bool:
    async with async_session_factory() as session:
        result = await session.execute(delete(OppChannel).where(OppChannel.channel_id == channel_id))
        await session.commit()
        return result.rowcount > 0


async def list_channels() -> list[OppChannel]:
    async with async_session_factory() as session:
        result = await session.execute(select(OppChannel).order_by(OppChannel.id))
        return list(result.scalars().all())


async def get_channel_by_db_id(db_id: int) -> Optional[OppChannel]:
    async with async_session_factory() as session:
        return await session.get(OppChannel, db_id)


async def get_channel(channel_id: int) -> Optional[OppChannel]:
    async with async_session_factory() as session:
        return (
            await session.execute(select(OppChannel).where(OppChannel.channel_id == channel_id))
        ).scalar_one_or_none()


async def remove_channel_by_db_id(db_id: int) -> bool:
    async with async_session_factory() as session:
        row = await session.get(OppChannel, db_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True


async def get_last_seen(channel_id: int) -> int:
    async with async_session_factory() as session:
        row = (
            await session.execute(select(OppChannel).where(OppChannel.channel_id == channel_id))
        ).scalar_one_or_none()
        return row.last_seen if row else 0


async def set_last_seen(channel_id: int, msg_id: int) -> None:
    async with async_session_factory() as session:
        row = (
            await session.execute(select(OppChannel).where(OppChannel.channel_id == channel_id))
        ).scalar_one_or_none()
        if row is not None:
            row.last_seen = msg_id
            await session.commit()


# ── Takror oldini olish ───────────────────────────────

async def is_sent(opp_hash: str) -> bool:
    async with async_session_factory() as session:
        row = (
            await session.execute(select(OppSent).where(OppSent.hash == opp_hash))
        ).scalar_one_or_none()
        return row is not None


async def mark_sent(opp_hash: str) -> None:
    async with async_session_factory() as session:
        existing = (
            await session.execute(select(OppSent).where(OppSent.hash == opp_hash))
        ).scalar_one_or_none()
        if existing is not None:
            return
        session.add(OppSent(hash=opp_hash))
        await session.commit()

        # Eski cheklov (oxirgi 5000) — undan oshsa eng eskisini o'chir.
        count = (
            await session.execute(select(func.count()).select_from(OppSent))
        ).scalar_one()
        if count > _MAX_SENT_HASHES:
            overflow = count - _MAX_SENT_HASHES
            old_ids = (
                await session.execute(
                    select(OppSent.id).order_by(OppSent.id.asc()).limit(overflow)
                )
            ).scalars().all()
            if old_ids:
                await session.execute(delete(OppSent).where(OppSent.id.in_(old_ids)))
                await session.commit()


# ── Statistika ────────────────────────────────────────

async def record_check(found: int, when: Optional[str] = None) -> None:
    when = when or datetime.now(timezone.utc).isoformat()
    async with async_session_factory() as session:
        row = await _get_or_create_stats(session)
        row.total_checks += 1
        row.total_found += found
        row.last_check = when
        await session.commit()


async def record_match(when: Optional[str] = None) -> None:
    """Real-vaqtda bitta imkoniyat topilganda (catch_up emas): total_found += 1."""
    when = when or datetime.now(timezone.utc).isoformat()
    async with async_session_factory() as session:
        row = await _get_or_create_stats(session)
        row.total_found += 1
        row.last_check = when
        await session.commit()


async def get_stats() -> dict[str, Any]:
    async with async_session_factory() as session:
        row = await _get_or_create_stats(session)
        await session.commit()
        return {
            "total_checks": row.total_checks,
            "total_found": row.total_found,
            "last_check": row.last_check,
        }


# ── Guruhlar (Stage 6; eski group_add/confirm/list/remove) ──

async def add_group(chat_id: int, title: str) -> OppGroup:
    """Guruh qo'shadi (status=pending). Mavjud bo'lsa nomi yangilanadi, status saqlanadi."""
    async with async_session_factory() as session:
        existing = (
            await session.execute(select(OppGroup).where(OppGroup.chat_id == chat_id))
        ).scalar_one_or_none()
        if existing is not None:
            existing.title = title
            await session.commit()
            await session.refresh(existing)
            return existing
        row = OppGroup(chat_id=chat_id, title=title, status="pending")
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def list_groups(status: Optional[str] = None) -> list[OppGroup]:
    async with async_session_factory() as session:
        query = select(OppGroup).order_by(OppGroup.id)
        if status is not None:
            query = query.where(OppGroup.status == status)
        return list((await session.execute(query)).scalars().all())


async def get_group_by_db_id(db_id: int) -> Optional[OppGroup]:
    async with async_session_factory() as session:
        return await session.get(OppGroup, db_id)


async def confirm_group(db_id: int) -> Optional[OppGroup]:
    async with async_session_factory() as session:
        row = await session.get(OppGroup, db_id)
        if row is None:
            return None
        row.status = "confirmed"
        await session.commit()
        await session.refresh(row)
        return row


async def remove_group_by_db_id(db_id: int) -> bool:
    async with async_session_factory() as session:
        row = await session.get(OppGroup, db_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True
