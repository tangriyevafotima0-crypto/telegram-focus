"""
test_opportunity_bot_and_lifespan.py — bot_commands (owner_only, buyruqlar) va main.py lifespan
izolyatsiyasi (Stage 6). FakeEvent/FakeBotClient + haqiqiy SQLite + TestClient. pytest EMAS.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
_DB_PATH = Path(tempfile.mkdtemp()) / "test_bot.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH}"
os.environ["TELEGRAM_API_ID"] = "123"
os.environ["TELEGRAM_API_HASH"] = "abc"
os.environ["TELEGRAM_PHONE"] = "+10000000000"
os.environ.pop("BOT_TOKEN", None)
os.environ.pop("OWNER_ID", None)

from app.database import init_db  # noqa: E402
from app.opportunity import bot_commands as bc, delivery, service, store  # noqa: E402


class FakeEvent:
    def __init__(self, text, sender_id, is_private=True):
        self.raw_text = text
        self.text = text
        self.sender_id = sender_id
        self.is_private = is_private
        self.replies: list[str] = []

    async def respond(self, msg):
        self.replies.append(msg)


class FakeBot:
    def __init__(self):
        self.handlers = []

    def add_event_handler(self, callback, event):
        self.handlers.append((callback, event))


async def run():
    await init_db()

    # 1: BOT_TOKEN/OWNER_ID yo'q -> register() hech narsa qilmaydi, xatosiz
    bot = FakeBot()
    assert bc.register(bot) == 0 and bot.handlers == []
    os.environ["BOT_TOKEN"] = "1:X"
    assert bc.register(bot) == 0, "OWNER_ID yo'q -> ro'yxatdan o'tmaydi"
    assert bc.register(None) == 0
    print("1 OK: BOT_TOKEN/OWNER_ID yo'q -> modul yuklanmaydi (xatosiz)")

    # 2: ikkalasi bor -> 15 buyruq
    os.environ["OWNER_ID"] = "42"
    bot = FakeBot()
    n = bc.register(bot)
    assert n == 15 and len(bot.handlers) == 15, n
    print("2 OK: 15 buyruq ro'yxatdan o'tdi")

    # 3: owner_only — begona/guruh e'tiborsiz, ega javob oladi
    called = []

    @bc.owner_only
    async def h(event):
        called.append(event.sender_id)

    await h(FakeEvent("/x", 7))
    await h(FakeEvent("/x", 42, is_private=False))
    assert called == []
    await h(FakeEvent("/x", 42))
    assert called == [42]

    @bc.owner_in_group
    async def g(event):
        called.append(("g", event.sender_id))

    await g(FakeEvent("/x", 7, is_private=False))
    await g(FakeEvent("/x", 42, is_private=False))
    assert called == [42, ("g", 42)], called
    os.environ["OWNER_ID"] = ""
    await h(FakeEvent("/x", 42))
    assert called == [42, ("g", 42)], "OWNER_ID bo'sh bo'lsa hech kim ruxsat olmaydi"
    os.environ["OWNER_ID"] = "42"
    print("3 OK: owner_only/owner_in_group (begona, guruh, OWNER_ID bo'sh)")

    # 4: registratsiya orqali haqiqiy handler — ega bo'lmasa javob yo'q
    start_cb = bot.handlers[0][0]
    stranger = FakeEvent("/start", 7)
    await start_cb(stranger)
    assert stranger.replies == []
    owner = FakeEvent("/start", 42)
    await start_cb(owner)
    assert owner.replies == [bc.START_TEXT]
    for cmd in ("monitor_add", "group_confirm", "profile_set", "scan_now"):
        assert f"/{cmd}" in bc.START_TEXT
    print("4 OK: /start faqat egaga, matn START_TEXT")

    # 5: profil buyruqlari
    assert "Yosh:" in await bc.do_profile()
    assert (await bc.do_profile_set("age 17")).startswith("✅")
    assert (await store.get_profile())["age"] == 17
    assert "❌" in await bc.do_profile_set("age 3")
    assert "❌" in await bc.do_profile_set("age abc")
    assert (await bc.do_profile_set("grade -")).startswith("✅") and (await store.get_profile())["grade"] is None
    assert (await bc.do_profile_set("ielts 6,5")).startswith("✅") and (await store.get_profile())["ielts"] == 6.5
    assert (await bc.do_profile_set("only_free yo'q")).startswith("✅") and (await store.get_profile())["only_free"] is False
    assert (await bc.do_profile_set("interests IT, Til")).startswith("✅")
    assert (await store.get_profile())["interests"] == ["IT", "Til"]
    assert "Noto'g'ri qiziqish" in await bc.do_profile_set("interests Yolg'on")
    assert "Ishlatish" in await bc.do_profile_set("nomalum 1")
    assert (await store.get_profile())["age"] == 17, "xato qiymat profilni buzmasligi kerak"
    print("5 OK: /profile, /profile_set (turlar, chegaralar, None, xato)")

    # 6: monitor on/off/status/list/remove
    assert "yoqildi" in await bc.do_monitor_toggle(True) and (await store.get_settings())["enabled"] is True
    assert "o'chirildi" in await bc.do_monitor_toggle(False) and (await store.get_settings())["enabled"] is False
    assert (await store.get_settings())["min_score"] == 40, "toggle min_score'ni buzmasligi kerak"
    assert "Kanallar yo'q" in await bc.do_monitor_list()
    row = await store.add_channel(-100123, "Kanal A")
    assert "Kanal A" in await bc.do_monitor_list()
    assert "Kanallar: 1" in await bc.do_monitor_status()
    assert "❌" in await bc.do_monitor_remove("abc")
    assert (await bc.do_monitor_remove(str(row.id))).startswith("✅")
    assert "❌" in await bc.do_monitor_remove(str(row.id))
    print("6 OK: monitor_on/off/status/list/remove")

    # 7: userbot yo'q -> tushunarli xato (add/scan/refresh)
    assert "ulanmagan" in await bc.do_monitor_add("@x")
    assert "ulanmagan" in await bc.do_scan_now()
    assert "ulanmagan" in await bc.do_refresh()
    assert "ulanmagan" in await bc.do_group_add("@g")
    assert "Ishlatish" in await bc.do_monitor_add("")
    print("7 OK: Telegram mijozi yo'q -> aniq xabar")

    # 8: guruh oqimi pending -> confirmed (userbot rejimi, FakeUserbot)
    class UB:
        def __init__(self):
            self.sent = []

        async def get_me(self):
            return object()

        async def get_entity(self, cid):
            return cid

        async def get_permissions(self, e, me):
            class P:
                is_admin = False
                is_creator = False
                send_messages = True
            return P()

        async def send_message(self, chat_id, text, parse_mode=None, link_preview=True):
            self.sent.append((chat_id, text))

    ub = UB()
    import app.telethon_client as tc
    tc._client = ub
    from telethon.tl.types import Channel

    ch = Channel.__new__(Channel)
    ch.id = 555
    ch.title = "Bot Guruh"

    async def fake_resolve(client, target):
        return ch if target in ("@bg", "bg", "555") else None  # t.me/bg -> "bg" (normalize_target)

    service.resolve_target = fake_resolve
    delivery._bot_client = None  # userbot rejimi
    out = await bc.do_group_add("https://t.me/bg")
    assert "kutilmoqda" in out and "Bot Guruh" in out, out
    g = (await store.list_groups())[0]
    assert g.status == "pending" and g.chat_id == -100555
    assert "❌" in await bc.do_group_add("@yoq")
    assert "pending" not in await bc.do_group_list() and "●" in await bc.do_group_list()
    assert "❌" in await bc.do_group_confirm("999")
    assert "Ishlatish" in await bc.do_group_confirm("x")
    out = await bc.do_group_confirm(str(g.id))
    assert out.startswith("✅") and (await store.list_groups())[0].status == "confirmed"
    assert ub.sent and ub.sent[-1][1] == delivery.CONFIRMED_TEXT
    assert "✓" in await bc.do_group_list()
    assert (await bc.do_group_remove(str(g.id))).startswith("✅") and await store.list_groups() == []
    assert "❌" in await bc.do_group_remove(str(g.id))
    tc._client = None
    print("8 OK: group_add -> pending, confirm -> confirmed (+xabar), list, remove")

    # 9: bot rejimida admin bo'lmasa /group_confirm rad etiladi
    class Bot(UB):
        async def get_permissions(self, e, me):
            class P:
                is_admin = False
                is_creator = False
            return P()

    delivery._bot_client = Bot()
    g = await store.add_group(-100777, "BG2")
    out = await bc.do_group_confirm(str(g.id))
    assert out.startswith("❌") and "administrator" in out
    assert (await store.list_groups())[0].status == "pending"
    delivery._bot_client = None
    print("9 OK: bot rejimida admin emas -> confirm rad")


def lifespan_isolation():
    """Bitta fon vazifa yiqilsa qolganlari ishlaydi; to'xtatishda hammasi bekor qilinadi."""
    from fastapi.testclient import TestClient

    import app.main as m

    stopped = {"ok": False, "auto": False}

    async def boom(*a, **k):
        raise RuntimeError("telethon yiqildi")

    async def email_ok(broadcast):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            stopped["ok"] = True
            raise

    async def auto_ok():
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            stopped["auto"] = True
            raise

    m.run_telegram_client = boom
    m.email_worker_loop = email_ok
    m._auto_archive_loop = auto_ok
    os.environ.pop("BOT_TOKEN", None)

    with TestClient(m.app) as client:
        import time
        time.sleep(0.4)
        tasks = m.app.state.background_tasks
        assert set(tasks) == {"telethon", "auto_archive", "email_worker", "opportunity_catchup", "bot_commands"}, set(tasks)
        assert tasks["telethon"].done() and tasks["telethon"].exception() is None, "yiqilgan vazifa himoyalangan"
        assert not tasks["email_worker"].done() and not tasks["auto_archive"].done()
        assert client.get("/api/health").json() == {"status": "ok"}
        assert client.get("/api/messages/counts").status_code == 200
        assert client.get("/api/opp/status").status_code == 200
    assert stopped["ok"] and stopped["auto"], stopped
    assert all(t.done() for t in m.app.state.background_tasks.values())
    print("L1 OK: telethon yiqildi -> email/arxiv/HTTP ishlashda davom etdi; to'xtatishda hammasi bekor qilindi")


if __name__ == "__main__":
    asyncio.run(run())
    lifespan_isolation()
    print("ALL BOT/LIFESPAN TESTS PASSED")
