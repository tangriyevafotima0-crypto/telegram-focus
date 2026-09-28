import asyncio
import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

# 1. Bazada imkoniyatlar qidiruvini faollashtirish
db_path = str(BACKEND_DIR / "data" / "focus.db")
con = sqlite3.connect(db_path)
con.execute("UPDATE opp_settings SET enabled = 1 WHERE id = 1")
con.commit()
con.close()
print("[+] opp_settings faollashtirildi (enabled = 1)")

from telethon import TelegramClient
from app.opportunity.engine import catch_up

async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    session_path = str(BACKEND_DIR / "telegram_focus.session")

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        print("[!] Telegram sessiyasi topilmadi yoki avtorizatsiyadan o'tmagan!")
        return

    print("[*] Telegramga ulandi. 11 ta kanal bo'yicha catch_up() tahlili boshlanmoqda...")
    print("[*] Postlar Gemini orqali o'rganilib, SCHOLARSHHIP{} guruhiga jo'natiladi...\n")

    found = await catch_up(client)

    print("\n" + "=" * 60)
    print(f"[✓] Tahlil yakunlandi! Topilgan va guruhga jo'natilgan imkoniyatlar: {found} ta")
    print("=" * 60)

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
