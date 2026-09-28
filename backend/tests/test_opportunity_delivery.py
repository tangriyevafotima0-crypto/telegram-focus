"""
test_opportunity_delivery.py — delivery.py + guruh oqimi + /api/opp/groups (Stage 6).
FakeBot/FakeUserbot + haqiqiy SQLite fayl + fastapi TestClient. pytest EMAS.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_DB_PATH = Path(tempfile.mkdtemp()) / "test_delivery.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_DB_PATH}"
os.environ["TELEGRAM_API_ID"] = "123"
os.environ["TELEGRAM_API_HASH"] = "abc"
os.environ["TELEGRAM_PHONE"] = "+10000000000"
os.environ.pop("BOT_TOKEN", None)

from sqlalchemy import select  # noqa: E402

from app.database import async_session_factory, init_db  # noqa: E402
from app.models import Message  # noqa: E402
from app.opportunity import delivery, engine, store  # noqa: E402
from app.opportunity.delivery import FloodWaitError  # noqa: E402


class _Perms:
    def __init__(self, admin=False, creator=False, send=True):
        self.is_admin = admin
        self.is_creator = creator
        self.send_messages = send


class FakeClient:
    """Bot ham, userbot ham shu klass bilan taqlid qilinadi."""

    def __init__(self, name="fake", admin_chats=(), missing_chats=(), send_ok=True):
        self.name = name
        self.admin_chats = set(admin_chats)
        self.missing_chats = set(missing_chats)
        self.send_ok = send_ok
        self.sent: list[tuple] = []  # (chat_id, text, parse_mode, link_preview)
        self.fail_plan: dict[int, list] = {}  # chat_id -> [exception, ...] (har urinishda bittadan)

    async def get_me(self):
        return object()

    async def get_entity(self, chat_id):
        if chat_id in self.missing_chats:
            raise ValueError("chat topilmadi")
        return chat_id

    async def get_permissions(self, entity, me):
        return _Perms(admin=entity in self.admin_chats, send=self.send_ok)

    async def send_message(self, chat_id, text, parse_mode=None, link_preview=True):
        plan = self.fail_plan.get(chat_id)
        if plan:
            exc = plan.pop(0)
            if exc is not None:
                raise exc
        self.sent.append((chat_id, text, parse_mode, link_preview))


def _flood(seconds):
    e = FloodWaitError.__new__(FloodWaitError)
    e.seconds = seconds
    return e


async def _reset_groups():
    for g in await store.list_groups():
        await store.remove_group_by_db_id(g.id)


async def run():
    await init_db()

    # --- 1: rejim aniqlash
    assert delivery.delivery_mode() == "userbot"
    info = delivery.mode_info()
    assert info["mode"] == "userbot" and info["bot_configured"] is False
    assert "akkauntingiz nomidan" in info["warning"]
    print("1 OK: BOT_TOKEN yo'q -> userbot rejimi + ogohlantirish")

    # asyncio.sleep ni tezlashtirish
    slept = []
    real_sleep = asyncio.sleep

    async def fake_sleep(s, *a, **k):
        slept.append(s)
        await real_sleep(0)

    delivery.asyncio.sleep = fake_sleep  # delivery modulidagi asyncio obyektini emas, sleep'ni almashtiramiz

    # --- 2: guruh yo'q -> 0, xato yo'q
    ub = FakeClient("userbot")
    assert await delivery.deliver("salom", userbot_client=ub) == 0 and ub.sent == []
    print("2 OK: tasdiqlangan guruh yo'q -> hech narsa yuborilmadi")

    # --- 3: pending yuborilmaydi, confirmed yuboriladi (userbot)
    g1 = await store.add_group(-1001, "G1")
    g2 = await store.add_group(-1002, "G2")
    assert g1.status == "pending"
    await store.confirm_group(g1.id)
    n = await delivery.deliver("🎯 **Test**", userbot_client=ub)
    assert n == 1 and [x[0] for x in ub.sent] == [-1001], ub.sent
    assert ub.sent[0][3] is False, "link_preview=False bo'lishi kerak"
    assert ub.sent[0][2] == "md"
    print("3 OK: faqat confirmed guruhga, link_preview=False")

    # --- 4: bitta guruh xatosi boshqalarni to'xtatmaydi
    await store.confirm_group(g2.id)
    ub2 = FakeClient("userbot")
    ub2.fail_plan[-1001] = [RuntimeError("chat yopiq")] * 5
    n = await delivery.deliver("🎯 **Test**", userbot_client=ub2)
    assert n == 1 and [x[0] for x in ub2.sent] == [-1002], ub2.sent
    print("4 OK: G1 xato berdi, G2 baribir yuborildi")

    # --- 5: markdown xatosi -> ** olib tashlab qayta
    ub3 = FakeClient("userbot")
    ub3.fail_plan[-1001] = [ValueError("bad markdown"), None]
    ub3.fail_plan[-1002] = [None]
    n = await delivery.deliver("🎯 **Sarlavha**", userbot_client=ub3)
    assert n == 2
    g1_msgs = [x for x in ub3.sent if x[0] == -1001]
    assert len(g1_msgs) == 1 and g1_msgs[0][1] == "🎯 Sarlavha" and g1_msgs[0][2] is None, g1_msgs
    print("5 OK: markdown xatosi -> ** siz oddiy matn fallback")

    # --- 6: FloodWait <=300 kutib 1 marta qayta urinadi; >300 kesiladi
    ub4 = FakeClient("userbot")
    ub4.fail_plan[-1001] = [_flood(7), None]
    ub4.fail_plan[-1002] = [_flood(9999), None]
    slept.clear()
    n = await delivery.deliver("x " * 30, userbot_client=ub4)
    assert n == 2, (n, ub4.sent)
    assert 8 in slept, slept  # 7+1
    assert 301 in slept, slept  # min(9999, 300)+1
    print("6 OK: FloodWait kutildi (7s, 9999s -> 300s cheklandi) va qayta urinildi")

    # --- 7: FloodWait ikkinchi urinishda ham bo'lsa — guruh o'tkaziladi, boshqasi ishlaydi
    ub5 = FakeClient("userbot")
    ub5.fail_plan[-1001] = [_flood(1), _flood(1)]
    n = await delivery.deliver("y " * 30, userbot_client=ub5)
    assert n == 1 and [x[0] for x in ub5.sent] == [-1002], ub5.sent
    print("7 OK: takroriy FloodWait — o'tkazildi, boshqa guruh ishladi")

    # --- 8: bot rejimi — admin qayta tekshiriladi
    os.environ["BOT_TOKEN"] = "123456:SECRET-TOKEN-VALUE"
    bot = FakeClient("bot", admin_chats={-1002})  # faqat G2 da admin
    delivery._bot_client = bot
    assert delivery.delivery_mode() == "bot"
    info = delivery.mode_info()
    assert info["mode"] == "bot" and info["bot_configured"] is True and info["warning"] is None
    assert "SECRET" not in repr(info)
    ub6 = FakeClient("userbot")
    n = await delivery.deliver("bot matni", userbot_client=ub6)
    assert n == 1 and [x[0] for x in bot.sent] == [-1002] and ub6.sent == [], (bot.sent, ub6.sent)
    print("8 OK: bot rejimi — admin bo'lmagan G1 o'tkazildi, G2 bot orqali yuborildi, userbot ishlatilmadi")

    # --- 9: check_group_ready — bot rejimi
    ok, reason = await delivery.check_group_ready(None, -1001)
    assert not ok and "administrator" in reason
    ok, reason = await delivery.check_group_ready(None, -1002)
    assert ok and reason == ""
    bot.missing_chats.add(-1003)
    ok, reason = await delivery.check_group_ready(None, -1003)
    assert not ok and "topa olmadi" in reason
    print("9 OK: bot rejimida admin/topilmadi sabablari aniq")

    # --- 10: check_group_ready — userbot rejimi (admin shart emas, yuborish huquqi kerak)
    delivery._bot_client = None
    os.environ.pop("BOT_TOKEN", None)
    ok, _ = await delivery.check_group_ready(FakeClient(send_ok=True), -1001)
    assert ok
    ok, reason = await delivery.check_group_ready(FakeClient(send_ok=False), -1001)
    assert not ok and "huquqi yo'q" in reason
    ok, reason = await delivery.check_group_ready(FakeClient(missing_chats={-1001}), -1001)
    assert not ok and "topa olmadi" in reason
    ok, reason = await delivery.check_group_ready(None, -1001)
    assert not ok
    print("10 OK: userbot rejimida yozish huquqi tekshiriladi (admin shart emas)")

    # --- 11: engine — Message DB'da qoladi, yuborish xatosi uni yo'qotmaydi
    await store.update_settings(enabled=True, min_score=0, check_interval=600)
    await store.update_profile(age=16, grade=11, ielts=6.0, knows_english=True, is_student=False,
                               is_pupil=True, interests=["IT"], only_free=True)
    await store.add_channel(-100555, "Kanal X")
    await store.set_last_seen(-100555, 1)

    boom = FakeClient("userbot")
    boom.fail_plan[-1001] = [RuntimeError("x")] * 5
    boom.fail_plan[-1002] = [RuntimeError("x")] * 5
    text = (
        "IT sohasida yozgi dastur!\nYosh: 15-18 yosh oralig'ida\nBepul / to'liq grant\n"
        "Oxirgi muddat: 2099-yil 20-iyun\nAriza: https://forms.gle/abc123\n"
    )
    broadcasts = []

    async def bc(payload):
        broadcasts.append(payload)

    matched = await engine.handle_incoming(-100555, "Kanal X", text, None, 10, bc, boom)
    assert matched is True and len(broadcasts) == 1
    async with async_session_factory() as session:
        rows = (await session.execute(select(Message).where(Message.channel == "opportunity"))).scalars().all()
    assert len(rows) == 1
    print("11 OK: yuborish xatosiga qaramay Message DB'da + broadcast qilindi")

    # --- 12: engine muvaffaqiyatli yuborish (boshqa matn, yangi hash)
    good = FakeClient("userbot")
    text2 = text.replace("IT sohasida yozgi dastur!", "IT sohasida qishki maktab!")
    matched = await engine.handle_incoming(-100555, "Kanal X", text2, None, 11, bc, good)
    assert matched is True
    assert sorted(x[0] for x in good.sent) == [-1002, -1001] or sorted(x[0] for x in good.sent) == [-1002, -1001][::-1]
    assert all("🎯" in x[1] for x in good.sent)
    print("12 OK: engine.handle_incoming -> tasdiqlangan guruhlarga yuborildi")

    # --- 13: send_confirmation matni
    c = FakeClient("userbot")
    assert await delivery.send_confirmation(c, -1001) is True
    assert c.sent[0][1] == delivery.CONFIRMED_TEXT and "tasdiqlandi" in c.sent[0][1]
    assert await delivery.send_confirmation(None, -1001) is False
    print("13 OK: tasdiqlash xabari")

    delivery.asyncio.sleep = real_sleep
    await _reset_groups()


def run_http():
    """TestClient — guruh oqimi (pending -> confirmed) va rejim endpointi."""
    from fastapi.testclient import TestClient

    from app.main import app
    from app.routers import opportunity as router_mod
    from app.opportunity import service as service_mod

    class Ent:
        def __init__(self, id_, title):
            self.id = id_
            self.title = title

    class FC(FakeClient):
        pass

    from telethon.tl.types import Channel

    ch = Channel.__new__(Channel)
    ch.id = 777
    ch.title = "Test Guruh"

    userbot = FC("userbot", admin_chats=set())

    async def fake_resolve(client, target):
        if target in ("777", "@testguruh", "-100777"):
            return ch
        return None

    service_mod.resolve_target = fake_resolve
    router_mod.get_client = lambda: userbot

    with TestClient(app) as client:
        # startup: telegram_task interactive=False, fake creds -> xato bo'lishi mumkin, oqim davom etadi
        r = client.get("/api/opp/delivery-mode")
        assert r.status_code == 200, r.text
        assert r.json()["mode"] == "userbot" and r.json()["bot_configured"] is False
        assert "akkauntingiz nomidan" in (r.json()["warning"] or "")
        print("H1 OK: GET /delivery-mode")

        r = client.post("/api/opp/groups", json={})
        assert r.status_code == 422
        r = client.post("/api/opp/groups", json={"identifier": "@yoq"})
        assert r.status_code == 404
        r = client.post("/api/opp/groups", json={"identifier": "@testguruh"})
        assert r.status_code == 201, r.text
        g = r.json()
        assert g["chat_id"] == -100777 and g["status"] == "pending" and g["title"] == "Test Guruh"
        r = client.post("/api/opp/groups", json={"chat_id": 777, "title": "Nom 2"})
        assert r.status_code == 201 and r.json()["id"] == g["id"] and r.json()["status"] == "pending"
        assert r.json()["title"] == "Nom 2"
        print("H2 OK: POST /groups (422/404/201, takroriy — yangilanadi)")

        assert [x["status"] for x in client.get("/api/opp/groups").json()] == ["pending"]

        # userbot yozish huquqi yo'q -> 400
        userbot.send_ok = False
        r = client.post(f"/api/opp/groups/{g['id']}/confirm")
        assert r.status_code == 400 and "huquqi yo'q" in r.json()["detail"], r.text
        assert client.get("/api/opp/groups").json()[0]["status"] == "pending"
        userbot.send_ok = True
        r = client.post(f"/api/opp/groups/{g['id']}/confirm")
        assert r.status_code == 200 and r.json()["status"] == "confirmed", r.text
        assert userbot.sent and userbot.sent[-1][1] == delivery.CONFIRMED_TEXT
        assert client.post("/api/opp/groups/99999/confirm").status_code == 404
        print("H3 OK: confirm — 400 (sabab bilan) -> 200, '✅ tasdiqlandi' yuborildi, 404")

        # bot rejimi: admin emas -> 400
        os.environ["BOT_TOKEN"] = "1:TOPSECRET"
        delivery._bot_client = FakeClient("bot", admin_chats=set())
        g2 = client.post("/api/opp/groups", json={"identifier": "@testguruh"}).json()
        r = client.post(f"/api/opp/groups/{g2['id']}/confirm")
        assert r.status_code == 400 and "administrator" in r.json()["detail"], r.text
        assert "TOPSECRET" not in r.text
        m = client.get("/api/opp/delivery-mode").json()
        assert m["mode"] == "bot" and m["bot_configured"] is True and "TOPSECRET" not in str(m)
        delivery._bot_client.admin_chats.add(-100777)
        r = client.post(f"/api/opp/groups/{g2['id']}/confirm")
        assert r.status_code == 200, r.text
        assert delivery._bot_client.sent[-1][1] == delivery.CONFIRMED_TEXT
        delivery._bot_client = None
        os.environ.pop("BOT_TOKEN", None)
        print("H4 OK: bot rejimida admin tekshiruvi (400 -> 200), token javobda yo'q")

        # --- Lenta: engine yozgan Message -> /api/opp/feed (ball, muddat, teg, havola)
        import asyncio as _a
        from datetime import date as _d, timedelta as _td

        deadline = _d.today() + _td(days=2)
        feed_text = (
            "IT sohasida yozgi lager!\nYosh: 15-18 yosh oralig'ida\nBepul / to'liq grant\n"
            f"Oxirgi muddat: {deadline.isoformat()}\nAriza: https://forms.gle/feed1\n"
        )

        async def _seed():
            await store.update_settings(enabled=True, min_score=0, check_interval=600)
            await store.add_channel(-100999, "Feed Kanal")
            await store.set_last_seen(-100999, 1)
            return await engine.handle_incoming(-100999, "Feed Kanal", feed_text, None, 5, None, None)

        assert _a.run(_seed()) is True
        feed = client.get("/api/opp/feed").json()
        assert len(feed) >= 1, feed
        item = feed[0]
        assert item["title"].startswith("IT sohasida yozgi lager"), item
        assert isinstance(item["score"], int) and item["score"] > 0, item
        assert item["deadline"] == deadline.isoformat() and item["days_left"] == 2, item
        assert item["is_free"] is True and "IT" in item["fields"], item
        assert item["link"] == "https://forms.gle/feed1" and item["channel_name"] == "Feed Kanal", item
        assert item["is_read"] is False and item["is_archived"] is False
        counts = client.get("/api/messages/counts").json()
        assert counts["opportunity_unread"] >= 1
        # o'qildi -> counts kamayadi; arxivga -> feed(archived=true) da ko'rinadi
        before = counts["opportunity_unread"]
        assert client.patch(f"/api/messages/{item['id']}/read?archive=false").status_code == 200
        assert client.get("/api/messages/counts").json()["opportunity_unread"] == before - 1
        assert client.patch(f"/api/messages/{item['id']}/archive").status_code == 200
        assert all(x["id"] != item["id"] for x in client.get("/api/opp/feed").json())
        assert any(x["id"] == item["id"] for x in client.get("/api/opp/feed?archived=true").json())
        assert client.get("/api/opp/feed?limit=0").status_code == 422
        # boshqa kanallar lentaga aralashmaydi
        tg = client.get("/api/messages?channel=telegram").json()
        assert all(m["channel"] == "telegram" for m in tg)
        print("H6 OK: GET /feed (ball/muddat/teg/havola), counts, read/archive, kanal ajratilishi")

        assert client.delete(f"/api/opp/groups/{g['id']}").status_code == 204
        assert client.delete(f"/api/opp/groups/{g['id']}").status_code == 404
        assert client.get("/api/opp/groups").json() == []
        print("H5 OK: DELETE /groups (204 -> 404)")


if __name__ == "__main__":
    asyncio.run(run())
    run_http()
    print("ALL DELIVERY TESTS PASSED")
