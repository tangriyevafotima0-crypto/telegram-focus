"""test_dashboard_formatter.py — Stage 4: strukturalangan JSON parsing va
formatlash sinovlari. Haqiqiy Gemini API kerak emas — `call_gemini_raw`
monkeypatch qilinadi.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.opportunity import dashboard_formatter as df


VALID = {
    "xulosa": "Bu bepul, muddati yaqin imkoniyat.",
    "holat": "Bepul",
    "tavsiya": "Xabardor qilish",
    "tahlil": ["Muddat: 2026-10-01", "To'lov yo'q"],
}


# ═══════════════════════════════════════════════════════
# extract_dashboard_json — 3+ ta holat
# ═══════════════════════════════════════════════════════

def test_extract_clean_json():
    raw = json.dumps(VALID, ensure_ascii=False)
    result = df.extract_dashboard_json(raw)
    assert result is not None
    assert result["holat"] == "Bepul"
    assert result["tavsiya"] == "Xabardor qilish"
    assert result["tahlil"] == VALID["tahlil"]


def test_extract_markdown_fenced_json():
    raw = "```json\n" + json.dumps(VALID, ensure_ascii=False) + "\n```"
    result = df.extract_dashboard_json(raw)
    assert result is not None
    assert result["xulosa"] == VALID["xulosa"]


def test_extract_json_with_surrounding_text():
    raw = "Mana natija:\n" + json.dumps(VALID, ensure_ascii=False) + "\nRahmat!"
    result = df.extract_dashboard_json(raw)
    assert result is not None
    assert result["holat"] == "Bepul"


def test_extract_plain_fence_no_json_label():
    raw = "```\n" + json.dumps(VALID, ensure_ascii=False) + "\n```"
    result = df.extract_dashboard_json(raw)
    assert result is not None


def test_extract_empty_returns_none():
    assert df.extract_dashboard_json("") is None
    assert df.extract_dashboard_json("   ") is None


def test_extract_garbage_returns_none():
    assert df.extract_dashboard_json("bu JSON emas, oddiy matn.") is None


def test_extract_invalid_holat_rejected():
    bad = dict(VALID)
    bad["holat"] = "Yangi kategoriya"  # ruxsat etilmagan qiymat
    raw = json.dumps(bad, ensure_ascii=False)
    assert df.extract_dashboard_json(raw) is None


def test_extract_invalid_tavsiya_rejected():
    bad = dict(VALID)
    bad["tavsiya"] = "Kutish"  # ruxsat etilmagan qiymat
    raw = json.dumps(bad, ensure_ascii=False)
    assert df.extract_dashboard_json(raw) is None


def test_extract_missing_xulosa_rejected():
    bad = dict(VALID)
    bad["xulosa"] = ""
    raw = json.dumps(bad, ensure_ascii=False)
    assert df.extract_dashboard_json(raw) is None


def test_extract_tahlil_as_string_normalized_to_list():
    bad = dict(VALID)
    bad["tahlil"] = "yakka bullet matn"
    raw = json.dumps(bad, ensure_ascii=False)
    result = df.extract_dashboard_json(raw)
    assert result is not None
    assert result["tahlil"] == ["yakka bullet matn"]


# ═══════════════════════════════════════════════════════
# generate_dashboard_format — Gemini muvaffaqiyat/muvaffaqiyatsizlik
# ═══════════════════════════════════════════════════════

def test_generate_dashboard_format_gemini_success(monkeypatch):
    monkeypatch.setattr(
        df.gemini_analyzer, "call_gemini_raw", lambda *a, **k: json.dumps(VALID, ensure_ascii=False)
    )
    result = df.generate_dashboard_format("Wharton musobaqasi to'liq bepul.")
    assert result["holat"] == "Bepul"
    assert result["tavsiya"] == "Xabardor qilish"


def test_generate_dashboard_format_gemini_broken_json_falls_back(monkeypatch):
    monkeypatch.setattr(df.gemini_analyzer, "call_gemini_raw", lambda *a, **k: "buzilgan javob {{{")
    result = df.generate_dashboard_format("Bu dastur $500 to'lov talab qiladi, muddati bugun.")
    assert result["holat"] in df.ALLOWED_HOLAT
    assert result["tavsiya"] in df.ALLOWED_TAVSIYA
    assert result["holat"] == "Pullik"
    assert result["tavsiya"] == "Darhol javob berish"


def test_generate_dashboard_format_gemini_unavailable_falls_back(monkeypatch):
    monkeypatch.setattr(df.gemini_analyzer, "call_gemini_raw", lambda *a, **k: "")
    result = df.generate_dashboard_format("Bu to'liq bepul stipendiya, xarajatsiz.")
    assert result["holat"] == "Bepul"


def test_generate_dashboard_format_empty_content_never_raises():
    result = df.generate_dashboard_format("")
    assert set(result.keys()) == {"xulosa", "holat", "tavsiya", "tahlil"}
    assert result["holat"] in df.ALLOWED_HOLAT
    assert result["tavsiya"] in df.ALLOWED_TAVSIYA


def test_generate_dashboard_format_gemini_exception_falls_back(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("tarmoq xatosi")

    monkeypatch.setattr(df.gemini_analyzer, "call_gemini_raw", _raise)
    result = df.generate_dashboard_format("Har qanday matn.")
    assert result["holat"] in df.ALLOWED_HOLAT


# ═══════════════════════════════════════════════════════
# format_media_analysis
# ═══════════════════════════════════════════════════════

def test_format_media_analysis_document():
    result = {
        "ok": True,
        "text": "hujjat matni",
        "analysis": {
            "deadline": "2026-10-15",
            "amount": "Bepul",
            "requirements": ["IELTS 7.0", "Transkript"],
            "summary": "Bu to'liq grant dasturi.",
        },
    }
    dashboard = df.format_media_analysis("document", result)
    assert dashboard is not None
    assert dashboard["holat"] == "Bepul"
    assert any("Muddat" in item for item in dashboard["tahlil"])
    assert any("IELTS" in item for item in dashboard["tahlil"])


def test_format_media_analysis_not_ok_returns_none():
    assert df.format_media_analysis("photo", {"ok": False, "text": ""}) is None
    assert df.format_media_analysis("photo", None) is None


def test_format_media_analysis_empty_ocr_returns_none():
    result = {"ok": True, "text": "[Matn topilmadi]"}
    assert df.format_media_analysis("photo", result) is None


def test_format_media_analysis_photo_uses_gemini(monkeypatch):
    monkeypatch.setattr(
        df.gemini_analyzer, "call_gemini_raw", lambda *a, **k: json.dumps(VALID, ensure_ascii=False)
    )
    result = {"ok": True, "text": "Bu skrinshotdagi taklif matni."}
    dashboard = df.format_media_analysis("photo", result)
    assert dashboard is not None
    assert dashboard["holat"] == "Bepul"


# ═══════════════════════════════════════════════════════
# format_triage_emergency
# ═══════════════════════════════════════════════════════

def test_format_triage_emergency_forces_muhim_and_urgent(monkeypatch):
    # Gemini "Bepul"/"Xabardor qilish" qaytarsa ham, emergency majburlanadi.
    monkeypatch.setattr(
        df.gemini_analyzer, "call_gemini_raw", lambda *a, **k: json.dumps(VALID, ensure_ascii=False)
    )
    dashboard = df.format_triage_emergency("Tabriklaymiz! Siz Wharton dasturiga qabul qilindingiz.", "kalit so'z")
    assert dashboard["holat"] == "Muhim"
    assert dashboard["tavsiya"] == "Darhol javob berish"


def test_format_triage_emergency_never_raises(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("xato")

    monkeypatch.setattr(df.gemini_analyzer, "call_gemini_raw", _raise)
    dashboard = df.format_triage_emergency("Shoshilinch xabar", "sabab")
    assert dashboard["holat"] == "Muhim"
    assert dashboard["tavsiya"] == "Darhol javob berish"
