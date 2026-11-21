from datetime import datetime, timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models import (
    User, EmailAccount, EmailMessage, UserPreference,
    CategoryEnum, PriorityEnum, ReplyToneEnum
)
from app.services.ai_agent import AIAgentService


SAMPLE_EMAILS = [
    {
        "sender_name": "Google Cloud Alerts",
        "sender_email": "alerts@google.com",
        "subject": "CRITICAL: Production Database cluster CPU usage exceeded 98% [INC-89421]",
        "body_text": """Dear Engineering Lead,

This is an automated high-priority alert from Google Cloud Monitoring.
Incident ID: INC-89421
Cluster: db-prod-asia-southeast1
Trigger: CPU Utilization > 98% sustained for over 15 minutes.
Impact: Incoming read/write queries are encountering timeouts. Some customer API requests are failing with HTTP 504 Gateway Timeout.

Immediate Action Required:
1. Review active long-running query locks in Cloud Spanner / Cloud SQL.
2. Scale up replica capacity or restart hung worker pods.
3. Post status update to internal incident Slack channel #incident-response.

Time: 2026-11-21 06:15:00 UTC
Dashboard URL: https://console.cloud.google.com/monitoring/incidents/89421""",
        "body_html": """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:600px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #fee2e2;overflow:hidden;box-shadow:0 4px 6px -1px rgba(0,0,0,0.05)">
<div style="background:#dc2626;color:#ffffff;padding:16px 20px;display:flex;align-items:center;justify-content:between">
<h2 style="margin:0;font-size:16px;font-weight:700;letter-spacing:0.5px">🚨 GOOGLE CLOUD ALERT: #INC-89421</h2>
</div>
<div style="padding:24px;color:#1e293b">
<p style="font-size:14px;color:#64748b;margin-top:0">Dear Engineering Lead,</p>
<div style="background:#fef2f2;border-left:4px solid #ef4444;padding:12px 16px;border-radius:4px;margin-bottom:20px">
<p style="margin:0;font-size:14px;font-weight:600;color:#991b1b">Trigger: CPU Utilization &gt; 98% sustained for 15 minutes</p>
<p style="margin:4px 0 0;font-size:12px;color:#b91c1c">Cluster: db-prod-asia-southeast1 | Severity: CRITICAL</p>
</div>
<p style="font-size:13px;line-height:1.6">Incoming read/write queries are encountering timeouts. Some customer API requests are failing with <b>HTTP 504 Gateway Timeout</b>.</p>
<h4 style="font-size:13px;color:#0f172a;margin:16px 0 8px;text-transform:uppercase;letter-spacing:0.5px">Immediate Action Required:</h4>
<ol style="font-size:13px;line-height:1.7;color:#334155;padding-left:20px;margin:0">
<li>Review active long-running query locks in Cloud Spanner / Cloud SQL.</li>
<li>Scale up replica capacity or restart hung worker pods.</li>
<li>Post status update to internal incident Slack channel #incident-response.</li>
</ol>
<div style="margin-top:24px;padding-top:16px;border-top:1px solid #f1f5f9;text-align:center">
<a href="https://console.cloud.google.com/monitoring" style="display:inline-block;background:#dc2626;color:#ffffff;text-decoration:none;font-size:13px;font-weight:600;padding:10px 24px;border-radius:8px">Open Cloud Console</a>
</div>
</div>
</div>""",
        "days_ago": 0,
        "hours_ago": 1,
    },
    {
        "sender_name": "Google Security Team",
        "sender_email": "no-reply@accounts.google.com",
        "subject": "Security alert: New sign-in from Firefox on macOS",
        "body_text": """Your Google Account was just accessed from a new device:

Device: macOS Firefox
Location: Frankfurt, Germany
IP Address: 185.220.101.5
Time: Yesterday at 22:40

If this was you, you don't need to do anything. If you don't recognize this activity, your password may have been compromised.
Please secure your account immediately:
https://myaccount.google.com/secureaccount""",
        "body_html": """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:550px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;padding:28px;color:#1f2937">
<div style="text-align:center;margin-bottom:20px">
<img src="https://www.gstatic.com/images/branding/googlelogo/2x/googlelogo_color_74x24dp.png" alt="Google" width="74" height="24">
</div>
<h2 style="font-size:20px;font-weight:600;color:#202124;text-align:center;margin:0 0 16px">Yangi qurilmadan hisobga kirildi</h2>
<p style="font-size:14px;color:#3c4043;line-height:1.5;margin-bottom:20px">Google hisobingizga yangi qurilma orqali kirish amalga oshirildi:</p>
<div style="background:#f8fafc;border-radius:8px;padding:16px;margin-bottom:24px;font-size:13px;line-height:1.8;color:#475569">
<div>🖥️ <b>Qurilma:</b> macOS Firefox</div>
<div>📍 <b>Joylashuv:</b> Frankfurt, Germany</div>
<div>🌐 <b>IP manzil:</b> 185.220.101.5</div>
<div>🕒 <b>Vaqt:</b> Kecha, 22:40</div>
</div>
<p style="font-size:13px;color:#5f6368;line-height:1.5">Agar bu siz bo'lmasangiz, parolingiz oshkor bo'lgan bo'lishi mumkin. Hisobingizni zudlik bilan himoyalang:</p>
<div style="text-align:center;margin-top:24px">
<a href="https://myaccount.google.com/secureaccount" style="display:inline-block;background:#1a73e8;color:#ffffff;text-decoration:none;font-size:14px;font-weight:500;padding:10px 24px;border-radius:6px">Faoliyatni tekshirish</a>
</div>
</div>""",
        "days_ago": 1,
        "hours_ago": 8,
    },
    {
        "sender_name": "Sardor Rahimov (FinTech Partner)",
        "sender_email": "s.rahimov@fintech-ventures.uz",
        "subject": "Q4 Hamkorlik shartnomasi va integratsiya talablari bo'yicha taklif",
        "body_text": """Assalomu alaykum hurmatli jamoa,

Kompaniyamiz siz bilan 4-chorak doirasida elektron to'lov tizimini integratsiya qilish loyihasini muhokama qilmoqchi.

Hujjatlar va talablar ro'yxati:
1. API v2 orqali xavfsiz webhooks o'rnatish;
2. Kunlik 50,000 tranzaksiyaga mo'ljallangan yuklamaga chidamlilik testi;
3. Shartnoma loyihasi biriktirilgan (iloovani ko'ring).

Iltimos, taklifni jamoangiz bilan ko'rib chiqib, dushanba soat 15:00 gacha o'z fikrlaringizni va boshlang'ich texnik bahoingizni bildirsangiz.
Shuningdek, seshanba kuni Zoom orqali 30 daqiqalik sinxron uchrashuv o'tkazishni taklif qilamiz.

Hurmat bilan,
Sardor Rahimov
Bosh texnologik maslahatchi""",
        "body_html": """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:620px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;padding:24px;color:#1e293b">
<div style="border-bottom:2px solid #3b82f6;padding-bottom:12px;margin-bottom:16px;display:flex;justify-content:between;align-items:center">
<h3 style="margin:0;color:#1d4ed8;font-size:16px">FinTech Ventures Uzbekistan</h3>
<span style="font-size:12px;color:#64748b;font-weight:500">Hamkorlik taklifi #Q4-2026</span>
</div>
<p style="font-size:14px;line-height:1.6">Assalomu alaykum hurmatli jamoa,</p>
<p style="font-size:14px;line-height:1.6">Kompaniyamiz siz bilan 4-chorak doirasida <b>elektron to'lov tizimini integratsiya qilish</b> loyihasini muhokama qilmoqchi.</p>
<div style="background:#f8fafc;border-radius:8px;padding:16px;margin:16px 0;border-left:4px solid #3b82f6">
<h4 style="margin:0 0 8px;font-size:13px;color:#0f172a">Texnik talablar va topshiriqlar:</h4>
<ul style="margin:0;padding-left:18px;font-size:13px;line-height:1.7;color:#334155">
<li><b>API v2</b> orqali xavfsiz webhooks o'rnatish;</li>
<li>Kunlik <b>50,000 tranzaksiya</b> yuklamasiga chidamlilik testi;</li>
<li>Biriktirilgan <code>Shartnoma_Loyiha_v1.pdf</code> hujjatini imzolash.</li>
</ul>
</div>
<p style="font-size:13px;line-height:1.6;color:#475569">Iltimos, taklifni jamoangiz bilan ko'rib chiqib, <b>dushanba soat 15:00 gacha</b> o'z fikrlaringizni bildirsangiz. Seshanba kuni Zoom uchrashuvi taklif etiladi.</p>
<p style="font-size:13px;color:#64748b;margin-top:24px;border-top:1px solid #f1f5f9;padding-top:12px">
<b>Hurmat bilan,</b><br>
Sardor Rahimov<br>
<i>Bosh texnologik maslahatchi</i>
</p>
</div>""",
        "days_ago": 2,
        "hours_ago": 3,
    },
    {
        "sender_name": "Alisher (Colleague)",
        "sender_email": "alisher.dev@gmail.com",
        "subject": "Shanba kungi kofe va yangi AI loyihalar haqida suhbat",
        "body_text": """Salom do'stim!

Qandaysan, ishlar yaxshimi? Anchadan beri ko'rishmadik.
Eshitdim, yangi agentik AI tizimlar ustida ishlayotgan ekansan.
Agar shanba kuni bo'sh bo'lsang, soat 17:00 atrofida markazda kofe ichib, yangiliklarni muhokama qilsak qanday bo'lardi?

Javobingni kutaman!""",
        "body_html": """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:500px;margin:0 auto;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;padding:24px;color:#1e293b">
<p style="font-size:15px;line-height:1.6;margin-top:0">Salom do'stim!</p>
<p style="font-size:14px;line-height:1.6">Qandaysan, ishlar yaxshimi? Anchadan beri ko'rishmadik.</p>
<p style="font-size:14px;line-height:1.6">Eshitdim, yangi <b>agentik AI tizimlar</b> ustida ishlayotgan ekansan. Agar shanba kuni bo'sh bo'lsang, soat <b>17:00 atrofida markazda kofe ichib</b>, yangiliklarni muhokama qilsak qanday bo'lardi?</p>
<p style="font-size:14px;line-height:1.6">Javobingni kutaman! ☕</p>
</div>""",
        "days_ago": 3,
        "hours_ago": 5,
    },
    {
        "sender_name": "TechStore Megasale",
        "sender_email": "deals@techstore-uz.com",
        "subject": "💥 Black Friday! Noutbuklar va smartfonlarga 70% gacha CHEGIRMA!",
        "body_text": """Faqatgina 3 kun! Yilning eng katta chegirmalari boshlandi!

- MacBook Pro M3 Max - 25% chegirma!
- iPhone 16 Pro - sovg'a sifatida AirPods!
- Monitorlar va mexanik klaviaturalar 50% arzonroq!

Chegirma kodidan foydalaning: BLACKFRIDAY2026
Do'konga o'tish uchun bosing: https://techstore-uz.com/blackfriday
Obunani bekor qilish uchun pastdagi havolani bosing.""",
        "body_html": """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:550px;margin:0 auto;background:linear-gradient(135deg,#1e1b4b,#312e81);border-radius:12px;overflow:hidden;color:#ffffff;box-shadow:0 10px 15px -3px rgba(0,0,0,0.3)">
<div style="padding:32px 24px;text-align:center">
<span style="background:#4f46e5;color:#e0e7ff;font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;text-transform:uppercase;letter-spacing:1px">Cheklangan muddat: 3 kun</span>
<h1 style="font-size:26px;font-weight:800;margin:12px 0 8px">💥 BLACK FRIDAY 2026</h1>
<p style="font-size:15px;color:#c7d2fe;margin:0 0 24px">Eng sara elektronika va noutbuklarga <b>70% gacha CHEGIRMA!</b></p>
<div style="background:rgba(255,255,255,0.1);backdrop-filter:blur(10px);border:1px dashed rgba(255,255,255,0.3);border-radius:8px;padding:12px;margin-bottom:24px;display:inline-block">
<span style="font-size:12px;color:#a5b4fc">Promokod:</span>
<span style="font-size:16px;font-weight:700;color:#ffffff;letter-spacing:2px;margin-left:8px">BLACKFRIDAY2026</span>
</div>
<div>
<a href="#" style="display:inline-block;background:#ffffff;color:#4338ca;font-weight:700;font-size:14px;padding:12px 32px;border-radius:8px;text-decoration:none;box-shadow:0 4px 6px rgba(0,0,0,0.2)">Xaridni boshlash</a>
</div>
</div>
</div>""",
        "days_ago": 4,
        "hours_ago": 12,
    },
    {
        "sender_name": "Crypto Lottery Global",
        "sender_email": "claims@urgent-crypto-prizes.net",
        "subject": "CONGRATULATIONS: You have won 2.5 BTC in international lucky draw!",
        "body_text": """Dear Winner,

Your email address was randomly selected as the lucky winner of 2.50 Bitcoin ($220,000 USD) in the Global Blockchain Lottery Draw.
To claim your funds, please click the link below and verify your private seed phrase or transfer 0.005 BTC processing fee within 24 hours.

Failure to claim will result in forfeiture of the prize.
Click here to claim immediately: http://suspicious-crypto-claim-phishing.ru/verify""",
        "body_html": """<div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:550px;margin:0 auto;background:#ffffff;border:2px dashed #f59e0b;border-radius:12px;padding:24px;color:#1e293b">
<div style="background:#fef3c7;border-radius:8px;padding:12px;text-align:center;margin-bottom:16px">
<h3 style="margin:0;color:#b45309;font-size:16px">⚠️ SUSPICIOUS / SPAM ALERT</h3>
</div>
<h2 style="color:#d97706;font-size:18px;margin-top:0">🎉 YOU HAVE WON 2.50 BITCOIN! ($220,000 USD)</h2>
<p style="font-size:13px;line-height:1.6">Your email address was randomly selected in the Global Blockchain Lottery. To claim, transfer 0.005 BTC processing fee within 24 hours.</p>
</div>""",
        "days_ago": 5,
        "hours_ago": 14,
    }
]


async def seed_initial_demo_data(db: AsyncSession, force: bool = False) -> bool:
    """Seeds default user, preference, email account, and analyzed sample emails if DB is empty, or re-seeds if force=True."""
    stmt = select(User).limit(1)
    result = await db.execute(stmt)
    user = result.scalars().first()

    if user and not force:
        return False  # Already seeded

    if not user:
        # 1. Create Default User
        user = User(
            username="demo_user",
            email="demo@agent.ai",
            telegram_chat_id=None
        )
        db.add(user)
        await db.flush()

        # 2. Create User Preference (User Preference Memory)
        pref = UserPreference(
            user_id=user.id,
            preferred_tone=ReplyToneEnum.PROFESSIONAL,
            preferred_language="Uzbek",
            max_summary_bullets=4,
            notify_urgent=True,
            notify_telegram=True,
            custom_instructions="Javoblar qisqa, aniq va professional uslubda bo'lsin. O'zbek tilida yozilsin."
        )
        db.add(pref)
    else:
        pref_stmt = select(UserPreference).where(UserPreference.user_id == user.id)
        pref = (await db.execute(pref_stmt)).scalars().first()

    # Find active account or fallback
    acc_stmt = select(EmailAccount).where(EmailAccount.user_id == user.id, EmailAccount.is_active == True)
    account = (await db.execute(acc_stmt)).scalars().first()
    if not account:
        any_acc_stmt = select(EmailAccount).where(EmailAccount.user_id == user.id)
        account = (await db.execute(any_acc_stmt)).scalars().first()

    if not account:
        account = EmailAccount(
            user_id=user.id,
            email_address="agent.workspace@gmail.com",
            imap_host="imap.gmail.com",
            imap_port=993,
            imap_use_ssl=True,
            smtp_host="smtp.gmail.com",
            smtp_port=465,
            smtp_use_ssl=True,
            username="agent.workspace@gmail.com",
            password="app_password_mock",
            is_active=True,
            last_synced_at=datetime.utcnow()
        )
        db.add(account)
        await db.flush()

    # 4. Create and AI-Analyze Sample Emails
    now = datetime.utcnow()
    for sample in SAMPLE_EMAILS:
        chk_stmt = select(EmailMessage).where(EmailMessage.subject == sample["subject"])
        existing_msg = (await db.execute(chk_stmt)).scalars().first()
        if existing_msg:
            existing_msg.account_id = account.id
            if sample.get("body_html"):
                existing_msg.body_html = sample["body_html"]
            continue

        received_time = now - timedelta(days=sample["days_ago"], hours=sample["hours_ago"])
        analysis = await AIAgentService.analyze_email(
            subject=sample["subject"],
            body=sample["body_text"],
            sender=sample["sender_email"],
            user_preference=pref
        )

        email_msg = EmailMessage(
            account_id=account.id,
            message_id=f"msg-{sample['sender_email']}-{received_time.timestamp()}",
            sender_name=sample["sender_name"],
            sender_email=sample["sender_email"],
            recipient_email=account.email_address,
            subject=sample["subject"],
            snippet=sample["body_text"][:180].replace("\n", " ").strip(),
            body_text=sample["body_text"],
            body_html=sample.get("body_html") or f"<p>{sample['body_text'].replace(chr(10), '<br>')}</p>",
            received_at=received_time,
            category=analysis["category"],
            priority=analysis["priority"],
            key_takeaway=analysis.get("key_takeaway", sample["subject"]),
            summary=analysis["summary"],
            action_suggested=analysis["action_suggested"],
            action_items=analysis.get("action_items"),
            detected_deadline=analysis.get("detected_deadline"),
            sentiment=analysis.get("sentiment", "Neutral"),
            is_read=False,
            is_starred=(analysis["priority"] in [PriorityEnum.URGENT, PriorityEnum.HIGH]),
            has_attachments=("shartnoma" in sample["body_text"].lower()),
            ai_processed_at=datetime.utcnow()
        )
        db.add(email_msg)

    await db.commit()
    return True
