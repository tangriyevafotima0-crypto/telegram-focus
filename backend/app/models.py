from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, Float, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class SourceType(str, enum.Enum):
    USER = "user"
    GROUP = "group"
    CHANNEL = "channel"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    identifier: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[SourceType] = mapped_column(
        Enum(SourceType, native_enum=False),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    # Stage 4/5: 'telegram' | 'email' | 'opportunity'. New table not needed.
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="telegram")

    messages: Mapped[list["Message"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_source_received", "source_id", "received_at"),
        Index("ix_messages_received", "received_at"),
        Index("ix_messages_archived_received", "is_archived", "received_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_name: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    media_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    media_path: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        index=True,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Stage 1 additions (see docs/DEVELOPMENT_GUIDE.md, STATUS.md) ---
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_to_message_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chat_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False, default="in")
    has_media_file: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    media_mime: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    media_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    link_urls: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Stage 4/5: 'telegram' | 'email' | 'opportunity'. New table not needed.
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="telegram")
    opp_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Stage 6: imkoniyat bali
    # Stage 1 (media tahlil): OCR/PDF tahlilidan chiqqan struktura (deadline,
    # summa, talablar va h.k.) JSON matn sifatida. OCR/transkripsiya matnining
    # o'zi mavjud `text` ustuniga yoziladi (yangi ustun ochilmadi).
    media_analysis_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Stage 2 (triage): 4-darajali klassifikatsiya (0=silent drop, 1=info,
    # 2=notification, 3=emergency) va sababi. NULL = hali klassifikatsiya
    # qilinmagan (eski xabarlar / Stage 2'dan oldingi yozuvlar).
    triage_level: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    triage_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    triage_auto_reply: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Stage 4: Daraja 3 (EMERGENCY) xabarlar uchun tayyor dashboard JSON
    # ({xulosa, holat, tavsiya, tahlil}) — UI'da qayta so'rov qilmasdan ko'rsatish uchun.
    triage_dashboard_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    source: Mapped[Source] = relationship(back_populates="messages")


class OppProfile(Base):
    """Imkoniyat-motor foydalanuvchi profili (yagona qator, id=1)."""

    __tablename__ = "opp_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    age: Mapped[int] = mapped_column(Integer, nullable=False, default=16)
    grade: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=11)
    ielts: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=6.0)
    knows_english: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_student: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_pupil: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interests: Mapped[str] = mapped_column(Text, nullable=False, default="[]")  # JSON matn
    only_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OppSettings(Base):
    """Imkoniyat-motor sozlamalari (yagona qator, id=1)."""

    __tablename__ = "opp_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_score: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    check_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=600)


class OppChannel(Base):
    """Kuzatilayotgan kanal (imkoniyat-motor)."""

    __tablename__ = "opp_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    last_seen: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class OppSent(Base):
    """Yuborilgan imkoniyatlar hash'i (takror oldini olish)."""

    __tablename__ = "opp_sent"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hash: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class OppStats(Base):
    """Imkoniyat-motor statistikasi (yagona qator, id=1)."""

    __tablename__ = "opp_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    total_checks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_check: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class OppGroup(Base):
    """Imkoniyatlar yuboriladigan Telegram guruhi (pending -> confirmed)."""

    __tablename__ = "opp_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EmailAccount(Base):
    """IMAP hisobi. Parol faqat shifrlangan ko'rinishda (email_crypto.py)."""

    __tablename__ = "email_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_host: Mapped[str] = mapped_column(String(255), nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, nullable=False, default=993)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    folder: Mapped[str] = mapped_column(String(255), nullable=False, default="INBOX")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_uid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    uid_validity: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )


class SubmittedOpportunity(Base):
    __tablename__ = "submitted_opportunities"

    id = Column(Integer, primary_key=True, index=True)
    opportunity_id = Column(Integer, ForeignKey("opportunities.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="submitted")
    submitted_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    related_email_thread_id = Column(String(255), nullable=True, index=True)
    next_deadline = Column(DateTime, nullable=True)
    next_deadline_note = Column(Text, nullable=True)

    opportunity = relationship("Opportunity", back_populates="submissions")

    __table_args__ = (
        Index("ix_submitted_opp_status", "status"),
        Index("ix_submitted_opp_next_deadline", "next_deadline"),
    )

class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    organization = Column(String(255), nullable=True)
    url = Column(String(500), nullable=True)
    match_score = Column(Float, default=0.0, index=True)
    is_paid = Column(Boolean, default=False)
    deadline = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    submissions = relationship("SubmittedOpportunity", back_populates="opportunity", cascade="all, delete-orphan")
