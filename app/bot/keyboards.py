from typing import Optional
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from app.models import ReplyToneEnum


def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Persistent bottom keyboard for fast navigation."""
    kb = [
        [KeyboardButton(text="📥 Inbox"), KeyboardButton(text="⭐ Muhim (Important)")],
        [KeyboardButton(text="📊 Xulosa (Summary)"), KeyboardButton(text="🔍 Qidiruv (Search)")],
        [KeyboardButton(text="🔄 Sinxronlash"), KeyboardButton(text="📧 Email Ulash")],
        [KeyboardButton(text="⏰ Eslatmalar"), KeyboardButton(text="⚙️ Sozlamalar")],
        [KeyboardButton(text="ℹ️ Yordam")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def get_connect_provider_keyboard() -> InlineKeyboardMarkup:
    """Provider selection keyboard for email connection in Telegram."""
    buttons = [
        [
            InlineKeyboardButton(text="🔴 Gmail (Tavsiya etiladi)", callback_data="connect_prov:gmail"),
            InlineKeyboardButton(text="🔵 Outlook / Hotmail", callback_data="connect_prov:outlook")
        ],
        [
            InlineKeyboardButton(text="🟣 Yahoo Mail", callback_data="connect_prov:yahoo"),
            InlineKeyboardButton(text="⚙️ Boshqa (Custom IMAP)", callback_data="connect_prov:custom")
        ],
        [
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="cancel_connect")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_email_list_keyboard(emails: list, page: int = 1, total_pages: int = 1) -> InlineKeyboardMarkup:
    """Inline buttons for each email in a list."""
    buttons = []
    priority_icons = {
        "Urgent": "🔴",
        "High": "🟠",
        "Normal": "🟡",
        "Low": "⚪"
    }

    for em in emails:
        p_icon = priority_icons.get(em.priority.value, "✉️")
        short_sub = em.subject[:32] + ("..." if len(em.subject) > 32 else "")
        buttons.append([
            InlineKeyboardButton(
                text=f"{p_icon} {short_sub}",
                callback_data=f"view_email:{em.id}"
            )
        ])

    # Navigation buttons
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Oldingi", callback_data=f"page:{page - 1}"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Keyingi ➡️", callback_data=f"page:{page + 1}"))
    
    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_email_detail_keyboard(email_id: int) -> InlineKeyboardMarkup:
    """Action buttons for a single email: Draft Reply, Summary, Reminder, Mark Read."""
    buttons = [
        [
            InlineKeyboardButton(text="📝 Javob draft tayyorlash", callback_data=f"draft_tone_select:{email_id}"),
            InlineKeyboardButton(text="📑 AI Xulosa", callback_data=f"summarize_email:{email_id}")
        ],
        [
            InlineKeyboardButton(text="⏰ Eslatma qo'yish (Follow-up)", callback_data=f"remind_quick_menu:{email_id}"),
            InlineKeyboardButton(text="⬅️ Ro'yxatga qaytish", callback_data="back_to_inbox")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tone_selection_keyboard(email_id: int) -> InlineKeyboardMarkup:
    """Buttons to select tone for generating draft."""
    buttons = [
        [
            InlineKeyboardButton(text="👔 Professional", callback_data=f"gen_draft:{email_id}:Professional"),
            InlineKeyboardButton(text="😊 Do'stona (Friendly)", callback_data=f"gen_draft:{email_id}:Friendly")
        ],
        [
            InlineKeyboardButton(text="⚡ Qisqa (Short)", callback_data=f"gen_draft:{email_id}:Short"),
            InlineKeyboardButton(text="📋 Batafsil (Detailed)", callback_data=f"gen_draft:{email_id}:Detailed")
        ],
        [
            InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"view_email:{email_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_reminder_quick_keyboard(email_id: int) -> InlineKeyboardMarkup:
    """Quick duration selection for Follow-up reminders."""
    buttons = [
        [
            InlineKeyboardButton(text="⏱️ 2 soatdan so'ng", callback_data=f"set_rem_hrs:{email_id}:2"),
            InlineKeyboardButton(text="⏱️ 6 soatdan so'ng", callback_data=f"set_rem_hrs:{email_id}:6")
        ],
        [
            InlineKeyboardButton(text="📅 Ertaga (24 soat)", callback_data=f"set_rem_hrs:{email_id}:24"),
            InlineKeyboardButton(text="📅 2 kundan keyin", callback_data=f"set_rem_hrs:{email_id}:48")
        ],
        [
            InlineKeyboardButton(text="⬅️ Ortga", callback_data=f"view_email:{email_id}")
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_settings_keyboard(
    current_tone: str = "Professional",
    current_lang: str = "Uzbek",
    notify_urgent: bool = True
) -> InlineKeyboardMarkup:
    """Settings modification keyboard with live checkmark status."""
    def mark(val, target):
        return f"✅ {val}" if val.lower() == target.lower() else val

    buttons = [
        [
            InlineKeyboardButton(text=f"👔 {mark('Professional', current_tone)}", callback_data="set_pref:tone:Professional"),
            InlineKeyboardButton(text=f"😊 {mark('Do\'stona', current_tone)}", callback_data="set_pref:tone:Friendly")
        ],
        [
            InlineKeyboardButton(text=f"⚡ {mark('Qisqa', current_tone)}", callback_data="set_pref:tone:Short"),
            InlineKeyboardButton(text=f"📋 {mark('Batafsil', current_tone)}", callback_data="set_pref:tone:Detailed")
        ],
        [
            InlineKeyboardButton(text=f"🇺🇿 {mark('O\'zbek', current_lang)}", callback_data="set_pref:lang:Uzbek"),
            InlineKeyboardButton(text=f"🇬🇧 {mark('English', current_lang)}", callback_data="set_pref:lang:English"),
            InlineKeyboardButton(text=f"🇷🇺 {mark('Русский', current_lang)}", callback_data="set_pref:lang:Russian")
        ],
        [
            InlineKeyboardButton(
                text=f"🔔 Shoshilinch xabarnomalar: {'Yoqilgan ✅' if notify_urgent else 'O\'chirilgan ❌'}",
                callback_data="set_pref:notify_toggle"
            )
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
