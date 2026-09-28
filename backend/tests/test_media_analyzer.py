"""media_analyzer.py sinovi — fake Gemini javobi bilan (haqiqiy API kaliti
kerak emas). urllib.request.urlopen mock qilinadi, xuddi test_email_client.py
uslubidagi kabi fake tashqi chaqiruv naqshi."""
import asyncio
import json
import os
import sys
import unittest.mock as mock
from pathlib import Path

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

os.environ["GEMINI_API_KEY"] = "fake-key-for-test"
from app.opportunity import media_analyzer as ma  # noqa: E402


class FakeResp:
    def __init__(self, payload: dict):
        self.payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen_text(answer_text: str):
    def _inner(req, timeout=25):
        return FakeResp({"candidates": [{"content": {"parts": [{"text": answer_text}]}}]})
    return _inner


def _fake_urlopen_fail(req, timeout=25):
    raise TimeoutError("simulated network timeout")


async def _main():
    # 1. analyze_image: missing file -> graceful, no exception
    r = await ma.analyze_image(Path("/tmp/__nope__.jpg"))
    assert r == {"ok": False, "text": "", "error": "Fayl topilmadi"}, r
    print("1 OK: analyze_image missing file")

    # 2. analyze_image: fake Gemini success
    img_path = Path("/tmp/__test_img.jpg")
    img_path.write_bytes(b"\xff\xd8\xff" + b"0" * 50)
    with mock.patch("urllib.request.urlopen", _fake_urlopen_text("Salom dunyo")):
        r = await ma.analyze_image(img_path)
    assert r["ok"] is True and r["text"] == "Salom dunyo", r
    print("2 OK: analyze_image success (mocked)")

    # 3. analyze_image: all Gemini models fail (network error) -> ok False, no exception raised
    with mock.patch("urllib.request.urlopen", _fake_urlopen_fail):
        r = await ma.analyze_image(img_path)
    assert r["ok"] is False and r["error"], r
    print("3 OK: analyze_image all-models-fail handled gracefully")

    # 4. analyze_audio: unsupported (all models fail) -> unsupported flag set
    audio_path = Path("/tmp/__test_audio.ogg")
    audio_path.write_bytes(b"OggS" + b"0" * 50)
    with mock.patch("urllib.request.urlopen", _fake_urlopen_fail):
        r = await ma.analyze_audio(audio_path)
    assert r["ok"] is False and r["unsupported"] is True, r
    print("4 OK: analyze_audio unsupported path")

    # 5. analyze_audio: success
    with mock.patch("urllib.request.urlopen", _fake_urlopen_text("Bu ovozli xabar matni")):
        r = await ma.analyze_audio(audio_path)
    assert r["ok"] is True and r["text"] == "Bu ovozli xabar matni", r
    print("5 OK: analyze_audio success (mocked)")

    # 6. analyze_document: non-pdf rejected
    doc = Path("/tmp/__test.docx")
    doc.write_bytes(b"not a pdf")
    r = await ma.analyze_document(doc)
    assert r["ok"] is False and ".docx" in r["error"]
    print("6 OK: analyze_document rejects non-pdf")

    # 7. analyze_document: oversized file rejected before any Gemini call
    big_pdf = Path("/tmp/__big.pdf")
    big_pdf.write_bytes(b"%PDF-1.4\n" + b"0" * (ma.MAX_FILE_BYTES + 1))
    r = await ma.analyze_document(big_pdf)
    assert r["ok"] is False and "katta" in r["error"]
    print("7 OK: analyze_document oversized rejected")

    # 8. analyze_document: text extraction + Gemini JSON structuring
    pdf_bytes = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]"
        b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj\n"
        b"4 0 obj<</Length 58>>stream\n"
        b"BT /F1 12 Tf 10 100 Td (Deadline: 2026-10-01) Tj ET\n"
        b"endstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"xref\n0 6\n"
        b"trailer<</Size 6/Root 1 0 R>>\n"
        b"startxref\n0\n%%EOF"
    )
    good_pdf = Path("/tmp/__good.pdf")
    good_pdf.write_bytes(pdf_bytes)
    fake_json = json.dumps({
        "deadline": "2026-10-01", "amount": "Bepul",
        "requirements": ["IELTS"], "summary": "Test xulosa",
    })
    with mock.patch("urllib.request.urlopen", _fake_urlopen_text(fake_json)):
        r = await ma.analyze_document(good_pdf)
    assert r["ok"] is True, r
    assert r["analysis"]["deadline"] == "2026-10-01", r
    assert "Deadline" in r["text"], r
    print("8 OK: analyze_document full success (mocked)")

    # 9. No API key at all -> graceful skip, no exception
    saved = os.environ.pop("GEMINI_API_KEY")
    try:
        r = await ma.analyze_image(img_path)
        assert r["ok"] is False
        print("9 OK: no API key handled gracefully")
    finally:
        os.environ["GEMINI_API_KEY"] = saved


asyncio.run(_main())
print("HAMMASI OK")
