import asyncio
import email
from email.header import decode_header
import email.utils
import imaplib
import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Dict, Any
from bs4 import BeautifulSoup

from app.models import EmailAccount, EmailMessage, CategoryEnum, PriorityEnum


def _decode_mime_header(header_value: Optional[str]) -> str:
    """Safely decodes RFC 2047 MIME encoded headers."""
    if not header_value:
        return ""
    decoded_fragments = []
    try:
        parts = decode_header(header_value)
        for part, encoding in parts:
            if isinstance(part, bytes):
                try:
                    decoded_fragments.append(part.decode(encoding or "utf-8", errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    decoded_fragments.append(part.decode("latin1", errors="replace"))
            else:
                decoded_fragments.append(str(part))
        return "".join(decoded_fragments).strip()
    except Exception:
        return str(header_value)


def _extract_email_body(msg: email.message.Message) -> Tuple[str, str, bool]:
    """Extracts plain text body, html body, and checks for attachments."""
    text_parts = []
    html_parts = []
    has_attachments = False

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disposition.lower():
                has_attachments = True
                continue

            try:
                payload = part.get_payload(decode=True)
                if not payload:
                    continue
                charset = part.get_content_charset() or "utf-8"
                decoded_str = payload.decode(charset, errors="replace")

                if content_type == "text/plain":
                    text_parts.append(decoded_str)
                elif content_type == "text/html":
                    html_parts.append(decoded_str)
            except Exception:
                continue
    else:
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            decoded_str = payload.decode(charset, errors="replace")
            if content_type == "text/html":
                html_parts.append(decoded_str)
            else:
                text_parts.append(decoded_str)

    html_content = "\n".join(html_parts)
    text_content = "\n".join(text_parts)

    # If no plain text, convert HTML to plain text using BeautifulSoup
    if not text_content and html_content:
        soup = BeautifulSoup(html_content, "html.parser")
        text_content = soup.get_text(separator="\n").strip()

    return text_content.strip(), html_content.strip(), has_attachments


class EmailService:
    @staticmethod
    def test_connection_sync(account: EmailAccount) -> Tuple[bool, str]:
        """Synchronously tests IMAP connection credentials with enhanced diagnostics."""
        clean_host = account.imap_host.strip()
        clean_username = account.username.strip() if account.username else account.email_address.strip()
        clean_password = account.password.replace(" ", "") if (len(account.password.replace(" ", "")) == 16 or "gmail" in clean_host.lower()) else account.password.strip()

        try:
            if account.imap_use_ssl:
                server = imaplib.IMAP4_SSL(clean_host, account.imap_port, timeout=20)
            else:
                server = imaplib.IMAP4(clean_host, account.imap_port, timeout=20)
            
            server.login(clean_username, clean_password)
            server.logout()
            return True, "Ulanish muvaffaqiyatli amalga oshirildi!"
        except (TimeoutError, socket.timeout) as e:
            return False, (
                f"Server bilan bog'lanish vaqti tugadi (Timeout: 20s).\n"
                f"Sabablari: 1) Internet provayderingiz yoki Wi-Fi tarmog'ingizda 993-port (IMAP) yopiq bo'lishi mumkin; "
                f"2) IMAP host ({clean_host}:{account.imap_port}) noto'g'ri; "
                f"3) Gmail uchun oddiy akkount paroli emas, 16 xonali 'App Password' kerak."
            )
        except (imaplib.IMAP4.error, imaplib.IMAP4.abort, imaplib.IMAP4.readonly) as e:
            err_msg = str(e)
            if "eof" in err_msg.lower():
                return False, (
                    "IMAP server ulanishni darhol uzdi (socket error: EOF).\n\n"
                    "Buning 2 ta asosiy sababi bor:\n"
                    "1. Gmail hisobingizda IMAP O'CHIRILGAN bo'lishi mumkin. Yoqish tartibi:\n"
                    "   • Gmail pochta sahifangizga kiring (mail.google.com)\n"
                    "   • Yuqori o'ng burchakdagi Tishli g'ildirakcha (Sozlamalar) -> 'See all settings' (Barcha sozlamalar)ni bosing\n"
                    "   • 'Forwarding and POP/IMAP' bo'limiga o'ting\n"
                    "   • 'IMAP Access' qismida 'Enable IMAP' (IMAP-ni yoqish)ni tanlang va pastda 'Save Changes'ni bosing.\n\n"
                    "2. Yoki provayderingiz tarmog'ida 993-port bloklangan bo'lishi mumkin. "
                    "Bunday holda 'Ulanishni tekshirmasdan saqlash' (Sinov rejimi) katakchasini belgilab ulanishingiz mumkin."
                )
            if "AUTHENTICATIONFAILED" in err_msg or "Invalid credentials" in err_msg:
                return False, (
                    "Autentifikatsiya xatosi: Parol yoki login noto'g'ri. "
                    "Agar Gmail bo'lsa, oddiy akkaunt paroli emas, Google Hisobingizdan (Security -> App Passwords) 16 xonali 'Ilova Paroli' yaratishingiz shart!"
                )
            return False, f"IMAP xatosi: {err_msg}"
        except Exception as e:
            err_str = str(e)
            if "timed out" in err_str.lower() or "timeout" in err_str.lower():
                return False, (
                    f"Server bilan bog'lanish vaqti tugadi (Timeout).\n"
                    f"Iltimos, IMAP server ({clean_host}:{account.imap_port}) va internet aloqasini tekshiring."
                )
            return False, f"Ulanishda xatolik: {err_str}"

    @classmethod
    async def test_connection(cls, account: EmailAccount) -> Tuple[bool, str]:
        """Asynchronously tests IMAP credentials in a thread pool."""
        return await asyncio.to_thread(cls.test_connection_sync, account)

    @staticmethod
    def fetch_emails_sync(account: EmailAccount, limit: int = 10, folder: str = "INBOX") -> List[Dict[str, Any]]:
        """Synchronously connects to IMAP, selects folder, and fetches recent emails."""
        results = []
        clean_host = account.imap_host.strip()
        clean_username = account.username.strip() if account.username else account.email_address.strip()
        clean_password = account.password.replace(" ", "") if (len(account.password.replace(" ", "")) == 16 or "gmail" in clean_host.lower()) else account.password.strip()

        try:
            if account.imap_use_ssl:
                server = imaplib.IMAP4_SSL(clean_host, account.imap_port, timeout=25)
            else:
                server = imaplib.IMAP4(clean_host, account.imap_port, timeout=25)

            server.login(clean_username, clean_password)
            status, _ = server.select(folder, readonly=True)
            if status != "OK":
                server.logout()
                return []

            # Search all or recent messages
            status, messages = server.search(None, "ALL")
            if status != "OK" or not messages or not messages[0]:
                server.logout()
                return []

            mail_ids = messages[0].split()
            # Get latest 'limit' messages
            recent_ids = mail_ids[-limit:]
            recent_ids.reverse()

            for msg_id in recent_ids:
                status, data = server.fetch(msg_id, "(RFC822)")
                if status != "OK" or not data:
                    continue

                for response_part in data:
                    if isinstance(response_part, tuple):
                        raw_msg = email.message_from_bytes(response_part[1])
                        
                        subject = _decode_mime_header(raw_msg.get("Subject"))
                        from_header = _decode_mime_header(raw_msg.get("From"))
                        to_header = _decode_mime_header(raw_msg.get("To"))
                        date_str = raw_msg.get("Date")
                        message_id = raw_msg.get("Message-ID", "")

                        real_name, sender_email = email.utils.parseaddr(from_header)
                        if not sender_email:
                            sender_email = from_header

                        # Parse date
                        parsed_date = datetime.utcnow()
                        if date_str:
                            try:
                                parsed_tuple = email.utils.parsedate_to_datetime(date_str)
                                if parsed_tuple:
                                    parsed_date = parsed_tuple.astimezone(timezone.utc).replace(tzinfo=None)
                            except Exception:
                                pass

                        text_body, html_body, has_attachments = _extract_email_body(raw_msg)
                        snippet = text_body[:200].replace("\n", " ").strip() if text_body else subject

                        results.append({
                            "message_id": message_id,
                            "sender_name": real_name or sender_email,
                            "sender_email": sender_email,
                            "recipient_email": to_header or account.email_address,
                            "subject": subject or "(No Subject)",
                            "snippet": snippet,
                            "body_text": text_body,
                            "body_html": html_body,
                            "received_at": parsed_date,
                            "has_attachments": has_attachments,
                        })

            server.logout()
        except Exception as e:
            print(f"[EmailService.fetch_emails_sync] Error: {e}")

        return results

    @classmethod
    async def fetch_emails(cls, account: EmailAccount, limit: int = 10) -> List[Dict[str, Any]]:
        """Asynchronously fetches emails in a worker thread."""
        return await asyncio.to_thread(cls.fetch_emails_sync, account, limit)

    @staticmethod
    def send_email_sync(
        account: EmailAccount,
        to_email: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Synchronously sends an email reply via SMTP."""
        clean_host = account.smtp_host.strip()
        clean_username = account.username.strip() if account.username else account.email_address.strip()
        clean_password = account.password.replace(" ", "") if (len(account.password.replace(" ", "")) == 16 or "gmail" in clean_host.lower()) else account.password.strip()

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"{clean_username} <{account.email_address}>"
            msg["To"] = to_email
            msg["Date"] = email.utils.formatdate(localtime=True)

            if in_reply_to:
                msg["In-Reply-To"] = in_reply_to
                msg["References"] = in_reply_to

            msg.attach(MIMEText(body, "plain", "utf-8"))

            if account.smtp_use_ssl:
                server = smtplib.SMTP_SSL(clean_host, account.smtp_port, timeout=25)
            else:
                server = smtplib.SMTP(clean_host, account.smtp_port, timeout=25)
                server.starttls()

            server.login(clean_username, clean_password)
            server.sendmail(account.email_address, [to_email], msg.as_string())
            server.quit()
            return True, "Xat muvaffaqiyatli jo'natildi!"
        except Exception as e:
            return False, f"Xat jo'natishda xatolik: {str(e)}"

    @classmethod
    async def send_email(
        cls,
        account: EmailAccount,
        to_email: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Asynchronously sends email via SMTP."""
        return await asyncio.to_thread(
            cls.send_email_sync, account, to_email, subject, body, in_reply_to
        )
