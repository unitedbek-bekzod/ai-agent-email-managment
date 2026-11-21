import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, desc, or_, and_
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db import AsyncSessionLocal
from app.models import (
    User, EmailAccount, EmailMessage, UserPreference, FollowUpReminder,
    CategoryEnum, PriorityEnum
)
from app.services.email_service import EmailService
from app.services.ai_agent import AIAgentService
from app.bot.bot import bot
from app.bot.keyboards import get_email_detail_keyboard
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logger = logging.getLogger("background_scheduler")
scheduler: Optional[AsyncIOScheduler] = None


async def sync_all_accounts_job(user_id: Optional[int] = None) -> int:
    """Background or on-demand job that checks active email accounts for new emails and analyzes them."""
    logger.info(f"Running email sync job (user_id={user_id})...")
    total_synced_count = 0
    async with AsyncSessionLocal() as session:
        # Fetch active accounts
        stmt = (
            select(EmailAccount)
            .where(EmailAccount.is_active == True)
            .options(selectinload(EmailAccount.user).selectinload(User.preferences))
        )
        if user_id:
            stmt = stmt.where(EmailAccount.user_id == user_id)

        res = await session.execute(stmt)
        accounts = res.scalars().all()

        for acc in accounts:
            # Skip mock test accounts
            if acc.password == "app_password_mock":
                continue

            user = acc.user
            user_pref = user.preferences if user else None

            try:
                raw_emails = await EmailService.fetch_emails(acc, limit=10)
                new_emails = []

                for raw in raw_emails:
                    # Check if already processed
                    chk_stmt = select(EmailMessage).where(EmailMessage.message_id == raw["message_id"])
                    existing = (await session.execute(chk_stmt)).scalars().first()
                    if existing:
                        continue

                    # Analyze new incoming email with AI
                    analysis = await AIAgentService.analyze_email(
                        subject=raw["subject"],
                        body=raw["body_text"],
                        sender=raw["sender_email"],
                        user_preference=user_pref
                    )

                    email_msg = EmailMessage(
                        account_id=acc.id,
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
                    session.add(email_msg)
                    new_emails.append(email_msg)
                    total_synced_count += 1

                acc.last_synced_at = datetime.utcnow()
                await session.commit()

                # Dispatch Telegram Alerts for Urgent / High priority emails
                if new_emails and user and user.telegram_chat_id and bot:
                    notify_urgent_setting = user_pref.notify_urgent if user_pref else True
                    notify_telegram_setting = user_pref.notify_telegram if user_pref else True

                    if notify_telegram_setting:
                        for em in new_emails:
                            # Send alert if Urgent, or if High priority and user enabled urgent notifications
                            if em.priority == PriorityEnum.URGENT or (em.priority == PriorityEnum.HIGH and notify_urgent_setting):
                                await send_telegram_alert(user.telegram_chat_id, em)

            except Exception as e:
                logger.error(f"Error syncing account {acc.email_address}: {e}")

    return total_synced_count


async def send_telegram_alert(chat_id: str, email_msg: EmailMessage):
    """Sends immediate high-priority alert to the user's Telegram."""
    if not bot:
        return

    priority_badge = "🚨 <b>SHOSHILINCH EMAIL! (🔴 Urgent)</b>" if email_msg.priority == PriorityEnum.URGENT else "🟠 <b>MUHIM EMAIL! (Yuqori Prioritet)</b>"
    deadline_info = f"\n⏰ <b>Muddat:</b> {email_msg.detected_deadline}" if email_msg.detected_deadline else ""
    takeaway_info = f"\n🎯 <b>Asosiy mazmun:</b> {email_msg.key_takeaway}\n" if email_msg.key_takeaway else ""

    alert_text = (
        f"{priority_badge}\n\n"
        f"📧 <b>Mavzu:</b> {email_msg.subject}\n"
        f"👤 <b>Kimdan:</b> {email_msg.sender_name} (<code>{email_msg.sender_email}</code>)\n"
        f"🏷️ <b>Kategoriya:</b> {email_msg.category.value}{deadline_info}\n"
        f"{takeaway_info}\n"
        f"📑 <b>AI Xulosasi:</b>\n{email_msg.summary or 'Xulosa tayyorlanmagan'}\n\n"
        f"⚡ <i>Pastdagi tugmalar orqali darhol javob draft tayyorlashingiz yoki eslatma o'rnatishingiz mumkin:</i>"
    )

    try:
        await bot.send_message(
            chat_id=chat_id,
            text=alert_text,
            parse_mode="HTML",
            reply_markup=get_email_detail_keyboard(email_msg.id)
        )
        logger.info(f"Telegram alert sent to {chat_id} for email {email_msg.id}")
    except Exception as e:
        logger.error(f"Failed to send Telegram alert to {chat_id}: {e}")


async def check_due_reminders_job() -> int:
    """Checks for due follow-up reminders and notifies the user via Telegram."""
    processed_count = 0
    async with AsyncSessionLocal() as session:
        now = datetime.utcnow()
        stmt = (
            select(FollowUpReminder)
            .where(
                and_(
                    FollowUpReminder.remind_at <= now,
                    FollowUpReminder.is_completed == False,
                    FollowUpReminder.notified_at.is_(None)
                )
            )
            .options(selectinload(FollowUpReminder.user), selectinload(FollowUpReminder.email))
        )
        res = await session.execute(stmt)
        due_reminders = res.scalars().all()

        for rem in due_reminders:
            user = rem.user
            if user and user.telegram_chat_id and bot:
                rem_email = rem.email
                email_sub = f" (Xat: '{rem_email.subject[:30]}...')" if rem_email else ""
                
                text = (
                    f"⏰ <b>FOLLOW-UP ESLATMA VAQTI KELDI!</b>\n\n"
                    f"📌 <b>Vazifa:</b> {rem.reminder_text}{email_sub}\n"
                    f"🕒 <b>Belgilangan vaqt:</b> {rem.remind_at.strftime('%Y-%m-%d %H:%M')}\n\n"
                    f"<i>Ushbu vazifani bajardingizmi?</i>"
                )

                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Bajarildi deb belgilash",
                            callback_data=f"complete_rem:{rem.id}"
                        )
                    ]
                ])

                try:
                    await bot.send_message(
                        chat_id=user.telegram_chat_id,
                        text=text,
                        parse_mode="HTML",
                        reply_markup=kb
                    )
                    rem.notified_at = now
                    processed_count += 1
                    logger.info(f"Reminder notification sent for reminder {rem.id}")
                except Exception as e:
                    logger.error(f"Failed to send reminder notification: {e}")
            else:
                rem.notified_at = now
                processed_count += 1

        if due_reminders:
            await session.commit()

    return processed_count


def start_scheduler():
    """Initializes and starts the AsyncIOScheduler for background tasks."""
    global scheduler
    if scheduler and scheduler.running:
        return scheduler

    scheduler = AsyncIOScheduler()
    
    # Email sync job (every 2 minutes)
    scheduler.add_job(
        sync_all_accounts_job,
        trigger="interval",
        minutes=getattr(settings, "SYNC_INTERVAL_MINUTES", 2),
        id="sync_emails_job",
        replace_existing=True
    )

    # Reminders checker job (every 60 seconds)
    scheduler.add_job(
        check_due_reminders_job,
        trigger="interval",
        seconds=getattr(settings, "REMINDER_CHECK_INTERVAL_SECONDS", 60),
        id="check_reminders_job",
        replace_existing=True
    )

    scheduler.start()
    logger.info("APScheduler background tasks started (Email sync: 2m, Reminders check: 60s)")
    return scheduler


def stop_scheduler():
    """Gracefully shuts down the background scheduler."""
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler background tasks stopped.")
