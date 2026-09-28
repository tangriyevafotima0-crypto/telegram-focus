import sys
import os
import re
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Ishchi katalog va yo'llarni qat'iy belgilash
BACKEND_DIR = Path(__file__).resolve().parent
os.chdir(BACKEND_DIR)
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from telethon import TelegramClient
from app.opportunity import store
from app.opportunity.gemini_analyzer import analyze_opportunity

TARGET_GROUP_ID = -5414128616  # SCHOLARSHHIP{}

async def main():
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    session_path = str(BACKEND_DIR / "telegram_focus.session")

    client = TelegramClient(session_path, api_id, api_hash)
    await client.connect()

    if not await client.is_user_authorized():
        print("[X] Telegram sessiyasi ochilmadi!")
        return

    channels = await store.list_channels()
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    
    accepted_count = 0
    rejected_masters = 0

    print("=" * 70)
    print("[*] QAT'IY FILTR BILAN 7 KUNLIK TAHLIL BOSHLANDI:")
    print("[*] Mezon: 16 yosh, 11-sinf, faqat bepul (Maktab / Bakalavr / Tanlov)")
    print("[*] Qoida: Magistratura, PhD, pullik kurslar DARHOL BLOKLANADI.")
    print("=" * 70)

    for ch in channels:
        ch_name = ch.name or f"Kanal ({ch.channel_id})"
        print(f"\n---> [{ch_name}] tekshirilmoqda...")

        try:
            entity = await client.get_entity(ch.channel_id)
            async for msg in client.iter_messages(entity, limit=20):
                text = (getattr(msg, "text", None) or getattr(msg, "message", None) or "").strip()
                msg_date = getattr(msg, "date", None)

                if not text or len(text) < 40:
                    continue
                if msg_date and msg_date < seven_days_ago:
                    break

                urls = re.findall(r"https?://\S+", text)
                res = await analyze_opportunity(text, urls)

                if not res:
                    if any(w in text.lower() for w in ["master", "magistr", "phd", "aspirant"]):
                        rejected_masters += 1
                        print(f"   [BLOKLANDI] Magistratura/PhD dasturi to'xtatildi (ID #{msg.id})")
                    continue

                level = res.get("education_level", "Noma'lum")
                score = res.get("match_score", 0)
                title = res.get("title", "Nomsiz")
                deadline = res.get("deadline", "Noma'lum")

                if score >= 70 and ("magistr" not in level.lower() and "phd" not in level.lower()):
                    accepted_count += 1
                    print(f"   [✓ QABUL QILINDI] {title[:40]} | Bosqich: {level} | Ball: {score}")

                    card = (
                        f"🎓 **{title}**\n\n"
                        f"📌 **Daraja:** {level}\n"
                        f"📅 **Muddati (Deadline):** {deadline}\n"
                        f"⭐️ **Moslik:** {score}/100\n\n"
                        f"📝 {res.get('summary', '')}\n\n"
                        f"🔗 [Asl xabarni ko'rish](https://t.me/c/{str(ch.channel_id).replace('-100', '')}/{msg.id})"
                    )

                    try:
                        await client.send_message(TARGET_GROUP_ID, card)
                    except Exception as err:
                        print(f"      [!] Guruhga yuborishda xatolik: {err}")

                await asyncio.sleep(1.2)

        except Exception as e:
            print(f"   [!] Kanalni o'qishda xatolik: {e}")

    print("\n" + "=" * 70)
    print(f"[TAMOM] Tahlil yakunlandi!")
    print(f" - Rad etilgan magistratura/nomunosib dasturlar: {rejected_masters} ta")
    print(f" - SCHOLARSHHIP{{}} guruhiga yuborilgan to'g'ri grantlar: {accepted_count} ta")
    print("=" * 70)

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
