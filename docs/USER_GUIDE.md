# Telegram Focus — foydalanuvchi qo'llanmasi

Ilova uch bo'limdan iborat: **Telegram**, **Email**, **Imkoniyatlar**. Har bir tab yonidagi
raqam — o'qilmagan xabarlar soni.

## 1. Telegram: javob yozish va arxiv

- **Manba qo'shish:** chapdagi forma — `@username` yoki ID kiriting, turini tanlang.
- **Javob yozish:** xabar kartasida "Javob" tugmasi. Matn yozing yoki fayl qo'shing
  (tanlash, sudrab tashlash yoki Ctrl+V bilan rasm qo'yish). "Hujjat sifatida" — rasmni siqmasdan yuboradi.
- **O'qildi / Arxivga:** kartadagi tugmalar. "Arxiv" tabida qidirish bor, "Qaytarish" xabarni
  kiruvchilarga qaytaradi. Bir nechtasini belgilab "Tanlanganlarni arxivga" bosish mumkin.
- **⚙ Arxiv sozlamalari:** "O'qildi" bosilganda yoki javob yozilganda avtomatik arxivlash;
  N kundan eski o'qilganlarni avto-arxivlash (0 — o'chirilgan).

## 2. Email ulash (Gmail)

Ilova xatlarni **faqat o'qiydi** (yubormaydi, o'chirmaydi).

1. Google hisobingizda **2 bosqichli tasdiqlash** yoqilgan bo'lishi kerak.
2. https://myaccount.google.com/apppasswords ga kiring.
3. Nom kiriting (masalan "Telegram Focus") va **App Password** yarating (16 belgi).
4. Ilovada **Email** tabi → xizmat: **Gmail** (server va port avtomatik to'ladi).
5. Login — to'liq email manzilingiz; Parol — 4-qadamdagi App Password (oddiy parol EMAS).
6. "Hisob qo'shish" — ilova ulanishni tekshiradi. Xatolik bo'lsa matni ko'rsatiladi.

Eslatma: Outlook/Hotmail hozircha qo'llab-quvvatlanmaydi (OAuth2 kerak). Parol serverda
shifrlangan holda saqlanadi va hech qachon qaytarilmaydi.

## 3. Imkoniyat monitorini sozlash

**Imkoniyatlar** tabida 6 bo'lim bor. Tartib bilan:

1. **Profil** — yosh, sinf, IELTS, qiziqishlarni belgilab "Saqlash". Ball shu ma'lumotga qarab hisoblanadi.
2. **Kanallar** — `@kanal`, `t.me/kanal` yoki ID kiriting. Akkauntingiz shu kanalga **a'zo** bo'lishi shart.
   Kanal topilmasa "Dialoglarni yangilash"ni bosing va qayta urining.
3. **Sozlamalar** — monitorni yoqing (toggle), **minimal ball** slayderini tanlang (past — ko'proq
   natija, yuqori — faqat juda mos), "Saqlash".
4. **Sinov** — biror e'lon matnini joylab "Tahlil qilish": ball, mos kelish va rad etish sabablari
   ko'rinadi. Profil/ball sozlamasini shu yerda sinab sozlang.
5. **Lenta** — mos topilgan imkoniyatlar: sarlavha, ball (yashil ≥80, ko'k ≥50), qolgan kun
   (≤3 kun — qizil), yo'nalish teglari, "Havola". "O'qildi" / "Arxivga" tugmalari.
6. **Hozir tekshirish** (Kanallar bo'limi) — ilova o'chiq turgan vaqtda kelgan postlarni tekshiradi.
   Yangi qo'shilgan kanalning eski postlari yuborilmaydi (faqat yangilari).

Yangi postlar real vaqtda tekshiriladi — kutish shart emas.

## 4. Guruhga yuborish

Mos topilgan imkoniyat tasdiqlangan guruhlarga ham yuboriladi.

1. **Imkoniyatlar → Sozlamalar**da **yetkazish rejimi**ni ko'ring:
   - **Bot** (serverda `BOT_TOKEN` bor) — xabar bot nomidan boradi; bot guruhda **administrator** bo'lishi shart.
   - **Userbot** (`BOT_TOKEN` yo'q) — xabar **sizning akkauntingiz nomidan** yuboriladi.
2. **Guruhlar** bo'limi → `@guruh`/link/ID → "Guruh qo'shish" (holat: ● kutilmoqda).
3. "Tasdiqlash" bosing. Bot rejimida bot admin ekani, userbot rejimida yozish huquqi tekshiriladi;
   muammo bo'lsa sababi ko'rsatiladi. Muvaffaqiyatda guruhga "✅ tasdiqlandi" xabari boradi.
4. Guruhni olib tashlash: "O'chirish".

Yuborish muvaffaqiyatsiz bo'lsa ham imkoniyat Lentada saqlanadi.

## 5. Telegram buyruqlari (ixtiyoriy)

Serverda `BOT_TOKEN` va `OWNER_ID` (sizning Telegram ID'ingiz) berilgan bo'lsa, botga shaxsiy
xabarda `/start` yozing — buyruqlar ro'yxati chiqadi (`/monitor_*`, `/group_*`, `/profile`, `/scan_now`).
Bot faqat egasiga javob beradi. Bu qism shart emas — hamma narsa UI orqali ham boshqariladi.

## 6. Muammolar

| Belgi | Sabab / yechim |
|---|---|
| "Telegram mijozi ulanmagan" | Server hali ulanmagan yoki session yo'q — administratorga murojaat qiling |
| "Kanal topilmadi" | Akkaunt kanalga a'zo emas yoki noto'g'ri nom; "Dialoglarni yangilash" |
| "Bot guruhda administrator emas" | Botni guruhda admin qiling, qayta "Tasdiqlash" |
| Lenta bo'sh | Monitor yoqilganmi? Minimal ballni pasaytiring; "Sinov"da matnni tekshiring |
