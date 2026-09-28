"""
parser.py — Opportunity Parser
Kanal eksport faylidan (.txt) imkoniyatlarni ajratib oladi.
Sof Python — AI yo'q, faqat regex va qoidalar.

Har bir post tahlil qilinadi:
  - sarlavha (birinchi mazmunli qator)
  - oxirgi muddat (deadline) — sana sifatida
  - yosh talabi (min/max)
  - til talabi (IELTS/TOEFL bali)
  - narx (bepul/grant/pullik)
  - yo'nalish (IT, til, fan, biznes...)
  - havola (ariza linki)
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional


# ═══════════════════════════════════════════════════════
# O'ZBEKCHA OY NOMLARI
# ═══════════════════════════════════════════════════════

UZ_MONTHS = {
    "yanvar": 1, "fevral": 2, "mart": 3, "aprel": 4, "may": 5, "iyun": 6,
    "iyul": 7, "avgust": 8, "sentabr": 9, "sentyabr": 9, "oktabr": 10,
    "oktyabr": 10, "noyabr": 11, "dekabr": 12,
    # Ko'p uchraydigan variantlar
    "apreldan": 4, "maygacha": 5, "iyunga": 6, "iyulga": 7,
}

UZ_MONTHS_PATTERN = "|".join(sorted(UZ_MONTHS.keys(), key=len, reverse=True))


@dataclass
class Opportunity:
    """Bitta imkoniyat (post)."""
    title: str
    raw_text: str
    post_date: Optional[date] = None
    deadline: Optional[date] = None
    deadline_raw: str = ""
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    grade_min: Optional[int] = None     # sinf (5-11)
    grade_max: Optional[int] = None
    ielts_required: Optional[float] = None
    english_required: bool = False
    is_free: Optional[bool] = None      # True=bepul, False=pullik, None=noma'lum
    fields: list = field(default_factory=list)   # ['IT', 'til', ...]
    link: str = ""
    source_channel: str = ""

    # Hisoblanadigan
    score: int = 0
    match_reasons: list = field(default_factory=list)
    reject_reasons: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════
# SANA TAHLILI
# ═══════════════════════════════════════════════════════

def _parse_uz_date(
    text: str, ref_year: int, ref_date: Optional[date] = None
) -> Optional[date]:
    """
    O'zbekcha sanani date ga aylantiradi.
    Naqshlar:
      "2025-yil 20-iyun"  → 2025-06-20
      "20-iyun, 2025"     → 2025-06-20
      "15-iyun"           → ref_year-06-15
      "12-maygacha"       → ref_year-05-12
      "2025-06-20"        → 2025-06-20

    Yil ko'rsatilmagan sanalar uchun yil chegarasi (rollover) tuzatiladi:
    masalan dekabr postida "15-yanvar" → keyingi yil yanvari (o'tgan emas).
    ref_date berilsa, shu sanadan ~45 kundan ko'proq oldin bo'lsa +1 yil.
    """
    text = text.lower().strip()

    # Format: YYYY-MM-DD yoki DD.MM.YYYY
    iso = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            pass

    dmy = re.search(r"(\d{1,2})[./](\d{1,2})[./](20\d{2})", text)
    if dmy:
        try:
            return date(int(dmy.group(3)), int(dmy.group(2)), int(dmy.group(1)))
        except ValueError:
            pass

    # Yil bor: "2025-yil 20-iyun" yoki "2025 yil 20 iyun"
    ym = re.search(
        rf"(20\d{{2}})[-\s]*yil\s*(\d{{1,2}})[-\s]*({UZ_MONTHS_PATTERN})", text
    )
    if ym:
        year  = int(ym.group(1))
        day   = int(ym.group(2))
        month = UZ_MONTHS[ym.group(3)]
        try:
            return date(year, month, day)
        except ValueError:
            pass

    # "20-iyun, 2025" yoki "20 iyun 2025"
    dym = re.search(
        rf"(\d{{1,2}})[-\s]*({UZ_MONTHS_PATTERN})[,\s]+(20\d{{2}})", text
    )
    if dym:
        day   = int(dym.group(1))
        month = UZ_MONTHS[dym.group(2)]
        year  = int(dym.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            pass

    # Yilsiz: "15-iyun" yoki "12-maygacha" → ref_year (rollover bilan)
    dm = re.search(rf"(\d{{1,2}})[-\s]*({UZ_MONTHS_PATTERN})", text)
    if dm:
        day   = int(dm.group(1))
        month = UZ_MONTHS[dm.group(2)]
        try:
            cand = date(ref_year, month, day)
        except ValueError:
            return None
        # Yil chegarasi: ref_date dan ancha oldin bo'lsa — keyingi yil
        # (masalan dekabr postidagi "yanvar" muddati 2024 emas, 2025).
        if ref_date and cand < ref_date - timedelta(days=45):
            try:
                cand = date(ref_year + 1, month, day)
            except ValueError:
                pass
        return cand

    return None


# Deadline'ni ko'rsatuvchi kalit so'zlar
DEADLINE_MARKERS = [
    "oxirgi muddat", "so'nggi muddat", "songgi muddat", "soʻnggi muddat",
    "ariza topshirish muddati", "ro'yxatdan o'tish muddati",
    "royxatdan otish muddati", "muddat:", "deadline", "oxirgi sana",
    "ariza topshirishning", "topshirish uchun",
]


def _extract_deadline(text: str, post_date: Optional[date]) -> tuple:
    """Postdan deadline'ni topadi. (date|None, raw_str) qaytaradi."""
    ref_year = post_date.year if post_date else date.today().year
    lines = text.split("\n")

    for i, line in enumerate(lines):
        low = line.lower()
        if any(marker in low for marker in DEADLINE_MARKERS):
            # Shu qatorda sana bormi?
            d = _parse_uz_date(line, ref_year, post_date)
            if d:
                return d, line.strip()
            # Keyingi qatorda bo'lishi mumkin
            if i + 1 < len(lines):
                d = _parse_uz_date(lines[i + 1], ref_year, post_date)
                if d:
                    return d, lines[i + 1].strip()

    return None, ""


# ═══════════════════════════════════════════════════════
# YOSH / SINF TAHLILI
# ═══════════════════════════════════════════════════════

def _extract_age(text: str) -> tuple:
    """Yosh oralig'ini topadi. (min, max) qaytaradi."""
    low = text.lower()

    # "17-40 yosh", "18-45 yosh oralig'ida", "13–18 yosh oralig'ida"
    m = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s*yosh", low)
    if m:
        return int(m.group(1)), int(m.group(2))

    # "8 yoshdan 12 yoshgacha" — ikkalasi ham bitta iborada
    m = re.search(r"(\d{1,2})\s*yoshdan\s*(\d{1,2})\s*yoshgacha", low)
    if m:
        return int(m.group(1)), int(m.group(2))

    # Faqat pastki yoki faqat yuqori chegara.
    # "yoshdan" ni oldin tekshiramiz — "18 yoshdan" alohida uchraganda
    # "40 yoshgacha" bilan aralashib ketmasligi uchun.
    m = re.search(r"(\d{1,2})\s*yoshdan", low)
    if m:
        return int(m.group(1)), None
    m = re.search(r"(\d{1,2})\s*yoshgacha", low)
    if m:
        return None, int(m.group(1))

    return None, None


def _extract_grade(text: str) -> tuple:
    """
    Sinf oralig'ini topadi (5-11). (min, max).

    DIQQAT: raqamlar faqat "sinf" so'ziga yaqin joyda hisobga olinadi va
    5..11 oralig'ida bo'lishi shart. Aks holda sanalar ("2025-10-20"),
    narxlar va telefon raqamlari xato sinf sifatida o'qilardi (bug fix).
    """
    low = text.lower()

    # "sinf" umuman yo'q bo'lsa — sinf talabi ham yo'q
    if "sinf" not in low:
        return None, None

    # "9-10 sinf" kabi aniq oraliq — eng ishonchli
    rng = re.search(r"(\d{1,2})\s*[-–]\s*(\d{1,2})\s*sinf", low)
    if rng:
        lo, hi = int(rng.group(1)), int(rng.group(2))
        if 5 <= lo <= 11 and 5 <= hi <= 11 and lo <= hi:
            return lo, hi

    # "sinf: 9-11" / "sinf 9-11" kabi teskari tartib
    rng2 = re.search(r"sinf\s*:?\s*(\d{1,2})\s*[-–]\s*(\d{1,2})", low)
    if rng2:
        lo, hi = int(rng2.group(1)), int(rng2.group(2))
        if 5 <= lo <= 11 and 5 <= hi <= 11 and lo <= hi:
            return lo, hi

    grade_nums: list[int] = []

    # To'g'ridan-to'g'ri: "9-sinf", "9 sinf", "9sinf"
    for g in re.findall(r"(\d{1,2})\s*[-–]?\s*sinf", low):
        gi = int(g)
        if 5 <= gi <= 11:
            grade_nums.append(gi)

    # Sanab o'tilgan: "5-, 6-, 7-, 8-, 9-sinf" — faqat "sinf" oldidagi oynada.
    # (?<!\d) va (?!\s*\d): sana ("2025-10-20") o'rtasidagi raqamlarni chetlab o'tadi.
    for m in re.finditer(r"sinf", low):
        window = low[max(0, m.start() - 30):m.start()]
        for g in re.findall(r"(?<!\d)(\d{1,2})\s*[-–](?!\s*\d)", window):
            gi = int(g)
            if 5 <= gi <= 11:
                grade_nums.append(gi)

    if grade_nums:
        return min(grade_nums), max(grade_nums)

    return None, None


# ═══════════════════════════════════════════════════════
# TIL TALABI
# ═══════════════════════════════════════════════════════

def _extract_language(text: str) -> tuple:
    """(ielts_bali|None, ingliz_tili_kerakmi)."""
    low = text.lower()

    ielts = None
    m = re.search(r"ielts\s*(\d(?:[.,]\d)?)\s*\+?", low)
    if m:
        ielts = float(m.group(1).replace(",", "."))

    english = bool(
        re.search(r"ingliz\s*til|english|ielts|toefl", low)
    )

    return ielts, english


# ═══════════════════════════════════════════════════════
# NARX (bepul / pullik)
# ═══════════════════════════════════════════════════════

FREE_MARKERS = [
    "bepul", "tekin", "to'liq qoplanadi", "toliq qoplanadi",
    "to'liq qoplanadigan", "fully funded", "xarajatlari qoplanadi",
    "xarajatlar qoplanadi", "barcha xarajatlar", "grant", "stipendiya",
    "to'liq grant", "toliq grant", "bepul qatnashish",
]

PAID_MARKERS = [
    "to'lov", "tolov", "narxi", "pullik", "to'lash", "kontrakt summa",
    "ishtirok badali", "to'lov miqdori",
]


def _extract_cost(text: str) -> Optional[bool]:
    """True=bepul, False=pullik, None=noma'lum."""
    low = text.lower()
    has_free = any(m in low for m in FREE_MARKERS)
    has_paid = any(m in low for m in PAID_MARKERS)

    if has_free and not has_paid:
        return True
    if has_paid and not has_free:
        return False
    if has_free and has_paid:
        return True   # grant bo'lsa, ehtimol asosan bepul
    return None


# ═══════════════════════════════════════════════════════
# YO'NALISH (field)
# ═══════════════════════════════════════════════════════

FIELD_KEYWORDS = {
    "IT": ["it sohas", "dasturlash", "programming", "coding", "kompyuter",
           "sun'iy intellekt", "ai ", "robototexnika", "web", "software"],
    "Til": ["ingliz til", "english", "til o'rgan", "language", "til kurs",
            "koreys til", "yapon til", "nemis til"],
    "Fan": ["matematika", "fizika", "kimyo", "biologiya", "science",
            "ilm-fan", "tabiiy fan", "math"],
    "Biznes": ["biznes", "business", "tadbirkor", "startup", "iqtisod",
               "menejment", "marketing", "moliyaviy"],
    "Debat": ["debat", "debate", "munozara", "notiqlik", "public speaking"],
    "Liderlik": ["liderlik", "leadership", "yetakchilik", "yetakchi"],
    "Madaniyat": ["madaniyat", "culture", "sayohat", "almashinuv",
                  "exchange", "lager", "camp", "oromgoh"],
    "San'at": ["rassom", "art", "ijod", "musiqa", "dizayn", "design"],
}


def _extract_fields(text: str) -> list:
    """Yo'nalishlarni aniqlaydi."""
    low = text.lower()
    found = []
    for field_name, keywords in FIELD_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            found.append(field_name)
    return found


# ═══════════════════════════════════════════════════════
# HAVOLA
# ═══════════════════════════════════════════════════════

def _extract_link(text: str) -> str:
    """Ariza/batafsil havolasini topadi."""
    # forms.gle, grantgo, bit.ly, t.me/... ariza linklari
    priority = re.search(
        r"https?://(?:forms\.gle|docs\.google\.com/forms|grantgo\.uz|bit\.ly)\S+",
        text,
    )
    if priority:
        return priority.group(0).rstrip(").,]")

    # Har qanday havola
    any_link = re.search(r"https?://\S+", text)
    if any_link:
        return any_link.group(0).rstrip(").,]")

    return ""


# ═══════════════════════════════════════════════════════
# SARLAVHA
# ═══════════════════════════════════════════════════════

def _extract_title(text: str) -> str:
    """Birinchi mazmunli qatorni sarlavha sifatida oladi."""
    for line in text.split("\n"):
        clean = line.strip().strip("*").strip()
        # Emoji va belgilarni olib tashlaymiz boshidan
        clean = re.sub(r"^[^\w\u0400-\u04FF]+", "", clean)
        if len(clean) > 15:   # mazmunli qator
            return clean[:120]
    # Zaxira: birinchi bo'sh bo'lmagan qator
    for line in text.split("\n"):
        if line.strip():
            return line.strip()[:120]
    return "(sarlavhasiz)"


# ═══════════════════════════════════════════════════════
# ASOSIY PARSER
# ═══════════════════════════════════════════════════════

def parse_post(raw_text: str, post_date: Optional[date], channel: str) -> Opportunity:
    """Bitta postni Opportunity obyektiga aylantiradi."""
    deadline, deadline_raw = _extract_deadline(raw_text, post_date)
    age_min, age_max        = _extract_age(raw_text)
    grade_min, grade_max    = _extract_grade(raw_text)
    ielts, english          = _extract_language(raw_text)
    is_free                 = _extract_cost(raw_text)
    fields_found            = _extract_fields(raw_text)
    link                    = _extract_link(raw_text)
    title                   = _extract_title(raw_text)

    return Opportunity(
        title=title,
        raw_text=raw_text,
        post_date=post_date,
        deadline=deadline,
        deadline_raw=deadline_raw,
        age_min=age_min,
        age_max=age_max,
        grade_min=grade_min,
        grade_max=grade_max,
        ielts_required=ielts,
        english_required=english,
        is_free=is_free,
        fields=fields_found,
        link=link,
        source_channel=channel,
    )


# ═══════════════════════════════════════════════════════
# EKSPORT FAYLINI O'QISH
# ═══════════════════════════════════════════════════════

# Post boshlanishi: [2025-05-29 05:29:07] Yuboruvchi:
POST_HEADER = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}:\d{2}\]\s+(.+?):\s*(.*)$"
)


def parse_export_file(filepath: str) -> tuple:
    """
    Eksport faylini o'qib, postlar ro'yxatini qaytaradi.
    Qaytaradi: (channel_name, [Opportunity, ...])
    """
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")

    # Kanal nomini sarlavhadan olamiz
    channel = "Noma'lum"
    for line in lines[:5]:
        if line.startswith("Suhbat"):
            channel = line.split(":", 1)[1].strip()
            break

    # Postlarni ajratamiz
    posts = []           # [(date, sender, text), ...]
    cur_date = None
    cur_text = []

    # Sarlavhadan keyin boshlanadigan qism (─── dan keyin)
    body_started = False

    for line in lines:
        if not body_started:
            if line.startswith("───") or line.startswith("---"):
                body_started = True
            continue

        m = POST_HEADER.match(line)
        if m:
            # Oldingi postni saqlaymiz
            if cur_text:
                posts.append((cur_date, "\n".join(cur_text).strip()))
            # Yangi post boshlanadi
            try:
                cur_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                cur_date = None
            first_content = m.group(3).strip()
            cur_text = [first_content] if first_content else []
        else:
            # Davomi (ko'p qatorli post)
            cur_text.append(line.rstrip())

    # Oxirgi post
    if cur_text:
        posts.append((cur_date, "\n".join(cur_text).strip()))

    # Har bir postni tahlil qilamiz
    opportunities = []
    for post_date, text in posts:
        if len(text) < 40:   # juda qisqa — imkoniyat emas
            continue
        opp = parse_post(text, post_date, channel)
        opportunities.append(opp)

    return channel, opportunities


if __name__ == "__main__":
    import sys
    ch, opps = parse_export_file(sys.argv[1])
    print(f"Kanal: {ch}")
    print(f"Postlar: {len(opps)}")
    for o in opps[:5]:
        print(f"\n— {o.title}")
        print(f"  Deadline: {o.deadline} | Yosh: {o.age_min}-{o.age_max} | "
              f"IELTS: {o.ielts_required} | Bepul: {o.is_free} | {o.fields}")
