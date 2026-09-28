# AWS Ubuntu serverini tayyorlash

Ushbu qo‘llanma Telegram Focus backend’ini AWS Ubuntu serverida ishga tushirish
uchun mo‘ljallangan. Buyruqlar server terminalida bajariladi.

## 1. Serverga SSH orqali ulanish

Mac terminalida:

```bash
chmod 400 /path/to/your-key.pem
ssh -i /path/to/your-key.pem ubuntu@SERVER_PUBLIC_IP
```

Ubuntu AMI turiga qarab foydalanuvchi `ubuntu` yoki `ec2-user` bo‘lishi mumkin.
`SERVER_PUBLIC_IP` o‘rniga AWS EC2 public IPv4 manzilini yozing.

## 2. Python 3.11+ va virtual muhit

Avval tekshiring:

```bash
python3 --version
```

Ubuntu 22.04/24.04 da Python 3.11 mavjud bo‘lmasa:

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo apt install -y python3.11 python3.11-venv python3.11-dev
```

Agar `python3.11` paketi topilmasa, Ubuntu versiyangizga mos rasmiy Python
paketini o‘rnating. Ishchi katalogni yaratib, virtual muhitni ishga tushiring:

```bash
mkdir -p ~/telegram-focus
cd ~/telegram-focus
python3.11 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
mkdir -p backend/data
```

Virtual muhit har yangi SSH sessiyasida alohida yoqiladi:

```bash
cd ~/telegram-focus
source venv/bin/activate
```

## 3. Telegram API ma’lumotlarini olish

1. Brauzerda `https://my.telegram.org` manzilini oching.
2. Telegram telefon raqamingiz bilan kiring.
3. Telegram yuborgan tasdiqlash kodini kiriting.
4. **API development tools** bo‘limini oching.
5. `App title` va `Short name` kiriting.
6. Ko‘rsatilgan `api_id` va `api_hash` qiymatlarini saqlang.

`api_hash`, telefon raqami va `.session` faylini hech kimga yubormang. Ularni
git'ga commit qilmang.

## 4. `.env` faylini yaratish

```bash
cp backend/.env.example backend/.env
chmod 600 backend/.env
nano backend/.env
```

Quyidagilarni to‘ldiring:

```dotenv
TELEGRAM_API_ID=YOUR_NUMERIC_API_ID
TELEGRAM_API_HASH=YOUR_API_HASH
TELEGRAM_PHONE=+998XXXXXXXXX
DATABASE_URL=sqlite+aiosqlite:///./data/focus.db
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
ALLOWED_ORIGINS=http://localhost:8000
```

Qiymatlarda qo‘shtirnoq shart emas. Haqiqiy secret qiymatlarni hujjatga,
chatga yoki repository'ga yozmang.

## 5. AWS Security Group va port

EC2 instance'ning **Security Group → Inbound rules** qismida quyidagilarni
qo‘shing:

| Type | Protocol | Port | Source |
|---|---|---:|---|
| Custom TCP | TCP | 8000 | Mac kompyuteringizning public IP manzili `/32` bilan |

Port 8000 backend API uchun kerak. `0.0.0.0/0` ni source sifatida qo‘ymang:
bu backend'ni butun internetga ochadi. Public IP o‘zgaradigan bo‘lsa, inbound
rule'ni yangilang. SSH (22) uchun ham faqat o‘z IP manzilingizga ruxsat bering.

Ubuntu ichki firewall ishlatilsa:

```bash
sudo ufw allow from YOUR_PUBLIC_IP to any port 8000 proto tcp
sudo ufw allow from YOUR_PUBLIC_IP to any port 22 proto tcp
sudo ufw enable
sudo ufw status
```

## 6. Birinchi Telethon login

Bosqich 2 dagi `backend/app/telethon_client.py` mavjud bo‘lgach, backend
papkasidan quyidagini ishga tushiring:

```bash
cd ~/telegram-focus/backend
../venv/bin/python -m app.telethon_client
```

Terminal so‘raganda Telegram SMS/kodini, 2FA yoqilgan bo‘lsa parolni qo‘lda
kiriting. Bu interaktiv jarayon bir marta bajariladi. Muvaffaqiyatli login'dan
keyin `backend/` ichida `.session` fayli saqlanadi; keyingi ishga tushirishlarda
kod odatda qayta so‘ralmaydi.

## 7. Systemd service namunasi

Loyiha to‘liq bo‘lgach, quyidagi namunani moslang:

```ini
[Unit]
Description=Telegram Focus backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/telegram-focus/backend
EnvironmentFile=/home/ubuntu/telegram-focus/backend/.env
ExecStart=/home/ubuntu/telegram-focus/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

O‘rnating va ishga tushiring:

```bash
sudo nano /etc/systemd/system/telegram-focus.service
sudo systemctl daemon-reload
sudo systemctl enable telegram-focus
sudo systemctl start telegram-focus
sudo systemctl status telegram-focus
```

Loglarni ko‘rish:

```bash
sudo journalctl -u telegram-focus -f
```

`scripts/setup.sh` mavjud bo‘lsa, u yuqoridagi sozlamalarni interaktiv tarzda
avtomatlashtiradi. Bosqich 2–3 tugamaguncha service ishga tushirilmaydi.

## 8. Tekshiruv

Serverning o‘zida:

```bash
curl -f http://127.0.0.1:8000/docs
```

Mac brauzerida:

```text
http://SERVER_PUBLIC_IP:8000/docs
```

Ulanish ishlamasa, avval Security Group source IP'si, port, UFW va service
loglarini tekshiring. Telegram login xatolari uchun `.session` faylini
o‘chirishdan oldin logdagi sababni saqlab oling.