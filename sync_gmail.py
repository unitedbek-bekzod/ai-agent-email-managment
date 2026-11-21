import asyncio
import imaplib
import email
from email.header import decode_header
import email.utils
from datetime import datetime, timezone
from sqlalchemy import select
from bs4 import BeautifulSoup

from app.db import AsyncSessionLocal, init_db
from app.models import EmailAccount, EmailMessage, UserPreference, CategoryEnum, PriorityEnum
from app.services.ai_agent import AIAgentService
from app.services.email_service import _decode_mime_header, _extract_email_body


async def sync_gmail_direct():
    print("=" * 65)
    print("📬 GMAIL'DAN MA'LUMOTLARNI YUKLASH VA AI TAHLIL QILISH")
    print("=" * 65)

    await init_db()

    async with AsyncSessionLocal() as session:
        # Find active account
        stmt = select(EmailAccount).where(EmailAccount.email_address == "bekzodeoke@gmail.com")
        accs = (await session.execute(stmt)).scalars().all()

        if not accs:
            print("❌ 'bekzodeoke@gmail.com' akkaunti topilmadi.")
            return

        acc = accs[0]
        # Clean up duplicate accounts in DB
        for dup in accs[1:]:
            await session.delete(dup)
        acc.is_active = True
        await session.commit()

        email_addr = acc.email_address
        raw_pwd = acc.password.strip().replace(" ", "")
        print(f"📧 Akkaunt: {email_addr}")
        print(f"🔑 Saqlangan parol uzunligi: {len(raw_pwd)} ta belgi")

        # Passwords to test
        passwords_to_try = [raw_pwd]
        if len(raw_pwd) == 17:
            passwords_to_try.append(raw_pwd[:-1])  # remove last char
            passwords_to_try.append(raw_pwd[1:])   # remove first char

        working_server = None
        working_password = None

        print("\n🔍 Google IMAP serveriga ulanish tekshirilmoqda...")

        for pwd_variant in passwords_to_try:
            variant_desc = f"{pwd_variant[:4]}...{pwd_variant[-4:]} (uzunligi: {len(pwd_variant)})"
            print(f"  • Parol varianti sinab ko'rilmoqda: {variant_desc}...")
            try:
                server = imaplib.IMAP4_SSL(acc.imap_host, acc.imap_port, timeout=20)
                server.login(email_addr, pwd_variant)
                print(f"  ✅ Muvaffaqiyatli login qilindi! Working password: {variant_desc}")
                working_server = server
                working_password = pwd_variant
                break
            except imaplib.IMAP4.error as e:
                err = str(e)
                print(f"    ⚠️ Login rad etildi: {err}")
            except Exception as e:
                print(f"    ⚠️ Ulanish xatosi: {e}")

        if not working_server:
            print("\n❌ GMAIL BILAN BOG'LANISH AMALGA OSHMADI.")
            print("-" * 65)
            print("Sabablari va yechimlar:")
            print("1. 🔴 Gmail hisobingizda IMAP O'CHIRILGAN bo'lishi mumkin:")
            print("   • Brauzerda oching: https://mail.google.com/mail/u/0/#settings/fwdandpop")
            print("   • 'IMAP Access' bo'limida 'Enable IMAP' (IMAP-ni yoqish)ni tanlang")
            print("   • Pastda 'Save Changes' (O'zgarishlarni saqlash)ni bosing.")
            print("\n2. 🔑 Yangi 16 xonali App Password yarating:")
            print("   • https://myaccount.google.com/apppasswords sahifasiga kiring")
            print("   • Ilova nomiga 'Email Agent' deb yozib, yangi 16 ta harfli kod oling.")
            print("=" * 65)
            return

        # Update correct password in DB
        acc.password = working_password
        await session.commit()

        # Fetch emails from INBOX
        print("\n📥 Gmail INBOX papkasi ochilmoqda...")
        status, _ = working_server.select("INBOX", readonly=True)
        if status != "OK":
            print(f"❌ INBOX papkasini ochib bo'lmadi: {status}")
            working_server.logout()
            return

        status, messages = working_server.search(None, "ALL")
        if status != "OK" or not messages or not messages[0]:
            print("📭 INBOX papkasida xabarlar topilmadi.")
            working_server.logout()
            return

        mail_ids = messages[0].split()
        total_inbox = len(mail_ids)
        print(f"📊 INBOX papkasidagi jami xatlar soni: {total_inbox} ta")

        limit = 10
        recent_ids = mail_ids[-limit:]
        recent_ids.reverse()

        print(f"⚡ Oxirgi {len(recent_ids)} ta xabar yuklanmoqda va AI tahlildan o'tkazilmoqda...\n")

        # Get user preference
        pref_stmt = select(UserPreference).where(UserPreference.user_id == acc.user_id)
        user_pref = (await session.execute(pref_stmt)).scalars().first()

        synced_count = 0
        for i, msg_id in enumerate(recent_ids, 1):
            status, data = working_server.fetch(msg_id, "(RFC822)")
            if status != "OK" or not data:
                continue

            for part in data:
                if isinstance(part, tuple):
                    raw_msg = email.message_from_bytes(part[1])
                    subject = _decode_mime_header(raw_msg.get("Subject")) or "(Mavzusiz)"
                    from_header = _decode_mime_header(raw_msg.get("From"))
                    to_header = _decode_mime_header(raw_msg.get("To"))
                    date_str = raw_msg.get("Date")
                    message_id = raw_msg.get("Message-ID", f"gmail-{msg_id.decode()}-{datetime.utcnow().timestamp()}")

                    real_name, sender_email = email.utils.parseaddr(from_header)
                    if not sender_email:
                        sender_email = from_header

                    parsed_date = datetime.utcnow()
                    if date_str:
                        try:
                            parsed_tuple = email.utils.parsedate_to_datetime(date_str)
                            if parsed_tuple:
                                parsed_date = parsed_tuple.astimezone(timezone.utc).replace(tzinfo=None)
                        except Exception:
                            pass

                    text_body, html_body, has_attachments = _extract_email_body(raw_msg)
                    snippet = text_body[:180].replace("\n", " ").strip() if text_body else subject

                    # Check duplicate
                    chk = select(EmailMessage).where(EmailMessage.message_id == message_id)
                    existing = (await session.execute(chk)).scalars().first()
                    if existing:
                        print(f"  [{i}/{len(recent_ids)}] ⏩ Mavjud xabar o'tkazib yuborildi: {subject[:45]}...")
                        continue

                    print(f"  [{i}/{len(recent_ids)}] 🤖 AI tahlil qilinmoqda: '{subject[:45]}...'")
                    analysis = await AIAgentService.analyze_email(
                        subject=subject,
                        body=text_body or snippet,
                        sender=sender_email,
                        user_preference=user_pref
                    )

                    new_msg = EmailMessage(
                        account_id=acc.id,
                        message_id=message_id,
                        sender_name=real_name or sender_email,
                        sender_email=sender_email,
                        recipient_email=to_header or acc.email_address,
                        subject=subject,
                        snippet=snippet,
                        body_text=text_body,
                        body_html=html_body,
                        received_at=parsed_date,
                        category=analysis["category"],
                        priority=analysis["priority"],
                        key_takeaway=analysis.get("key_takeaway", subject),
                        summary=analysis["summary"],
                        action_suggested=analysis["action_suggested"],
                        action_items=analysis.get("action_items"),
                        detected_deadline=analysis.get("detected_deadline"),
                        sentiment=analysis.get("sentiment", "Neutral"),
                        has_attachments=has_attachments,
                        ai_processed_at=datetime.utcnow()
                    )
                    session.add(new_msg)
                    synced_count += 1
                    print(f"      🏷️ Kategoriya: {analysis['category'].value} | Prioritet: {analysis['priority'].value}")

        acc.last_synced_at = datetime.utcnow()
        await session.commit()
        working_server.logout()

        print("\n" + "=" * 65)
        print(f"🎉 TAYYOR! Jami {synced_count} ta yangi real xat Gmail'dan yuklandi!")
        print("Endi http://localhost:8000 sahifasida barcha xabarlaringiz ko'rinadi.")
        print("=" * 65)


if __name__ == "__main__":
    asyncio.run(sync_gmail_direct())
