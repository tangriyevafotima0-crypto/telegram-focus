"""dashboard_formatter.py — Stage 4: barcha briefing/triage/media-tahlil
natijalarini bitta qat'iy formatga ({Xulosa, Holat, Tavsiya etilgan harakat,
Tahlil}) jamlaydi.

Naqsh gemini_analyzer.py / media_analyzer.py'dan olindi: hech qachon
exception otmaydi, Gemini javob bermasa yoki JSON buzilgan bo'lsa mahalliy
(lokal) zaxira natija bilan davom etadi.

JSON kalitlar (Gemini bilan ichki muloqot uchun, ingliz kalit so'zlar):
    xulosa: str
    holat: "Bepul" | "Pullik" | "Shubhali" | "Muhim"
    tavsiya: "E'tiborsiz qoldirish" | "Xabardor qilish" | "Darhol javob berish"
    tahlil: list[str]
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from . import gemini_analyzer

logger = logging.getLogger(__name__)

ALLOWED_HOLAT = {"Bepul", "Pullik", "Shubhali", "Muhim"}
ALLOWED_TAVSIYA = {"E'tiborsiz qoldirish", "Xabardor qilish", "Darhol javob berish"}

_SYSTEM_PROMPT = """Sen ma'lumotni qat'iy dashboard formatiga solib beruvchi tahlilchisan.
FAQAT toza JSON qaytar — hech qanday izoh, markdown kod-fence yoki boshqa matn qo'shma:
{"xulosa": "1 aniq va ta'sirli jumla", "holat": "Bepul", "tavsiya": "Xabardor qilish", "tahlil": ["muddat/to'lov/talab haqida bullet 1", "bullet 2"]}

QAT'IY QOIDALAR:
- "holat" maydoni FAQAT shu 4 ta qiymatdan biri bo'lishi shart: Bepul, Pullik, Shubhali, Muhim. Boshqa so'z ixtiro qilma.
- "tavsiya" maydoni FAQAT shu 3 ta qiymatdan biri bo'lishi shart: E'tiborsiz qoldirish, Xabardor qilish, Darhol javob berish. Boshqa so'z ixtiro qilma.
- "tahlil" — muddatlar, to'lovlar, talablarni ko'rsatuvchi qisqa bullet point'lar ro'yxati (kamida 1 ta).
- Javobing FAQAT JSON bo'lsin, boshqa hech narsa yozma.
"""


def _validate(data: Any) -> Optional[Dict[str, Any]]:
    """Gemini'dan qaytgan (yoki qo'lda qurilgan) dict'ni tekshiradi.

    Talablarga mos kelmasa (majburiy maydon yo'q, yoki holat/tavsiya ruxsat
    etilgan ro'yxatdan tashqarida) — None qaytaradi (chaqiruvchi fallback
    ishlatadi). Hech qachon exception otmaydi.
    """
    try:
        if not isinstance(data, dict):
            return None
        xulosa = str(data.get("xulosa") or "").strip()
        holat = str(data.get("holat") or "").strip()
        tavsiya = str(data.get("tavsiya") or "").strip()
        tahlil_raw = data.get("tahlil")

        if not xulosa or holat not in ALLOWED_HOLAT or tavsiya not in ALLOWED_TAVSIYA:
            return None

        if isinstance(tahlil_raw, list):
            tahlil = [str(item).strip() for item in tahlil_raw if str(item).strip()]
        elif tahlil_raw:
            tahlil = [str(tahlil_raw).strip()]
        else:
            tahlil = []

        if not tahlil:
            tahlil = ["Qo'shimcha tafsilot ko'rsatilmagan."]

        return {
            "xulosa": xulosa[:400],
            "holat": holat,
            "tavsiya": tavsiya,
            "tahlil": tahlil[:8],
        }
    except Exception:
        logger.exception("Dashboard format validatsiyasida kutilmagan xato")
        return None


def extract_dashboard_json(raw: str) -> Optional[Dict[str, Any]]:
    """Gemini javobidan strukturalangan JSON'ni ajratib oladi va tekshiradi.

    Uch holatni qamrab oladi: toza JSON, markdown kod-fence bilan o'ralgan
    JSON, JSON atrofida qo'shimcha matn bor holat. Hech qachon exception
    otmaydi — xato bo'lsa loglanadi va None qaytariladi.
    """
    if not raw or not raw.strip():
        return None

    candidate = raw.strip()
    # Markdown kod-fence'ni olib tashlash (```json ... ``` yoki ``` ... ```)
    candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"\s*```$", "", candidate).strip()

    try:
        data = json.loads(candidate)
        validated = _validate(data)
        if validated is not None:
            return validated
    except json.JSONDecodeError:
        pass
    except Exception:
        logger.exception("Dashboard JSON parse qilishda kutilmagan xato")

    # JSON atrofida begona matn bo'lsa — birinchi '{' dan oxirgi '}' gacha ajratib olamiz.
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = candidate[start : end + 1]
        try:
            data = json.loads(snippet)
            validated = _validate(data)
            if validated is not None:
                return validated
        except json.JSONDecodeError as exc:
            logger.warning("Dashboard JSON parse xatosi (JSONDecodeError): %s | raw=%r", exc, raw[:300])
            return None
        except Exception:
            logger.exception("Dashboard JSON snippet parse qilishda kutilmagan xato")
            return None

    logger.warning("Dashboard formatida javob topilmadi/JSON emas: raw=%r", raw[:300])
    return None


def _local_fallback(content: str) -> Dict[str, Any]:
    """Gemini javob bermasa yoki JSON buzilgan bo'lsa ishlatiladigan mahalliy
    (heuristika asosidagi) zaxira natija. Hech qachon bo'sh/None qaytarmaydi."""
    text = content or ""

    is_paid = bool(re.search(r"(\$|fee|payment|tuition|pullik|to'lov|tolov)", text, re.I))
    is_free = bool(re.search(r"(fully funded|free|bepul|stipendiya|scholarship|grant)", text, re.I))
    if is_free and not is_paid:
        holat = "Bepul"
    elif is_paid:
        holat = "Pullik"
    elif text.strip():
        holat = "Muhim"
    else:
        holat = "Shubhali"

    urgent = bool(re.search(r"(bugun|shoshilinch|urgent|deadline|muddat)", text, re.I))
    if urgent:
        tavsiya = "Darhol javob berish"
    elif text.strip():
        tavsiya = "Xabardor qilish"
    else:
        tavsiya = "E'tiborsiz qoldirish"

    sentences: List[str] = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    tahlil = sentences[:3] if sentences else ["Qo'shimcha ma'lumot topilmadi."]
    xulosa = (sentences[0][:200] if sentences else "Tahlil qilish uchun yetarli ma'lumot topilmadi.")

    return {"xulosa": xulosa, "holat": holat, "tavsiya": tavsiya, "tahlil": tahlil}


def generate_dashboard_format(content: str, *, context: str = "") -> Dict[str, Any]:
    """Berilgan matnni Gemini orqali strukturalangan dashboard formatiga
    o'giradi. Hech qachon exception otmaydi va hech qachon None/bo'sh
    qaytarmaydi — Gemini javob bermasa yoki JSON buzilgan bo'lsa, mahalliy
    zaxira (`_local_fallback`) ishlatiladi.
    """
    content = (content or "").strip()
    if not content:
        return _local_fallback("")

    prompt_prefix = f"KONTEKST: {context}\n" if context else ""
    prompt = f"{prompt_prefix}MATN:\n{content[:6000]}"

    raw = ""
    try:
        raw = gemini_analyzer.call_gemini_raw(
            [{"parts": [{"text": prompt}]}], _SYSTEM_PROMPT, max_tokens=600
        )
    except Exception:
        logger.exception("Dashboard formatlash uchun Gemini chaqiruvida xato")
        raw = ""

    parsed = extract_dashboard_json(raw) if raw else None
    if parsed is not None:
        return parsed
    return _local_fallback(content)


_MEDIA_KIND_LABELS = {
    "photo": "Rasmdan (skrinshot) o'qilgan matn",
    "voice": "Ovozli xabar transkripsiyasi",
    "audio": "Audio fayl transkripsiyasi",
}


def format_media_analysis(media_type: Optional[str], result: Optional[dict]) -> Optional[Dict[str, Any]]:
    """Stage 1 media tahlil natijasini (rasm/audio/PDF) dashboard formatiga
    o'giradi. Tahlil muvaffaqiyatsiz yoki mazmunsiz bo'lsa None qaytaradi
    (chaqiruvchi bunda umuman dashboard ko'rsatmasligi kerak). Hech qachon
    exception otmaydi.
    """
    try:
        if not result or not result.get("ok"):
            return None

        if media_type == "document":
            analysis = result.get("analysis") or {}
            deadline = str(analysis.get("deadline") or "Ko'rsatilmagan")
            amount = str(analysis.get("amount") or "Ko'rsatilmagan")
            requirements = analysis.get("requirements") or []
            summary = str(analysis.get("summary") or (result.get("text") or "")[:200] or "Hujjat tahlil qilindi.")

            tahlil = [f"Muddat: {deadline}", f"To'lov/Summasi: {amount}"]
            tahlil += [str(r) for r in requirements if str(r).strip()][:6]

            is_paid = bool(re.search(r"(\$|fee|to'lov|tolov|pullik)", amount, re.I))
            is_free = bool(re.search(r"(bepul|free|grant|stipendiya)", amount, re.I))
            if is_free and not is_paid:
                holat = "Bepul"
            elif is_paid:
                holat = "Pullik"
            else:
                holat = "Muhim"

            urgent = bool(re.search(r"(bugun|shoshilinch|urgent)", deadline, re.I))
            tavsiya = "Darhol javob berish" if urgent else "Xabardor qilish"

            return {
                "xulosa": summary[:300],
                "holat": holat,
                "tavsiya": tavsiya,
                "tahlil": tahlil or ["Tafsilot topilmadi."],
            }

        text = (result.get("text") or "").strip()
        if not text or text in ("[Matn topilmadi]",):
            return None

        context = _MEDIA_KIND_LABELS.get(media_type or "", "Media tahlili")
        return generate_dashboard_format(text, context=context)
    except Exception:
        logger.exception("format_media_analysis xatosi (media_type=%s)", media_type)
        return None


def format_triage_emergency(text: str, reason: Optional[str] = None) -> Dict[str, Any]:
    """Daraja 3 (EMERGENCY ESCALATION) xabarini dashboard formatiga o'giradi.

    Emergency ta'rifiga ko'ra holat/tavsiya har doim "Muhim" / "Darhol javob
    berish" bilan majburlanadi (Gemini boshqacha qaytarsa ham) — bu daraja
    tabiatan shoshilinch. Hech qachon exception otmaydi.
    """
    try:
        context = "Shoshilinch (EMERGENCY) xabar" + (f" — sabab: {reason}" if reason else "")
        result = generate_dashboard_format(text, context=context)
        result["holat"] = "Muhim"
        result["tavsiya"] = "Darhol javob berish"
        return result
    except Exception:
        logger.exception("format_triage_emergency xatosi")
        return {
            "xulosa": "Shoshilinch xabar aniqlandi, darhol ko'rib chiqing.",
            "holat": "Muhim",
            "tavsiya": "Darhol javob berish",
            "tahlil": [reason] if reason else ["Tafsilot topilmadi."],
        }
