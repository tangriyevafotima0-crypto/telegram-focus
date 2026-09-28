"""Archive settings: backend/data/settings.json (Stage 3, Checkpoint 1).

Small JSON file, no new table needed. Writes are atomic (tmp file + os.replace).
"""
import json
import os
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
SETTINGS_PATH = BACKEND_DIR / "data" / "settings.json"

DEFAULT_ARCHIVE_SETTINGS: dict[str, Any] = {
    "archive_on_read": True,
    "archive_on_reply": True,
    "auto_archive_days": 0,
}

# Stage 3: Executive Auto-Responder. Default OFF (xavfsizlik uchun) — Zafar
# frontend orqali o'zi yoqadi.
DEFAULT_AUTO_RESPONDER_SETTINGS: dict[str, Any] = {
    "auto_reply_enabled": False,
}


def read_archive_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_ARCHIVE_SETTINGS)
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return dict(DEFAULT_ARCHIVE_SETTINGS)
    merged = dict(DEFAULT_ARCHIVE_SETTINGS)
    if isinstance(data, dict):
        merged.update({k: v for k, v in data.items() if k in DEFAULT_ARCHIVE_SETTINGS})
    return merged


def write_archive_settings(settings: dict[str, Any]) -> dict[str, Any]:
    merged = read_archive_settings()
    merged.update({k: v for k, v in settings.items() if k in DEFAULT_ARCHIVE_SETTINGS})

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = SETTINGS_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SETTINGS_PATH)
    return merged


def _read_raw() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_auto_responder_settings() -> dict[str, Any]:
    data = _read_raw()
    merged = dict(DEFAULT_AUTO_RESPONDER_SETTINGS)
    merged.update(
        {k: v for k, v in data.items() if k in DEFAULT_AUTO_RESPONDER_SETTINGS}
    )
    return merged


def write_auto_responder_settings(settings: dict[str, Any]) -> dict[str, Any]:
    """Archive settings kaliti bilan bir faylni ulashadi — boshqa kalitlarga tegmaydi."""
    data = _read_raw()
    data.update(
        {k: v for k, v in settings.items() if k in DEFAULT_AUTO_RESPONDER_SETTINGS}
    )

    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = SETTINGS_PATH.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp_path, SETTINGS_PATH)
    return read_auto_responder_settings()
