import sys
import os
import json
import asyncio
import base64
import urllib.request
import urllib.error
from pathlib import Path

print("=" * 65)
print("     GEMINI API KALITINI O'RNATISH VA TEST QILISH")
print("=" * 65)

if len(sys.argv) < 2:
    print("\n[-] XATO: API kalit kiritilmadi!")
    print("Foydalanish: ../venv/bin/python apply_key.py AIzaSy...")
    sys.exit(1)

new_key = sys.argv[1].strip().strip('"').strip("'")
print(f"[*] Tekshirilayotgan kalit: {new_key[:8]}...{new_key[-4:]} (Uzunligi: {len(new_key)})")

# 1. Google API bilan tekshirish
test_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={new_key}"
try:
    req = urllib.request.Request(test_url)
    with urllib.request.urlopen(req) as resp:
        if resp.status == 200:
            print("[+++] QABUL QILINDI: Google API kalitni tasdiqladi (HTTP 200 OK)!")
except urllib.error.HTTPError as e:
    err_body = e.read().decode('utf-8', errors='ignore')
    print(f"\n[---] XATO: Google API rad etdi (HTTP {e.code}):")
    try:
        err_json = json.loads(err_body)
        print("     Sabab:", err_json.get("error", {}).get("message", err_body))
    except Exception:
        print("     ", err_body)
    sys.exit(1)

# 2. Barcha .env fayllariga yozish
env_targets = [
    Path("/home/ubuntu/telegram-focus/backend/.env"),
    Path("/home/ubuntu/telegram-focus/.env"),
    Path("/home/ubuntu/server_vault/.env")
]

for p in env_targets:
    if not p.exists():
        continue
    lines = p.read_text(encoding="utf-8").splitlines()
    new_lines = []
    g_found, gem_found = False, False
    for l in lines:
        if l.startswith("GEMINI_API_KEY="):
            new_lines.append(f'GEMINI_API_KEY="{new_key}"')
            gem_found = True
        elif l.startswith("GOOGLE_API_KEY="):
            new_lines.append(f'GOOGLE_API_KEY="{new_key}"')
            g_found = True
        else:
            new_lines.append(l)
    if not gem_found:
        new_lines.append(f'GEMINI_API_KEY="{new_key}"')
    if not g_found:
        new_lines.append(f'GOOGLE_API_KEY="{new_key}"')
    p.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"[+] Yangilandi: {p}")

# 3. Model zanjirining boshiga rasmiy va eng barqaror gemini-1.5-flash ni qo'yish
ma_file = Path("app/opportunity/media_analyzer.py")
if ma_file.exists():
    ma_code = ma_file.read_text(encoding="utf-8")
    if '"gemini-1.5-flash"' not in ma_code:
        ma_code = ma_code.replace('MODEL_CHAIN = [', 'MODEL_CHAIN = [\n    "gemini-1.5-flash",')
        ma_file.write_text(ma_code, encoding="utf-8")
        print("[+] media_analyzer.py dagi MODEL_CHAIN boshiga gemini-1.5-flash ulandi.")

# 4. Servisni qayta yuklash
os.system("sudo systemctl restart telegram-focus")
print("[+] telegram-focus servisi qayta ishga tushirildi.")

# 5. OCR ni real sinovdan o'tkazish
print("\n" + "=" * 65)
print("     MEDIA ANALYZER (OCR) SINOVI")
print("=" * 65)

from app.opportunity.media_analyzer import analyze_image

tmp_img = Path("/tmp/ocr_verified.png")
tmp_img.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="))

async def test_ocr():
    res = await analyze_image(tmp_img)
    print("\n[+] OCR NATIJASI:")
    print(res)
    if res.get("ok"):
        print("\n>>> GEMINI OCR 100% ISHLAMOQDA! <<<")

try:
    asyncio.run(test_ocr())
finally:
    if tmp_img.exists():
        tmp_img.unlink()
