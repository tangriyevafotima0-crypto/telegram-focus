from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import SourceType


class SourceCreate(BaseModel):
    identifier: str = Field(min_length=1, max_length=255)
    display_name: Optional[str] = Field(default=None, max_length=255)
    type: SourceType

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Identifier bo‘sh bo‘lishi mumkin emas.")
        return value

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        value = value.strip()
        return value or None


class SourceUpdate(BaseModel):
    is_active: Optional[bool] = None
    display_name: Optional[str] = Field(default=None, max_length=255)


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    identifier: str
    display_name: str
    type: SourceType
    is_active: bool
    created_at: datetime


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    source_display_name: str
    sender_name: str
    text: str
    media_type: Optional[str]
    media_path: Optional[str]
    telegram_message_id: int
    received_at: datetime
    is_read: bool
    # --- Stage 1 additions: all optional/defaulted so old frontend keeps working ---
    is_archived: bool = False
    archived_at: Optional[datetime] = None
    reply_to_message_id: Optional[int] = None
    chat_id: Optional[int] = None
    direction: str = "in"
    has_media_file: bool = False
    media_mime: Optional[str] = None
    media_name: Optional[str] = None
    link_urls: Optional[list[str]] = None
    channel: str = "telegram"

    @field_validator("link_urls", mode="before")
    @classmethod
    def _parse_link_urls(cls, value):
        if value is None or isinstance(value, list):
            return value
        import json

        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return None


class MessageCountsOut(BaseModel):
    telegram_unread: int
    email_unread: int
    archived: int
    opportunity_unread: int