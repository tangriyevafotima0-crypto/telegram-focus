import os
import re
import json
import logging
import urllib.request
from typing import Dict, Any, List, Optional, Tuple
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. FOYDALANUVChI DOIMIY XOTIRASI VA MEZONLARI
# ==============================================================================
USER_PROFILE = {
    "age": 16,
    "role": "Maktab o'quvchisi (High School Student)",
    "location": "O'zbekiston (International Applicant)",
    "target_degree": "Undergraduate / Bachelor's",
    "focus_areas": [
        "AQSh va Yevropa nufuzli universitetlariga to'liq grantlar (Full-ride scholarships)",
        "SAT va IELTS imtihonlari natijalari",
        "Biznes, moliya, investitsiya musobaqalari (Wharton Global High School Investment Competition kabi)",
        "Sun'iy intellekt, dasturlash va xalqaro olimpiadalar"
    ],
    "disqualifiers": [
        "Faqat AQSh/Yevropa fuqarolari uchun mo'ljallangan dasturlar",
        "Katta tolov (tuition/application fee) talab qiladigan tijoriy summer camplar"
    ]
}

MODEL_CHAIN = [
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3.7-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash"
]

# ==============================================================================
# 2. CHIDAMLI SKRAPER (ROBUST WEB SCRAPER)
# ==============================================================================
def extract_urls(text: str) -> List[str]:
    if not text:
        return []
    url_pattern = r'(https?://[^\s<>"]+|www\.[^\s<>"]+)'
    urls = re.findall(url_pattern, text)
    cleaned = []
    for u in urls:
        u = u.rstrip(".,;!?)>")
        if not u.startswith("http"):
            u = "https://" + u
        cleaned.append(u)
    return cleaned

def scrape_webpage(url: str, max_chars: int = 4000) -> str:
    """Saytga ulanib, matnni tozalab oladi (xatoliklarga 100% chidamli)"""
    if not url:
        return ""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }
        with httpx.Client(follow_redirects=True, timeout=25.0, headers=headers, verify=False) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return f"[Saytga ulanib bo'lmadi: HTTP {resp.status_code}]"

            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
                tag.decompose()

            raw_text = " ".join(soup.stripped_strings)
            clean_text = re.sub(r'\s+', ' ', raw_text)
            return clean_text[:max_chars]
    except Exception as e:
        logger.warning(f"Skraping xatosi ({url}): {e}")
        return f"[Saytdan ma'lumot olishda uzilish: {str(e)[:100]}]"

# ==============================================================================
# 3. GEMINI API VA XATOLIKLARGA CHIDAMLI MULOQOT
# ==============================================================================
def call_gemini_raw(contents: list, system_instruction: str, max_tokens: int = 3000) -> str:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return ""

    for model in MODEL_CHAIN:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {"temperature": 0.2, "maxOutputTokens": max_tokens}
        }
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ans = data.get("candidates", [])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                if ans.strip():
                    return ans.strip()
        except Exception:
            continue
    return ""

# ==============================================================================
# 4. CHUQUR IMKONIYAT VA MOLIYAVIY TAHLIL (ROBUST OPPORTUNITY ANALYZER)
# ==============================================================================
def analyze_opportunity_deeply(post_text: str, web_url: Optional[str] = None) -> Dict[str, Any]:
    urls = extract_urls(post_text)
    target_url = web_url or (urls[0] if urls else "")
    web_text = scrape_webpage(target_url) if target_url else ""

    sys_prompt = f"""Sen o'ta talabchan 'Chief of Staff' va saralovchisan.
FOYDALANUVChI XOTIRASI:
{json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)}

VAZIFA: Ushbu e'lon va sayt matnini o'rganib, quyidagi JSON formatida aniq tahlil ber.
Faqat toza JSON qaytar, begona so'z qo'shma:
{{
  "title": "Imkoniyat yoki Musobaqa nomi",
  "organization": "Tashkilotchi",
  "is_free": true yoki false,
  "cost_type": "Mutlaqo bepul" | "To'liq grant (stipendiya bilan)" | "Pullik (badal talab qilinadi)",
  "cost_details": "Narx, badal yoki to'liq stipendiya miqdori",
  "match_percentage": 0 dan 100 gacha raqam,
  "match_reasons": ["Mos kelgan jihatlar"],
  "unfit_reasons": ["To'g'ri kelmagan sabablar (yosh, fuqarolik, katta summa)"],
  "deadline": "Oxirgi ariza sanasi yoki 'Ko'rsatilmagan'",
  "one_sentence_verdict": "Foydalanuvchiga 1 jumlalik qat'iy tavsiya"
}}
"""
    prompt = f"XABAR MATNI:\n{post_text}\n\nSAYTDAN OLINGAN MATN ({target_url}):\n{web_text}"
    raw = call_gemini_raw([{"parts": [{"text": prompt}]}], sys_prompt, max_tokens=3000)

    try:
        clean = re.sub(r'^```json\s*', '', raw, flags=re.MULTILINE)
        clean = re.sub(r'\s*```$', '', clean, flags=re.MULTILINE).strip()
        return json.loads(clean)
    except Exception:
        # Fallback lokal tahlilchi (Gemini javob bermasa ham to'xtamaydi)
        is_paid = bool(re.search(r'(\$|fee|payment|tuition|pullik|tolov)', post_text + web_text, re.I))
        is_free = bool(re.search(r'(fully funded|free|bepul|stipendiya|scholarship)', post_text + web_text, re.I))
        return {
            "title": "Tahlil qilingan imkoniyat",
            "organization": "Xabardan olindi",
            "is_free": not is_paid or is_free,
            "cost_type": "Mutlaqo bepul / Grant" if is_free else ("Pullik" if is_paid else "Aniq ko'rsatilmagan"),
            "cost_details": "Saytga kirib aniqlashtirish tavsiya etiladi",
            "match_percentage": 85 if is_free else 40,
            "match_reasons": ["Umumiy talablarga mos keladi"],
            "unfit_reasons": ["Yashirin tolovlar bo'lishi mumkin"] if is_paid else [],
            "deadline": "E'londa ko'rsatilmagan",
            "one_sentence_verdict": "Uka, imkoniyatni ko'rib chiqish mumkin, rasmiy saytini tekshiramiz."
        }

# ==============================================================================
# 5. CHAT VA UI KONTEKSTINI JONLI TAHLIL QILISH
# ==============================================================================
def generate_chat_response(message: str, history: List[Dict[str, Any]], facts: Dict[str, Any], current_context: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    recent_msgs = "\n".join(facts.get("recent_messages", [])[-15:])
    
    # Ekranda ochiq turgan joy
    screen_info = ""
    if current_context:
        tab = current_context.get("active_tab", "Telegram")
        source = current_context.get("active_source", "Umumiy")
        visible = current_context.get("visible_items", "")
        screen_info = (
            f"\n[FOYDALANUVChINING HOZIRGI EKRAN HOLATI]:\n"
            f"- Bo'lim: {tab} | Manba: {source}\n"
            f"- Ekranda ochiq xabarlar:\n{visible[:1200]}\n"
        )

    # Savolda havola bo'lsa, uni darhol skraping qilish
    urls = extract_urls(message)
    scraped_part = ""
    if urls:
        scraped_part = f"\n\n[SAVOLDAGI HAVOLA SAYTI O'QILDI ({urls[0]})]:\n{scrape_webpage(urls[0], 2500)}\n"

    # Ekranda ochiq turgan imkoniyat kartasida havola bo'lsa, uni ham o'qib olish
    if not urls and current_context:
        visible = current_context.get("visible_items", "") or ""
        screen_urls = re.findall(r"\[HAVOLA: (https?://[^\]]+)\]", visible)
        if screen_urls:
            scraped_part = (
                f"\n\n[EKRANDAGI IMKONIYAT HAVOLASI O'QILDI ({screen_urls[0]})]:\n"
                f"{scrape_webpage(screen_urls[0], 2500)}\n"
            )

    sys_instruct = f"""Sen 16 yoshli o'quvchining shaxsiy 'Chief of Staff' (katta akasi)san.
FOYDALANUVChI XOTIRASI:
{json.dumps(USER_PROFILE, ensure_ascii=False, indent=2)}

QOIDALAR:
- Har bir fikr va jumlani oxirigacha mantiqan yakunla. Hech qachon ro'yxat yoki gap o'rtasida to'xtab qolma (YARIMTA GAP BILAN TO'XTAMA).
1. Foydalanuvchi hozir ekranning qaysi qismida turganini to'liq ko'rib turibsan.
2. Agar u 'buni tekshir', 'xatga nima deymiz', 'bular nima haqida' desa, to'g'ridan-to'g'ri ochiq turgan xabarlarga va tanlangan manbaga qarab javob ber.
3. Imkoniyatlar va kurslar bo'yicha: pullimi yoki tekin, yoshiga to'g'ri keladimi - vaqtini tejash uchun ochiqchasiga ayt.
4. Uslub: O'zbekcha, o'ta londa, aniq, dalillarga asoslangan do'stona aka uslubi."""

    contents = []
    for h in history[-5:]:
        role = "user" if h.get("sender") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": h.get("text", "")}]})

    full_prompt = (
        f"{screen_info}\n"
        f"BAZADAGI ASOSIY XABARLAR:\n{recent_msgs}\n"
        f"{scraped_part}\n"
        f"SAVOL: {message}"
    )
    contents.append({"role": "user", "parts": [{"text": full_prompt}]})

    ans = call_gemini_raw(contents, sys_instruct, max_tokens=3000)
    if not ans:
        ans = "Xabaringizni qabul qildim. Hozirgi ochiq xabarlar va asosiy maqsadlarimiz bo'yicha ishlashda davom etamiz."
    return ans, "gemini-screen-aware"

def generate_welcome_briefing(facts: Dict[str, Any]) -> Tuple[str, str]:
    tg = facts.get("telegram", {}).get("unread_count", 0)
    rule = facts.get("rule_of_one_focus", "Universitet arizalari")
    prompt = f"Yangi xabarlar: {tg} ta. Asosiy fokus: {rule}. O'quvchiga 2 jumla bilan samimiy salom va kunlik start vazifasini ayt."
    ans = call_gemini_raw([{"parts": [{"text": prompt}]}], "Sen Chief of Staff mentorisan. O'zbekcha qisqa javob ber.")
    return ans or f"Assalomu alaykum! Bazada {tg} ta yangi Telegram xabari bor. Asosiy diqqatni '{rule}' vazifasiga qaratamiz!", "gemini-intelligence"

# ==============================================================================
# 6. ROUTERLAR UCHUN XATOSIZ IMPORT ALIASLARI (ZERO-REGRESSION)
# ==============================================================================
def generate_ai_briefing(payload: Any = None, *args, **kwargs) -> str:
    if isinstance(payload, dict):
        res, _ = generate_welcome_briefing(payload)
        return res
    res, _ = generate_welcome_briefing({})
    return str(res)

def analyze_opportunity(post_text: str = "", web_url: Optional[str] = None, *args, **kwargs) -> Dict[str, Any]:
    return analyze_opportunity_deeply(post_text, web_url)
