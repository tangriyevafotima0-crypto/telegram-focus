"""test_auto_responder.py — Stage 3: Executive Auto-Responder.
FakeClient + haqiqiy SQLite fayl + fastapi TestClient. pytest EMAS.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_DB_PATH = Path(tempfile.mkdtemp()) / "test_auto_responder.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH}"
os.environ["TELEGRAM_API_ID"] = "123"
os.environ["TELEGRAM_API_HASH"] = "abc"
os.environ["TELEGRAM_PHONE"] = "+10000000000"
os.environ.pop("BOT_TOKEN", None)

from app import telethon_client as tc  # noqa: E402
from app.database import async_session_factory, init_db  # noqa: E402
from app.models import Message, Source, SourceType  # noqa: E402
from app.opportunity import auto_responder  # noqa: E402
from app import settings_store  # noqa: E402


class FakeSentMessage:
    def __init__(self, msg_id):
        self.id = msg_id


class FakeClient:
    def __init__(self):
        self.sent: list[tuple] = []
        self._next_id = 9000

    async def send_message(self, chat_id, text, reply_to=None, link_preview=True):
        self.sent.append((chat_id, text, reply_to))
        self._next_id += 1
        return FakeSentMessage(self._next_id)

    async def send_file(self, *a, **k):  # pragma: no cover - not used here
        raise AssertionError("send_file should not be called for text-only auto-reply")

    def is_connected(self):
        return False


PASS = []
FAIL = []


def check(name, cond, detail=""):
    if cond:
        PASS.append(name)
    else:
        FAIL.append(f"{name} :: {detail}")


async def _make_source_and_message(session, *, chat_id, triage_level, has_media_file=False):
    source = Source(identifier=str(chat_id), display_name="Test", type=SourceType.USER)
    session.add(source)
    await session.flush()
    msg = Message(
        source_id=source.id,
        sender_name="Someone",
        text="Iltimos, javob bering",
        telegram_message_id=1,
        chat_id=chat_id,
        direction="in",
        has_media_file=has_media_file,
        channel="telegram",
        triage_level=triage_level,
        triage_reason="test",
        triage_auto_reply="test auto reply text",
    )
    session.add(msg)
    await session.commit()
    await session.refresh(msg)
    return msg


async def main():
    await init_db()
    fake = FakeClient()
    tc._client = fake  # patch module-level singleton used by get_client()

    # --- Case 1: disabled by default -> no send ---
    settings_store.write_auto_responder_settings({"auto_reply_enabled": False})
    async with async_session_factory() as session:
        msg1 = await _make_source_and_message(session, chat_id=111, triage_level=2)
    result1 = await auto_responder.send_executive_reply(msg1)
    check("disabled_by_default_no_send", result1.sent is False and result1.reason == "disabled",
          f"{result1}")
    check("disabled_no_telegram_call", len(fake.sent) == 0, f"{fake.sent}")

    # --- Case 2: enabled, text-only template ---
    settings_store.write_auto_responder_settings({"auto_reply_enabled": True})
    async with async_session_factory() as session:
        msg2 = await _make_source_and_message(session, chat_id=222, triage_level=2, has_media_file=False)
    result2 = await auto_responder.send_executive_reply(msg2)
    check("enabled_sends", result2.sent is True and result2.reason == "sent", f"{result2}")
    check("text_template_used", fake.sent[-1][1] == auto_responder.TEXT_TEMPLATE, f"{fake.sent[-1]}")
    check("template_verbatim_no_extra", fake.sent[-1][1].count("\n") == 0)

    # --- Case 3: media template ---
    async with async_session_factory() as session:
        msg3 = await _make_source_and_message(session, chat_id=333, triage_level=2, has_media_file=True)
    result3 = await auto_responder.send_executive_reply(msg3)
    check("media_case_sends", result3.sent is True, f"{result3}")
    check("media_template_used", fake.sent[-1][1] == auto_responder.MEDIA_TEMPLATE, f"{fake.sent[-1]}")

    # --- Case 4: rate limit -- second message same chat within 24h ---
    async with async_session_factory() as session:
        msg4 = await _make_source_and_message(session, chat_id=222, triage_level=2)
    sent_count_before = len(fake.sent)
    result4 = await auto_responder.send_executive_reply(msg4)
    check("rate_limited_no_resend", result4.sent is False and result4.reason == "rate_limited",
          f"{result4}")
    check("rate_limited_no_telegram_call", len(fake.sent) == sent_count_before, f"{fake.sent}")

    # --- Case 5: wrong triage level (not 2) -> no send, even if enabled ---
    async with async_session_factory() as session:
        msg5 = await _make_source_and_message(session, chat_id=444, triage_level=3)
    result5 = await auto_responder.send_executive_reply(msg5)
    check("wrong_level_no_send", result5.sent is False and result5.reason == "wrong_level",
          f"{result5}")

    # --- Case 6: no chat_id -> no send ---
    async with async_session_factory() as session:
        source = Source(identifier="nochat", display_name="NoChat", type=SourceType.USER)
        session.add(source)
        await session.flush()
        msg6 = Message(
            source_id=source.id, sender_name="X", text="hi", telegram_message_id=2,
            chat_id=None, direction="in", channel="telegram", triage_level=2,
        )
        session.add(msg6)
        await session.commit()
        await session.refresh(msg6)
    result6 = await auto_responder.send_executive_reply(msg6)
    check("no_chat_id_no_send", result6.sent is False and result6.reason == "no_chat", f"{result6}")

    # --- Case 7: force=True bypasses auto_reply_enabled but not rate limit ---
    settings_store.write_auto_responder_settings({"auto_reply_enabled": False})
    async with async_session_factory() as session:
        msg7 = await _make_source_and_message(session, chat_id=555, triage_level=2)
    result7 = await auto_responder.send_executive_reply(msg7, force=True)
    check("force_bypasses_disabled", result7.sent is True and result7.reason == "sent", f"{result7}")

    async with async_session_factory() as session:
        msg7b = await _make_source_and_message(session, chat_id=555, triage_level=2)
    result7b = await auto_responder.send_executive_reply(msg7b, force=True)
    check("force_still_rate_limited", result7b.sent is False and result7b.reason == "rate_limited",
          f"{result7b}")

    # --- Case 8: settings endpoints ---
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        r = client.get("/api/settings/auto-responder")
        check("settings_get_ok", r.status_code == 200, r.text)
        check("settings_default_false_after_last_write", r.json()["auto_reply_enabled"] is False, r.text)

        r = client.put("/api/settings/auto-responder", json={"auto_reply_enabled": True})
        check("settings_put_ok", r.status_code == 200 and r.json()["auto_reply_enabled"] is True, r.text)

    print(f"PASS: {len(PASS)}  FAIL: {len(FAIL)}")
    for f in FAIL:
        print("  FAILED:", f)
    return len(FAIL) == 0


async def endpoint_tests():
    from fastapi.testclient import TestClient
    from app.main import app

    async with async_session_factory() as session:
        msg_confirm = await _make_source_and_message(session, chat_id=777, triage_level=2)
        msg_cancel = await _make_source_and_message(session, chat_id=888, triage_level=2)
        msg_wrong = await _make_source_and_message(session, chat_id=999, triage_level=1)

    settings_store.write_auto_responder_settings({"auto_reply_enabled": False})

    with TestClient(app) as client:
        # app lifespan tries a real Telethon connection; replace with FakeClient
        # for this test process so send_reply() hits our fake instead of network.
        tc._client = FakeClient()

        r = client.post(f"/api/messages/{msg_confirm.id}/confirm-auto-reply")
        check("confirm_endpoint_sends", r.status_code == 200 and r.json()["sent"] is True, r.text)

        r2 = client.post(f"/api/messages/{msg_confirm.id}/confirm-auto-reply")
        check("confirm_endpoint_rate_limited_second_time",
              r2.status_code == 200 and r2.json()["reason"] == "rate_limited", r2.text)

        r3 = client.post(f"/api/messages/{msg_cancel.id}/cancel-auto-reply")
        check("cancel_endpoint_archives", r3.status_code == 200 and r3.json()["sent"] is False, r3.text)

        async with async_session_factory() as session:
            row = await session.get(Message, msg_cancel.id)
            check("cancel_endpoint_actually_archived", row.is_archived is True)

        r4 = client.post(f"/api/messages/{msg_wrong.id}/confirm-auto-reply")
        check("confirm_endpoint_rejects_wrong_level", r4.status_code == 422, r4.text)


if __name__ == "__main__":
    ok = asyncio.run(main())
    asyncio.run(endpoint_tests())
    print(f"TOTAL PASS: {len(PASS)}  TOTAL FAIL: {len(FAIL)}")
    for f in FAIL:
        print("  FAILED:", f)
    sys.exit(0 if len(FAIL) == 0 else 1)
