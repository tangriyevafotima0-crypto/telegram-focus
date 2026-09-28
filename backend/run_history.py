import sys
import os
import asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from telethon import TelegramClient
from app.opportunity import store
from app.opportunity.engine import handle_incoming, resolve_target

async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    session_path = str(BACKEND_DIR / "telegram_focus.session")

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        print("[X] Telegram sessiyasi avtorizatsiyadan o'tmagan!")
        return

    channels = await store.list_channels()
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    total_matched = 0

    print("=" * 65)
    print(f"[*] {len(channels)} ta kanal bo'yicha 7 kunlik tahlil boshlandi...")
    print("[*] Saralangan grantlar SCHOLARSHHIP{} guruhiga jo'natiladi.")
    print("=" * 65)

    for ch in channels:
        ch_name = ch.name or f"Kanal ({ch.channel_id})"
        print(f"\n---> [{ch_name}] tekshirilmoqda...")

        try:
            entity = await resolve_target(client, str(ch.channel_id))
            if not entity:
                print(f"   [!] Kanal topilmadi: {ch.channel_id}")
                continue

            async for msg in client.iter_messages(entity, limit=25):
                text = (getattr(msg, "text", None) or getattr(msg, "message", None) or "").strip()
                msg_date = getattr(msg, "date", None)

                if not text or len(text) < 40:
                    continue
                if msg_date and msg_date < seven_days_ago:
                    break

                matched = await handle_incoming(
                    ch.channel_id, ch.name, text, msg_date, msg.id, None, client
                )
                if matched:
                    total_matched += 1
                    print(f"   [+] Grant topildi va SCHOLARSHHIP{{}} ga yuborildi! (ID: {msg.id})")

                await asyncio.sleep(1.0)

        except Exception as e:
            print(f"   [!] Kanalni o'qishda xatolik: {e}")

    print("\n" + "=" * 65)
    print(f"[✓] Tahlil to'liq yakunlandi!")
    print(f"[✓] Guruhga jo'natilgan imkoniyatlar: {total_matched} ta")
    print("=" * 65)

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
