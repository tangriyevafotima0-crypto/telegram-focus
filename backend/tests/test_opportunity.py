"""
test_opportunity.py — opportunity/parser.py, matcher.py, formatting.py testlari.
pytest EMAS — oddiy assert, `python3 -m backend.tests.test_opportunity` yoki
to'g'ridan-to'g'ri `python3 backend/tests/test_opportunity.py` bilan ishlaydi.
Eski test_monitor.py dagi parser/matcher/format testi (GOOD_TEXT,
test_format_opportunity_no_crash_on_sparse_fields) shu yerga ko'chirilgan,
qo'shimcha parser bug-fix testlari bilan.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.opportunity.parser import parse_post, _parse_uz_date, _extract_grade
from app.opportunity.matcher import Profile, evaluate, is_real_opportunity, filter_and_rank
from app.opportunity.formatting import format_opportunity, _opp_hash


GOOD_TEXT = (
    "IT sohasida yozgi dastur!\n"
    "Yosh: 15-18 yosh oralig'ida\n"
    "Bepul / to'liq grant\n"
    "Oxirgi muddat: 2099-yil 20-iyun\n"
    "Ariza: https://forms.gle/abc123\n"
)


def test_format_opportunity_no_crash_on_sparse_fields():
    opp = parse_post(
        "IT dasturi, grant, ariza topshirish uchun kanalga yozing",
        date(2025, 1, 1), "Kanal2",
    )
    p = Profile(age=16, interests=["IT"])
    evaluate(opp, p, date(2025, 1, 1))
    text = format_opportunity(opp, "Kanal2")
    assert "Kanal2" in text
    assert "🎯" in text


def test_good_text_parses_and_matches():
    opp = parse_post(GOOD_TEXT, date(2025, 1, 1), "Test Kanal")
    assert opp.age_min == 15 and opp.age_max == 18
    assert opp.is_free is True
    assert opp.link == "https://forms.gle/abc123"
    assert opp.deadline == date(2099, 6, 20)
    assert "IT" in opp.fields

    profile = Profile(age=16, interests=["IT"], only_free=True)
    evaluate(opp, profile, date(2025, 1, 1))
    assert opp.score > 0
    assert not opp.reject_reasons


def test_year_rollover_bugfix():
    # Dekabr postida "15-yanvar" muddati — o'tgan yil emas, KEYINGI yil bo'lishi kerak.
    ref = date(2025, 12, 20)
    d = _parse_uz_date("15-yanvar", 2025, ref)
    assert d == date(2026, 1, 15)


def test_grade_not_confused_with_date():
    # "2025-10-20" kabi sanalar sinf sifatida noto'g'ri o'qilmasligi kerak (bug fix).
    text = "Tadbir 2025-10-20 kuni bo'ladi. Ishtirokchilar: 9-sinf o'quvchilari."
    lo, hi = _extract_grade(text)
    assert lo == 9 and hi == 9
    # "sinf" so'zi umuman yo'q bo'lsa — sinf talabi ham yo'q.
    lo2, hi2 = _extract_grade("Narxi 2025 so'm, ariza 10-20 kun ichida.")
    assert lo2 is None and hi2 is None


def test_is_real_opportunity_needs_signals_and_keyword():
    plain_chat = parse_post("Salom, qalaysiz? Bugun ob-havo yaxshi ekan.", date(2025, 1, 1), "K")
    assert not is_real_opportunity(plain_chat)
    real = parse_post(GOOD_TEXT, date(2025, 1, 1), "K")
    assert is_real_opportunity(real)


def test_deadline_expired_is_rejected():
    text = GOOD_TEXT.replace("2099-yil 20-iyun", "2020-yil 20-iyun")
    opp = parse_post(text, date(2025, 1, 1), "K")
    profile = Profile(age=16, interests=["IT"])
    evaluate(opp, profile, date(2025, 1, 1))
    assert opp.score == -1000
    assert any("o'tgan" in r for r in opp.reject_reasons)


def test_filter_and_rank_sorts_by_score():
    opps = [
        parse_post(GOOD_TEXT, date(2025, 1, 1), "K1"),
        parse_post(GOOD_TEXT.replace("15-18 yosh", "40-60 yosh"), date(2025, 1, 1), "K2"),
    ]
    profile = Profile(age=16, interests=["IT"])
    ranked = filter_and_rank(opps, profile, date(2025, 1, 1))
    # Yosh mos kelmagan (K2) rad etiladi, faqat K1 qoladi.
    assert len(ranked) == 1
    assert ranked[0].source_channel == "K1"


def test_opp_hash_stable_for_same_title_and_deadline():
    opp1 = parse_post(GOOD_TEXT, date(2025, 1, 1), "K1")
    opp2 = parse_post(GOOD_TEXT, date(2025, 1, 1), "K2")  # boshqa kanal, bir xil matn
    assert _opp_hash(opp1) == _opp_hash(opp2)


if __name__ == "__main__":
    test_format_opportunity_no_crash_on_sparse_fields()
    test_good_text_parses_and_matches()
    test_year_rollover_bugfix()
    test_grade_not_confused_with_date()
    test_is_real_opportunity_needs_signals_and_keyword()
    test_deadline_expired_is_rejected()
    test_filter_and_rank_sorts_by_score()
    test_opp_hash_stable_for_same_title_and_deadline()
    print("ALL TESTS PASSED")
