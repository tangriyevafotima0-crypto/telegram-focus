import os
import sys
import json
import base64
import logging
import asyncio
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Muhit o'zgaruvchilarini yuklash
for p in [Path(".env"), Path("../.env"), Path("/home/ubuntu/telegram-focus/backend/.env"), Path("/home/ubuntu/telegram-focus/.env"), Path("/home/ubuntu/server_vault/.env")]:
    if p.exists():
        load_dotenv(p)

# Eng barqaror va tezkor Gemini modellari zanjiri
MODEL_CHAIN = [
    "gemma-4-26b-a4b-it",
    "gemini-flash-lite-latest",
    "gemini-3-flash-preview"
]

def _guess_mime(path: Path, table: dict[str, str], default: str) -> str:
    ext = path.suffix.lower()
    return table.get(ext, default)

def _read_and_encode(path: Path) -> Optional[str]:
    try:
        data = path.read_bytes()
        return base64.b64encode(data).decode("utf-8")
    except Exception as e:
        logger.error(f"Faylni o'qishda xatolik: {e}")
        return None

def _extract_pdf_text(path: Path, max_chars: int = 15000) -> str:
    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        text = "\n".join([page.extract_text() or "" for page in reader.pages])
        return text[:max_chars].strip()
    except Exception:
        try:
            import PyPDF2
            reader = PyPDF2.PdfReader(str(path))
            text = "\n".join([page.extract_text() or "" for page in reader.pages])
            return text[:max_chars].strip()
        except Exception:
            return ""

def _extract_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    raw = raw.strip()
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in raw:
        raw = raw.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except Exception:
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        return None

def _call_gemini_multimodal(
    inline_mime: str,
    inline_b64: str,
    prompt: str,
    system_instruction: str,
    max_tokens: int = 2000,
) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY topilmadi.")
        return None

    payload = {
        "contents": [
            {
                "parts": [
                    {"inlineData": {"mimeType": inline_mime, "data": inline_b64}},
                    {"text": prompt}
                ]
            }
        ],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens}
    }
    body = json.dumps(payload).encode("utf-8")

    for model in MODEL_CHAIN:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        # Standard API Key auth
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
        except urllib.error.HTTPError as e:
            logger.warning(f"Gemini {model} HTTP xatosi: {e.code}")
            continue
        except Exception as e:
            logger.warning(f"Gemini {model} ulanish xatosi: {e}")
            continue
    return None

def _call_gemini_text(
    prompt: str,
    system_instruction: str,
    max_tokens: int = 1500,
) -> Optional[str]:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens}
    }
    body = json.dumps(payload).encode("utf-8")

    for model in MODEL_CHAIN:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key
        }
        # Standard API Key auth
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
        except Exception:
            continue
    return None

async def analyze_image(path: Path) -> Dict[str, Any]:
    b64 = _read_and_encode(path)
    if not b64:
        return {"ok": False, "text": "", "error": "Rasmni o'qib bo'lmadi"}

    mime = _guess_mime(path, {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".heic": "image/heic",
    }, "image/jpeg")

    prompt = (
        "Ushbu tasvirdagi barcha matn va muhim ma'lumotlarni o'qi (OCR). "
        "Agar matn bo'lmasa, tasvir nima haqida ekanligini qisqacha tavsifla."
    )
    sys_inst = "Sen OCR va tasvir tahlilchisisan. Rasmdagi matnni aniq ko'chirib ber."

    raw = await asyncio.to_thread(_call_gemini_multimodal, mime, b64, prompt, sys_inst)
    if raw is None:
        return {"ok": False, "text": "", "error": "Gemini OCR javob bermadi"}

    clean_text = raw.strip()
    return {
        "ok": True,
        "text": clean_text if clean_text else "[Matn topilmadi]",
        "error": None
    }

async def analyze_document(path: Path) -> Dict[str, Any]:
    ext = path.suffix.lower()
    text = ""
    if ext == ".pdf":
        text = _extract_pdf_text(path)
    elif ext in [".txt", ".md", ".log", ".json", ".csv"]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:15000]
        except Exception:
            text = ""

    if text:
        prompt = f"Quyidagi hujjat matnini tahlil qil va xulosani ber:\n\n{text[:4000]}"
        sys_inst = "Hujjatlar tahlili bo'yicha yordamchisan."
        summary = await asyncio.to_thread(_call_gemini_text, prompt, sys_inst)
        return {
            "ok": True,
            "text": text,
            "summary": summary or "",
            "error": None
        }

    b64 = _read_and_encode(path)
    if not b64:
        return {"ok": False, "text": "", "error": "Hujjatni o'qib bo'lmadi"}
    mime = "application/pdf" if ext == ".pdf" else "application/octet-stream"
    raw = await asyncio.to_thread(
        _call_gemini_multimodal,
        mime,
        b64,
        "Ushbu hujjatdagi barcha ma'lumotlarni tahlil qil va xulosa ber.",
        "Hujjat tahlilchisi"
    )
    if raw:
        return {"ok": True, "text": raw, "summary": raw, "error": None}
    return {"ok": False, "text": "", "error": "Hujjatni tahlil qilib bo'lmadi"}

async def analyze_audio(path: Path) -> Dict[str, Any]:
    b64 = _read_and_encode(path)
    if not b64:
        return {"ok": False, "text": "", "error": "Audio faylni o'qib bo'lmadi"}

    mime = _guess_mime(path, {
        ".mp3": "audio/mp3",
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".wav": "audio/wav",
        ".m4a": "audio/m4a",
        ".aac": "audio/aac",
    }, "audio/ogg")

    prompt = "Ushbu audio xabarni so'zma-so'z transkripsiya qil (matnga aylantir)."
    sys_inst = "Ovozli xabarlarni aniq transkripsiya qiluvchi yordamchisan."

    raw = await asyncio.to_thread(_call_gemini_multimodal, mime, b64, prompt, sys_inst)
    if raw is None:
        return {"ok": False, "text": "", "error": "Audio transkripsiya javob bermadi"}
    return {
        "ok": True,
        "text": raw.strip(),
        "error": None
    }
