from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc, or_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.db import get_db, AsyncSessionLocal
from app.config import settings
from app.models import (
    User, EmailAccount, EmailMessage, EmailDraft, UserPreference, FollowUpReminder, AgentAuditLog,
    CategoryEnum, PriorityEnum, ReplyToneEnum
)
from app.services.ai_agent import AIAgentService
from app.services.action_agent import ActionAgent
from app.services.email_service import EmailService
from app.services.mock_data import seed_initial_demo_data

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")


# -------------------------------------------------------------
# Pydantic Schemas for API Requests
# -------------------------------------------------------------
class AgentChatRequest(BaseModel):
    message: str
class GenerateReplyRequest(BaseModel):
    tone: ReplyToneEnum = ReplyToneEnum.PROFESSIONAL
    custom_prompt: Optional[str] = None


class SendReplyRequest(BaseModel):
    draft_id: Optional[int] = None
    subject: str
    body: str


class NaturalSearchRequest(BaseModel):
    query: str


class ConnectAccountRequest(BaseModel):
    email_address: str
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    username: Optional[str] = None
    password: str
    skip_verify: bool = False


class CreateReminderRequest(BaseModel):
    email_id: Optional[int] = None
    reminder_text: str
    hours_from_now: int = 24


class UpdatePreferencesRequest(BaseModel):
    preferred_tone: ReplyToneEnum
    preferred_language: str
    max_summary_bullets: int
    custom_instructions: str
    signature: Optional[str] = "Hurmat bilan,\nAI Email Agent"


# -------------------------------------------------------------
# HTML Views
# -------------------------------------------------------------
@router.get("/", response_class=HTMLResponse)
async def view_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    # Get or create demo user
    stmt = select(User).options(selectinload(User.preferences)).limit(1)
    res = await db.execute(stmt)
    user = res.scalars().first()

    if not user:
        await seed_initial_demo_data(db)
        res = await db.execute(stmt)
        user = res.scalars().first()

    # Get stats
    total_emails = (await db.execute(select(func.count(EmailMessage.id)))).scalar() or 0
    urgent_emails = (await db.execute(select(func.count(EmailMessage.id)).where(EmailMessage.priority == PriorityEnum.URGENT))).scalar() or 0
    high_emails = (await db.execute(select(func.count(EmailMessage.id)).where(EmailMessage.priority == PriorityEnum.HIGH))).scalar() or 0
    work_emails = (await db.execute(select(func.count(EmailMessage.id)).where(EmailMessage.category == CategoryEnum.WORK))).scalar() or 0

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "user": user,
            "settings": settings,
            "stats": {
                "total": total_emails,
                "urgent": urgent_emails,
                "high": high_emails,
                "work": work_emails
            }
        }
    )


@router.get("/settings", response_class=HTMLResponse)
async def view_settings_page(request: Request, db: AsyncSession = Depends(get_db)):
    stmt = select(User).options(selectinload(User.preferences)).limit(1)
    res = await db.execute(stmt)
    user = res.scalars().first()
    return templates.TemplateResponse(
        request=request,
        name="settings.html",
        context={
            "user": user,
            "settings": settings
        }
    )


# -------------------------------------------------------------
# JSON REST API Endpoints
# -------------------------------------------------------------
@router.get("/api/emails")
async def get_emails(
    category: Optional[str] = None,
    priority: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    query = select(EmailMessage).order_by(desc(EmailMessage.received_at))

    if category and category != "all":
        try:
            query = query.where(EmailMessage.category == CategoryEnum(category))
        except ValueError:
            pass

    if priority and priority != "all":
        try:
            query = query.where(EmailMessage.priority == PriorityEnum(priority))
        except ValueError:
            pass

    res = await db.execute(query)
    emails = res.scalars().all()

    return [
        {
            "id": e.id,
            "sender_name": e.sender_name,
            "sender_email": e.sender_email,
            "subject": e.subject,
            "snippet": e.snippet,
            "category": e.category.value,
            "priority": e.priority.value,
            "key_takeaway": e.key_takeaway,
            "summary": e.summary,
            "action_suggested": e.action_suggested,
            "detected_deadline": e.detected_deadline,
            "sentiment": e.sentiment,
            "is_read": e.is_read,
            "is_starred": e.is_starred,
            "has_attachments": e.has_attachments,
            "received_at": e.received_at.strftime("%Y-%m-%d %H:%M"),
        }
        for e in emails
    ]


@router.get("/api/emails/{email_id}")
async def get_email_detail(email_id: int, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(EmailMessage)
        .where(EmailMessage.id == email_id)
        .options(selectinload(EmailMessage.drafts), selectinload(EmailMessage.reminders))
    )
    res = await db.execute(stmt)
    em = res.scalars().first()

    if not em:
        raise HTTPException(status_code=404, detail="Email topilmadi")

    # Mark as read
    if not em.is_read:
        em.is_read = True
        await db.commit()

    action_items_list = []
    if em.action_items:
        try:
            action_items_list = json.loads(em.action_items)
        except Exception:
            action_items_list = [em.action_items]

    return {
        "id": em.id,
        "sender_name": em.sender_name,
        "sender_email": em.sender_email,
        "recipient_email": em.recipient_email,
        "subject": em.subject,
        "snippet": em.snippet,
        "body_text": em.body_text,
        "body_html": em.body_html,
        "category": em.category.value,
        "priority": em.priority.value,
        "key_takeaway": em.key_takeaway,
        "summary": em.summary,
        "action_suggested": em.action_suggested,
        "action_items": action_items_list,
        "detected_deadline": em.detected_deadline,
        "sentiment": em.sentiment,
        "is_read": em.is_read,
        "has_attachments": em.has_attachments,
        "received_at": em.received_at.strftime("%Y-%m-%d %H:%M"),
        "drafts": [
            {
                "id": d.id,
                "tone": d.tone.value,
                "subject": d.subject,
                "body": d.body,
                "is_sent": d.is_sent,
                "created_at": d.created_at.strftime("%Y-%m-%d %H:%M")
            }
            for d in em.drafts
        ]
    }


@router.post("/api/emails/{email_id}/generate-reply")
async def generate_reply(
    email_id: int,
    payload: GenerateReplyRequest,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(EmailMessage).where(EmailMessage.id == email_id)
    res = await db.execute(stmt)
    em = res.scalars().first()

    if not em:
        raise HTTPException(status_code=404, detail="Email topilmadi")

    # Get user preference
    pref_stmt = select(UserPreference).limit(1)
    pref_res = await db.execute(pref_stmt)
    user_pref = pref_res.scalars().first()

    draft_text = await AIAgentService.generate_reply(
        subject=em.subject,
        body=em.body_text,
        sender_name=em.sender_name,
        sender_email=em.sender_email,
        tone=payload.tone,
        user_preference=user_pref
    )

    # Save draft
    draft = EmailDraft(
        email_id=em.id,
        tone=payload.tone,
        subject=f"Re: {em.subject}",
        body=draft_text
    )
    db.add(draft)
    await db.commit()
    await db.refresh(draft)

    return {
        "success": True,
        "draft_id": draft.id,
        "tone": draft.tone.value,
        "subject": draft.subject,
        "body": draft.body
    }


@router.post("/api/emails/{email_id}/send-reply")
async def send_reply(
    email_id: int,
    payload: SendReplyRequest,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(EmailMessage).where(EmailMessage.id == email_id).options(selectinload(EmailMessage.account))
    res = await db.execute(stmt)
    em = res.scalars().first()

    if not em:
        raise HTTPException(status_code=404, detail="Email topilmadi")

    account = em.account
    if not account or account.password == "app_password_mock":
        # Mock mode
        return {
            "success": True,
            "mock": True,
            "message": "Demo rejim: Xat muvaffaqiyatli jo'natildi deb belgilandi (Haqiqiy SMTP ulanmagan)."
        }

    success, msg = await EmailService.send_email(
        account=account,
        to_email=em.sender_email,
        subject=payload.subject,
        body=payload.body,
        in_reply_to=em.message_id
    )

    if not success:
        raise HTTPException(status_code=500, detail=msg)

    if payload.draft_id:
        draft_stmt = select(EmailDraft).where(EmailDraft.id == payload.draft_id)
        d_res = await db.execute(draft_stmt)
        draft = d_res.scalars().first()
        if draft:
            draft.is_sent = True
            draft.sent_at = datetime.utcnow()
            await db.commit()

    return {"success": True, "message": msg}


@router.post("/api/search")
async def natural_search(payload: NaturalSearchRequest, db: AsyncSession = Depends(get_db)):
    filters = await AIAgentService.parse_search_query(payload.query)

    query = select(EmailMessage)
    if filters.get("category"):
        try:
            query = query.where(EmailMessage.category == CategoryEnum(filters["category"]))
        except ValueError:
            pass

    if filters.get("priority"):
        try:
            query = query.where(EmailMessage.priority == PriorityEnum(filters["priority"]))
        except ValueError:
            pass

    if filters.get("sender"):
        s = f"%{filters['sender']}%"
        query = query.where(or_(EmailMessage.sender_name.ilike(s), EmailMessage.sender_email.ilike(s)))

    if filters.get("keywords"):
        kw_list = [w.strip() for w in filters["keywords"].split() if len(w.strip()) > 2]
        for word in kw_list:
            k = f"%{word}%"
            query = query.where(
                or_(
                    EmailMessage.subject.ilike(k),
                    EmailMessage.body_text.ilike(k),
                    EmailMessage.sender_name.ilike(k),
                    EmailMessage.sender_email.ilike(k)
                )
            )

    if filters.get("days_back"):
        cutoff = datetime.utcnow() - timedelta(days=filters["days_back"])
        query = query.where(EmailMessage.received_at >= cutoff)

    query = query.order_by(desc(EmailMessage.received_at)).limit(15)
    res = await db.execute(query)
    emails = res.scalars().all()

    return {
        "filters_parsed": filters,
        "count": len(emails),
        "results": [
            {
                "id": e.id,
                "sender_name": e.sender_name,
                "sender_email": e.sender_email,
                "subject": e.subject,
                "snippet": e.snippet,
                "category": e.category.value,
                "priority": e.priority.value,
                "summary": e.summary,
                "received_at": e.received_at.strftime("%Y-%m-%d %H:%M")
            }
            for e in emails
        ]
    }


@router.get("/api/accounts")
async def get_connected_accounts(db: AsyncSession = Depends(get_db)):
    stmt = select(EmailAccount).order_by(desc(EmailAccount.is_active), desc(EmailAccount.created_at))
    accounts = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": a.id,
            "email_address": a.email_address,
            "imap_host": a.imap_host,
            "is_active": a.is_active,
            "last_synced_at": a.last_synced_at.strftime("%Y-%m-%d %H:%M") if a.last_synced_at else "Hali sinxronlanmagan"
        }
        for a in accounts
    ]


@router.post("/api/accounts/connect")
async def connect_account(payload: ConnectAccountRequest, db: AsyncSession = Depends(get_db)):
    user_stmt = select(User).limit(1)
    res = await db.execute(user_stmt)
    user = res.scalars().first()

    clean_host = payload.imap_host.strip()
    clean_username = payload.username.strip() if payload.username else payload.email_address.strip()
    clean_pwd = payload.password.replace(" ", "") if (len(payload.password.replace(" ", "")) == 16 or "gmail" in clean_host.lower()) else payload.password.strip()

    account = EmailAccount(
        user_id=user.id,
        email_address=payload.email_address.strip(),
        imap_host=clean_host,
        imap_port=payload.imap_port,
        smtp_host=payload.smtp_host.strip(),
        smtp_port=payload.smtp_port,
        username=clean_username,
        password=clean_pwd,
        is_active=True
    )

    if not payload.skip_verify:
        success, msg = await EmailService.test_connection(account)
        if not success:
            raise HTTPException(status_code=400, detail=msg)

    # Deactivate existing mock account if real account connects
    mock_stmt = select(EmailAccount).where(EmailAccount.password == "app_password_mock")
    mock_acc = (await db.execute(mock_stmt)).scalars().first()
    if mock_acc:
        mock_acc.is_active = False

    db.add(account)
    await db.commit()
    await db.refresh(account)

    # Immediately trigger initial sync for the newly connected account
    synced_count = 0
    try:
        raw_emails = await EmailService.fetch_emails(account, limit=15)
        pref_stmt = select(UserPreference).where(UserPreference.user_id == user.id)
        user_pref = (await db.execute(pref_stmt)).scalars().first()

        for raw in raw_emails:
            chk = select(EmailMessage).where(EmailMessage.message_id == raw["message_id"])
            if (await db.execute(chk)).scalars().first():
                continue

            analysis = await AIAgentService.analyze_email(
                subject=raw["subject"],
                body=raw["body_text"],
                sender=raw["sender_email"],
                user_preference=user_pref
            )

            em = EmailMessage(
                account_id=account.id,
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
            db.add(em)
            synced_count += 1

        account.last_synced_at = datetime.utcnow()
        await db.commit()
    except Exception as e:
        print(f"[connect_account auto-sync error]: {e}")

    return {
        "success": True,
        "message": f"Email akkaunt muvaffaqiyatli ulandi! {synced_count} ta yangi xat yuklandi va AI tahlildan o'tkazildi.",
        "account_id": account.id,
        "synced_count": synced_count
    }


@router.delete("/api/accounts/{account_id}")
async def delete_account(account_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(EmailAccount).where(EmailAccount.id == account_id)
    acc = (await db.execute(stmt)).scalars().first()
    if not acc:
        raise HTTPException(status_code=404, detail="Akkaunt topilmadi")
    await db.delete(acc)
    await db.commit()
    return {"success": True, "message": "Email akkaunt o'chirildi"}


@router.post("/api/accounts/sync")
async def sync_account(db: AsyncSession = Depends(get_db)):
    from app.services.scheduler import sync_all_accounts_job
    try:
        total_synced = await sync_all_accounts_job()
        return {"success": True, "synced_count": total_synced}
    except Exception as e:
        return {"success": False, "detail": str(e), "synced_count": 0}


@router.post("/api/seed-demo")
async def seed_demo(db: AsyncSession = Depends(get_db)):
    success = await seed_initial_demo_data(db, force=True)
    return {"success": True, "seeded": success}


@router.get("/api/reminders")
async def get_reminders(db: AsyncSession = Depends(get_db)):
    stmt = select(FollowUpReminder).order_by(FollowUpReminder.remind_at)
    res = await db.execute(stmt)
    reminders = res.scalars().all()
    return [
        {
            "id": r.id,
            "email_id": r.email_id,
            "reminder_text": r.reminder_text,
            "remind_at": r.remind_at.strftime("%Y-%m-%d %H:%M"),
            "is_completed": r.is_completed
        }
        for r in reminders
    ]


@router.post("/api/reminders")
async def create_reminder(payload: CreateReminderRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).limit(1))).scalars().first()
    due = datetime.utcnow() + timedelta(hours=payload.hours_from_now)
    r = FollowUpReminder(
        user_id=user.id,
        email_id=payload.email_id,
        reminder_text=payload.reminder_text,
        remind_at=due
    )
    db.add(r)
    await db.commit()
    return {"success": True, "reminder_id": r.id}


@router.post("/api/settings")
async def update_settings(payload: UpdatePreferencesRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).limit(1))).scalars().first()
    stmt = select(UserPreference).where(UserPreference.user_id == user.id)
    pref = (await db.execute(stmt)).scalars().first()

    if not pref:
        pref = UserPreference(user_id=user.id)
        db.add(pref)

    pref.preferred_tone = payload.preferred_tone
    pref.preferred_language = payload.preferred_language
    pref.max_summary_bullets = payload.max_summary_bullets
    pref.custom_instructions = payload.custom_instructions
    pref.signature = payload.signature

    await db.commit()
    return {"success": True, "message": "Sozlamalar yangilandi!"}


@router.patch("/api/emails/{email_id}/toggle-star")
async def toggle_star(email_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(EmailMessage).where(EmailMessage.id == email_id)
    em = (await db.execute(stmt)).scalars().first()
    if not em:
        raise HTTPException(status_code=404, detail="Email topilmadi")
    em.is_starred = not em.is_starred
    await db.commit()
    return {"success": True, "is_starred": em.is_starred}


@router.patch("/api/emails/{email_id}/toggle-read")
async def toggle_read(email_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(EmailMessage).where(EmailMessage.id == email_id)
    em = (await db.execute(stmt)).scalars().first()
    if not em:
        raise HTTPException(status_code=404, detail="Email topilmadi")
    em.is_read = not em.is_read
    await db.commit()
    return {"success": True, "is_read": em.is_read}


@router.patch("/api/reminders/{reminder_id}/complete")
async def complete_reminder(reminder_id: int, db: AsyncSession = Depends(get_db)):
    stmt = select(FollowUpReminder).where(FollowUpReminder.id == reminder_id)
    rem = (await db.execute(stmt)).scalars().first()
    if not rem:
        raise HTTPException(status_code=404, detail="Eslatma topilmadi")
    rem.is_completed = not rem.is_completed
    await db.commit()
    return {"success": True, "is_completed": rem.is_completed}


# -------------------------------------------------------------
# Action Agent Chat & Tool-Calling Endpoints (Phase 2)
# -------------------------------------------------------------
@router.post("/api/agent/chat")
async def chat_with_action_agent(payload: AgentChatRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).options(selectinload(User.preferences)).limit(1))).scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="Foydalanuvchi topilmadi")

    agent_result = await ActionAgent.process_user_instruction(
        user=user,
        instruction=payload.message,
        db=db
    )
    return agent_result


@router.get("/api/agent/audit-logs")
async def get_agent_audit_logs(db: AsyncSession = Depends(get_db)):
    stmt = select(AgentAuditLog).order_by(desc(AgentAuditLog.created_at)).limit(20)
    logs = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": l.id,
            "tool_name": l.tool_name,
            "arguments": l.arguments_json,
            "result_summary": l.result_summary,
            "created_at": l.created_at.strftime("%Y-%m-%d %H:%M:%S")
        }
        for l in logs
    ]
