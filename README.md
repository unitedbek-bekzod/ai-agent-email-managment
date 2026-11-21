# 🤖 AI Email Management Agent & Telegram Bot

Elektron pochtalarni (Gmail/IMAP) tahlil qiluvchi, ularni avtomatik kategoriyalarga ajratuvchi, prioritetini (shoshilinchlik darajasini) aniqlovchi, uzun xatlarni qisqacha mazmun (summary) ko'rinishida beruvchi, 4 xil tonda aqlli javob draftlarini generatsiya qiluvchi hamda **Telegram Bot** va **Zamonaviy Web Dashboard** orqali boshqariluvchi to'liq agentik AI tizimi.

---

## 🌟 Asosiy Imkoniyatlar (Features)

1. **Smart Email Categorization**:
   - `Work` — Kompaniya vazifalari, texnik monitoring, mijozlar va shartnomalar
   - `Personal` — Do'stlar, oila va shaxsiy suhbatlar
   - `Important` — Xavfsizlik signallari, bank, shoshilinch xabarnomalar
   - `Spam / Suspicious` — Fishing, shubhali fishing havolalari, firibgarlik
   - `Promotions` — Chegirmalar, Black Friday, aksiyalar va marketing
   - `Other` — Boshqa xabarlar

2. **Priority Detection**:
   - 🔴 **Urgent (Shoshilinch)** — Server nosozliklari, bugungi shoshilinch dedlaynlar
   - 🟠 **High (Yuqori)** — Muhim biznes va mijoz murojaatlari
   - 🟡 **Normal (Oddiy)** — Rejali ish yozishmalari
   - ⚪ **Low (Past)** — Reklama, obuna xabarlari

3. **Email Summarizer**:
   - 3-5 sahifalik uzun emailni 3–4 ta punktga qisqartiradi: asosiy mavzu, talab etilgan chora va muhim muddat.

4. **Smart Reply Generator**:
   - 👔 **Professional** — Rasmiy, xushmuomala ishbilarmonlik uslubi
   - 😊 **Friendly (Do'stona)** — Iliq, hamkorlikka ochiq uslub
   - ⚡ **Short (Qisqa)** — Vaqtni tejovchi 1-2 jumlali aniq javob
   - 📋 **Detailed (Batafsil)** — Qadam-baqadam to'liq tushuntirish beruvchi javob

5. **Email Search Agent (Natural Language)**:
   - Tabiiy tildagi so'rovlarni tushunadi: *"Find emails from Google received last week"*, *"Shoshilinch loyiha xatlarini top"*.

6. **Email Action Agent & User Preference Memory**:
   - Foydalanuvchining afzal ko'rgan tili, toni va maxsus qoidalarini doimiy xotirasida saqlab qoladi.

7. **Telegram Bot**:
   - `/start` — Botni ishga tushirish va xush kelibsiz xabari
   - `/inbox` — Oxirgi kelgan barcha email'larni ko'rish va ochish
   - `/important` — Faqat shoshilinch (🔴) va yuqori muhim (🟠) xabarlar
   - `/summary` — Pochta umumiy dayjesti va qilinishi kerak bo'lgan ishlar
   - `/search <matn>` — Tabiiy tildagi aqlli qidiruv
   - `/settings` — Agent sozlamalari va tonni o'zgartirish
   - `/help` — Buyruqlar haqida to'liq ma'lumot
   - Inline tugmalar orqali 1 ta klik bilan AI draft yaratish va eslatma (Follow-up) o'rnatish.

---

## 🚀 O'rnatish va Ishga Tushirish

### 1. Talablar:
- Python 3.11+ yoki `uv` paket menejeri

### 2. O'rnatish:
```bash
# Virtual muhit va kutubxonalarni o'rnatish (uv orqali):
uv sync
```

### 3. Sozlamalar (.env):
`.env` faylida o'z parametrlaringizni belgilang:
```env
TELEGRAM_BOT_TOKEN=your_botfather_token_here
TELEGRAM_BOT_USERNAME=YourBotUsername

# LLM API kaliti (Ixtiyoriy - kiritilsa OpenAI/Gemini/Groq ishlaydi, bo'lmasa o'rnatilgan lokal aqlli AI ishlaydi)
GEMINI_API_KEY=your_gemini_api_key
# yoki
OPENAI_API_KEY=your_openai_api_key
```

### 4. Serverni ishga tushirish:
```bash
uv run python -m app.main
```
Server ishga tushgach:
- 🌐 **Web Dashboard**: `http://localhost:8000`
- 🤖 **Telegram Bot**: avtomatik orqa fonda polling rejimida ishlaydi!
- 🗄️ **SQLite DB**: `email_agent.db` faylida barcha xatlar, draftlar va xotira avtomatik saqlanadi.

---

## 💻 Loyiha Strukturasi

```
email-agent/
├── app/
│   ├── config.py             # Pydantic sozlamalari (.env)
│   ├── db.py                 # Async SQLAlchemy + SQLite
│   ├── models.py             # User, Email, Draft, Preference, Reminder modellari
│   ├── services/
│   │   ├── email_service.py  # IMAP/SMTP client, MIME parser
│   │   ├── ai_agent.py       # Tahlil, prioritet, summary, draft va qidiruv agenti
│   │   └── mock_data.py      # Realistik test xabarlar generatori
│   ├── bot/
│   │   ├── bot.py            # Aiogram 3 bot skeleti
│   │   ├── handlers.py       # Telegram buyruqlari va callbacklar
│   │   └── keyboards.py      # Inline va reply klaviaturalar
│   ├── web/
│   │   ├── routes.py         # FastAPI REST API va sahifalar
│   │   └── templates/        # Zamonaviy Tailwind HTML shablonlari
│   └── main.py               # Asosiy entrypoint
├── pyproject.toml
└── README.md
```
