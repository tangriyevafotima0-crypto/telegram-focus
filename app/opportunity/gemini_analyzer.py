import json
import os
import re
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional, List
import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")
from app.opportunity.scraper import web_scraper

# Google AI rasmiy ishchi modellari
FALLBACK_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]

SYSTEM_PROMPT = """
Siz ta'lim grantlari bo'yicha qat'iy Bosh AI Ekspertsiz.
NOMZOD: 16 yosh, 11-sinf maktab o'quvchisi, IELTS 6.0, IT/Biznes/Debat/Liderlik.

QAT'IY QIZIL CHIZIQLAR (DARHOL 0 BALL):
- Magistratura (Master's Degree), Aspirantura, PhD, Postdoc.
- Universitet diplomi (bakalavr diplomi) talab qiluvchi dasturlar.
- Pullik kurslar, to'lovli repetitorlik reklamasi.

QABUL QILINADIGAN (75-100 BALL):
- 9-11 sinf xalqaro olimpiada, tanlov va hakatonlar.
- Bakalavriat (Undergraduate) to'liq grantlari (Full Ride).
- Bepul yozgi oromgohlar (FLEX, UWC, TechGirls).

Javobni FAQAT SOF JSON formatida ber:
{
  "title": "Nom",
  "education_level": "Maktab / Bakalavr / Magistr",
  "match_score": 85,
  "is_relevant": true,
  "is_free": true,
  "financial_type": "fully_funded",
  "deadline": "YYYY-MM-DD",
  "summary": "Tahlil xulosasi",
  "tags": ["grant"]
}
"""

async def analyze_opportunity(text: str, urls: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
    if not text or len(text.strip()) < 40:
        return None
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("[Gemini] API kalit topilmadi!")
        return None

    scraped_context = ""
    if urls:
        pages = await web_scraper.scrape_multiple_urls(urls)
        for p in pages:
            if p.content:
                scraped_context += f"\n[HAVOLA MATNI]: {p.title}\n{p.content[:800]}\n"

    user_content = f"POST MATNI:\n{text}\n\n{scraped_context}\nNomzod: 16 yoshli 11-sinf o'quvchisi (IELTS 6.0)."
    payload = {
        "contents": [{"parts": [{"text": SYSTEM_PROMPT}, {"text": user_content}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1}
    }

    async with httpx.AsyncClient(timeout=25.0) as client:
        for model in FALLBACK_MODELS:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
            try:
                res = await client.post(url, json=payload)
                if res.status_code == 200:
                    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", res.json()["candidates"][0]["content"]["parts"][0]["text"].strip())
                    data = json.loads(raw)
                    
                    level = str(data.get("education_level", "")).lower()
                    fin = str(data.get("financial_type", "")).lower()
                    title = str(data.get("title", "")).lower()
                    
                    # Qat'iy qizil chiziqlar
                    if any(w in level or w in title for w in ["magistr", "master", "phd", "aspirant"]) or fin == "paid":
                        data["match_score"] = 0
                        data["is_relevant"] = False
                    return data
                elif res.status_code in (429, 503):
                    await asyncio.sleep(1.5)
                else:
                    print(f"[Gemini Error] Model: {model} -> HTTP {res.status_code}: {res.text[:150]}")
            except Exception as e:
                print(f"[Gemini Exception] {model}: {e}")
                continue
    return None
