import asyncio
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
import aiosqlite
from dotenv import load_dotenv
from telethon import TelegramClient

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
API_HASH = os.getenv("TELEGRAM_API_HASH", "")
DB_PATH = str(BACKEND_DIR / "data" / "focus.db")

from app.opportunity.gemini_analyzer import analyze_opportunity

async def main():
    print("=" * 60)
    print(" [1/3] Kanallar tarixini (oxirgi 7 kun) tahlil qilish boshlandi...")
    print("=" * 60)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT channel_id, title FROM monitored_channels WHERE is_active = 1") as cursor:
            channels = await cursor.fetchall()

    if not channels:
        print("[!] Faol kanallar topilmadi!")
        return

    print(f"[*] Kuzatilayotgan kanallar soni: {len(channels)} ta")

    client = TelegramClient(
        str(BACKEND_DIR / "telegram_focus.session"),
        API_ID,
        API_HASH
    )
    await client.connect()

    if not await client.is_user_authorized():
        print("[X] Telegram sessiyasi ochilmadi!")
        return

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    total_added = 0

    for ch in channels:
        ch_id = int(ch["channel_id"]) if str(ch["channel_id"]).lstrip("-").isdigit() else ch["channel_id"]
        ch_title = ch["title"] or f"Kanal ({ch_id})"
        print(f"\n---> [{ch_title}] ko\x27rib chiqilmoqda...")

        try:
            entity = await client.get_entity(ch_id)
            async for msg in client.iter_messages(entity, limit=25):
                if not msg.text or len(msg.text.strip()) < 40:
                    continue
                if msg.date < seven_days_ago:
                    break

                async with aiosqlite.connect(DB_PATH) as db:
                    async with db.execute(
                        "SELECT id FROM processed_messages WHERE channel_id = ? AND message_id = ?",
                        (str(ch_id), msg.id)
                    ) as cur:
                        if await cur.fetchone():
                            continue

                urls = re.findall(r"https?://\S+", msg.text)
                analysis = await analyze_opportunity(msg.text, urls)

                if analysis:
                    score = analysis.get("match_score", 0)
                    title = analysis.get("title", "Nomsiz imkoniyat")
                    summary = analysis.get("summary", "")
                    deadline = analysis.get("deadline", "Noma\x27lum")

                    print(f"   [+] Post {msg.id}: {title[:35]}... | Ball: {score}")

                    if score >= 70:
                        total_added += 1
                        print(f"       >>> BAZAGA QO\x27SHILDI (Ball: {score})")
                        async with aiosqlite.connect(DB_PATH) as db:
                            await db.execute("""
                                INSERT OR REPLACE INTO opportunities 
                                (channel_id, message_id, title, summary, match_score, deadline, is_relevant, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                            """, (str(ch_id), msg.id, title, summary, score, deadline, datetime.now(timezone.utc).isoformat()))
                            await db.commit()

                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("""
                            INSERT OR IGNORE INTO processed_messages (channel_id, message_id, processed_at)
                            VALUES (?, ?, ?)
                        """, (str(ch_id), msg.id, datetime.now(timezone.utc).isoformat()))
                        await db.commit()

                await asyncio.sleep(1.0)
        except Exception as e:
            print(f"   [!] Kanalni o\x27qishda xatolik: {e}")

    await client.disconnect()
    print("\n" + "=" * 60)
    print(f" [TAMOM] Tahlil tugadi! Bazaga {total_added} ta yangi imkoniyat qo\x27shildi.")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
