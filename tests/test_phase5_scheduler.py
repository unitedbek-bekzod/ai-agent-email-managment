import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath("."))
from datetime import datetime, timedelta
from sqlalchemy import select, and_

from app.db import init_db, AsyncSessionLocal
from app.models import (
    User, EmailAccount, EmailMessage, FollowUpReminder, UserPreference,
    CategoryEnum, PriorityEnum, ReplyToneEnum
)
from app.services.scheduler import (
    start_scheduler, stop_scheduler, sync_all_accounts_job,
    check_due_reminders_job, send_telegram_alert, scheduler
)
from app.bot.keyboards import get_email_detail_keyboard, get_main_reply_keyboard


async def run_phase5_tests():
    print("=" * 60)
    print("🚀 PHASE 5: BACKGROUND SCHEDULER & TELEGRAM PUSH ALERTS TEST")
    print("=" * 60)

    # 1. Initialize Database
    await init_db()
    print("✅ Database initialized successfully.")

    # 2. Test Scheduler Lifecycle
    sched = start_scheduler()
    assert sched is not None, "Scheduler should not be None"
    assert sched.running, "Scheduler should be running"

    jobs = sched.get_jobs()
    job_ids = [j.id for j in jobs]
    print(f"📋 Registered scheduler jobs: {job_ids}")
    assert "sync_emails_job" in job_ids, "sync_emails_job must be registered"
    assert "check_reminders_job" in job_ids, "check_reminders_job must be registered"
    print("✅ Scheduler started and background jobs verified (sync_emails_job & check_reminders_job).")

    stop_scheduler()
    print("✅ Scheduler stopped gracefully.")

    # 3. Test sync_all_accounts_job
    print("\n--- Testing sync_all_accounts_job ---")
    synced_count = await sync_all_accounts_job()
    print(f"ℹ️ Background sync executed without error. Synced count: {synced_count}")
    assert isinstance(synced_count, int), "synced_count should be an integer"
    print("✅ sync_all_accounts_job verified.")

    # 4. Test check_due_reminders_job with simulated due reminder
    print("\n--- Testing check_due_reminders_job ---")
    async with AsyncSessionLocal() as session:
        # Fetch or create demo user
        stmt = select(User).limit(1)
        user = (await session.execute(stmt)).scalars().first()
        if not user:
            user = User(email="test_scheduler@example.com", full_name="Scheduler Tester")
            session.add(user)
            await session.commit()
            await session.refresh(user)

        # Create an expired reminder
        past_time = datetime.utcnow() - timedelta(minutes=15)
        test_reminder = FollowUpReminder(
            user_id=user.id,
            reminder_text="Test Phase 5 Follow-up Reminder",
            remind_at=past_time,
            is_completed=False,
            notified_at=None
        )
        session.add(test_reminder)
        await session.commit()
        reminder_id = test_reminder.id
        print(f"ℹ️ Created test due reminder with ID: {reminder_id}, remind_at: {past_time}")

    # Run check_due_reminders_job
    processed_count = await check_due_reminders_job()
    print(f"ℹ️ check_due_reminders_job processed {processed_count} reminders.")
    assert processed_count >= 1, "At least 1 reminder should be processed"

    # Verify reminder has notified_at populated in DB
    async with AsyncSessionLocal() as session:
        chk_stmt = select(FollowUpReminder).where(FollowUpReminder.id == reminder_id)
        rem = (await session.execute(chk_stmt)).scalars().first()
        assert rem is not None
        assert rem.notified_at is not None, "Reminder notified_at must be populated after job execution"
        print(f"✅ Reminder {reminder_id} notified_at successfully updated to: {rem.notified_at}")

        # Clean up test reminder
        await session.delete(rem)
        await session.commit()

    # 5. Test Telegram Alert Markup & Keyboard Generation
    print("\n--- Testing Telegram Push Alert Components ---")
    dummy_email = EmailMessage(
        id=9999,
        account_id=1,
        message_id="dummy-test-msg-001",
        sender_name="Emergency Security Team",
        sender_email="security@cloudcorp.com",
        recipient_email="user@example.com",
        subject="CRITICAL: Database Replica Outage Detected",
        snippet="Immediate attention required",
        body_text="Our main DB replica is failing healthchecks.",
        category=CategoryEnum.IMPORTANT,
        priority=PriorityEnum.URGENT,
        key_takeaway="DB replikasi ishlamayapti, darhol tekshirish zarur",
        summary="• 🔴 Shoshilinch xabar: Baza replikasi to'xtagan.\n• Darhol serverga ulaning.",
        action_suggested="Darhol hal qilish",
        detected_deadline="30 daqiqa ichida",
        sentiment="Negative"
    )

    alert_kb = get_email_detail_keyboard(dummy_email.id)
    assert alert_kb is not None
    assert len(alert_kb.inline_keyboard) >= 2
    buttons_text = [btn.text for row in alert_kb.inline_keyboard for btn in row]
    print(f"📋 Generated Alert Inline Buttons: {buttons_text}")
    assert any("Javob draft" in b for b in buttons_text), "Must include Draft button"
    assert any("AI Xulosa" in b for b in buttons_text), "Must include Summary button"
    assert any("Eslatma" in b for b in buttons_text), "Must include Reminder button"
    print("✅ Alert Inline Keyboard generation verified.")

    # 6. Test Main Navigation Keyboard with /sync button
    main_kb = get_main_reply_keyboard()
    main_buttons = [btn.text for row in main_kb.keyboard for btn in row]
    print(f"📋 Main Persistent Keyboard Buttons: {main_buttons}")
    assert "🔄 Sinxronlash" in main_buttons, "Must include 🔄 Sinxronlash button"
    print("✅ Main Telegram navigation keyboard includes '🔄 Sinxronlash'.")

    # 7. Test Web API Sync Route
    print("\n--- Testing Web API /api/accounts/sync ---")
    from httpx import AsyncClient, ASGITransport
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/accounts/sync")
        print(f"Response status: {resp.status_code}, data: {resp.json()}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "synced_count" in data
        print("✅ Web API /api/accounts/sync endpoint verified.")

        # Test Health check
        h_resp = await client.get("/health")
        assert h_resp.status_code == 200
        h_data = h_resp.json()
        print(f"Health response: {h_data}")
        assert h_data["status"] == "healthy"
        print("✅ Health check endpoint verified.")

    print("\n" + "=" * 60)
    print("🎉 ALL PHASE 5 TESTS PASSED SUCCESSFULLY! 100% OPERATIONAL")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_phase5_tests())
