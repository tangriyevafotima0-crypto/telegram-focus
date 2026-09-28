"""triage.py sinovi — fake Gemini javobi bilan (haqiqiy API kaliti kerak
emas). `urllib.request.urlopen` mock qilinadi, `test_media_analyzer.py`dagi
bilan bir xil naqsh. Kamida 10 ta qo'lda yozilgan misol xabar bilan
`classify_message()` tekshiriladi.
"""
import asyncio
import json
import os
import sys
import types
import unittest.mock as mock
from dataclasses import dataclass
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

os.environ["GEMINI_API_KEY"] = "fake-key-for-test"

# httpx/bs4 bu sinov muhitida o'rnatilmagan bo'lishi mumkin (tarmoq yo'q);
# gemini_analyzer.py ularni faqat scrape_webpage() uchun ishlatadi, bu yerda
# chaqirilmaydi — shuning uchun xavfsiz stub bilan almashtiramiz (xuddi shu
# muhitda test_media_analyzer.py ham shu muammoga duch kelishi mumkin).
if "httpx" not in sys.modules:
    fake_httpx = types.ModuleType("httpx")

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **kw):
            raise RuntimeError("network disabled in test")

    fake_httpx.Client = _FakeClient
    sys.modules["httpx"] = fake_httpx

if "bs4" not in sys.modules:
    try:
        import bs4  # noqa: F401
    except ImportError:
        fake_bs4 = types.ModuleType("bs4")

        class _FakeSoup:
            def __init__(self, *a, **kw):
                pass

            def __call__(self, *a, **kw):
                return []

            @property
            def stripped_strings(self):
                return []

        fake_bs4.BeautifulSoup = _FakeSoup
        sys.modules["bs4"] = fake_bs4

from app.opportunity import triage  # noqa: E402


@dataclass
class FakeMessage:
    """Message ORM obyektining o'rnini bosuvchi — faqat .text kerak."""
    text: str


class FakeResp:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen_json(level: int, reason: str = "test", auto_reply: str = ""):
    def _inner(req, timeout=25):
        answer = json.dumps({"level": level, "reason": reason, "auto_reply": auto_reply})
        return FakeResp({"candidates": [{"content": {"parts": [{"text": answer}]}}]})
    return _inner


def _fake_urlopen_fail(req, timeout=25):
    raise TimeoutError("simulated network timeout")


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_heuristic_greeting_is_level_0():
    """Bir so'zli salomlashish — Gemini chaqirilmasdan Daraja 0."""
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("Gemini chaqirilmasligi kerak")):
        result = run(triage.classify_message(FakeMessage(text="Salom")))
    assert result.level == 0, result
    print("OK: greeting -> level 0, no Gemini call")


def test_heuristic_empty_text_is_level_0():
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("Gemini chaqirilmasligi kerak")):
        result = run(triage.classify_message(FakeMessage(text="   ")))
    assert result.level == 0, result
    print("OK: empty text -> level 0")


def test_heuristic_spam_click_here_is_level_0():
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("Gemini chaqirilmasligi kerak")):
        result = run(triage.classify_message(FakeMessage(text="Click here to win a free iPhone!!!")))
    assert result.level == 0, result
    print("OK: spam -> level 0, no Gemini call")


def test_heuristic_chain_message_is_level_0():
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("Gemini chaqirilmasligi kerak")):
        result = run(triage.classify_message(
            FakeMessage(text="Ushbu xabarni 10 kishiga yuboring, aks holda baxtsizlik keladi")
        ))
    assert result.level == 0, result
    print("OK: chain message -> level 0")


def test_heuristic_emoji_only_is_level_0():
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("Gemini chaqirilmasligi kerak")):
        result = run(triage.classify_message(FakeMessage(text="👍")))
    assert result.level == 0, result
    print("OK: emoji only -> level 0")


def test_quick_signal_wharton_is_level_3_no_gemini():
    """Aniq shoshilinch kalit so'z (Wharton) — Gemini chaqirilmasdan Daraja 3."""
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("Gemini chaqirilmasligi kerak")):
        result = run(triage.classify_message(
            FakeMessage(text="Wharton jamoasidan xabar: muddat ertaga tugaydi")
        ))
    assert result.level == 3, result
    print("OK: Wharton keyword -> level 3, no Gemini call")


def test_quick_signal_acceptance_is_level_3():
    with mock.patch("urllib.request.urlopen", side_effect=AssertionError("Gemini chaqirilmasligi kerak")):
        result = run(triage.classify_message(
            FakeMessage(text="Tabriklaymiz! Siz dasturga qabul qilindingiz.")
        ))
    assert result.level == 3, result
    print("OK: acceptance keyword -> level 3")


def test_gemini_book_request_is_level_2():
    """Noaniq holat (kitob so'rash) — Gemini chaqiriladi, Daraja 2 qaytadi."""
    fake = _fake_urlopen_json(2, "Kitobni qaytarib berish so'ralmoqda",
                               "Assalomu alaykum! Kitobni ertaga qaytarib beraman.")
    with mock.patch("urllib.request.urlopen", side_effect=fake):
        result = run(triage.classify_message(
            FakeMessage(text="Salom, o'sha kitobni ertami qaytarib bera olasizmi?")
        ))
    assert result.level == 2, result
    assert result.auto_reply_text, "Daraja 2 uchun auto-reply bo'lishi kerak"
    print("OK: book request -> level 2 with auto-reply")


def test_gemini_school_admin_is_level_2():
    fake = _fake_urlopen_json(2, "Maktab ma'muriyati xabari", "Xabaringiz qabul qilindi.")
    with mock.patch("urllib.request.urlopen", side_effect=fake):
        result = run(triage.classify_message(
            FakeMessage(text="Ertaga soat 15:00 da ota-ona majlisi bo'ladi, iltimos yetib keling")
        ))
    assert result.level == 2, result
    print("OK: school admin message -> level 2")


def test_gemini_general_chat_is_level_1():
    fake = _fake_urlopen_json(1, "Umumiy guruh suhbati")
    with mock.patch("urllib.request.urlopen", side_effect=fake):
        result = run(triage.classify_message(
            FakeMessage(text="Bugun ob-havo juda issiq, hammaga yaxshi kun tilayman")
        ))
    assert result.level == 1, result
    assert result.auto_reply_text is None
    print("OK: general chat -> level 1, no auto-reply")


def test_gemini_wharton_email_simulation_is_level_3():
    """Wharton emailini simulyatsiya qilish — bu holatda kalit so'z ham bor,
    lekin quick_signal orqali emas, umumiyroq matn orqali Gemini yo'lini
    tekshiramiz (agar quick_signal ushlab qolmasa)."""
    fake = _fake_urlopen_json(3, "Rasmiy qabul emaili")
    with mock.patch("urllib.request.urlopen", side_effect=fake):
        result = run(triage.classify_message(
            FakeMessage(text="Sizning arizangiz komissiya tomonidan ko'rib chiqildi, natija biriktirilgan")
        ))
    assert result.level == 3, result
    print("OK: formal admission email simulation -> level 3")


def test_gemini_failure_falls_back_gracefully():
    """Gemini butunlay javob bermasa (tarmoq xatosi) — zaxira heuristika
    ishlaydi va hech qanday exception otilmaydi."""
    with mock.patch("urllib.request.urlopen", side_effect=_fake_urlopen_fail):
        result = run(triage.classify_message(
            FakeMessage(text="Iltimos, ertaga uchrashuvni tasdiqlab bera olasizmi?")
        ))
    assert result.level in (1, 2), result
    print("OK: Gemini failure -> graceful fallback, no exception")


def test_no_api_key_falls_back_gracefully():
    with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
        result = run(triage.classify_message(FakeMessage(text="Bugun necha soat ishladik?")))
    assert result.level in (0, 1, 2, 3), result
    print("OK: no API key -> graceful fallback")


def test_never_raises_on_malformed_gemini_json():
    def _fake_bad_json(req, timeout=25):
        return FakeResp({"candidates": [{"content": {"parts": [{"text": "not valid json {{{"}]}}]})
    with mock.patch("urllib.request.urlopen", side_effect=_fake_bad_json):
        result = run(triage.classify_message(FakeMessage(text="Nimadir noaniq xabar shu yerda")))
    assert result.level in (0, 1, 2, 3), result
    print("OK: malformed Gemini JSON -> graceful fallback, no exception")


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL: {t.__name__}: {exc}")
    total = len(tests)
    if failed:
        print(f"\n{failed}/{total} TEST(LAR) MUVAFFAQIYATSIZ")
        sys.exit(1)
    print(f"\nHAMMASI OK ({total}/{total})")
