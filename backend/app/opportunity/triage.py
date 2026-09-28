"""triage.py — Kiruvchi xabarlar uchun 4-darajali triage matritsasi.

Daraja 0 (SILENT DROP)      — spam, mazmunsiz salomlashish, memlar.
Daraja 1 (INFORMATIONAL)    — umumiy suhbat, javob talab qilmaydi.
Daraja 2 (NOTIFICATION)     — shoshilinch bo'lmagan inson so'rovi/ma'muriyat.
Daraja 3 (EMERGENCY)        — rasmiy qabul/stipendiya, muhim shaxsiy masala.

Avval arzon heuristika bilan aniq holatlar ajratiladi (token tejash uchun —
Daraja 0 uchun Gemini UMUMAN chaqirilmaydi). Faqat noaniq holatlarda
`gemini_analyzer.call_gemini_raw` ga murojaat qilinadi.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

from . import gemini_analyzer

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# NATIJA STRUKTURASI
# ═══════════════════════════════════════════════════════

@dataclass
class TriageResult:
    level: int  # 0-3
    reason: str
    auto_reply_text: Optional[str] = None  # faqat daraja 2 uchun


# ═══════════════════════════════════════════════════════
# HEURISTIKA — DARAJA 0 (SILENT DROP)
# ═══════════════════════════════════════════════════════

_GREETING_ONLY = {
    "salom", "salomlar", "assalomu alaykum", "assalomu alaykum!",
    "qalesiz", "qalaysiz", "qanaqasiz", "yaxshimisiz", "hormat",
    "hi", "hello", "hey", "salomm", "assalom",
    "rahmat", "raxmat", "ok", "okay", "xop", "yaxshi", "tushunarli",
    "👍", "👌", "😂", "❤️", "🔥", "😊", "🙏",
}

_SPAM_PATTERNS = [
    r"^(bepul|tekin)\s+(pul|dollar|billet)",
    r"click here", r"bosing? bu(?:yerga|erga)",
    r"@everyone", r"forward(?:ed)? message",
    r"^\s*[.!?]{2,}\s*$",
]

# Ko'p uchraydigan zanjir xabar / chain-letter belgilari
_CHAIN_MARKERS = [
    "har bir do'stingizga yuboring", "10 kishiga yuboring",
    "forward qiling", "ushbu xabarni ulashing",
]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_silent_drop_heuristic(text: str) -> Optional[str]:
    """Aniq spam/salomlashish bo'lsa sababni qaytaradi, aks holda None."""
    norm = _normalize(text)
    if not norm:
        return "Bo'sh xabar"

    # Faqat bir-ikki so'zli salomlashish/emoji
    stripped = norm.strip(" !.,?😀😊🙏❤️🔥👍👌😂")
    if stripped in _GREETING_ONLY or norm in _GREETING_ONLY:
        return "Mazmunsiz salomlashish"

    word_count = len(norm.split())
    if word_count <= 2 and stripped in _GREETING_ONLY:
        return "Mazmunsiz salomlashish"

    for pattern in _SPAM_PATTERNS:
        if re.search(pattern, norm):
            return "Spam belgilari topildi"

    for marker in _CHAIN_MARKERS:
        if marker in norm:
            return "Zanjir xabar (chain message)"

    return None


# ═══════════════════════════════════════════════════════
# HEURISTIKA — DARAJA 3 (EMERGENCY) tezkor signal
# ═══════════════════════════════════════════════════════

_EMERGENCY_KEYWORDS = [
    "wharton", "qabul qilindingiz", "congratulations", "tabriklaymiz",
    "admission", "acceptance", "stipendiya tasdiqlandi", "scholarship award",
    "deadline bugun", "muddati bugun", "urgent", "shoshilinch",
    "favqulodda", "kasalxona", "avariya", "yo'qoldi",
]

_ADMIN_SCHOOL_KEYWORDS = [
    "direktor", "maktab ma'muriyati", "ota-ona majlisi", "kitobni qaytarib",
    "hujjat topshirish", "attestatsiya",
]


def _quick_signal(text: str) -> Optional[int]:
    """Aniq kalit so'zlar orqali darajani tezkor aniqlaydi (Gemini'siz)."""
    norm = _normalize(text)
    if any(kw in norm for kw in _EMERGENCY_KEYWORDS):
        return 3
    return None


# ═══════════════════════════════════════════════════════
# GEMINI ORQALI NOANIQ HOLATLARNI KLASSIFIKATSIYA QILISH
# ═══════════════════════════════════════════════════════

_TRIAGE_SYSTEM_PROMPT = f"""Sen xabarlarni 4 darajaga ajratuvchi qat'iy triage tizimisan.
FOYDALANUVCHI XOTIRASI:
{json.dumps(gemini_analyzer.USER_PROFILE, ensure_ascii=False, indent=2)}

DARAJALAR:
0 = SILENT DROP — spam, mazmunsiz salomlashish, memlar, zanjir xabarlar.
1 = INFORMATIONAL LOG — umumiy guruh suhbati, javob talab qilmaydigan status/receipt.
2 = NOTIFICATION REQUIRED — shoshilinch bo'lmagan inson so'rovi (masalan kitobni
    qaytarib berish, uchrashuv so'rash), maktab ma'muriyati xabari.
3 = EMERGENCY ESCALATION — rasmiy qabul/stipendiya emaili, Wharton jamoasi
    muddatlari, muhim oilaviy/shaxsiy masala.

Faqat toza JSON qaytar, boshqa hech narsa yozma:
{{"level": 0-3 raqam, "reason": "qisqa sabab (bir jumla)", "auto_reply": "agar level=2 bo'lsa muloyim executive javob matni, aks holda bo'sh satr"}}
"""


def _gemini_classify(text: str) -> Optional[TriageResult]:
    prompt = f"XABAR MATNI:\n{text}"
    raw = gemini_analyzer.call_gemini_raw(
        [{"parts": [{"text": prompt}]}], _TRIAGE_SYSTEM_PROMPT, max_tokens=400
    )
    if not raw:
        return None
    try:
        clean = re.sub(r"^```json\s*", "", raw, flags=re.MULTILINE)
        clean = re.sub(r"\s*```$", "", clean, flags=re.MULTILINE).strip()
        data = json.loads(clean)
        level = int(data.get("level", 1))
        level = max(0, min(3, level))
        reason = str(data.get("reason") or "Gemini klassifikatsiyasi")
        auto_reply = data.get("auto_reply") or None
        return TriageResult(level=level, reason=reason, auto_reply_text=auto_reply if level == 2 else None)
    except Exception:
        logger.warning("Triage Gemini javobini JSON qilib o'qib bo'lmadi: %r", raw[:200])
        return None


# ═══════════════════════════════════════════════════════
# DARAJA 2 UCHUN ZAXIRA AUTO-REPLY (Gemini javob bermasa)
# ═══════════════════════════════════════════════════════

_FALLBACK_AUTO_REPLY = (
    "Assalomu alaykum! Xabaringiz qabul qilindi, tez orada javob beraman."
)


# ═══════════════════════════════════════════════════════
# ASOSIY FUNKSIYA
# ═══════════════════════════════════════════════════════

async def classify_message(message, *args, **kwargs) -> TriageResult:
    """Xabarni 4 darajaga ajratadi.

    `message` — `Message` ORM obyekti (yoki shunga o'xshash `.text` atributiga
    ega har qanday obyekt/dublikat — testlarda oddiy namespace ham ishlaydi).
    Hech qachon exception otmaydi: xato bo'lsa Daraja 1 (xavfsiz default)
    qaytaradi va log yozadi.
    """
    # Matnni str, dict yoki Telegram/Telethon Message (text/caption)dan xavfsiz olish
    if isinstance(message, str):
        text = message
    elif isinstance(message, dict):
        text = message.get("text") or message.get("caption") or ""
    else:
        text = getattr(message, "text", None) or getattr(message, "caption", "") or ""
    text = (text or "").strip()

    try:
        # 1) Tez, arzon heuristika — Daraja 0 (Gemini chaqirilmaydi)
        drop_reason = _is_silent_drop_heuristic(text)
        if drop_reason:
            logger.info("[Triage] Daraja 0 (heuristika): %s", drop_reason)
            return TriageResult(level=0, reason=drop_reason)

        # 2) Tezkor signal — Daraja 3 aniq kalit so'zlar bilan
        quick_level = _quick_signal(text)
        if quick_level == 3:
            reason = "Shoshilinch kalit so'z topildi (qabul/stipendiya/favqulodda)"
            logger.info("[Triage] Daraja 3 (tezkor signal): %s", reason)
            return TriageResult(level=3, reason=reason)

        # 3) Noaniq holat — Gemini'ga murojaat
        logger.info(
            "[Gemini chaqiruv log] modul=triage, matn_uzunligi=%d, model_zanjiri=%s",
            len(text), gemini_analyzer.MODEL_CHAIN,
        )
        result = _gemini_classify(text)
        if result is not None:
            logger.info("[Triage] Daraja %d (Gemini): %s", result.level, result.reason)
            if result.level == 2 and not result.auto_reply_text:
                result.auto_reply_text = _FALLBACK_AUTO_REPLY
            return result

        # 4) Gemini javob bermadi (API kalit yo'q/xato) — mahalliy zaxira heuristika
        norm = _normalize(text)
        if any(kw in norm for kw in _ADMIN_SCHOOL_KEYWORDS) or "iltimos" in norm or "so'rayman" in norm:
            return TriageResult(
                level=2,
                reason="Zaxira heuristika: inson so'rovi/ma'muriyat xabari",
                auto_reply_text=_FALLBACK_AUTO_REPLY,
            )
        return TriageResult(level=1, reason="Zaxira heuristika: umumiy suhbat (Gemini mavjud emas)")

    except Exception:
        logger.exception("Triage klassifikatsiyasida xato — xavfsiz Daraja 1 qaytarildi")
        return TriageResult(level=1, reason="Klassifikatsiya xatosi — xavfsiz standart")
