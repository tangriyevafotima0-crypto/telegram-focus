"""Imkoniyat-aniqlash motori API'si (Stage 5) + guruhga yuborish (Stage 6)."""
import json
import logging
import os
import tempfile
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models import Message
from ..opportunity import delivery, service, store
from ..opportunity.formatting import parse_formatted_meta
from ..opportunity.engine import catch_up
from ..opportunity.matcher import Profile, evaluate, filter_and_rank
from ..opportunity.parser import Opportunity, parse_export_file, parse_post
from ..opportunity.resolve import _load_dialog_cache
from ..telethon_client import get_client
from .messages import message_manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/opp", tags=["opportunity"])

VALID_INTERESTS = ["IT", "Til", "Fan", "Biznes", "Debat", "Liderlik", "Madaniyat", "San'at"]

_MAX_IMPORT_BYTES = 2 * 1024 * 1024


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


def _opp_to_dict(opp: Opportunity) -> dict:
    return {
        "title": opp.title,
        "deadline": opp.deadline.isoformat() if opp.deadline else None,
        "deadline_raw": opp.deadline_raw,
        "age_min": opp.age_min,
        "age_max": opp.age_max,
        "grade_min": opp.grade_min,
        "grade_max": opp.grade_max,
        "ielts_required": opp.ielts_required,
        "english_required": opp.english_required,
        "is_free": opp.is_free,
        "fields": opp.fields,
        "link": opp.link or None,
        "score": opp.score,
        "match_reasons": opp.match_reasons,
        "reject_reasons": opp.reject_reasons,
    }


def _get_connected_client():
    try:
        return get_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# ── PROFIL ────────────────────────────────────────────

class OppProfileIn(BaseModel):
    age: int = Field(ge=5, le=100)
    grade: Optional[int] = Field(default=None, ge=1, le=11)
    ielts: Optional[float] = Field(default=None, ge=0, le=9)
    knows_english: bool = True
    is_student: bool = True
    is_pupil: bool = True
    interests: list[str] = Field(default_factory=list)
    only_free: bool = True

    @field_validator("interests")
    @classmethod
    def _validate_interests(cls, value: list[str]) -> list[str]:
        invalid = [item for item in value if item not in VALID_INTERESTS]
        if invalid:
            raise ValueError(f"Noto'g'ri qiziqish: {', '.join(invalid)}")
        return value


class OppProfileOut(BaseModel):
    age: int
    grade: Optional[int] = None
    ielts: Optional[float] = None
    knows_english: bool
    is_student: bool
    is_pupil: bool
    interests: list[str]
    only_free: bool


@router.get("/profile", response_model=OppProfileOut)
async def get_profile() -> OppProfileOut:
    return OppProfileOut(**await store.get_profile())


@router.put("/profile", response_model=OppProfileOut)
async def put_profile(payload: OppProfileIn) -> OppProfileOut:
    updated = await store.update_profile(**payload.model_dump())
    return OppProfileOut(**updated)


# ── SOZLAMALAR ────────────────────────────────────────

class OppSettingsIn(BaseModel):
    enabled: bool
    min_score: int = Field(ge=0, le=200)
    check_interval: int = Field(ge=60)


class OppSettingsOut(BaseModel):
    enabled: bool
    min_score: int
    check_interval: int


@router.get("/settings", response_model=OppSettingsOut)
async def get_settings() -> OppSettingsOut:
    return OppSettingsOut(**await store.get_settings())


@router.put("/settings", response_model=OppSettingsOut)
async def put_settings(payload: OppSettingsIn) -> OppSettingsOut:
    updated = await store.update_settings(**payload.model_dump())
    return OppSettingsOut(**updated)


# ── KANALLAR ──────────────────────────────────────────

class OppChannelIn(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)

    @field_validator("identifier")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("identifier bo'sh bo'lishi mumkin emas.")
        return value


class OppChannelOut(BaseModel):
    id: int
    channel_id: int
    name: str
    last_seen: int
    created_at: datetime

    model_config = {"from_attributes": True}


_normalize_target = service.normalize_target


@router.post("/channels", response_model=OppChannelOut, status_code=status.HTTP_201_CREATED)
async def add_channel(payload: OppChannelIn) -> OppChannelOut:
    client = _get_connected_client()
    try:
        row = await service.add_channel_by_identifier(client, payload.identifier)
    except service.ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return OppChannelOut.model_validate(row)


@router.get("/channels", response_model=list[OppChannelOut])
async def list_channels() -> list[OppChannelOut]:
    rows = await store.list_channels()
    return [OppChannelOut.model_validate(row) for row in rows]


@router.delete("/channels/{channel_db_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_channel(channel_db_id: int) -> None:
    removed = await store.remove_channel_by_db_id(channel_db_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Kanal topilmadi.")


# ── DIALOG KESH / SKAN ────────────────────────────────

@router.post("/refresh-dialogs")
async def refresh_dialogs() -> dict:
    client = _get_connected_client()
    count = await _load_dialog_cache(client)
    return {"count": count}


@router.post("/scan-now")
async def scan_now() -> dict:
    client = _get_connected_client()
    found = await catch_up(client, message_manager.broadcast)
    return {"found": found}


# ── HOLAT ─────────────────────────────────────────────

class OppStatusOut(BaseModel):
    enabled: bool
    channels_count: int
    min_score: int
    check_interval: int
    total_checks: int
    total_found: int
    last_check: str


@router.get("/status", response_model=OppStatusOut)
async def get_status() -> OppStatusOut:
    return OppStatusOut(**await service.build_status())


# ── TAHLIL (yangi) ────────────────────────────────────

class AnalyzeIn(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


@router.post("/analyze")
async def analyze(payload: AnalyzeIn) -> dict:
    profile = _profile_from_dict(await store.get_profile())
    opp = parse_post(payload.text, date.today(), "")
    evaluate(opp, profile, date.today())
    result = _opp_to_dict(opp)
    result["title"] = opp.title
    return result


# ── EKSPORT FAYL TAHLILI (eski) ───────────────────────

class ImportExportIn(BaseModel):
    text: str = Field(min_length=1)


@router.post("/import-export")
async def import_export(payload: ImportExportIn) -> dict:
    encoded = payload.text.encode("utf-8")
    if len(encoded) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Matn 2 MB dan katta bo'lishi mumkin emas.")

    profile = _profile_from_dict(await store.get_profile())
    settings = await store.get_settings()

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(payload.text)
            tmp_path = handle.name
        channel, opportunities = parse_export_file(tmp_path)
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    ranked = filter_and_rank(opportunities, profile, min_score=settings["min_score"])
    return {
        "channel": channel,
        "total_posts": len(opportunities),
        "found": len(ranked),
        "opportunities": [_opp_to_dict(opp) for opp in ranked],
    }


# ── GURUHLAR (Stage 6; eski group_add/confirm/list/remove) ─────

class OppGroupIn(BaseModel):
    chat_id: Optional[int] = None
    identifier: Optional[str] = Field(default=None, max_length=255)
    title: Optional[str] = Field(default=None, max_length=255)

    @field_validator("identifier")
    @classmethod
    def _strip_identifier(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None


class OppGroupOut(BaseModel):
    id: int
    chat_id: int
    title: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DeliveryModeOut(BaseModel):
    mode: str
    bot_configured: bool
    warning: Optional[str] = None


@router.get("/delivery-mode", response_model=DeliveryModeOut)
async def get_delivery_mode() -> DeliveryModeOut:
    return DeliveryModeOut(**delivery.mode_info())


@router.get("/groups", response_model=list[OppGroupOut])
async def list_groups() -> list[OppGroupOut]:
    rows = await store.list_groups()
    return [OppGroupOut.model_validate(row) for row in rows]


@router.post("/groups", response_model=OppGroupOut, status_code=status.HTTP_201_CREATED)
async def add_group(payload: OppGroupIn) -> OppGroupOut:
    """Guruh qo'shadi (status=pending). `identifier` (@username/t.me/ID) yoki `chat_id` beriladi;
    resolve_target bilan tekshiriladi."""
    target = payload.identifier or (str(payload.chat_id) if payload.chat_id is not None else None)
    if not target:
        raise HTTPException(status_code=422, detail="chat_id yoki identifier kerak.")
    client = _get_connected_client()
    try:
        row = await service.add_group_by_identifier(client, target, payload.title)
    except service.ServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return OppGroupOut.model_validate(row)


@router.post("/groups/{group_db_id}/confirm", response_model=OppGroupOut)
async def confirm_group(group_db_id: int) -> OppGroupOut:
    group = await store.get_group_by_db_id(group_db_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Guruh topilmadi.")
    client = None
    try:
        client = get_client()
    except RuntimeError:
        client = None
    if delivery.delivery_mode() == "userbot" and client is None:
        raise HTTPException(status_code=503, detail="Telegram mijozi ulanmagan.")
    ok, reason = await delivery.check_group_ready(client, group.chat_id)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    row = await store.confirm_group(group_db_id)
    await delivery.send_confirmation(client, group.chat_id)
    return OppGroupOut.model_validate(row)


@router.delete("/groups/{group_db_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_db_id: int) -> None:
    removed = await store.remove_group_by_db_id(group_db_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Guruh topilmadi.")


# ── LENTA (Stage 6; frontend "Imkoniyatlar" tab'i uchun) ─────

class OppFeedItem(BaseModel):
    id: int
    title: str
    score: Optional[int] = None
    deadline: Optional[str] = None
    days_left: Optional[int] = None
    fields: list[str] = Field(default_factory=list)
    is_free: bool = False
    reasons: str = ""
    link: Optional[str] = None
    channel_name: str = ""
    received_at: datetime
    is_read: bool = False
    is_archived: bool = False


def _safe_http_link(value: Optional[str]) -> Optional[str]:
    """Faqat http/https havolalar (boshqa sxemalar — javobda None)."""
    if not value:
        return None
    lowered = value.strip().lower()
    return value.strip() if lowered.startswith(("http://", "https://")) else None


def _feed_item(message: Message) -> OppFeedItem:
    meta = parse_formatted_meta(message.text or "")
    link = meta["link"]
    if not link and message.link_urls:
        try:
            urls = json.loads(message.link_urls)
            link = urls[0] if urls else None
        except (TypeError, ValueError):
            link = None
    deadline = meta["deadline"]
    days_left = None
    if deadline:
        try:
            days_left = (date.fromisoformat(deadline) - date.today()).days
        except ValueError:
            deadline = None
    return OppFeedItem(
        id=message.id,
        title=meta["title"] or (message.text or "").split("\n")[0][:120],
        score=message.opp_score,
        deadline=deadline,
        days_left=days_left,
        fields=meta["fields"],
        is_free=meta["is_free"],
        reasons=meta["reasons"],
        link=_safe_http_link(link),
        channel_name=message.sender_name or "",
        received_at=message.received_at,
        is_read=message.is_read,
        is_archived=message.is_archived,
    )


@router.get("/feed", response_model=list[OppFeedItem])
async def get_feed(
    archived: bool = False,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> list[OppFeedItem]:
    """channel='opportunity' xabarlari, ball/muddat/teglar/havola bilan. O'qish/arxiv —
    mavjud PATCH /api/messages/{id}/read|archive|unarchive."""
    result = await db.execute(
        select(Message)
        .where(Message.channel == "opportunity", Message.is_archived == archived)
        .order_by(Message.received_at.desc(), Message.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return [_feed_item(item) for item in result.scalars().all()]
