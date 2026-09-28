# Telegram Focus — ishga tushirish qo‘llanmasi

## 1. Fayllarni AWS serverga ko‘chirish

Mac terminalidan:

```bash
scp -i /path/to/key.pem -r . ubuntu@SERVER_PUBLIC_IP:~/telegram-focus
```

Yoki repository mavjud bo‘lsa:

```bash
ssh -i /path/to/key.pem ubuntu@SERVER_PUBLIC_IP
git clone REPOSITORY_URL ~/telegram-focus
cd ~/telegram-focus
```

`MASTER_PROMPT.md`, `STATUS.md` va loyiha fayllari bir xil versiyada ekanini
tekshiring.

## 2. Avtomatik sozlash

```bash
cd ~/telegram-focus
bash scripts/setup.sh
```

Skript:

- Ubuntu/Debian va Python 3.11+ ni tekshiradi;
- `backend/.env` ni interaktiv yaratadi;
- virtual muhit va dependency'larni o‘rnatadi;
- `backend/data/` ni tayyorlaydi;
- birinchi Telethon loginini terminalda bajaradi;
- systemd service yaratadi va healthcheck qiladi.

API hash yoki Telegram kodini chatga, logga yoki repository'ga yozmang.

## 3. Birinchi login alohida bajarilsa

```bash
cd ~/telegram-focus
source venv/bin/activate
cd backend
python -m app.telethon_client
```

Telegram SMS/kodini va 2FA parolini terminalga kiriting. Session yaratilgach:

```bash
cd ~/telegram-focus
sudo systemctl restart telegram-focus
sudo systemctl status telegram-focus
```

## 4. Service va portni tekshirish

```bash
sudo systemctl is-active telegram-focus
sudo journalctl -u telegram-focus -n 50 --no-pager
curl -f http://127.0.0.1:8000/api/health
curl -f http://127.0.0.1:8000/docs
```

AWS Security Group'da TCP `8000` port faqat Mac public IP manzilingizdan
ochilgan bo‘lsin. Port o‘zgargan bo‘lsa, yuqoridagi buyruqlarda yangi portni
ishlating.

## 5. Frontend'ni ochish

Tavsiya etilgan usul — frontend'ni backend orqali ochish:

```text
http://SERVER_PUBLIC_IP:8000/
```

Shu usulda `frontend/app.js` avtomatik ravishda joriy origin'dan API va
WebSocket manzilini oladi.

`frontend/index.html` faylini to‘g‘ridan-to‘g‘ri ochsangiz, `frontend/app.js`
dagi `CONFIGURED_API_BASE_URL` qiymatiga AWS manzilini yozing. Mac oynasi
sozlamalari `docs/MAC_WINDOW_SETUP.md` da berilgan.

## 6. Yangilash

Kod yangilangandan keyin:

```bash
cd ~/telegram-focus
source venv/bin/activate
python -m pip install -r backend/requirements.txt
sudo systemctl restart telegram-focus
sudo journalctl -u telegram-focus -n 30 --no-pager
```

Database SQLite fayli `backend/data/focus.db` da. Backup:

```bash
cp backend/data/focus.db "backend/data/focus.backup.$(date +%Y%m%d-%H%M%S).db"
```