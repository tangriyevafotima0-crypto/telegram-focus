"""
test_final_integration.py — Stage 6 yakuniy integratsiya: 3 kanal bir vaqtda, WS ajratilishi,
badge/counts, Stage 1–5 endpoint shakllari (regressiya), xavfsizlik (sirlar, path traversal,
ruxsatsiz yuklash). Haqiqiy SQLite + TestClient. pytest EMAS.
"""
import asyncio
import base64
import logging
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
_TMP = Path(tempfile.mkdtemp())
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP / 'final.db'}"
os.environ["TELEGRAM_API_ID"] = "123"
os.environ["TELEGRAM_API_HASH"] = "SECRET_API_HASH_VALUE"
os.environ["TELEGRAM_PHONE"] = "+10000000000"
os.environ["BOT_TOKEN"] = "999:SECRET_BOT_TOKEN_VALUE"
os.environ["OWNER_ID"] = "42"
os.environ["EMAIL_SECRET_KEY"] = "SECRET_EMAIL_KEY_VALUE_0123456789"

from fastapi.testclient import TestClient  # noqa: E402

import app.main as m  # noqa: E402
from app.database import async_session_factory  # noqa: E402
from app.models import Message, Source, SourceType, utc_now  # noqa: E402
from app.opportunity import delivery, engine, store  # noqa: E402

SECRETS = ["SECRET_API_HASH_VALUE", "SECRET_BOT_TOKEN_VALUE", "SECRET_EMAIL_KEY_VALUE_0123456789"]


class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.records = []

    def emit(self, record):
        self.records.append(self.format(record))


async def _noop(*a, **k):
    await asyncio.sleep(3600)


def main():
    cap = LogCapture()
    logging.getLogger().addHandler(cap)
    logging.getLogger().setLevel(logging.DEBUG)

    # Tarmoqsiz: telethon/email/bot start no-op
    m.run_telegram_client = lambda **kw: _noop()
    m.email_worker_loop = lambda b: _noop()

    async def fake_start_bot():
        return None

    delivery.start_bot_client = fake_start_bot
    m.opportunity_delivery.start_bot_client = fake_start_bot

    with TestClient(m.app) as c:
        # ---- 3 kanal ma'lumot
        r = c.post("/api/sources", json={"identifier": "@tgsrc", "display_name": "TG Manba", "type": "channel"})
        assert r.status_code == 201, r.text
        src_tg = r.json()
        assert set(src_tg) >= {"id", "identifier", "display_name", "type", "is_active"}, src_tg

        async def seed():
            async with async_session_factory() as s:
                tg = (await s.get(Source, src_tg["id"]))
                em = Source(identifier="email:1", display_name="Gmail", type=SourceType.CHANNEL, is_active=True, kind="email")
                s.add(em)
                await s.flush()
                for i in range(2):
                    s.add(Message(source_id=tg.id, sender_name="A", text=f"tg {i}", telegram_message_id=100 + i,
                                  received_at=utc_now(), is_read=False, chat_id=1, direction="in",
                                  has_media_file=False, channel="telegram"))
                for i in range(3):
                    s.add(Message(source_id=em.id, sender_name="B", text=f"Mavzu {i}\n\nmatn", telegram_message_id=200 + i,
                                  received_at=utc_now(), is_read=False, chat_id=1, direction="in",
                                  has_media_file=False, channel="email"))
                await s.commit()
            await store.update_settings(enabled=True, min_score=0, check_interval=600)
            await store.add_channel(-100321, "Opp Kanal")
            await store.set_last_seen(-100321, 1)
            text = ("IT sohasida yozgi dastur!\nYosh: 15-18 yosh oralig'ida\nBepul / to'liq grant\n"
                    "Oxirgi muddat: 2099-yil 20-iyun\nAriza: https://forms.gle/int1\n")
            captured = []

            async def bcast(p):
                captured.append(p)

            ok = await engine.handle_incoming(-100321, "Opp Kanal", text, None, 9, bcast, None)
            return ok, captured

        ok, payloads = asyncio.run(seed())
        assert ok and len(payloads) == 1 and payloads[0]["channel"] == "opportunity"
        assert payloads[0]["opp_score"] > 0

        # ---- counts: 3 kanal to'g'ri ajratilgan
        counts = c.get("/api/messages/counts").json()
        assert counts == {"telegram_unread": 2, "email_unread": 3, "archived": 0, "opportunity_unread": 1}, counts
        for ch, n in (("telegram", 2), ("email", 3), ("opportunity", 1)):
            got = c.get(f"/api/messages?channel={ch}").json()
            assert len(got) == n and all(x["channel"] == ch for x in got), (ch, got)
        print("I1 OK: 3 kanal — counts/list to'g'ri ajratilgan")

        # ---- WS: uchala kanal bir vaqtda broadcast, payload `channel` bilan ajraladi
        got_ws = []
        with c.websocket_connect("/ws/messages") as ws:
            async def push():
                for ch in ("telegram", "email", "opportunity"):
                    await m.message_manager.broadcast({"id": 1, "channel": ch, "text": ch})

            c.portal.call(push)
            for _ in range(3):
                got_ws.append(ws.receive_json())
        assert [x["channel"] for x in got_ws] == ["telegram", "email", "opportunity"], got_ws
        print("I2 OK: WebSocket payload'lari channel maydoni bilan ajraladi")

        # ---- Regressiya: Stage 1–5 endpoint shakllari
        msg = c.get("/api/messages?channel=telegram").json()[0]
        assert set(msg) == {"id", "source_id", "source_display_name", "sender_name", "text", "media_type",
                            "media_path", "telegram_message_id", "received_at", "is_read", "is_archived",
                            "archived_at", "reply_to_message_id", "chat_id", "direction", "has_media_file",
                            "media_mime", "media_name", "link_urls", "channel",
                            "triage_level", "triage_reason", "triage_auto_reply",
                            "triage_dashboard", "media_analysis"}, sorted(msg)
        assert "opp_score" not in msg, "eski /api/messages formatiga yangi maydon qo'shilmasligi kerak"
        assert set(c.get("/api/messages/counts").json()) == {"telegram_unread", "email_unread", "archived", "opportunity_unread"}
        assert c.get("/api/health").json() == {"status": "ok"}
        assert c.get("/api/sources").status_code == 200
        assert c.patch(f"/api/sources/{src_tg['id']}", json={"is_active": False}).status_code == 200
        assert c.patch(f"/api/messages/{msg['id']}/read?archive=true").json()["is_archived"] is True
        assert c.patch(f"/api/messages/{msg['id']}/unarchive").json()["is_archived"] is False
        assert c.post("/api/messages/archive-bulk", json={"ids": [msg["id"]]}).json() == {"archived": 1}
        s = c.get("/api/settings/archive").json()
        assert set(s) == {"archive_on_read", "archive_on_reply", "auto_archive_days"}, s
        assert c.put("/api/settings/archive", json=s).status_code == 200
        assert isinstance(c.get("/api/email/presets").json(), (list, dict))
        assert c.get("/api/email/accounts").json() == []
        # Stage 5 shakllari
        assert set(c.get("/api/opp/status").json()) == {"enabled", "channels_count", "min_score", "check_interval", "total_checks", "total_found", "last_check"}
        assert set(c.get("/api/opp/profile").json()) == {"age", "grade", "ielts", "knows_english", "is_student", "is_pupil", "interests", "only_free"}
        assert set(c.get("/api/opp/settings").json()) == {"enabled", "min_score", "check_interval"}
        ch_list = c.get("/api/opp/channels").json()
        assert set(ch_list[0]) == {"id", "channel_id", "name", "last_seen", "created_at"}
        assert c.post("/api/opp/analyze", json={"text": "IT yozgi dastur yosh 15-18 bepul grant 2099-yil 20-iyun"}).status_code == 200
        assert c.put("/api/opp/profile", json={"age": 3}).status_code == 422
        assert c.put("/api/opp/settings", json={"enabled": True, "min_score": 10, "check_interval": 5}).status_code == 422
        assert c.post("/api/opp/channels", json={"identifier": "@x"}).status_code == 503
        assert c.post("/api/opp/refresh-dialogs").status_code == 503
        assert c.post("/api/opp/scan-now").status_code == 503
        assert c.post("/api/opp/import-export", json={"text": "x"}).status_code == 200
        assert c.delete("/api/opp/channels/99999").status_code == 404
        print("I3 OK: Stage 1–5 endpointlari eski formatda javob beradi")

        # ---- Email hisob javobida parol/shifrlangan parol YO'Q (haqiqiy qator bilan)
        from app.email_crypto import encrypt_password
        from app.models import EmailAccount

        async def add_acc():
            async with async_session_factory() as s:
                s.add(EmailAccount(label="T", imap_host="imap.example.com", imap_port=993, username="u@example.com",
                                   password_enc=encrypt_password("HUNTER2_PLAIN_PASSWORD"), folder="INBOX"))
                await s.commit()

        asyncio.run(add_acc())
        body = c.get("/api/email/accounts").text
        assert "HUNTER2_PLAIN_PASSWORD" not in body and "password_enc" not in body and "gAAAA" not in body, body
        assert c.get("/api/email/accounts").json()[0]["has_password"] is True
        print("I3b OK: email hisob javobida parol / password_enc yo'q")

        # ---- Reply: email/opportunity ga javob yuborilmaydi (422)
        em = c.get("/api/messages?channel=email").json()[0]
        assert c.post(f"/api/messages/{em['id']}/reply", json={"text": "x"}).status_code == 422
        op = c.get("/api/messages?channel=opportunity").json()[0]
        assert c.post(f"/api/messages/{op['id']}/reply", json={"text": "x"}).status_code == 422
        print("I4 OK: email/opportunity xabarlariga javob yuborish rad etiladi")

        # ---- Xavfsizlik: media path traversal
        async def evil_media():
            async with async_session_factory() as s:
                srcs = (await s.get(Source, src_tg["id"]))
                for name in ("../../../etc/passwd", "/etc/passwd", "..\\..\\x", "a/../../b"):
                    s.add(Message(source_id=srcs.id, sender_name="E", text="e", telegram_message_id=900 + len(name),
                                  received_at=utc_now(), is_read=False, chat_id=1, direction="in",
                                  has_media_file=True, media_name=name, media_mime="text/plain", channel="telegram"))
                await s.commit()
                from sqlalchemy import select
                rows = (await s.execute(select(Message.id).where(Message.has_media_file.is_(True)))).scalars().all()
                return rows

        for mid in asyncio.run(evil_media()):
            r = c.get(f"/api/media/{mid}")
            assert r.status_code == 404, (mid, r.status_code)
            assert "root:" not in r.text
        print("I5 OK: /api/media path traversal (../, /etc/passwd) -> 404")

        # ---- Xavfsizlik: ruxsatsiz yuklash (mime) va katta fayl
        tg_id = c.get("/api/messages?channel=telegram").json()[0]["id"]
        r = c.post(f"/api/messages/{tg_id}/reply", json={"files": [
            {"name": "evil.exe", "mime": "application/x-msdownload", "data_b64": base64.b64encode(b"MZ").decode()}]})
        assert r.status_code in (400, 415, 422), (r.status_code, r.text)
        r = c.post(f"/api/messages/{tg_id}/reply", json={"files": [
            {"name": "../../x.png", "mime": "image/png", "data_b64": "!!!not-base64!!!"}]})
        assert r.status_code in (400, 422, 503), (r.status_code, r.text)
        print("I6 OK: ruxsatsiz mime / yaroqsiz base64 yuklash rad etiladi")

        # ---- Xavfsizlik: sirlar javoblarda yo'q
        blobs = []
        for path in ("/api/opp/delivery-mode", "/api/opp/status", "/api/opp/groups", "/api/opp/feed",
                     "/api/email/accounts", "/api/email/presets", "/api/sources", "/api/health",
                     "/api/settings/archive", "/openapi.json"):
            r = c.get(path)
            blobs.append((path, r.text))
        r = c.post("/api/opp/channels", json={"identifier": "@x"})
        blobs.append(("POST channels 503", r.text))
        for path, body in blobs:
            for sec in SECRETS:
                assert sec not in body, (path, sec)
        print("I7 OK: javoblarda BOT_TOKEN / api_hash / email kaliti yo'q")

    joined = "\n".join(cap.records)
    for sec in SECRETS:
        assert sec not in joined, f"sir logda: {sec}"
    print("I8 OK: loglarda sirlar yo'q (butun sinov davomida)")

    # session/.db fayllari zipga kirmasligi uchun .gitignore tekshiruvi
    gi = (BACKEND_DIR.parent / ".gitignore").read_text()
    for pat in ("*.session", "*.env", "data/*.db", "data/.email_key"):
        assert pat in gi, pat
    print("I9 OK: .gitignore sir/db/session naqshlarini qamraydi")


if __name__ == "__main__":
    main()
    print("ALL FINAL INTEGRATION TESTS PASSED")
