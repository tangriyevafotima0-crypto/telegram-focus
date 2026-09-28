# Mac'da kichik desktop oyna

## 1. Brauzerda oddiy ochish

Backend ishlayotgan bo‘lsa, Chrome yoki Safari manzil satriga quyidagini
kiriting:

```text
http://SERVER_PUBLIC_IP:8000/
```

## 2. Chrome App mode

1. Chrome'da Telegram Focus manzilini oching.
2. `⋮` menyu → **Cast, save, and share** → **Create shortcut...** ni tanlang.
3. Nomini `Telegram Focus` qiling.
4. **Open as window** ni belgilang.
5. **Create** tugmasini bosing.
6. Yaratilgan shortcut'ni Applications yoki Dock'ka sudrang.

## 3. Terminal buyrug‘i bilan ochish

Frontend URL'ini o‘zgartirib, Mac terminalida:

```bash
open -a "Google Chrome" --args --app="http://SERVER_PUBLIC_IP:8000/"
```

Mac'ni qayta ishga tushirganda ham shu buyruqdan foydalanish mumkin. Alohida
shortcut kerak bo‘lsa, yuqoridagi Chrome menyu usuli qulayroq.

## 4. Lokal `index.html` fayli bilan ishlash

Agar `frontend/index.html` ni Mac'da bevosita ochsangiz:

1. `frontend/app.js` faylida `CONFIGURED_API_BASE_URL` qiymatini
   `http://SERVER_PUBLIC_IP:8000` ga almashtiring.
2. Faylni Chrome'da oching.
3. Kerak bo‘lsa Chrome App mode buyrug‘idan foydalaning:

```bash
open -a "Google Chrome" --args --app="file:///ABSOLUTE/PATH/telegram-focus/frontend/index.html"
```

Server CORS sozlamasidagi `ALLOWED_ORIGINS` lokal file origin uchun har doim
ideal ishlamasligi mumkin. Muammo bo‘lsa, frontend'ni backend orqali ochish
(`http://SERVER_PUBLIC_IP:8000/`) tavsiya qilinadi.