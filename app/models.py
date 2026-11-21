import enum
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum as SQLEnum
)
from sqlalchemy.orm import relationship
from app.db import Base


class CategoryEnum(str, enum.Enum):
    WORK = "Work"
    PERSONAL = "Personal"
    IMPORTANT = "Important"
    SPAM = "Spam / Suspicious"
    PROMOTIONS = "Promotions"
    OTHER = "Other"


class PriorityEnum(str, enum.Enum):
    URGENT = "Urgent"    # 🔴 Urgent
    HIGH = "High"        # 🟠 High
    NORMAL = "Normal"    # 🟡 Normal
    LOW = "Low"          # ⚪ Low


class ReplyToneEnum(str, enum.Enum):
    PROFESSIONAL = "Professional"
    FRIENDLY = "Friendly"
    SHORT = "Short"
    DETAILED = "Detailed"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    telegram_chat_id = Column(String(100), unique=True, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    accounts = relationship("EmailAccount", back_populates="user", cascade="all, delete-orphan")
    preferences = relationship("UserPreference", back_populates="user", uselist=False, cascade="all, delete-orphan")
    reminders = relationship("FollowUpReminder", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AgentAuditLog", back_populates="user", cascade="all, delete-orphan")


class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    email_address = Column(String(255), nullable=False)
    
    # IMAP Configuration
    imap_host = Column(String(255), default="imap.gmail.com")
    imap_port = Column(Integer, default=993)
    imap_use_ssl = Column(Boolean, default=True)

    # SMTP Configuration
    smtp_host = Column(String(255), default="smtp.gmail.com")
    smtp_port = Column(Integer, default=465)
    smtp_use_ssl = Column(Boolean, default=True)

    username = Column(String(255), nullable=False)
    password = Column(String(255), nullable=False)  # App Password
    
    is_active = Column(Boolean, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="accounts")
    emails = relationship("EmailMessage", back_populates="account", cascade="all, delete-orphan")


class EmailMessage(Base):
    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("email_accounts.id"), nullable=False)
    message_id = Column(String(255), index=True, nullable=True)  # RFC Message-ID
    
    sender_name = Column(String(255), default="")
    sender_email = Column(String(255), index=True, nullable=False)
    recipient_email = Column(String(255), default="")
    subject = Column(String(500), default="(No Subject)")
    snippet = Column(String(500), default="")
    body_text = Column(Text, default="")
    body_html = Column(Text, default="")
    
    received_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # AI Processed Metadata (Phase 2 Enhanced)
    category = Column(SQLEnum(CategoryEnum), default=CategoryEnum.OTHER, index=True)
    priority = Column(SQLEnum(PriorityEnum), default=PriorityEnum.NORMAL, index=True)
    key_takeaway = Column(String(500), nullable=True)  # 1-sentence TL;DR
    summary = Column(Text, nullable=True)              # 3-5 structured bullet points
    action_suggested = Column(String(255), nullable=True)
    action_items = Column(Text, nullable=True)         # JSON list of action items
    detected_deadline = Column(String(255), nullable=True)
    sentiment = Column(String(50), default="Neutral")  # Urgent, Positive, Inquiring, Critical, Neutral
    
    is_read = Column(Boolean, default=False)
    is_starred = Column(Boolean, default=False)
    has_attachments = Column(Boolean, default=False)
    ai_processed_at = Column(DateTime, nullable=True)

    account = relationship("EmailAccount", back_populates="emails")
    drafts = relationship("EmailDraft", back_populates="email", cascade="all, delete-orphan")
    reminders = relationship("FollowUpReminder", back_populates="email", cascade="all, delete-orphan")


class EmailDraft(Base):
    __tablename__ = "email_drafts"

    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(Integer, ForeignKey("email_messages.id"), nullable=False)
    tone = Column(SQLEnum(ReplyToneEnum), default=ReplyToneEnum.PROFESSIONAL)
    subject = Column(String(500), default="")
    body = Column(Text, nullable=False)
    is_sent = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)

    email = relationship("EmailMessage", back_populates="drafts")


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    
    preferred_tone = Column(SQLEnum(ReplyToneEnum), default=ReplyToneEnum.PROFESSIONAL)
    preferred_language = Column(String(50), default="Uzbek")  # Uzbek, English, Russian
    max_summary_bullets = Column(Integer, default=4)
    notify_urgent = Column(Boolean, default=True)
    notify_telegram = Column(Boolean, default=True)
    custom_instructions = Column(Text, default="Javoblar lo'nda, xushmuomala va professional bo'lsin.")
    signature = Column(String(255), default="Hurmat bilan,\nAI Email Agent")

    user = relationship("User", back_populates="preferences")


class FollowUpReminder(Base):
    __tablename__ = "follow_up_reminders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    email_id = Column(Integer, ForeignKey("email_messages.id"), nullable=True)
    
    reminder_text = Column(String(500), nullable=False)
    remind_at = Column(DateTime, nullable=False, index=True)
    is_completed = Column(Boolean, default=False)
    notified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="reminders")
    email = relationship("EmailMessage", back_populates="reminders")


class AgentAuditLog(Base):
    """Tracks Action Agent tool invocations, inputs, and results."""
    __tablename__ = "agent_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tool_name = Column(String(100), nullable=False)
    arguments_json = Column(Text, default="{}")
    result_summary = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="audit_logs")
