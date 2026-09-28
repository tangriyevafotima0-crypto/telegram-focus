"""
matcher.py — Profil bo'yicha moslashtirish
Foydalanuvchi profiliga qarab har bir imkoniyatni baholaydi va filtrlaydi.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from .parser import Opportunity


@dataclass
class Profile:
    """Foydalanuvchi profili."""
    age: int = 16
    grade: Optional[int] = 11          # sinf (None bo'lsa universitet)
    ielts: Optional[float] = 6.0
    knows_english: bool = True
    is_student: bool = True            # talabami (universitet)
    is_pupil: bool = True              # maktab o'quvchisimi
    interests: list = field(default_factory=list)   # ['IT', 'Biznes', ...]
    only_free: bool = True             # faqat bepul imkoniyatlar


# ═══════════════════════════════════════════════════════
# BAHOLASH
# ═══════════════════════════════════════════════════════

def is_real_opportunity(opp: Opportunity) -> bool:
    """
    Haqiqiy imkoniyatmi yoki oddiy suhbatmi?
    Kamida 2 ta "imkoniyat signali" bo'lishi kerak:
      - havola (ariza linki)
      - deadline (muddat)
      - bepul/grant belgisi
      - yosh yoki sinf talabi
      - yo'nalish aniqlangan
      - imkoniyat kalit so'zlari (dastur, grant, stipendiya, lager...)
    """
    low = opp.raw_text.lower()

    opportunity_keywords = [
        "dastur", "grant", "stipendiya", "stipend", "lager", "camp",
        "oromgoh", "tanlov", "konkurs", "imkoniyat", "ariza", "ro'yxatdan",
        "royxatdan", "qatnashish", "scholarship", "yozgi maktab", "summer",
        "forum", "konferensiya", "treningga", "seminar", "olimpiada",
        "musobaqa", "internship", "amaliyot",
    ]
    has_keyword = any(kw in low for kw in opportunity_keywords)

    signals = 0
    if opp.link:
        signals += 1
    if opp.deadline:
        signals += 1
    if opp.is_free is True:
        signals += 1
    if opp.age_min is not None or opp.age_max is not None:
        signals += 1
    if opp.grade_min is not None:
        signals += 1
    if opp.fields:
        signals += 1
    if has_keyword:
        signals += 1

    # Kamida 3 signal VA imkoniyat kalit so'zi bo'lishi shart
    return signals >= 3 and has_keyword


def evaluate(opp: Opportunity, profile: Profile, today: Optional[date] = None) -> Opportunity:
    """
    Imkoniyatni profilga moslab baholaydi.
    score va match_reasons/reject_reasons ni to'ldiradi.
    """
    today = today or date.today()
    opp.score = 0
    opp.match_reasons = []
    opp.reject_reasons = []

    # ── 0. HAQIQIY IMKONIYATMI? ───────────────────────
    if not is_real_opportunity(opp):
        opp.reject_reasons.append("Imkoniyat emas (oddiy xabar/suhbat)")
        opp.score = -1000
        return opp

    # ── 1. DEADLINE — eng muhim filtr ─────────────────
    if opp.deadline:
        days_left = (opp.deadline - today).days
        if days_left < 0:
            opp.reject_reasons.append(f"Muddati o'tgan ({opp.deadline})")
            opp.score = -1000          # butunlay rad
            return opp
        elif days_left <= 3:
            opp.score += 50
            opp.match_reasons.append(f"⏰ SHOSHILINCH: {days_left} kun qoldi!")
        elif days_left <= 7:
            opp.score += 30
            opp.match_reasons.append(f"📅 {days_left} kun qoldi")
        elif days_left <= 30:
            opp.score += 15
            opp.match_reasons.append(f"📅 {days_left} kun bor")
        else:
            opp.score += 5
    else:
        # Deadline topilmadi — past prioritet, lekin rad etmaymiz
        opp.score += 2

    # ── 2. YOSH MOSLIGI ───────────────────────────────
    if opp.age_min is not None or opp.age_max is not None:
        lo = opp.age_min if opp.age_min is not None else 0
        hi = opp.age_max if opp.age_max is not None else 200
        if lo <= profile.age <= hi:
            opp.score += 20
            opp.match_reasons.append(f"✅ Yosh mos ({lo}-{hi})")
        else:
            opp.reject_reasons.append(f"Yosh mos emas (talab: {lo}-{hi}, siz: {profile.age})")
            opp.score -= 100

    # ── 3. SINF MOSLIGI ───────────────────────────────
    if opp.grade_min is not None and profile.grade is not None:
        lo = opp.grade_min
        hi = opp.grade_max if opp.grade_max is not None else 11
        if lo <= profile.grade <= hi:
            opp.score += 20
            opp.match_reasons.append(f"✅ Sinf mos ({lo}-{hi})")
        else:
            opp.reject_reasons.append(f"Sinf mos emas (talab: {lo}-{hi}, siz: {profile.grade})")
            opp.score -= 80

    # ── 4. UNIVERSITET TALABI ─────────────────────────
    # Agar post "bakalavr/magistr talabalari uchun" desa va siz maktab o'quvchisi bo'lsangiz
    low = opp.raw_text.lower()
    requires_uni = any(k in low for k in [
        "bakalavr talabalari", "magistr talabalari", "talabalari uchun",
        "bakalavriat talabalari", "universitet talabasi",
    ])
    is_school_only = opp.grade_min is not None and opp.grade_max and opp.grade_max <= 11

    if requires_uni and profile.is_pupil and not profile.is_student and not is_school_only:
        opp.reject_reasons.append("Universitet talabalari uchun (siz maktab o'quvchisi)")
        opp.score -= 60

    # ── 5. TIL TALABI ─────────────────────────────────
    if opp.ielts_required is not None:
        if profile.ielts is not None and profile.ielts >= opp.ielts_required:
            opp.score += 15
            opp.match_reasons.append(f"✅ IELTS mos (talab: {opp.ielts_required}, siz: {profile.ielts})")
        else:
            opp.reject_reasons.append(
                f"IELTS yetarli emas (talab: {opp.ielts_required}, siz: {profile.ielts})"
            )
            opp.score -= 40
    elif opp.english_required:
        if profile.knows_english:
            opp.score += 10
            opp.match_reasons.append("✅ Ingliz tili (siz bilasiz)")

    # ── 6. NARX ───────────────────────────────────────
    if opp.is_free is True:
        opp.score += 25
        opp.match_reasons.append("💰 Bepul / Grant")
    elif opp.is_free is False:
        if profile.only_free:
            opp.reject_reasons.append("Pullik (siz bepulni xohlaysiz)")
            opp.score -= 50
        else:
            opp.score -= 5

    # ── 7. QIZIQISH MOSLIGI ───────────────────────────
    if profile.interests:
        matched = set(opp.fields) & set(profile.interests)
        if matched:
            opp.score += 15 * len(matched)
            opp.match_reasons.append(f"🎯 Qiziqish: {', '.join(matched)}")
        elif opp.fields:
            # Yo'nalishi bor lekin qiziqishingizga mos emas — biroz pasaytiramiz
            opp.score -= 5

    return opp


def filter_and_rank(
    opportunities: list,
    profile: Profile,
    today: Optional[date] = None,
    min_score: int = 1,
) -> list:
    """
    Imkoniyatlarni baholab, rad etilmaganlarini ball bo'yicha saralaydi.
    """
    today = today or date.today()
    evaluated = [evaluate(o, profile, today) for o in opportunities]

    # Faqat ijobiy ballga ega va rad etilmaganlar
    passed = [o for o in evaluated if o.score >= min_score and not o.reject_reasons]

    # Ball bo'yicha kamayish tartibida
    passed.sort(key=lambda o: o.score, reverse=True)
    return passed


def filter_urgent(opportunities: list, profile: Profile,
                  today: Optional[date] = None, days: int = 7) -> list:
    """Faqat muddati yaqin (N kun) imkoniyatlar."""
    today = today or date.today()
    passed = filter_and_rank(opportunities, profile, today)
    urgent = []
    for o in passed:
        if o.deadline:
            days_left = (o.deadline - today).days
            if 0 <= days_left <= days:
                urgent.append(o)
    return urgent
