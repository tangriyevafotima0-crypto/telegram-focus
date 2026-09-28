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
