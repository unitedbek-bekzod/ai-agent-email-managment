import re
import json
from datetime import datetime, timedelta
from typing import Optional
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from sqlalchemy import select, func, desc, or_
from sqlalchemy.orm import selectinload

from app.db import AsyncSessionLocal
from app.models import (
    User, EmailAccount, EmailMessage, EmailDraft, UserPreference, FollowUpReminder,
    CategoryEnum, PriorityEnum, ReplyToneEnum
)
from app.services.ai_agent import AIAgentService
from app.services.action_agent import ActionAgent
from app.services.email_service import EmailService
from app.bot.keyboards import (
    get_main_reply_keyboard,
    get_email_list_keyboard,
    get_email_detail_keyboard,
    get_tone_selection_keyboard,
    get_reminder_quick_keyboard,
    get_settings_keyboard,
    get_connect_provider_keyboard
)

router = Router()


# -------------------------------------------------------------
# FSM States for Connecting Email in Telegram
# -------------------------------------------------------------
class ConnectEmailStates(StatesGroup):
    waiting_for_email = State()
    waiting_for_password = State()
    waiting_for_custom_imap = State()
    waiting_for_custom_smtp = State()


async def get_or_create_user(chat_id: str, username: Optional[str] = None) -> User:
    """Finds or creates user linked to Telegram chat ID."""
    async with AsyncSessionLocal() as session:
        stmt = select(User).where(User.telegram_chat_id == chat_id).options(selectinload(User.preferences))
        res = await session.execute(stmt)
        user = res.scalars().first()

        if not user:
            stmt_demo = select(User).where(User.telegram_chat_id.is_(None)).options(selectinload(User.preferences))
            res_demo = await session.execute(stmt_demo)
            user = res_demo.scalars().first()

            if user:
                user.telegram_chat_id = chat_id
                if username and not user.username:
                    user.username = username
            else:
                user = User(
                    username=username or f"user_{chat_id}",
                    telegram_chat_id=chat_id,
                    email=f"user_{chat_id}@agent.ai"
                )
                session.add(user)
                await session.flush()

                pref = UserPreference(
                    user_id=user.id,
                    preferred_tone=ReplyToneEnum.PROFESSIONAL,
                    preferred_language="Uzbek",
                    max_summary_bullets=4
                )
                session.add(pref)

            await session.commit()
            await session.refresh(user)

        return user


# -------------------------------------------------------------
# 1. /start Command
# -------------------------------------------------------------
@router.message(CommandStart())
async def handle_start(message: Message):
    chat_id = str(message.chat.id)
    user = await get_or_create_user(chat_id, message.from_user.username or message.from_user.first_name)

    async with AsyncSessionLocal() as session:
        res_total = await session.execute(select(func.count(EmailMessage.id)))
        total_count = res_total.scalar() or 0

        res_urgent = await session.execute(
            select(func.count(EmailMessage.id)).where(EmailMessage.priority == PriorityEnum.URGENT)
        )
        urgent_count = res_urgent.scalar() or 0

        acc_stmt = select(EmailAccount).where(EmailAccount.user_id == user.id, EmailAccount.is_active == True)
        acc = (await session.execute(acc_stmt)).scalars().first()

    account_status = f"✅ Ulangan (<code>{acc.email_address}</code>)" if (acc and acc.password != "app_password_mock") else "⚠️ Demo rejim (Haqiqiy email ulanmagan)"

    welcome_text = (
        f"👋 <b>Assalomu alaykum, {message.from_user.first_name}!</b>\n\n"
        f"Men sizning shaxsiy <b>AI Email Management Agent</b>ingizman.\n"
        f"Men xatlaringizni tahlil qilaman, shoshilinchligini aniqlayman, xulosalayman va javob draftlarini tayyorlayman.\n\n"
        f"📬 <b>Pochta holati:</b>\n"
        f"• Akkaunt: {account_status}\n"
        f"• Jami xatlar: <b>{total_count}</b> ta\n"
        f"• 🔴 Shoshilinch xabarlar: <b>{urgent_count}</b> ta\n\n"
        f"<i>Agar haqiqiy emailingizni ulamoqchi bo'lsangiz, <b>'📧 Email Ulash'</b> tugmasini bosing!</i>"
    )

    await message.answer(
        welcome_text,
        parse_mode="HTML",
        reply_markup=get_main_reply_keyboard()
    )


# -------------------------------------------------------------
# 2. Email Connection FSM Flow (/connect or '📧 Email Ulash')
# -------------------------------------------------------------
@router.message(Command("connect"))
@router.message(F.text == "📧 Email Ulash")
async def handle_connect_start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        "📧 <b>Elektron pochtangizni AI Agentga ulash:</b>\n\n"
        "AI Agent sizning pochtangizni xavfsiz IMAP/SMTP orqali o'qiydi, "
        "yangi xatlarni tahlil qiladi va javoblarni tayyorlaydi.\n\n"
        "Qaysi pochta xizmatidan foydalanasiz? Tanlang:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_connect_provider_keyboard())


@router.callback_query(F.data.startswith("connect_prov:"))
async def cb_connect_provider(callback: CallbackQuery, state: FSMContext):
    prov = callback.data.split(":")[1]
    await state.update_data(provider=prov)

    if prov == "gmail":
        await state.update_data(imap_host="imap.gmail.com", imap_port=993, smtp_host="smtp.gmail.com", smtp_port=465)
        guide_text = (
            "🔴 <b>Gmail hisobini ulash:</b>\n\n"
            "Iltimos, <b>Gmail manzilingizni</b> yuboring:\n"
            "<i>Masalan: sizning_ismingiz@gmail.com</i>"
        )
    elif prov == "outlook":
        await state.update_data(imap_host="outlook.office365.com", imap_port=993, smtp_host="smtp.office365.com", smtp_port=587)
        guide_text = (
            "🔵 <b>Outlook hisobini ulash:</b>\n\n"
            "Iltimos, <b>Outlook manzilingizni</b> yuboring:\n"
            "<i>Masalan: name@outlook.com</i>"
        )
    elif prov == "yahoo":
        await state.update_data(imap_host="imap.mail.yahoo.com", imap_port=993, smtp_host="smtp.mail.yahoo.com", smtp_port=465)
        guide_text = (
            "🟣 <b>Yahoo hisobini ulash:</b>\n\n"
            "Iltimos, <b>Yahoo manzilingizni</b> yuboring:\n"
            "<i>Masalan: name@yahoo.com</i>"
        )
    else:
        guide_text = (
            "⚙️ <b>Custom IMAP hisobini ulash:</b>\n\n"
            "Iltimos, email manzilingizni yuboring:"
        )

    await state.set_state(ConnectEmailStates.waiting_for_email)
    await callback.message.edit_text(guide_text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "cancel_connect")
async def cb_cancel_connect(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Email ulash bekor qilindi.")
    await callback.answer()


@router.message(ConnectEmailStates.waiting_for_email)
async def handle_fsm_email_received(message: Message, state: FSMContext):
    email_addr = message.text.strip()
    if "@" not in email_addr or "." not in email_addr:
        await message.answer("⚠️ Iltimos, haqiqiy email manzilini kiriting (masalan: <i>name@gmail.com</i>):", parse_mode="HTML")
        return

    await state.update_data(email_address=email_addr)
    data = await state.get_data()
    prov = data.get("provider", "gmail")

    if prov == "gmail":
        pwd_prompt = (
            f"📧 Qabul qilindi: <code>{email_addr}</code>\n\n"
            f"🔑 <b>Endi Google App Password (16 xonali maxsus parol)ni kiriting:</b>\n\n"
            f"<i>Qanday olish mumkin (1 daqiqa):</i>\n"
            f"1. <a href='https://myaccount.google.com/security'>Google Xavfsizlik</a> sahifasiga kiring va 2-bosqichli tekshiruvni yoqing.\n"
            f"2. <a href='https://myaccount.google.com/apppasswords'>App Passwords (Ilova parollari)</a> sahifasiga o'ting.\n"
            f"3. Ilova nomiga <b>'Email Agent'</b> deb yozib, 16 ta harfli kod yarating.\n"
            f"4. Ushbu 16 ta harfli parolni bu yerga yuboring."
        )
    else:
        pwd_prompt = (
            f"📧 Qabul qilindi: <code>{email_addr}</code>\n\n"
            f"🔑 Iltimos, hisobingiz uchun yaratilgan <b>App Password (Ilova paroli)</b>ni kiriting:"
        )

    await state.set_state(ConnectEmailStates.waiting_for_password)
    await message.answer(pwd_prompt, parse_mode="HTML", disable_web_page_preview=True)


@router.message(ConnectEmailStates.waiting_for_password)
async def handle_fsm_password_received(message: Message, state: FSMContext):
    password = message.text.strip().replace(" ", "")
    data = await state.get_data()
    email_addr = data.get("email_address")
    imap_host = data.get("imap_host", "imap.gmail.com")
    imap_port = data.get("imap_port", 993)
    smtp_host = data.get("smtp_host", "smtp.gmail.com")
    smtp_port = data.get("smtp_port", 465)

    checking_msg = await message.answer("⏳ <i>Pochta serveri bilan bog'lanish tekshirilmoqda...</i>", parse_mode="HTML")

    chat_id = str(message.chat.id)
    user = await get_or_create_user(chat_id, message.from_user.username or message.from_user.first_name)

    clean_password = password.replace(" ", "") if (len(password.replace(" ", "")) == 16 or "gmail" in imap_host.lower()) else password.strip()

    temp_account = EmailAccount(
        user_id=user.id,
        email_address=email_addr,
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=email_addr,
        password=clean_password,
        is_active=True
    )

    success, msg = await EmailService.test_connection(temp_account)

    if not success:
        await state.update_data(
            temp_email=email_addr,
            temp_pwd=clean_password,
            temp_imap_host=imap_host,
            temp_imap_port=imap_port,
            temp_smtp_host=smtp_host,
            temp_smtp_port=smtp_port
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡ Baribir ulash (Sinov / Tekshiruvsiz)",
                    callback_data="force_save_fsm_account"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Qaytadan urinish",
                    callback_data="connect_prov:gmail"
                )
            ]
        ])
        await checking_msg.edit_text(
            f"❌ <b>Ulanishda xatolik yuz berdi:</b>\n\n<code>{msg}</code>\n\n"
            f"💡 <b>Tavsiyalar:</b>\n"
            f"1. <b>Gmail IMAP yoqilganligini tekshiring:</b>\n"
            f"   Gmail -> Sozlamalar -> 'Forwarding and POP/IMAP' bo'limiga kiring va 'Enable IMAP'ni yoqing.\n"
            f"2. <b>App Password:</b> Oddiy parol emas, 16 xonali Ilova Paroli ekanligiga ishonch hosil qiling.\n"
            f"3. <b>Sinov rejimi:</b> Agar internet provayderingizda 993-port cheklangan bo'lsa, pastdagi 'Baribir ulash' tugmasini bosing.",
            parse_mode="HTML",
            reply_markup=kb
        )
        return

    # Connection succeeded! Save to DB
    async with AsyncSessionLocal() as session:
        # Deactivate mock account
        mock_stmt = select(EmailAccount).where(EmailAccount.user_id == user.id, EmailAccount.password == "app_password_mock")
        m_acc = (await session.execute(mock_stmt)).scalars().first()
        if m_acc:
            m_acc.is_active = False

        session.add(temp_account)
        await session.commit()
        await session.refresh(temp_account)

        # Trigger initial sync
        await checking_msg.edit_text("✅ <b>Ulanish muvaffaqiyatli!</b>\n⏳ <i>Oxirgi xatlar yuklanmoqda va AI tahlildan o'tkazilmoqda...</i>", parse_mode="HTML")

        synced_count = 0
        try:
            raw_emails = await EmailService.fetch_emails(temp_account, limit=10)
            pref_stmt = select(UserPreference).where(UserPreference.user_id == user.id)
            user_pref = (await session.execute(pref_stmt)).scalars().first()

            for raw in raw_emails:
                chk = select(EmailMessage).where(EmailMessage.message_id == raw["message_id"])
                if (await session.execute(chk)).scalars().first():
                    continue

                analysis = await AIAgentService.analyze_email(
                    subject=raw["subject"],
                    body=raw["body_text"],
                    sender=raw["sender_email"],
                    user_preference=user_pref
                )

                em = EmailMessage(
                    account_id=temp_account.id,
                    message_id=raw["message_id"],
                    sender_name=raw["sender_name"],
                    sender_email=raw["sender_email"],
                    recipient_email=raw["recipient_email"],
                    subject=raw["subject"],
                    snippet=raw["snippet"],
                    body_text=raw["body_text"],
                    body_html=raw["body_html"],
                    received_at=raw["received_at"],
                    category=analysis["category"],
                    priority=analysis["priority"],
                    key_takeaway=analysis.get("key_takeaway"),
                    summary=analysis["summary"],
                    action_suggested=analysis["action_suggested"],
                    action_items=analysis.get("action_items"),
                    detected_deadline=analysis.get("detected_deadline"),
                    sentiment=analysis.get("sentiment", "Neutral"),
                    has_attachments=raw["has_attachments"],
                    ai_processed_at=datetime.utcnow()
                )
                session.add(em)
                synced_count += 1

            temp_account.last_synced_at = datetime.utcnow()
            await session.commit()
        except Exception as e:
            print(f"[Telegram FSM initial sync error]: {e}")

    await state.clear()
    success_text = (
        f"🎉 <b>Tabriklaymiz!</b>\n\n"
        f"Sizning <code>{email_addr}</code> pochtangiz muvaffaqiyatli ulandi!\n"
        f"• Yuklangan va AI tahlil qilingan xatlar: <b>{synced_count} ta</b>\n\n"
        f"Xabarlaringizni ko'rish uchun <code>/inbox</code> buyrug'ini bosing!"
    )
    await message.answer(success_text, parse_mode="HTML", reply_markup=get_main_reply_keyboard())


@router.callback_query(F.data == "force_save_fsm_account")
async def cb_force_save_fsm_account(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    email_addr = data.get("temp_email") or data.get("email_address")
    password = data.get("temp_pwd")
    imap_host = data.get("temp_imap_host") or data.get("imap_host", "imap.gmail.com")
    imap_port = data.get("temp_imap_port") or data.get("imap_port", 993)
    smtp_host = data.get("temp_smtp_host") or data.get("smtp_host", "smtp.gmail.com")
    smtp_port = data.get("temp_smtp_port") or data.get("smtp_port", 465)

    if not email_addr or not password:
        await callback.message.edit_text("⚠️ Ma'lumotlar topilmadi. Iltimos, /connect orqali qaytadan urinib ko'ring.")
        await state.clear()
        await callback.answer()
        return

    chat_id = str(callback.message.chat.id)
    user = await get_or_create_user(chat_id)

    account = EmailAccount(
        user_id=user.id,
        email_address=email_addr,
        imap_host=imap_host,
        imap_port=imap_port,
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        username=email_addr,
        password=password,
        is_active=True
    )

    async with AsyncSessionLocal() as session:
        mock_stmt = select(EmailAccount).where(EmailAccount.user_id == user.id, EmailAccount.password == "app_password_mock")
        m_acc = (await session.execute(mock_stmt)).scalars().first()
        if m_acc:
            m_acc.is_active = False

        session.add(account)
        await session.commit()

    await state.clear()
    await callback.message.edit_text(
        f"🎉 <b>Tabriklaymiz!</b>\n\n"
        f"Sizning <code>{email_addr}</code> pochtangiz muvaffaqiyatli saqlandi (Sinov / Tekshiruvsiz rejimida).\n\n"
        f"Xabarlaringizni ko'rish uchun <code>/inbox</code> buyrug'ini bosing!",
        parse_mode="HTML"
    )
    await callback.answer()


# -------------------------------------------------------------
# 2.5 /sync Command
# -------------------------------------------------------------
@router.message(Command("sync"))
@router.message(F.text == "🔄 Sinxronlash")
async def handle_sync_command(message: Message):
    chat_id = str(message.chat.id)
    user = await get_or_create_user(chat_id)

    status_msg = await message.answer(
        "🔄 <i>Pochtadagi yangi xatlar tekshirilmoqda va AI tahlildan o'tkazilmoqda...</i>",
        parse_mode="HTML"
    )

    from app.services.scheduler import sync_all_accounts_job
    try:
        new_synced = await sync_all_accounts_job(user_id=user.id)
        if new_synced > 0:
            ans = (
                f"✅ <b>Sinxronizatsiya muvaffaqiyatli yakunlandi!</b>\n\n"
                f"• Yangi kelgan va AI tahlildan o'tgan xatlar: <b>{new_synced} ta</b>\n\n"
                f"Xatlarni ko'rish uchun <code>/inbox</code> yoki <code>/important</code> buyrug'ini bosing."
            )
        else:
            ans = (
                "✅ <b>Pochta sinxronlandi.</b>\n\n"
                "Yangi o'qilmagan xatlar mavjud emas. Barcha hisoblaringiz yangilangan holatda."
            )
        await status_msg.edit_text(ans, parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Sinxronizatsiya jarayonida xatolik yuz berdi: {e}")


# -------------------------------------------------------------
# 3. /inbox Command
# -------------------------------------------------------------
@router.message(Command("inbox"))
@router.message(F.text == "📥 Inbox")
async def handle_inbox(message: Message):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(EmailMessage)
            .order_by(desc(EmailMessage.received_at))
            .limit(8)
        )
        res = await session.execute(stmt)
        emails = res.scalars().all()

    if not emails:
        await message.answer("📭 Hozircha sizning pochtangizda xatlar mavjud emas.")
        return

    text = "📥 <b>Oxirgi kelgan xatlar (Inbox):</b>\n\n"
    for i, em in enumerate(emails, 1):
        p_badge = {"Urgent": "🔴", "High": "🟠", "Normal": "🟡", "Low": "⚪"}.get(em.priority.value, "✉️")
        date_str = em.received_at.strftime("%d.%m %H:%M")
        text += (
            f"<b>{i}. {p_badge} [{em.category.value}]</b> {em.subject}\n"
            f"   👤 Kimdan: <i>{em.sender_name or em.sender_email}</i>\n"
            f"   🕒 {date_str}\n\n"
        )

    text += "<i>Xatni to'liq ko'rish yoki AI javob tayyorlash uchun pastdagi tugmani bosing:</i>"
    await message.answer(text, parse_mode="HTML", reply_markup=get_email_list_keyboard(emails))


# -------------------------------------------------------------
# 4. /important Command
# -------------------------------------------------------------
@router.message(Command("important"))
@router.message(F.text == "⭐ Muhim (Important)")
async def handle_important(message: Message):
    async with AsyncSessionLocal() as session:
        stmt = (
            select(EmailMessage)
            .where(or_(EmailMessage.priority == PriorityEnum.URGENT, EmailMessage.priority == PriorityEnum.HIGH))
            .order_by(desc(EmailMessage.received_at))
            .limit(8)
        )
        res = await session.execute(stmt)
        emails = res.scalars().all()

    if not emails:
        await message.answer("🎉 Hozircha shoshilinch yoki yuqori muhimlikdagi xatlar yo'q! Hammasi nazorat ostida.")
        return

    text = "⭐ <b>Muhim va Shoshilinch xabarlar:</b>\n\n"
    for i, em in enumerate(emails, 1):
        p_badge = "🔴 Shoshilinch" if em.priority == PriorityEnum.URGENT else "🟠 Yuqori"
        text += (
            f"<b>{i}. {p_badge} | {em.category.value}</b>\n"
            f"   📌 {em.subject}\n"
            f"   👤 {em.sender_name or em.sender_email}\n\n"
        )

    text += "<i>Kerakli xatni ochish uchun tugmani tanlang:</i>"
    await message.answer(text, parse_mode="HTML", reply_markup=get_email_list_keyboard(emails))


# -------------------------------------------------------------
# 5. /summary Command
# -------------------------------------------------------------
@router.message(Command("summary"))
@router.message(F.text == "📊 Xulosa (Summary)")
async def handle_summary(message: Message):
    async with AsyncSessionLocal() as session:
        stmt = select(EmailMessage).order_by(desc(EmailMessage.received_at)).limit(10)
        res = await session.execute(stmt)
        recent_emails = res.scalars().all()

        total = len(recent_emails)
        urgent = sum(1 for e in recent_emails if e.priority == PriorityEnum.URGENT)
        work = sum(1 for e in recent_emails if e.category == CategoryEnum.WORK)
        personal = sum(1 for e in recent_emails if e.category == CategoryEnum.PERSONAL)
        promo = sum(1 for e in recent_emails if e.category == CategoryEnum.PROMOTIONS)

    text = (
        f"📊 <b>Inbox Umumiy Tahlili va Xulosa:</b>\n\n"
        f"• Oxirgi tahlil qilingan xatlar: <b>{total} ta</b>\n"
        f"• 🔴 Zudlik bilan e'tibor talab etiladi: <b>{urgent} ta</b>\n"
        f"• 💼 Ishga oid xatlar: <b>{work} ta</b>\n"
        f"• 👤 Shaxsiy: <b>{personal} ta</b>\n"
        f"• 🛍️ Chegirma va aksiyalar: <b>{promo} ta</b>\n\n"
        f"⚡ <b>Tavsiya etilgan harakatlar:</b>\n"
    )

    action_items = [e for e in recent_emails if e.priority in [PriorityEnum.URGENT, PriorityEnum.HIGH]]
    if action_items:
        for item in action_items[:3]:
            text += f"• <b>{item.sender_name}:</b> {item.subject[:40]}... (Tavsiya: {item.action_suggested})\n"
    else:
        text += "• Hozirda hech qanday shoshilinch topshiriq yo'q. Barcha xabarlar o'z vaqtida ko'rib chiqilgan.\n"

    await message.answer(text, parse_mode="HTML")


# -------------------------------------------------------------
# 6. /search Command & Natural Language Query
# -------------------------------------------------------------
@router.message(Command("search"))
async def handle_search_command(message: Message):
    query = message.text.replace("/search", "").strip()
    if not query:
        await message.answer(
            "🔍 <b>Email qidirish:</b>\n"
            "Iltimos, qidiruv so'rovingizni yozing.\n"
            "<i>Masalan:</i>\n"
            "• <code>/search Google dan kelgan xatlar</code>\n"
            "• <code>/search shoshilinch xabarlar</code>\n"
            "• <code>/search Shartnoma</code>",
            parse_mode="HTML"
        )
        return

    await execute_search(message, query)


@router.message(F.text == "🔍 Qidiruv (Search)")
async def handle_search_button(message: Message):
    await message.answer(
        "🔍 <b>AI Qidiruv:</b> Qidirmoqchi bo'lgan ma'lumotingizni erkin tilda yozing:\n"
        "<i>Masalan: 'Google xatlarini ko'rsat' yoki 'O'tgan haftadagi shartnomalar'</i>",
        parse_mode="HTML"
    )


async def execute_search(message: Message, query_text: str):
    filters = await AIAgentService.parse_search_query(query_text)
    
    async with AsyncSessionLocal() as session:
        query = select(EmailMessage)

        if filters.get("category"):
            query = query.where(EmailMessage.category == CategoryEnum(filters["category"]))
        if filters.get("priority"):
            query = query.where(EmailMessage.priority == PriorityEnum(filters["priority"]))
        if filters.get("sender"):
            s = f"%{filters['sender']}%"
            query = query.where(or_(EmailMessage.sender_name.ilike(s), EmailMessage.sender_email.ilike(s)))
        if filters.get("keywords"):
            for w in filters["keywords"].split():
                k = f"%{w}%"
                query = query.where(or_(EmailMessage.subject.ilike(k), EmailMessage.body_text.ilike(k)))
        if filters.get("days_back"):
            cutoff = datetime.utcnow() - timedelta(days=filters["days_back"])
            query = query.where(EmailMessage.received_at >= cutoff)

        query = query.order_by(desc(EmailMessage.received_at)).limit(6)
        res = await session.execute(query)
        results = res.scalars().all()

    if not results:
        await message.answer(f"🔍 '{query_text}' bo'yicha hech qanday xat topilmadi.")
        return

    text = f"🔍 <b>Qidiruv natijalari ('{query_text}'):</b>\n\n"
    for i, em in enumerate(results, 1):
        text += f"{i}. [{em.category.value}] <b>{em.subject}</b> ({em.sender_name})\n"

    await message.answer(text, parse_mode="HTML", reply_markup=get_email_list_keyboard(results))


# -------------------------------------------------------------
# 7. /settings Command
# -------------------------------------------------------------
@router.message(Command("settings"))
@router.message(F.text == "⚙️ Sozlamalar")
async def handle_settings(message: Message):
    chat_id = str(message.chat.id)
    user = await get_or_create_user(chat_id)

    async with AsyncSessionLocal() as session:
        stmt = select(UserPreference).where(UserPreference.user_id == user.id)
        res = await session.execute(stmt)
        pref = res.scalars().first()

    tone = pref.preferred_tone.value if pref else "Professional"
    lang = pref.preferred_language if pref else "Uzbek"
    notify = pref.notify_urgent if pref else True

    text = (
        f"⚙️ <b>AI Agent Sozlamalari & Xotirasi (User Memory):</b>\n\n"
        f"• 👔 <b>Afzal ko'rilgan javob toni:</b> {tone}\n"
        f"• 🌐 <b>Muloqot tili:</b> {lang}\n"
        f"• 📑 <b>Xulosa punktlari soni:</b> {pref.max_summary_bullets if pref else 4} ta\n"
        f"• 🔔 <b>Shoshilinch xabarnomalar:</b> {'Yoqilgan' if notify else 'O\'chirilgan'}\n\n"
        f"<i>O'zgartirish uchun kerakli tugmani bosing:</i>"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=get_settings_keyboard(tone, lang, notify))


# -------------------------------------------------------------
# 8. /help Command
# -------------------------------------------------------------
@router.message(Command("help"))
@router.message(F.text == "ℹ️ Yordam")
async def handle_help(message: Message):
    text = (
        "📖 <b>AI Email Agent Qo'llanmasi:</b>\n\n"
        "• <code>/inbox</code> — Oxirgi kelgan xatlarni ko'rish va ochish\n"
        "• <code>/important</code> — Faqat shoshilinch (🔴) va muhim (🟠) xatlar\n"
        "• <code>/sync</code> — Pochtani zudlik bilan sinxronlash va yangi xatlarni AI tahlil qilish\n"
        "• <code>/summary</code> — Umumiy pochta dayjesti va qilinishi kerak bo'lgan ishlar\n"
        "• <code>/search &lt;matn&gt;</code> — Tabiiy tilda aqlli qidiruv\n"
        "• <code>/connect</code> — Yangi email hisobini ulash (Gmail/Outlook/IMAP)\n"
        "• <code>/reminders</code> — Faol Follow-up eslatmalarni ko'rish\n"
        "• <code>/settings</code> — Agent sozlamalari va tonni o'zgartirish\n"
        "• <code>/help</code> — Ushbu yordam xabari\n\n"
        "💡 <b>Agent bilan suhbat:</b>\n"
        "Siz botga to'g'ridan-to'g'ri tabiiy tilda buyruq yozishingiz mumkin, masalan:\n"
        "<i>'Sardor Rahimovning xatiga professional javob tayyorla va eslatma qo'y'</i>"
    )
    await message.answer(text, parse_mode="HTML")


# -------------------------------------------------------------
# 9. Follow-up Reminders Command
# -------------------------------------------------------------
@router.message(Command("reminders"))
@router.message(F.text == "⏰ Eslatmalar")
async def handle_reminders_list(message: Message):
    chat_id = str(message.chat.id)
    user = await get_or_create_user(chat_id)

    async with AsyncSessionLocal() as session:
        stmt = (
            select(FollowUpReminder)
            .where(FollowUpReminder.user_id == user.id)
            .order_by(FollowUpReminder.remind_at)
        )
        res = await session.execute(stmt)
        reminders = res.scalars().all()

    if not reminders:
        await message.answer("⏰ Sizda hali faol Follow-up eslatmalar yo'q. Biror xatni ochib eslatma qo'yishingiz mumkin.")
        return

    text = "⏰ <b>Sizning Follow-up eslatmalaringiz:</b>\n\n"
    buttons = []
    for r in reminders:
        status = "✅ Bajarildi" if r.is_completed else "⏳ Kutilmoqda"
        time_str = r.remind_at.strftime("%Y-%m-%d %H:%M")
        text += f"• <b>{r.reminder_text}</b>\n  🕒 {time_str} | {status}\n\n"
        if not r.is_completed:
            short_title = r.reminder_text[:28] + ("..." if len(r.reminder_text) > 28 else "")
            buttons.append([
                InlineKeyboardButton(
                    text=f"✅ {short_title} - Bajarildi",
                    callback_data=f"complete_rem:{r.id}"
                )
            ])

    kb = InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None
    await message.answer(text, parse_mode="HTML", reply_markup=kb)


@router.callback_query(F.data.startswith("complete_rem:"))
async def cb_complete_reminder_from_alert(callback: CallbackQuery):
    rem_id = int(callback.data.split(":")[1])
    async with AsyncSessionLocal() as session:
        stmt = select(FollowUpReminder).where(FollowUpReminder.id == rem_id)
        rem = (await session.execute(stmt)).scalars().first()
        if rem:
            rem.is_completed = True
            await session.commit()
            task_text = rem.reminder_text
        else:
            task_text = "Eslatma"

    await callback.message.edit_text(
        f"✅ <b>Eslatma bajarildi deb belgilandi!</b>\n\n📌 <i>{task_text}</i>",
        parse_mode="HTML"
    )
    await callback.answer("Bajarildi deb belgilandi! ✅")


# -------------------------------------------------------------
# 10. Callback Query Handlers (Interactive UI)
# -------------------------------------------------------------
@router.callback_query(F.data.startswith("view_email:"))
async def cb_view_email(callback: CallbackQuery):
    email_id = int(callback.data.split(":")[1])

    async with AsyncSessionLocal() as session:
        stmt = select(EmailMessage).where(EmailMessage.id == email_id)
        res = await session.execute(stmt)
        em = res.scalars().first()

    if not em:
        await callback.answer("Xat topilmadi!", show_alert=True)
        return

    p_badge = {"Urgent": "🔴 Shoshilinch", "High": "🟠 Yuqori", "Normal": "🟡 O'rtacha", "Low": "⚪ Past"}.get(em.priority.value, "Normal")
    date_str = em.received_at.strftime("%Y-%m-%d %H:%M")

    deadline_str = f"\n⏰ <b>Muddat:</b> {em.detected_deadline}" if em.detected_deadline else ""
    takeaway_str = f"\n🎯 <b>Asosiy Mazmun:</b> {em.key_takeaway}\n" if em.key_takeaway else ""

    text = (
        f"📧 <b>{em.subject}</b>\n\n"
        f"👤 <b>Kimdan:</b> {em.sender_name} (<code>{em.sender_email}</code>)\n"
        f"🕒 <b>Vaqti:</b> {date_str}\n"
        f"🏷️ <b>Kategoriya:</b> {em.category.value}\n"
        f"⚡ <b>Prioritet:</b> {p_badge}{deadline_str}\n"
        f"{takeaway_str}\n"
        f"📑 <b>AI Xulosasi:</b>\n{em.summary or 'Xulosa tayyorlanmagan'}\n\n"
        f"📜 <b>Xat matni:</b>\n"
        f"<i>{em.body_text[:500]}...</i>"
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=get_email_detail_keyboard(em.id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("draft_tone_select:"))
async def cb_draft_tone_select(callback: CallbackQuery):
    email_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "✍️ <b>Qaysi tonda javob draft tayyorlaymiz?</b>\n"
        "AI Agent kerakli uslubda mukammal javob matnini generatsiya qiladi:",
        parse_mode="HTML",
        reply_markup=get_tone_selection_keyboard(email_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("gen_draft:"))
async def cb_generate_draft(callback: CallbackQuery):
    parts = callback.data.split(":")
    email_id = int(parts[1])
    tone_str = parts[2]
    tone = ReplyToneEnum(tone_str)

    await callback.answer("AI javob tayyorlamoqda... ⏳")

    async with AsyncSessionLocal() as session:
        stmt = select(EmailMessage).where(EmailMessage.id == email_id)
        res = await session.execute(stmt)
        em = res.scalars().first()

        if not em:
            await callback.message.answer("Xat topilmadi.")
            return

        chat_id = str(callback.message.chat.id)
        user_stmt = select(User).where(User.telegram_chat_id == chat_id).options(selectinload(User.preferences))
        user = (await session.execute(user_stmt)).scalars().first()
        pref = user.preferences if user else None

        draft_text = await AIAgentService.generate_reply(
            subject=em.subject,
            body=em.body_text,
            sender_name=em.sender_name,
            sender_email=em.sender_email,
            tone=tone,
            user_preference=pref
        )

        draft = EmailDraft(
            email_id=em.id,
            tone=tone,
            subject=f"Re: {em.subject}",
            body=draft_text
        )
        session.add(draft)
        await session.commit()

    reply_msg = (
        f"✅ <b>AI tomonidan tayyorlangan javob ({tone.value} ton):</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<code>{draft_text}</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"<i>Ushbu draft veb-dashboardda saqlandi. Veb-sayt orqali to'g'ridan-to'g'ri jo'natishingiz mumkin.</i>"
    )

    await callback.message.answer(
        reply_msg,
        parse_mode="HTML",
        reply_markup=get_email_detail_keyboard(email_id)
    )


@router.callback_query(F.data.startswith("summarize_email:"))
async def cb_summarize_email(callback: CallbackQuery):
    email_id = int(callback.data.split(":")[1])

    async with AsyncSessionLocal() as session:
        stmt = select(EmailMessage).where(EmailMessage.id == email_id)
        res = await session.execute(stmt)
        em = res.scalars().first()

    if not em:
        await callback.answer("Xat topilmadi!")
        return

    text = (
        f"📑 <b>AI Xulosasi: '{em.subject}'</b>\n\n"
        f"{em.summary or 'Xulosa topilmadi.'}\n\n"
        f"🎯 <b>Tavsiya etilgan harakat:</b> {em.action_suggested or 'Ko‘rib chiqish'}"
    )
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("remind_quick_menu:"))
async def cb_remind_quick_menu(callback: CallbackQuery):
    email_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "⏰ <b>Follow-up eslatma muddatini tanlang:</b>",
        parse_mode="HTML",
        reply_markup=get_reminder_quick_keyboard(email_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("set_rem_hrs:"))
async def cb_set_reminder_hours(callback: CallbackQuery):
    parts = callback.data.split(":")
    email_id = int(parts[1])
    hours = int(parts[2])

    chat_id = str(callback.message.chat.id)
    user = await get_or_create_user(chat_id)

    async with AsyncSessionLocal() as session:
        stmt = select(EmailMessage).where(EmailMessage.id == email_id)
        em = (await session.execute(stmt)).scalars().first()

        due_time = datetime.utcnow() + timedelta(hours=hours)
        reminder = FollowUpReminder(
            user_id=user.id,
            email_id=em.id if em else None,
            reminder_text=f"Javob berish: '{em.subject[:35]}...'" if em else "Follow-up eslatma",
            remind_at=due_time
        )
        session.add(reminder)
        await session.commit()

    await callback.answer(f"Follow-up eslatma {hours} soatga muvaffaqiyatli o'rnatildi! ⏰", show_alert=True)
    if em:
        await cb_view_email(callback)


@router.callback_query(F.data.startswith("set_pref:"))
async def cb_set_preference(callback: CallbackQuery):
    parts = callback.data.split(":")
    pref_type = parts[1]

    chat_id = str(callback.message.chat.id)
    user = await get_or_create_user(chat_id)

    async with AsyncSessionLocal() as session:
        stmt = select(UserPreference).where(UserPreference.user_id == user.id)
        pref = (await session.execute(stmt)).scalars().first()
        if not pref:
            pref = UserPreference(user_id=user.id)
            session.add(pref)

        if pref_type == "tone":
            pref.preferred_tone = ReplyToneEnum(parts[2])
        elif pref_type == "lang":
            pref.preferred_language = parts[2]
        elif pref_type == "notify_toggle":
            pref.notify_urgent = not pref.notify_urgent

        await session.commit()
        await session.refresh(pref)

        tone = pref.preferred_tone.value
        lang = pref.preferred_language
        notify = pref.notify_urgent

    text = (
        f"⚙️ <b>AI Agent Sozlamalari & Xotirasi (User Memory):</b>\n\n"
        f"• 👔 <b>Afzal ko'rilgan javob toni:</b> {tone}\n"
        f"• 🌐 <b>Muloqot tili:</b> {lang}\n"
        f"• 📑 <b>Xulosa punktlari soni:</b> {pref.max_summary_bullets} ta\n"
        f"• 🔔 <b>Shoshilinch xabarnomalar:</b> {'Yoqilgan' if notify else 'O\'chirilgan'}\n\n"
        f"<i>O'zgartirish uchun kerakli tugmani bosing:</i>"
    )
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=get_settings_keyboard(tone, lang, notify))
    await callback.answer("Sozlamalar saqlandi!")


@router.callback_query(F.data == "back_to_inbox")
async def cb_back_to_inbox(callback: CallbackQuery):
    await handle_inbox(callback.message)
    await callback.answer()


# -------------------------------------------------------------
# 11. Natural Language Agent Processing (Action Agent)
# -------------------------------------------------------------
@router.message(F.text)
async def handle_natural_language_text(message: Message):
    text = message.text.strip()
    chat_id = str(message.chat.id)
    user = await get_or_create_user(chat_id, message.from_user.username or message.from_user.first_name)

    async with AsyncSessionLocal() as session:
        result = await ActionAgent.process_user_instruction(user, text, session)

    reply_text = result.get("response_message") or "Buyruq bajarildi."
    await message.answer(reply_text, parse_mode="HTML")
