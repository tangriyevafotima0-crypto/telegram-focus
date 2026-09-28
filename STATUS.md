# Telegram Focus — loyiha holati

## Bosqich 1 — Muhitni tayyorlash va AWS sozlash hujjati — 2026-09-18
- Holat: TUGALLANDI
- Yaratilgan fayllar: `backend/requirements.txt`, `backend/.env.example`, `docs/AWS_SETUP.md`, `.gitignore`, `scripts/setup.sh`, `STATUS.md`
- O‘zgartirilgan fayllar: yo‘q
- Sinovdan o‘tkazildimi: QISMAN — `scripts/setup.sh` Bash sintaksisi tekshirildi va paket versiyalari PyPI sahifalaridan tekshirildi; AWS o‘rnatishi, Telegram login'i va systemd ishga tushishi real server/API credentials bo‘lmagani uchun sinab ko‘rilmadi.
- Keyingi bosqichga eslatmalar: `backend/requirements.txt` va `backend/.env.example` tayyor. `scripts/setup.sh` keyingi bosqichlar tugagach to‘liq login/deploy jarayonini bajaradi; hozir `app/telethon_client.py` va `app/main.py` yo‘qligi sabab bu ikki qadamni ogohlantirib o‘tkazadi.
- Ochiq savollar / foydalanuvchidan kerak bo‘lgan narsa: Bosqich 2 uchun Telegram `api_id`, `api_hash` va telefon raqami kerak bo‘ladi; ularni chatga yubormang, serverdagi `backend/.env` orqali kiriting.

### Keyingi bosqich

Bosqich 2 ni boshlash mumkin: `backend/app/database.py`, `backend/app/models.py` va
`backend/app/telethon_client.py` yaratiladi. `MASTER_PROMPT.md` va ushbu `STATUS.md`
birga berilsin.

## Bosqich 2 — Ma’lumotlar bazasi va Telethon mijozi — 2026-09-18
- Holat: TUGALLANDI
- Yaratilgan fayllar: `backend/app/__init__.py`, `backend/app/database.py`, `backend/app/models.py`, `backend/app/telethon_client.py`
- O‘zgartirilgan fayllar: yo‘q
- Sinovdan o‘tkazildimi: QISMAN — Python syntax tekshiruvi bajarildi; real Telegram login'i API credentials va akkaunt mavjud emasligi sabab sinanmadi.
- Keyingi bosqichga eslatmalar: `run_telegram_client()` callback orqali yangi filtrlangan xabar payload'ini uzatadi. Birinchi login terminalda `python -m app.telethon_client` bilan bajariladi.
- Ochiq savollar / foydalanuvchidan kerak bo‘lgan narsa: serverdagi `backend/.env` ga Telegram qiymatlarini kiritish kerak.

## Bosqich 3 — FastAPI backend — 2026-09-18
- Holat: TUGALLANDI
- Yaratilgan fayllar: `backend/app/schemas.py`, `backend/app/routers/__init__.py`, `backend/app/routers/sources.py`, `backend/app/routers/messages.py`, `backend/app/main.py`
- O‘zgartirilgan fayllar: yo‘q
- Sinovdan o‘tkazildimi: HA (lokal smoke-test) — `/api/health`, source CRUD, duplicate validation, message history, read endpoint va frontend static serving tekshirildi. Real AWS/Telegram integratsiyasi sinanmadi.
- Keyingi bosqichga eslatmalar: REST endpointlar `/api/sources`, `/api/messages`; WebSocket `/ws/messages`. Telegram credentials bo‘lmasa ham FastAPI ishga tushadi.
- Ochiq savollar / foydalanuvchidan kerak bo‘lgan narsa: yo‘q.

## Bosqich 4 — Frontend — 2026-09-18
- Holat: TUGALLANDI
- Yaratilgan fayllar: `frontend/index.html`, `frontend/style.css`, `frontend/app.js`
- O‘zgartirilgan fayllar: yo‘q
- Sinovdan o‘tkazildimi: QISMAN — JavaScript syntax tekshirildi; real AWS backend bilan brauzer integratsiyasi AWS server bo‘lmagani sabab sinanmadi.
- Keyingi bosqichga eslatmalar: backend orqali ochilganda API manzili avtomatik olinadi; lokal `file://` rejimida `CONFIGURED_API_BASE_URL` ni AWS IP bilan almashtirish kerak.
- Ochiq savollar / foydalanuvchidan kerak bo‘lgan narsa: yo‘q.

## Bosqich 5 — Integratsiya va ishga tushirish hujjatlari — 2026-09-18
- Holat: QISMAN TUGALLANDI
- Yaratilgan fayllar: `docs/RUN_GUIDE.md`, `docs/MAC_WINDOW_SETUP.md`
- O‘zgartirilgan fayllar: `STATUS.md`
- Sinovdan o‘tkazildimi: QISMAN — lokal backend/static smoke-test bajarildi; AWS serveri, Telegram API credentials va real akkaunt mavjud emasligi sabab production deploy sinanmadi.
- Keyingi bosqichga eslatmalar: serverda `bash scripts/setup.sh` ishga tushiriladi, keyin `sudo systemctl status telegram-focus`, `/api/health` va `/docs` tekshiriladi.
- Ochiq savollar / foydalanuvchidan kerak bo‘lgan narsa: Telegram API qiymatlari faqat serverdagi `backend/.env` ga kiritilsin.

## Development channel — texnik qo‘llanma — 2026-09-18
- Holat: TUGALLANDI
- Yaratilgan fayllar: `docs/DEVELOPMENT_GUIDE.md`, `backend/.env.development.example`, `scripts/run_development.sh`
- O‘zgartirilgan fayllar: `STATUS.md`
- Sinovdan o‘tkazildimi: HA — development script va barcha kod syntax tekshiruvlari bajarildi; development server real Telegram akkaunti bilan ishga tushirilmadi.
- Keyingi bosqichga eslatmalar: development oqimi `127.0.0.1:8001` va `focus-dev.db`dan foydalanadi. Production `8000` port va `focus.db`ga o‘zgarishdan oldin backup shart.
- Ochiq savollar / foydalanuvchidan kerak bo‘lgan narsa: development uchun alohida test Telegram guruhi/kanali va kerak bo‘lsa alohida test akkaunti foydalanuvchi tomonidan yaratiladi.

## Stage 1 — Migratsiya, arxiv, media, kanal poydevori — 2026-09-19
- Holat: BAJARILDI
- MIGRATSIYA KERAK: HA — production `focus.db` da `run_migrations()` avtomatik ishlaydi (create_all'dan keyin, idempotent ALTER TABLE ADD COLUMN). Deploy paytida qo‘lda hech narsa qilish shart emas, lekin birinchi restart'dan keyin loglarda xato yo‘qligini tekshiring.
- O‘zgargan fayllar: `backend/app/database.py`, `backend/app/models.py`, `backend/app/schemas.py`, `backend/app/telethon_client.py`, `backend/app/routers/messages.py`, `.gitignore`
- Yangi fayllar: `backend/app/media.py`, `backend/data/media/.gitkeep`
- Yangi ustunlar: `messages.is_archived, archived_at, reply_to_message_id, chat_id, direction, has_media_file, media_mime, media_name, link_urls, channel`; `sources.kind`. Indeks: `(messages.is_archived, received_at)`.
- Yangi/o‘zgargan endpointlar: `GET /api/messages` (+`archived`, `channel`, `unread_only` query, default xatti-harakat o‘zgarmagan), `GET /api/messages/counts`, `GET /api/media/{message_id}`.
- Sinovdan o‘tkazildimi: HA — eski schema'li vaqtinchalik SQLite'da migratsiya ikki marta ishlatildi (xatosiz, mavjud qator saqlanib qoldi); yangi endpointlar FastAPI TestClient bilan sinaldi (health, messages default/archived/channel/unread_only filtrlari, counts, media 404, sources — barchasi kutilganidek). Real Telegram media yuklash sinalmadi (API credentials yo‘q); kod try/except bilan himoyalangan.
- Keyingi bosqichga eslatmalar: batafsil HANDOFF_1.md'da.

## Stage 2 — Telegram'ga javob yozish — 2026-09-19
- Holat: BAJARILDI
- O'zgargan fayllar: `backend/app/telethon_client.py` (get_client), `backend/app/media.py`
  (safe_tmp_media_path), `backend/app/routers/messages.py` (+POST reply), `frontend/app.js`,
  `frontend/style.css`
- Yangi fayllar: `backend/app/sender.py`
- MUHIM: `python-multipart` requirements.txt'da yo'q, shuning uchun fayl yuklash
  base64 JSON (`files: [{name, mime, data_b64}]`) formatida amalga oshirildi —
  ko'p fayl/multipart kerak bo'lsa, `python-multipart` qo'shishni ko'rib chiqing
  (foydalanuvchi tasdig'i bilan).
- Yangi endpoint: `POST /api/messages/{id}/reply` — {text?, files?: [{name,mime,data_b64}],
  as_document?}. Xatolar: 422 (bo'sh so'rov/noto'g'ri base64), 404 (xabar yoki chat_id yo'q),
  415 (ruxsat etilmagan MIME), 413 (50MB dan katta), 503 (Telegram ulanmagan), 429 (flood wait).
- Sinovdan o'tkazildimi: HA — compileall, node --check, TestClient orqali barcha xato
  holatlari, FakeClient orqali send_message/send_file/albom/FloodWaitError retry mantig'i
  tekshirildi.

## Stage 3 — Arxiv funksiyasi — 2026-09-19
- Holat: BAJARILDI
- O'zgargan fayllar: `backend/app/routers/messages.py` (+archive/unarchive/bulk/settings
  endpointlari, +search), `backend/app/sender.py` (archive_on_reply hook), `backend/app/main.py`
  (auto-archive fon vazifasi), `frontend/index.html` (tab, bulk bar, sozlamalar dialogi),
  `frontend/app.js`, `frontend/style.css`
- Yangi fayllar: `backend/app/settings_store.py` (settings.json, atomik yozuv)
- Schema o'zgarishi: YO'Q (Stage 1'dagi ustunlar ishlatildi)
- Yangi endpointlar: PATCH .../archive, PATCH .../unarchive, POST .../archive-bulk,
  GET/PUT /api/settings/archive; PATCH .../read ga ?archive query qo'shildi;
  GET /api/messages ga ?search qo'shildi.
- Sinovdan o'tkazildimi: HA — TestClient va FakeClient bilan barcha holatlar tekshirildi
  (batafsil HANDOFF_3.md'da).

## Stage 4 — Email bo'limi — 2026-09-19
- Holat: BAJARILDI (real IMAP serverga ulanib sinalmadi; FastAPI/SQLAlchemy muhitda yo'q edi — DB/TestClient sinovi o'tkazilmadi)
- O'zgargan fayllar: `backend/app/{models,database,main,telethon_client}.py`, `routers/{messages,sources}.py`,
  `frontend/{index.html,app.js,style.css}`, `.gitignore`
- Yangi fayllar: `backend/app/{email_crypto,email_client,email_worker}.py`, `routers/email.py`,
  `backend/tests/test_email_{client,crypto,worker_pure}.py`
- Yangi jadval: `email_accounts` (Message sxemasi O'ZGARMADI)
- Yangi endpointlar: GET /api/email/presets; POST/GET /api/email/accounts; PATCH/DELETE /api/email/accounts/{id};
  POST /api/email/accounts/{id}/check-now
- Xavfsizlik: parol shifrlangan (stdlib), API'da qaytmaydi; email HTML hech qachon innerHTML'ga xom qo'yilmaydi.
- Batafsil: HANDOFF_4.md

## Stage 5 — Imkoniyat-aniqlash motori (ufq_monitor ko'chirildi) — 2026-09-19
- Holat: BAJARILDI (real Telegram/IMAP serverga ulanib sinalmadi; DB/TestClient/engine
  sinovlari haqiqiy fastapi+sqlalchemy+aiosqlite+telethon muhitida o'tkazildi — hammasi o'tdi)
- Yangi paket: `backend/app/opportunity/` — `parser.py`, `matcher.py` (eski ufq_monitor botidan
  ko'chirilgan, o'zgarishsiz), `formatting.py` (eski monitor.py'dan), `store.py` (JSON→SQLite
  DB-qatlam), `engine.py` (real-vaqt aniqlash + catch_up tiklash), `resolve.py` (eski bot.py'dan
  resolve_target zanjiri)
- Yangi fayl: `backend/app/routers/opportunity.py` (profil/sozlama/kanal/skan/holat/tahlil API'si)
- Yangi jadvallar: `opp_profile`, `opp_settings`, `opp_channels`, `opp_sent`, `opp_stats`
- Yangi endpointlar: GET/PUT /api/opp/{profile,settings}; POST/GET/DELETE /api/opp/channels;
  POST /api/opp/{refresh-dialogs,scan-now,analyze,import-export}; GET /api/opp/status
- Arxitektura: polling (10 daq) → mavjud NewMessage oqimiga ulanish (polling YO'Q) + ishga
  tushgandagi bir martalik catch_up (tiklash). `main.py` lifespan'ga `opportunity_catchup_task`
  qo'shildi; `telethon_client.py`'ga 1 qatorli try/except chaqiruv (Source oqimidan mustaqil).
- Frontend: HALI YO'Q (Stage 6) — backend/API to'liq tayyor.
- Batafsil: HANDOFF_5.md

## Stage 6 — Guruhga yuborish, Imkoniyatlar UI, yakuniy integratsiya — 2026-09-19
- Holat: BAJARILDI (real Telegram / bot / guruh bilan sinalmadi — FakeClient + haqiqiy SQLite/TestClient bilan sinaldi)
- MIGRATSIYA KERAK: HA — avtomatik. `run_migrations()` birinchi restart'da yaratadi: jadval `opp_groups`,
  ustun `messages.opp_score` (idempotent, mavjud ma'lumot saqlanadi). Qo'lda hech narsa qilinmaydi.
- Yangi fayllar: `backend/app/opportunity/{delivery,service,bot_commands}.py`; testlar
  `backend/tests/test_opportunity_{delivery,bot_and_lifespan}.py`, `test_final_integration.py`;
  `docs/USER_GUIDE.md`
- O'zgargan fayllar: `backend/app/{models,database,main,telethon_client}.py`,
  `opportunity/{engine,store,formatting}.py`, `routers/opportunity.py`, `backend/.env.example`,
  `frontend/{index.html,app.js,style.css}`, `docs/DEVELOPMENT_GUIDE.md`, `tests/test_opportunity_engine.py` (spy imzosi)
- O'zgarmadi: `scripts/*.sh`, systemd, `requirements.txt` (yangi kutubxona yo'q)
- Yangi endpointlar: GET/POST `/api/opp/groups`, POST `/api/opp/groups/{id}/confirm`,
  DELETE `/api/opp/groups/{id}`, GET `/api/opp/delivery-mode`, GET `/api/opp/feed`
- Yangi .env (barchasi ixtiyoriy): `BOT_TOKEN`, `OWNER_ID`

### Yetkazish rejimi
`BOT_TOKEN` bor -> **bot** (xabar bot nomidan; bot guruhda admin bo'lishi shart, yuborishdan oldin qayta tekshiriladi).
Yo'q -> **userbot** (xabar foydalanuvchi akkaunti nomidan; UI'da ogohlantirish ko'rsatiladi).

### Stage 1–6 yakuniy jadval
| Stage | Mazmun | Holat | Migratsiya |
|---|---|---|---|
| 1 | Migratsiya, arxiv ustunlari, media | BAJARILDI | HA (`messages.*`, `sources.kind`) |
| 2 | Telegram'ga javob yozish | BAJARILDI | yo'q |
| 3 | Arxiv funksiyasi | BAJARILDI | yo'q |
| 4 | Email (IMAP, faqat o'qish) | BAJARILDI | HA (`email_accounts`) |
| 5 | Imkoniyat motori (ufq_monitor) | BAJARILDI | HA (`opp_*` 5 jadval) |
| 6 | Guruhga yuborish, UI, integratsiya, hujjat | BAJARILDI | HA (`opp_groups`, `messages.opp_score`) |

### Production deploy tartibi (DEVELOPMENT_GUIDE §7)
1. Lokal: `compileall`, `node --check`, `bash -n scripts/*.sh`, `for t in backend/tests/test_*.py`.
2. Serverda `focus.db` backup: `cp backend/data/focus.db backend/data/focus.backup.$(date +%Y%m%d-%H%M%S).db`
3. Kodni yuborish (`.env`, `*.session`, `*.db`, `data/.email_key` YUBORILMAYDI).
4. `pip install -r backend/requirements.txt` (o'zgarmagan) -> `sudo systemctl restart telegram-focus`.
5. Healthcheck: `curl http://127.0.0.1:8000/api/health`, `.../api/opp/delivery-mode`, `journalctl -u telegram-focus -n 50`.
6. Ixtiyoriy: `BOT_TOKEN`/`OWNER_ID` ni `backend/.env` ga qo'shib restart; botni guruhda admin qiling, guruhni UI'da qayta tasdiqlang.

### Eski botdan ko'chirish jadvali
To'liq jadval — `HANDOFF_6.md`. Eski `ufq_monitor_bot_fixed.zip` Stage 6 da yuklanmagan edi:
`group_*`/`on_match`/`/start`/`owner_only` HANDOFF_5 va STAGE_6_PROMPT tavsifidan tiklandi.
