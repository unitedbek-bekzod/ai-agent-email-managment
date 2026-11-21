import json
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import httpx

from app.config import settings
from app.models import CategoryEnum, PriorityEnum, ReplyToneEnum, UserPreference

logger = logging.getLogger("ai_agent_service")


class AIAgentService:
    """Core Agentic AI service for Email Management, Summarization, Drafting, and Search."""

    @classmethod
    async def _call_llm(cls, prompt: str, system_prompt: str = "") -> Optional[str]:
        """Calls configured LLM provider (Gemini, OpenAI, or Groq) using HTTP client."""
        # 1. Try Gemini
        if settings.GEMINI_API_KEY:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
                payload = {
                    "contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}],
                    "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024}
                }
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(url, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        candidates = data.get("candidates", [])
                        if candidates and "content" in candidates[0]:
                            parts = candidates[0]["content"].get("parts", [])
                            if parts:
                                return parts[0].get("text", "").strip()
            except Exception as e:
                logger.debug(f"[AIAgentService._call_llm Gemini Error]: {e}")

        # 2. Try OpenAI
        if settings.OPENAI_API_KEY:
            try:
                url = "https://api.openai.com/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": settings.OPENAI_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt or "You are an expert AI Email Assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2
                }
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.debug(f"[AIAgentService._call_llm OpenAI Error]: {e}")

        # 3. Try Groq
        if settings.GROQ_API_KEY:
            try:
                url = "https://api.groq.com/openai/v1/chat/completions"
                headers = {
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    "Content-Type": "application/json"
                }
                payload = {
                    "model": settings.GROQ_MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt or "You are an expert AI Email Assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2
                }
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        return data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                logger.debug(f"[AIAgentService._call_llm Groq Error]: {e}")

        return None

    # -------------------------------------------------------------
    # 1. Smart Email Categorization, Priority, Summary & Action Items
    # -------------------------------------------------------------
    @classmethod
    async def analyze_email(
        cls,
        subject: str,
        body: str,
        sender: str,
        user_preference: Optional[UserPreference] = None
    ) -> Dict[str, Any]:
        """Deep analysis of email: Category, Priority, Key Takeaway, Bullet Summary, Action Items, Deadline, Sentiment."""
        lang = user_preference.preferred_language if user_preference else settings.DEFAULT_LANGUAGE

        system_prompt = f"""You are an elite AI Email Management Agent with 10 years of experience.
Analyze the provided email and output STRICT JSON format without code fences:
{{
  "category": "Work" | "Personal" | "Important" | "Spam / Suspicious" | "Promotions" | "Other",
  "priority": "Urgent" | "High" | "Normal" | "Low",
  "key_takeaway": "1 clear sentence summarizing the most critical point in {lang}",
  "summary": "3 to 4 concise bullet points in {lang} highlighting key facts, requirements, and deadlines",
  "action_suggested": "Short recommended action (e.g. Reply needed, Review document, No action, Urgent investigation)",
  "action_items": ["Array of specific action items to perform"],
  "detected_deadline": "Explicit date/time mentioned or null",
  "sentiment": "Critical" | "Urgent" | "Inquiring" | "Positive" | "Neutral"
}}

Classification criteria:
- Work: client communications, project deadlines, meeting invites, invoices, devops, company tasks.
- Personal: family, friends, casual talks.
- Important: security alerts, banking/finance, password resets, legal, critical server outages.
- Spam / Suspicious: phishing, suspicious links, unknown sender claiming lottery/crypto prizes.
- Promotions: discounts, Black Friday, product sales, marketing newsletters.
- Other: standard automated alerts, social digests.

Priority rules:
- Urgent: needs immediate response within hours (server downtime, account breach alert, urgent blocker).
- High: important business tasks, client questions requiring response today.
- Normal: regular discussions, weekly status.
- Low: newsletters, promotions, FYIs.
"""

        prompt = f"Sender: {sender}\nSubject: {subject}\n\nEmail Body:\n{body[:3500]}"

        llm_response = await cls._call_llm(prompt, system_prompt)
        if llm_response:
            try:
                clean_json = re.sub(r"^```json\s*|\s*```$", "", llm_response.strip(), flags=re.MULTILINE)
                parsed = json.loads(clean_json)

                # Validate category
                category = parsed.get("category", CategoryEnum.OTHER.value)
                if category not in [c.value for c in CategoryEnum]:
                    category = CategoryEnum.OTHER.value

                # Validate priority
                priority = parsed.get("priority", PriorityEnum.NORMAL.value)
                if priority not in [p.value for p in PriorityEnum]:
                    priority = PriorityEnum.NORMAL.value

                action_items = parsed.get("action_items", [])
                if not isinstance(action_items, list):
                    action_items = [str(action_items)]

                return {
                    "category": CategoryEnum(category),
                    "priority": PriorityEnum(priority),
                    "key_takeaway": parsed.get("key_takeaway", subject),
                    "summary": parsed.get("summary", ""),
                    "action_suggested": parsed.get("action_suggested", "Ko'rib chiqish"),
                    "action_items": json.dumps(action_items, ensure_ascii=False),
                    "detected_deadline": parsed.get("detected_deadline"),
                    "sentiment": parsed.get("sentiment", "Neutral")
                }
            except Exception as e:
                logger.debug(f"[AIAgentService.analyze_email parsing error]: {e}")

        # Intelligent Heuristic Fallback Engine
        return cls._heuristic_analyze_email(subject, body, sender, lang)

    @classmethod
    def _heuristic_analyze_email(cls, subject: str, body: str, sender: str, lang: str = "Uzbek") -> Dict[str, Any]:
        """Intelligent heuristic rule-based analyzer when LLM API is unavailable."""
        combined = f"{subject} {body} {sender}".lower()

        # Multi-factor Priority detection
        urgent_keywords = ["urgent", "shoshilinch", "critical", "outage", "down", "emergency", "asap", "alert", "xavfsizlik", "buzilgan", "to'xtadi", "compromised"]
        high_keywords = ["important", "muhim", "deadline", "action required", "review", "invoice", "payment", "to'lov", "shartnoma", "client", "proposal", "taklif"]
        low_keywords = ["newsletter", "unsubscribe", "chegirma", "discount", "sale", "offer", "promotions", "reklama", "digest", "no-reply"]

        if any(k in combined for k in urgent_keywords):
            priority = PriorityEnum.URGENT
            sentiment = "Critical"
        elif any(k in combined for k in high_keywords):
            priority = PriorityEnum.HIGH
            sentiment = "Inquiring"
        elif any(k in combined for k in low_keywords):
            priority = PriorityEnum.LOW
            sentiment = "Neutral"
        else:
            priority = PriorityEnum.NORMAL
            sentiment = "Neutral"

        # Category detection
        spam_keywords = ["lottery", "crypto profit", "congratulations you won", "million dollars", "claim your prize", "wire transfer", "verify your wallet", "yutuq", "btc"]
        promo_keywords = ["sale", "discount", "off", "coupon", "promo", "deal", "store", "shop", "chegirma", "harid", "yangiliklar", "black friday"]
        important_keywords = ["security alert", "password reset", "verification code", "parol", "tasdiqlash kodi", "bank", "hujjat", "contract", "tax", "inc-"]
        work_keywords = ["project", "meeting", "task", "deploy", "server", "api", "database", "jira", "github", "gitlab", "client", "loyiha", "hisobot", "mijoz", "bajarish", "reja", "hamkorlik"]
        personal_keywords = ["salom do'stim", "coffee", "lunch", "family", "qachon ko'rishamiz", "choyxona", "weekend", "dam olish"]

        if any(k in combined for k in spam_keywords):
            category = CategoryEnum.SPAM
            priority = PriorityEnum.LOW
            sentiment = "Neutral"
        elif any(k in combined for k in promo_keywords):
            category = CategoryEnum.PROMOTIONS
            priority = PriorityEnum.LOW
        elif any(k in combined for k in important_keywords):
            category = CategoryEnum.IMPORTANT
            if priority == PriorityEnum.NORMAL:
                priority = PriorityEnum.HIGH
        elif any(k in combined for k in work_keywords):
            category = CategoryEnum.WORK
        elif any(k in combined for k in personal_keywords):
            category = CategoryEnum.PERSONAL
        else:
            category = CategoryEnum.OTHER

        # Detect deadline regex
        deadline = None
        deadline_patterns = [
            r"(dushanba|seshanba|chorshanba|payshanba|juma|shanba|yakshanba)\s+(soat\s+)?\d{1,2}:\d{2}(\s+gacha)?",
            r"(today|tomorrow|friday|monday)\s+(at\s+)?\d{1,2}(:\d{2})?\s*(am|pm)?",
            r"within\s+\d+\s+hours",
            r"\d{1,2}\s+(soat|kun)\s+ichida"
        ]
        for pattern in deadline_patterns:
            match = re.search(pattern, combined)
            if match:
                deadline = match.group(0).capitalize()
                break

        # Action items extraction
        action_items = []
        if priority == PriorityEnum.URGENT:
            action_items.append("Zudlik bilan tizim holatini tekshirish va xavfsizlik choralarini ko'rish")
            action_items.append("Tegishli xodimlarni xabardor qilish")
        elif priority == PriorityEnum.HIGH:
            action_items.append(f"Hujjat yoki taklifni ko'rib chiqish ({deadline or 'bugun'})")
            action_items.append("Yuboruvchiga batafsil javob qaytarish")
        elif category == CategoryEnum.PERSONAL:
            action_items.append("Qulay vaqt bo'yicha javob xati yozish")
        else:
            action_items.append("Ma'lumot uchun saqlash")

        # Sentence-based Summary
        sentences = [s.strip() for s in re.split(r'[.!?\n]+', body) if len(s.strip()) > 15]
        bullets = []
        bullets.append(f"• Asosiy mavzu: {subject}")
        if sentences:
            bullets.append(f"• Mazmun: {sentences[0]}")
            if len(sentences) > 1:
                bullets.append(f"• Tafsilot: {sentences[1]}")
        if deadline:
            bullets.append(f"• Belgilangan muddat: {deadline}")
        bullets.append(f"• Holat: {priority.value} darajali xabar, tavsiya: {action_items[0]}.")

        key_takeaway = sentences[0] if sentences else subject
        action_suggested = "Javob berish zarur" if priority in [PriorityEnum.URGENT, PriorityEnum.HIGH] else "Ko'rib chiqish"

        return {
            "category": category,
            "priority": priority,
            "key_takeaway": key_takeaway,
            "summary": "\n".join(bullets[:4]),
            "action_suggested": action_suggested,
            "action_items": json.dumps(action_items, ensure_ascii=False),
            "detected_deadline": deadline,
            "sentiment": sentiment
        }

    # -------------------------------------------------------------
    # 2. Smart Reply Generator (Professional, Friendly, Short, Detailed)
    # -------------------------------------------------------------
    @classmethod
    async def generate_reply(
        cls,
        subject: str,
        body: str,
        sender_name: str,
        sender_email: str,
        tone: ReplyToneEnum = ReplyToneEnum.PROFESSIONAL,
        user_preference: Optional[UserPreference] = None
    ) -> str:
        """Generates contextual draft reply matching requested tone, persona, and user memory."""
        lang = user_preference.preferred_language if user_preference else settings.DEFAULT_LANGUAGE
        custom_instructions = user_preference.custom_instructions if user_preference else ""
        signature = user_preference.signature if (user_preference and user_preference.signature) else "Hurmat bilan,\nAI Email Agent"

        tone_guidelines = {
            ReplyToneEnum.PROFESSIONAL: "Rasmiy, xushmuomala, aniq va ishbilarmonlik etikasiga to'liq mos keladigan uslub.",
            ReplyToneEnum.FRIENDLY: "Samimiy, do'stona, iliq va hamkorlikka ochiq uslub.",
            ReplyToneEnum.SHORT: "Juda lo'nda, 1-2 jumlali, vaqtni tejovchi va aniq javob.",
            ReplyToneEnum.DETAILED: "Batafsil, qadam-baqadam yoritilgan, barcha savollarga to'liq tushuntirish beruvchi javob."
        }

        system_prompt = f"""You are an elite AI Email Assistant with 10 years of enterprise experience.
Generate a draft email reply in {lang}.
Tone: {tone.value} — {tone_guidelines.get(tone, "")}
User Custom Instructions: {custom_instructions}

Rules:
- Write ONLY the body text of the reply.
- Address the sender appropriately ({sender_name or sender_email}).
- Keep formatting clean and natural.
- End with the signature: {signature}
"""

        prompt = f"Original Email:\nFrom: {sender_name} <{sender_email}>\nSubject: {subject}\nBody:\n{body[:3000]}"

        llm_response = await cls._call_llm(prompt, system_prompt)
        if llm_response:
            return llm_response.strip()

        # Heuristic / Template-based Generator Fallback
        return cls._heuristic_reply_generator(subject, sender_name, tone, lang, signature)

    @classmethod
    def _heuristic_reply_generator(
        cls,
        subject: str,
        sender_name: str,
        tone: ReplyToneEnum,
        lang: str = "Uzbek",
        signature: str = "Hurmat bilan,\nAI Email Agent"
    ) -> str:
        name = sender_name.strip() if sender_name else "Hamkor"

        if tone == ReplyToneEnum.PROFESSIONAL:
            return (
                f"Assalomu alaykum, {name}.\n\n"
                f"'{subject}' mavzusidagi xatingizni oldim va ko'rib chiqdim. "
                f"Bildirilgan masalalar bo'yicha kerakli ma'lumotlarni tayyorlab, "
                f"yaqin vaqt ichida sizga to'liq javob qaytaraman.\n\n"
                f"{signature}"
            )
        elif tone == ReplyToneEnum.FRIENDLY:
            return (
                f"Salom, {name}!\n\n"
                f"Xatingiz uchun katta rahmat! Mavzuni o'rganib chiqyapman. "
                f"Hammasini tez orada kelishib olamiz deb umid qilaman. "
                f"Agar shoshilinch bo'lsa, xabar qoldiring!\n\n"
                f"Ehtirom bilan,\nKuningiz xayrli o'tsin!"
            )
        elif tone == ReplyToneEnum.SHORT:
            return (
                f"Assalomu alaykum. Xatingiz qabul qilindi. Tez orada ko'rib chiqib aloqaga chiqaman. Rahmat!"
            )
        else:  # Detailed
            return (
                f"Assalomu alaykum, {name}.\n\n"
                f"'{subject}' bo'yicha yuborgan xatingiz uchun tashakkur. Quyidagi punktlar bo'yicha ish olib borilmoqda:\n"
                f"1. Taqdim etilgan ma'lumotlar va so'rovlar to'liq qayd etildi.\n"
                f"2. Kerakli hujjatlar va texnik tafsilotlar tekshirilmoqda.\n"
                f"3. Xulosa va keyingi qadamlar bo'yicha yakuniy javob bugun kun oxirigacha taqdim etiladi.\n\n"
                f"Qo'shimcha savollar tug'ilsa, bemalol murojaat qilishingiz mumkin.\n\n"
                f"{signature}"
            )

    # -------------------------------------------------------------
    # 3. Email Search Agent (Natural Language to Structured Query)
    # -------------------------------------------------------------
    @classmethod
    async def parse_search_query(cls, natural_language_query: str) -> Dict[str, Any]:
        """Parses natural language query into structured database search filters."""
        system_prompt = """You are an AI Search Agent for Emails.
Convert the user's natural language search request into strict JSON filter criteria:
{
  "sender": "string or null",
  "keywords": "string or null",
  "category": "Work" | "Personal" | "Important" | "Spam / Suspicious" | "Promotions" | null,
  "priority": "Urgent" | "High" | "Normal" | "Low" | null,
  "days_back": integer or null
}
"""
        prompt = f"Search query: {natural_language_query}"
        llm_response = await cls._call_llm(prompt, system_prompt)

        if llm_response:
            try:
                clean_json = re.sub(r"^```json\s*|\s*```$", "", llm_response.strip(), flags=re.MULTILINE)
                return json.loads(clean_json)
            except Exception:
                pass

        # Heuristic query parser
        q = natural_language_query.lower()
        filters: Dict[str, Any] = {
            "sender": None,
            "keywords": None,
            "category": None,
            "priority": None,
            "days_back": None
        }

        # Check category
        if "work" in q or "ish" in q or "loyiha" in q:
            filters["category"] = CategoryEnum.WORK.value
        elif "important" in q or "muhim" in q:
            filters["category"] = CategoryEnum.IMPORTANT.value
        elif "spam" in q:
            filters["category"] = CategoryEnum.SPAM.value
        elif "promo" in q or "chegirma" in q:
            filters["category"] = CategoryEnum.PROMOTIONS.value
        elif "personal" in q or "shaxsiy" in q:
            filters["category"] = CategoryEnum.PERSONAL.value

        # Check priority
        if "urgent" in q or "shoshilinch" in q:
            filters["priority"] = PriorityEnum.URGENT.value
        elif "high" in q or "yuqori" in q:
            filters["priority"] = PriorityEnum.HIGH.value
        elif "normal" in q or "oddiy" in q:
            filters["priority"] = PriorityEnum.NORMAL.value
        elif "low" in q or "past" in q:
            filters["priority"] = PriorityEnum.LOW.value

        # Check time
        if "yesterday" in q or "kecha" in q:
            filters["days_back"] = 1
        elif "last week" in q or "o'tgan hafta" in q:
            filters["days_back"] = 7
        elif "last month" in q or "o'tgan oy" in q:
            filters["days_back"] = 30

        # Extract sender if common companies or domains are mentioned
        known_senders = ["google", "apple", "microsoft", "github", "gitlab", "telegram", "slack", "techstore", "sardor", "alisher"]
        for s in known_senders:
            if s in q:
                filters["sender"] = s
                break

        # Extract words as keywords, avoiding category/priority stopwords
        stop_words = {
            "find", "show", "search", "emails", "from", "qidir", "top", "xatlar", "xatlarini", "xabar", "xabarlar",
            "urgent", "shoshilinch", "high", "yuqori", "normal", "oddiy", "low", "past",
            "work", "ish", "loyiha", "important", "muhim", "spam", "promo", "chegirma", "personal", "shaxsiy"
        }
        words = [w for w in re.findall(r'\w+', natural_language_query) if len(w) > 2 and w.lower() not in stop_words]
        if words:
            filters["keywords"] = " ".join(words)

        return filters
