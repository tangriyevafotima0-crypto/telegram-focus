"""
test_opportunity_engine.py — opportunity/engine.py (real-vaqt + catch_up) testlari.
FakeClient bilan (stdlib + sqlite, Telethon shart emas real ulanish uchun,
lekin `telethon` paketi import qilinadi — muhitda mavjud bo'lsa ishlaydi).

pytest EMAS — oddiy assert, __main__ orqali ishga tushadi.
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_DB_PATH = Path(tempfile.mkdtemp()) / "test_opportunity_engine.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH}"
os.environ.setdefault("TELEGRAM_API_ID", "123")
os.environ.setdefault("TELEGRAM_API_HASH", "abc")
os.environ.setdefault("TELEGRAM_PHONE", "+10000000000")

from sqlalchemy import select  # noqa: E402

from app.database import init_db, async_session_factory  # noqa: E402
from app.models import Message  # noqa: E402
from app.opportunity import store, engine  # noqa: E402


GOOD_TEXT = (
    "IT sohasida yozgi dastur!\n"
    "Yosh: 15-18 yosh oralig'ida\n"
    "Bepul / to'liq grant\n"
    "Oxirgi muddat: 2099-yil 20-iyun\n"
    "Ariza: https://forms.gle/abc123\n"
)


class FakeMsg:
    def __init__(self, id, text, dt):
        self.id = id
        self.text = text
        self.message = text
        self.date = dt


class FakeEntity:
    def __init__(self, id, title):
        self.id = id
        self.title = title


class FakeClient:
    def __init__(self, chan_msgs):
        self.chan_msgs = chan_msgs  # {int_id: [FakeMsg,...] ascending}

    async def iter_messages(self, entity, limit=None, min_id=0, reverse=False, **kw):
        msgs = [m for m in self.chan_msgs[entity.id] if m.id > min_id]
        if not reverse:
            msgs = list(reversed(msgs))
        if limit:
            msgs = msgs[:limit]
        for m in msgs:
            yield m


async def _reset_db():
    """Har bir test funksiyasi boshida jadvallarni tozalaydi (bitta DB fayl, ketma-ket testlar)."""
    from app.models import OppChannel, OppSent, OppProfile, OppSettings, OppStats
    async with async_session_factory() as session:
        for model in (OppChannel, OppSent, Message):
            await session.execute(model.__table__.delete())
        await session.execute(OppProfile.__table__.delete())
        await session.execute(OppSettings.__table__.delete())
        await session.execute(OppStats.__table__.delete())
        await session.commit()
    await store.update_settings(enabled=True, min_score=1, check_interval=600)


async def test_handle_incoming_disabled_or_unknown_channel():
    await _reset_db()
    await store.update_settings(enabled=False)
    matched = await engine.handle_incoming(-1001111, "Kanal", GOOD_TEXT, datetime(2025, 1, 1), 1)
    assert matched is False

    await store.update_settings(enabled=True)
    # Kanal opp_channels ichida yo'q — hali ham False.
    matched = await engine.handle_incoming(-1001111, "Kanal", GOOD_TEXT, datetime(2025, 1, 1), 1)
    assert matched is False


async def test_handle_incoming_short_text_skipped():
    await _reset_db()
    await store.add_channel(-1001111, "Kanal")
    matched = await engine.handle_incoming(-1001111, "Kanal", "juda qisqa", datetime(2025, 1, 1), 1)
    assert matched is False


async def test_handle_incoming_match_and_dedup():
    await _reset_db()
    await store.add_channel(-1001111, "Kanal")

    matched = await engine.handle_incoming(
        -1001111, "Kanal", GOOD_TEXT, datetime(2025, 1, 1, tzinfo=timezone.utc), 5
    )
    assert matched is True

    async with async_session_factory() as session:
        rows = (await session.execute(select(Message).where(Message.channel == "opportunity"))).scalars().all()
        assert len(rows) == 1
        assert rows[0].chat_id == -1001111
        assert rows[0].telegram_message_id == 5
        assert "IT sohasida" in rows[0].text

    # last_seen yangilangan bo'lishi kerak
    assert await store.get_last_seen(-1001111) == 5

    # Bir xil matn (bir xil title+deadline hash) yana kelsa — takror yozilmasin.
    matched_again = await engine.handle_incoming(
        -1001111, "Kanal", GOOD_TEXT, datetime(2025, 1, 1, tzinfo=timezone.utc), 6
    )
    assert matched_again is False
    async with async_session_factory() as session:
        rows = (await session.execute(select(Message).where(Message.channel == "opportunity"))).scalars().all()
        assert len(rows) == 1  # hali ham 1 ta


async def test_handle_incoming_low_score_rejected():
    await _reset_db()
    await store.update_settings(enabled=True, min_score=200)  # deyarli hech narsa o'tmaydi
    await store.add_channel(-1001111, "Kanal")
    matched = await engine.handle_incoming(
        -1001111, "Kanal", GOOD_TEXT, datetime(2025, 1, 1, tzinfo=timezone.utc), 5
    )
    assert matched is False


async def test_catch_up_baseline_then_new_message():
    await _reset_db()
    await store.add_channel(-1001111, "Fake Channel")

    msgs = [
        FakeMsg(1, "short", datetime(2025, 1, 1)),
        FakeMsg(2, GOOD_TEXT, datetime(2025, 1, 1)),
    ]
    client = FakeClient({12345: msgs})

    async def fake_resolve(c, target):
        return FakeEntity(12345, "Fake Channel")

    engine.resolve_target = fake_resolve

    # Birinchi catch_up: baseline (last_seen=0) — faqat oxirgi ID belgilanadi, hech narsa yuborilmaydi.
    found = await engine.catch_up(client)
    assert found == 0
    assert await store.get_last_seen(-1001111) == 2

    # Yangi mos xabar keladi.
    msgs.append(FakeMsg(3, GOOD_TEXT.replace("2099", "2098"), datetime(2025, 1, 2)))
    found = await engine.catch_up(client)
    assert found == 1
    assert await store.get_last_seen(-1001111) == 3

    # Qayta ishga tushirilsa — yangi xabar yo'q.
    found = await engine.catch_up(client)
    assert found == 0


async def test_catch_up_processes_oldest_to_newest():
    await _reset_db()
    await store.add_channel(-1002222, "Order Channel")
    await store.set_last_seen(-1002222, 10)  # baseline allaqachon o'rnatilgan

    order_seen = []

    original_handle_incoming = engine.handle_incoming

    async def tracking_handle_incoming(
        chat_id, chat_name, text, msg_date, msg_id, broadcast=None, userbot_client=None
    ):
        order_seen.append(msg_id)
        return await original_handle_incoming(
            chat_id, chat_name, text, msg_date, msg_id, broadcast, userbot_client
        )

    msgs = [
        FakeMsg(11, "juda qisqa 1", datetime(2025, 1, 1)),
        FakeMsg(12, "juda qisqa 2", datetime(2025, 1, 1)),
        FakeMsg(13, "juda qisqa 3", datetime(2025, 1, 1)),
    ]
    client = FakeClient({999: msgs})

    async def fake_resolve(c, target):
        return FakeEntity(999, "Order Channel")

    engine.resolve_target = fake_resolve
    engine.handle_incoming = tracking_handle_incoming
    try:
        await engine.catch_up(client)
    finally:
        engine.handle_incoming = original_handle_incoming

    assert order_seen == [11, 12, 13]  # eskidan-yangiga


async def test_catch_up_one_channel_crash_does_not_stop_others():
    await _reset_db()
    await store.add_channel(-100111, "Chan A")
    await store.add_channel(-100999, "Chan B (broken)")
    await store.set_last_seen(-100111, 0)
    await store.set_last_seen(-100999, 0)

    class CrashyClient(FakeClient):
        async def iter_messages(self, entity, limit=None, min_id=0, reverse=False, **kw):
            if entity.id == 999:
                raise RuntimeError("simulated crash")
            async for m in super().iter_messages(entity, limit=limit, min_id=min_id, reverse=reverse, **kw):
                yield m

    client = CrashyClient({111: [FakeMsg(1, GOOD_TEXT, datetime(2025, 1, 1))], 999: []})

    async def fake_resolve(c, target):
        cid = int(target)
        return FakeEntity(111, "Chan A") if cid == -100111 else FakeEntity(999, "Chan B")

    engine.resolve_target = fake_resolve

    # Baseline birinchi (last_seen=0 -> faqat set), keyin ikkinchi chaqiruvda haqiqiy o'qish.
    found = await engine.catch_up(client)
    assert found == 0  # ikkalasi ham baseline (yoki B — crash, lekin A ham hali baseline)

    msgs_a = client.chan_msgs[111]
    msgs_a.append(FakeMsg(2, GOOD_TEXT, datetime(2025, 1, 2)))
    # Chan B hamon bo'sh va crash beradi — Chan A baribir ishlashi kerak.
    found = await engine.catch_up(client)
    assert found == 1  # faqat Chan A dan


async def run_all():
    await init_db()
    await test_handle_incoming_disabled_or_unknown_channel()
    await test_handle_incoming_short_text_skipped()
    await test_handle_incoming_match_and_dedup()
    await test_handle_incoming_low_score_rejected()
    await test_catch_up_baseline_then_new_message()
    await test_catch_up_processes_oldest_to_newest()
    await test_catch_up_one_channel_crash_does_not_stop_others()
    print("ALL ENGINE TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(run_all())
