# Telegram Focus — Development Guide

Bu fayl loyiha bilan keyin ishlaydigan dasturchi yoki agent uchun asosiy
texnik qo‘llanma. Production server ishlayotgan holatda development o‘zgarish
kiritish va tekshirish tartibi shu yerda berilgan.

## 1. Loyiha maqsadi va cheklovlar

Telegram Focus foydalanuvchining shaxsiy Telegram akkaunti orqali tanlangan
odam, guruh va kanallardan kelgan xabarlarni kuzatadi. U Telegram Bot API emas,
Telethon userbot rejimidan foydalanadi.

Muhim qoidalar:

- `backend/.env`, `*.session`, SQLite database va API secret'lar repository yoki
  ZIP'ga qo‘shilmaydi.
- Production serverdagi fayllarni to‘g‘ridan-to‘g‘ri tahrirlamang.
- Avval development muhitida tekshiring, keyin backup qilib production'ga
  ko‘chiring.
- Development uchun production Telegram session'idan foydalanmang.
- Yangi o‘zgarishdan oldin `STATUS.md` va ushbu faylni o‘qing.

## 2. Hozirgi production konfiguratsiya

| Qism | Qiymat |
|---|---|
| Server | AWS Ubuntu instance |
| Public URL | `http://13.53.174.153:8000/` |
| Service | `telegram-focus.service` |
| Working directory | `/home/ubuntu/telegram-focus/backend` |
| Python | `/home/ubuntu/telegram-focus/venv/bin/python` |
| Database | `backend/data/focus.db` |
| Systemd port | `8000` |
| API healthcheck | `http://127.0.0.1:8000/api/health` |

Public IP o‘zgarishi mumkin. Har safar AWS EC2 sahifasidagi amaldagi Public IPv4
manzilini tekshiring.

Production tekshirish:

```bash
sudo systemctl status telegram-focus --no-pager
curl http://127.0.0.1:8000/api/health
sudo journalctl -u telegram-focus -n 50 --no-pager
```

Kutiladigan healthcheck:

```json
{"status":"ok"}
```

Telethon muvaffaqiyatli bo‘lsa logda quyidagisi chiqadi:

```text
Telethon ulandi; filtrlangan xabarlar tinglanmoqda.
```

## 3. Fayllar nima uchun kerak

```text
backend/
├── app/
│   ├── database.py             SQLAlchemy engine, session, idempotent run_migrations()
│   ├── models.py               Source, Message, EmailAccount, Opp* modellari
│   ├── schemas.py              REST request/response modellari
│   ├── telethon_client.py      Telegram login, NewMessage event, filtr, get_client()
│   ├── main.py                 FastAPI app, lifespan (5 ta mustaqil fon vazifa)
│   ├── media.py                Media yo'llari (path traversal himoyasi), MIME ruxsat ro'yxati
│   ├── sender.py               Telegram'ga javob yuborish (matn/fayl/albom, FloodWait)
│   ├── settings_store.py       Arxiv sozlamalari (data/settings.json)
│   ├── email_crypto.py         Email parol shifrlash (stdlib), data/.email_key
│   ├── email_client.py         IMAP mijozi (faqat o'qish), presetlar
│   ├── email_worker.py         Email fon sikli (EMAIL_POLL_SECONDS, backoff)
│   ├── opportunity/            Imkoniyat monitori (eski ufq_monitor botidan)
│   │   ├── parser.py           Post tahlili (muddat, yosh, sinf, IELTS, narx)
│   │   ├── matcher.py          Profilga moslash va ball berish
│   │   ├── formatting.py       Xabar matni, hash, parse_formatted_meta (UI uchun)
│   │   ├── store.py            SQLite qatlami: profil/sozlama/kanal/guruh/sent/stats
│   │   ├── engine.py           handle_incoming (real-vaqt) + catch_up; "mos topildi" nuqtasi
│   │   ├── resolve.py          @username / link / ID -> entity
│   │   ├── service.py          Router va bot buyruqlari UMUMIY amallari
│   │   ├── delivery.py         Guruhga yuborish (bot yoki userbot rejimi)
│   │   └── bot_commands.py     Ixtiyoriy Telegram buyruqlari (BOT_TOKEN+OWNER_ID kerak)
│   └── routers/
│       ├── sources.py          Manbalar CRUD
│       ├── messages.py         Xabarlar, arxiv, javob, media, WebSocket
│       ├── email.py            Email hisoblar
│       └── opportunity.py      /api/opp/* (profil, kanal, guruh, lenta, tahlil)
├── tests/                      pytest EMAS: `python3 tests/test_X.py`
├── data/
│   ├── focus.db                Production database, ZIP'ga kirmaydi
│   └── focus-dev.db            Development database, ZIP'ga kirmaydi
├── .env                       Production secrets, ZIP'ga kirmaydi
└── .env.development            Development secrets, ZIP'ga kirmaydi

frontend/
├── index.html                  UI: Telegram | Email | Imkoniyatlar tab'lari
├── style.css                   macOS-style dark UI
└── app.js                      API, WebSocket, bildirishnomalar, barcha bo'limlar

scripts/
├── setup.sh                    Birinchi AWS deploy va systemd
└── run_development.sh          Lokal development server

docs/
├── AWS_SETUP.md                AWS tayyorlash
├── RUN_GUIDE.md                Production ishga tushirish
├── MAC_WINDOW_SETUP.md         Mac app window
├── DEVELOPMENT_GUIDE.md        Ushbu fayl
└── USER_GUIDE.md               Foydalanuvchi qo'llanmasi (o'zbekcha)
```

### Endpointlar ro'yxati (to'liq)

| Guruh | Endpoint |
|---|---|
| Umumiy | `GET /api/health`, `WS /ws/messages` |
| Manbalar | `POST/GET /api/sources`, `PATCH/DELETE /api/sources/{id}` |
| Xabarlar | `GET /api/messages` (`archived`, `channel`, `unread_only`, `search`), `GET /api/messages/counts`, `PATCH /api/messages/{id}/read?archive=`, `PATCH .../archive`, `PATCH .../unarchive`, `POST /api/messages/archive-bulk`, `POST /api/messages/{id}/reply`, `GET /api/media/{id}` |
| Arxiv sozlamasi | `GET/PUT /api/settings/archive` |
| Email | `GET /api/email/presets`, `POST/GET /api/email/accounts`, `PATCH/DELETE /api/email/accounts/{id}`, `POST .../check-now` |
| Imkoniyat: sozlama | `GET/PUT /api/opp/profile`, `GET/PUT /api/opp/settings`, `GET /api/opp/status` |
| Imkoniyat: kanal | `POST/GET /api/opp/channels`, `DELETE /api/opp/channels/{db_id}`, `POST /api/opp/refresh-dialogs`, `POST /api/opp/scan-now` |
| Imkoniyat: guruh (Stage 6) | `GET/POST /api/opp/groups`, `POST /api/opp/groups/{id}/confirm`, `DELETE /api/opp/groups/{id}`, `GET /api/opp/delivery-mode` |
| Imkoniyat: boshqa | `GET /api/opp/feed` (Stage 6), `POST /api/opp/analyze`, `POST /api/opp/import-export` |

`DELETE /api/opp/channels|groups/{id}` — DB `id` bo'yicha (Telegram `channel_id`/`chat_id` bo'yicha EMAS).

### Yangi jadvallar va ustunlar (barchasi `run_migrations()` da idempotent)

`email_accounts`, `opp_profile`, `opp_settings`, `opp_channels`, `opp_sent`, `opp_stats`,
`opp_groups` (Stage 6); `messages.opp_score` (Stage 6) va Stage 1 ustunlari.

### Fon vazifalar (main.py lifespan)

`telethon`, `auto_archive`, `email_worker`, `opportunity_catchup`, `bot_commands` —
har biri `_guarded()` ichida: bittasi yiqilsa faqat log yoziladi, qolganlari ishlaydi.
To'xtatishda hammasi bekor qilinadi.

### Muhit o'zgaruvchilari (.env)

| O'zgaruvchi | Majburiy | Izoh |
|---|---|---|
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` | ha | my.telegram.org |
| `DATABASE_URL`, `BACKEND_HOST`, `BACKEND_PORT`, `ALLOWED_ORIGINS` | yo'q | standart qiymatlar bor |
| `EMAIL_POLL_SECONDS` | yo'q | email tekshiruv oralig'i (min 30, standart 60) |
| `EMAIL_SECRET_KEY` | yo'q | bo'sh bo'lsa `data/.email_key` avtomatik yaratiladi |
| `BOT_TOKEN` | yo'q | bo'lsa guruhga BOT nomidan yuboriladi (bot guruhda admin), bo'lmasa userbot |
| `OWNER_ID` | yo'q | `BOT_TOKEN` bilan birga bo'lsa Telegram buyruqlari yoqiladi (faqat shu ID'ga javob) |

Barcha ixtiyoriy o'zgaruvchilar `backend/.env.example` da qiymatsiz. `BOT_TOKEN` hech qachon
javob yoki logga chiqmaydi (testlar bilan tekshirilgan).


## 4. Development channel

Bu loyihadagi **Development Channel** — production'dan alohida o‘zgarishlar
oqimi. Uning chegaralari:

```text
Development branch/working copy
        ↓
Lokal API: 127.0.0.1:8001
        ↓
Development DB: backend/data/focus-dev.db
        ↓
Smoke-test
        ↓
Production backup + deploy
```

Telegram testlari uchun alohida private test guruh yoki kanal yarating va
faqat development muhitiga qo‘shing. Production manbasini development'ga
qo‘shmang. Telegram kanal yaratish Telegram ilovasida qo‘lda bajariladi:

```text
Telegram → New Message → New Channel
```

Keyin development ilovasida shu kanal username yoki ID'sini source sifatida
qo‘shing. Ushbu loyiha Telegram akkauntidan kanal yaratishni avtomatik
amalga oshirmaydi.

### Development channel qoidalari

1. Bitta o‘zgarish — bitta aniq task.
2. Avval `backend/.env.development` va `focus-dev.db` ishlatilishini tekshiring.
3. Production `.env` yoki `.session` faylini development katalogiga ko‘chirmang.
4. API yoki database schema o‘zgarsa, `STATUS.md`ga yozing.
5. Frontend o‘zgarsa, brauzerda hard refresh va API smoke-test qiling.
6. Faqat smoke-testdan keyin production deploy qiling.

## 5. Lokal development muhitini ishga tushirish

Mac’da loyiha papkasiga kiring:

```bash
cd ~/telegram-focus
chmod +x scripts/run_development.sh
./scripts/run_development.sh
```

Birinchi ishga tushirishda `backend/.env.development` yaratiladi. Uni oching:

```bash
nano backend/.env.development
```

Development uchun qiymatlar:

```dotenv
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_PHONE=...
DATABASE_URL=sqlite+aiosqlite:///./data/focus-dev.db
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8001
ALLOWED_ORIGINS=http://127.0.0.1:8001,http://localhost:8001
```

Keyingi ishga tushirish:

```bash
./scripts/run_development.sh
```

Brauzer:

```text
http://127.0.0.1:8001/
```

Development Telegram login'i kerak bo‘lsa, alohida terminalda, development
`.env` bilan ishlaydigan session yarating. Production session faylini
development'ga ko‘chirmang.

Serverni to‘xtatish:

```text
Ctrl+C
```

## 6. O‘zgarish kiritish xaritasi

### Yangi manba qo‘shish yoki manba matching'ini o‘zgartirish

Asosiy fayllar:

- `backend/app/routers/sources.py`
- `backend/app/telethon_client.py`
- `backend/app/models.py`

Identifier username (`@name` yoki `name`) va raqamli ID sifatida ishlaydi.
Matching case-insensitive va `@` belgisini e’tiborsiz qoldiradi.

### Xabar saqlash yoki yangi media turi

Asosiy fayllar:

- `backend/app/models.py`
- `backend/app/telethon_client.py`
- `backend/app/schemas.py`
- `backend/app/routers/messages.py`

Database modelini o‘zgartirishdan oldin backup qiling. Bu loyihada migration
tool yo‘q; mavjud schema o‘zgarsa, `MIGRATSIYA KERAK` deb `STATUS.md`ga yozing.

### API endpoint qo‘shish

Router fayliga endpoint qo‘shing, keyin `schemas.py`da Pydantic schema yarating.
API kontraktini frontend bilan bir xil saqlang.

Mavjud endpointlar:

```text
POST   /api/sources
GET    /api/sources
PATCH  /api/sources/{id}
DELETE /api/sources/{id}
GET    /api/messages?source_id=&limit=&offset=
PATCH  /api/messages/{id}/read
WS     /ws/messages
GET    /api/health
```

### UI o‘zgartirish

- Layout va matn: `frontend/index.html`
- Rang, spacing, responsive: `frontend/style.css`
- API, WebSocket, event handler: `frontend/app.js`

External CDN, npm yoki build-tool qo‘shmang. Frontend oddiy statik fayl bo‘lib
qolishi kerak.

### Imkoniyat monitorini o'zgartirish

- **Moslash/ball qoidasi:** `opportunity/matcher.py` (`evaluate`), tahlil qoidalari — `parser.py`.
  O'zgartirgach `python3 backend/tests/test_opportunity.py` ishga tushiring.
- **"Mos topildi" nuqtasi:** `engine._save_match()` — Message yoziladi, WS broadcast,
  keyin `delivery.deliver()`. Yangi chiqish kanali (masalan, email) shu yerga ulanadi.
- **Guruhga yuborish rejimi:** `delivery.delivery_mode()` — `BOT_TOKEN` bor va bot klienti ishga
  tushgan bo'lsa `bot`, aks holda `userbot` (xabar foydalanuvchi akkaunti nomidan).
- **Telegram buyruqlari:** `bot_commands.py`; mantiq `service.py`/`store.py` da, buyruqda
  ikkilamang — HTTP router ham shularni chaqiradi.
- **UI:** `frontend/app.js` dagi "Imkoniyatlar (Stage 6)" bo'limi; barcha matn `escapeHtml`
  orqali, havolalar `safeHttpUrl` (faqat http/https).

## 7. Production'ga xavfsiz chiqarish

Avval lokal tekshiruv:

```bash
python3 -m compileall -q backend/app backend/tests
bash -n scripts/setup.sh
bash -n scripts/run_development.sh
node --check frontend/app.js
cd backend && for t in tests/test_*.py; do python3 "$t" || break; done
```

Testlar `fastapi`, `sqlalchemy`, `aiosqlite`, `telethon` o'rnatilgan muhitda haqiqiy DB va
TestClient bilan ishlaydi (`pip install -r backend/requirements.txt`).

**Migratsiya:** Stage 6 yangi `opp_groups` jadvali va `messages.opp_score` ustunini qo'shadi.
`init_db()` → `run_migrations()` ularni birinchi restart'da o'zi, idempotent tarzda yaratadi
(qo'lda hech narsa kerak emas; eski ma'lumot saqlanadi). Restart'dan keyin logda xato
yo'qligini tekshiring.

Production serverda backup:

```bash
cd ~/telegram-focus
cp backend/data/focus.db "backend/data/focus.backup.$(date +%Y%m%d-%H%M%S).db"
```

Kodlarni Mac’dan serverga yuborishdan oldin `.env`, `.session` va `.db` fayllarini
yubormang. Keyin serverda:

```bash
cd ~/telegram-focus
source venv/bin/activate
python -m pip install -r backend/requirements.txt
sudo systemctl restart telegram-focus
sleep 5
curl http://127.0.0.1:8000/api/health
sudo journalctl -u telegram-focus -n 50 --no-pager
```

Healthcheck'dan keyin `curl http://127.0.0.1:8000/api/opp/delivery-mode` rejimni ko'rsatadi
(`userbot` yoki `bot`). `BOT_TOKEN` qo'shsangiz, botni guruhga admin qilib qo'shing va
guruhni UI'da qayta tasdiqlang.

Deploy'dan keyin Mac’da:

```bash
curl -I --max-time 10 http://CURRENT_PUBLIC_IP:8000/
```

AWS Security Group'da TCP `8000` faqat kerakli public IP uchun ochiq bo‘lsin.

## 8. Database va session xavfsizligi

Quyidagilarni ZIP, Git yoki chatga yubormang:

```text
backend/.env
backend/.env.development
backend/telegram_focus.session
backend/data/*.db
```

Database backup'i ham xabar matnlari va shaxsiy ma’lumotlarni o‘z ichiga olishi
mumkin. Uni faqat serverda himoyalangan joyda saqlang.

## 9. Muammo bo‘lsa tekshirish tartibi

### Brauzer ochilmasa

```bash
sudo systemctl status telegram-focus --no-pager
sudo ss -ltnp | grep ':8000'
```

Mac’dan tekshiring, Ubuntu server ichidan public IP'ni tekshirmang:

```bash
curl -v --connect-timeout 10 http://CURRENT_PUBLIC_IP:8000/
```

### API ishlaydi, Telegram xabar kelmaydi

```bash
sudo journalctl -u telegram-focus -n 100 --no-pager
```

`Telethon ulandi; filtrlangan xabarlar tinglanmoqda.` yozuvi bo‘lishi kerak.
Source active ekanini va username/ID to‘g‘ri kiritilganini tekshiring.

### Service ishlamayapti

```bash
sudo systemctl restart telegram-focus
sudo systemctl status telegram-focus --no-pager
sudo journalctl -u telegram-focus -n 100 --no-pager
```

### Eski botlar bilan konflikt

```bash
sudo ss -ltnp
sudo systemctl list-units --type=service --state=running | grep -Ei 'telegram|bot'
```

Har bir servis alohida port, session va database ishlatishi kerak.

## 10. Future agent uchun qisqa checklist

1. `STATUS.md`ni o‘qing.
2. `docs/DEVELOPMENT_GUIDE.md`ni o‘qing.
3. Production `.env` va session'ga tegmang.
4. Development channel va `focus-dev.db`da ishlang.
5. O‘zgarishdan keyin Python/Bash/JavaScript syntax tekshiring.
6. API smoke-test qiling.
7. Production database backup qiling.
8. `systemctl restart`dan keyin log va `/api/health`ni tekshiring.
9. `STATUS.md`ga o‘zgarish va test natijasini yozing.