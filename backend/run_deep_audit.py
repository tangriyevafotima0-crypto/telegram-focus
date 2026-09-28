import sys
import os
import asyncio
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from app.opportunity.gemini_analyzer import analyze_opportunity
from app.opportunity.scraper import web_scraper

async def run_audit():
    print("=" * 72)
    print("  TELEGRAM FOCUS: ENGINE & SEMANTIC FILTER AUDIT TOOL  ")
    print("=" * 72)

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    key_str = f"PASS ({api_key[:8]}...)" if api_key else "FAIL (Kalit topilmadi!)"
    print(f"\n[1] SOZLAMALAR:\n  - Gemini API Kalit: {key_str}\n  - Nomzod: 16 yosh, 11-sinf, IELTS 6.0")

    db_path = str(BACKEND_DIR / "data" / "focus.db")
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode = WAL;")
    con.execute("PRAGMA busy_timeout = 60000;")
    mode = con.execute("PRAGMA journal_mode;").fetchone()[0]
    print(f"\n[2] BAZA HOLATI:\n  - SQLite Journal Mode: {mode} (WAL faol)")

    print(f"\n[3] RESILIENT SCRAPER:")
    page = await web_scraper.scrape_url("https://example.com")
    print(f"  - Scraper Status: {'PASS (Ishladi)' if page.is_success else 'FAIL'}")

    print(f"\n[4] SEMANTIK FILTR SINOVI:")
    master = await analyze_opportunity("DAAD Master's degree scholarship in Germany for university graduates.")
    bachelor = await analyze_opportunity("International High School AI Olympiad and Full-ride Undergraduate scholarship for 11th grade.")

    m_score = master.get("match_score", 0) if master else 0
    b_score = bachelor.get("match_score", 0) if bachelor else 0

    print(f"  - Magistratura Granti: Ball {m_score}/100 | {'[PASS - BLOKLANDI]' if m_score == 0 else '[FAIL]'}")
    print(f"  - Maktab/Bakalavr    : Ball {b_score}/100 | {'[PASS - QABUL]' if b_score >= 75 else '[FAIL]'}")
    print("\n" + "=" * 72)

if __name__ == "__main__":
    asyncio.run(run_audit())
