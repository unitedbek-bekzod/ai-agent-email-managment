import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "AI Email Management Agent"
    VERSION: str = "0.1.0"
    DEBUG: bool = True

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./email_agent.db"

    # Telegram Bot
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_BOT_USERNAME: Optional[str] = "YourEmailAgentBot"

    # AI Model Providers
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-1.5-flash"

    GROQ_API_KEY: Optional[str] = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    DEFAULT_LLM_PROVIDER: str = "auto"  # auto, openai, gemini, groq, heuristic

    # User Preferences Defaults
    DEFAULT_REPLY_TONE: str = "Professional"  # Professional, Friendly, Short, Detailed
    DEFAULT_LANGUAGE: str = "Uzbek"  # Uzbek, English, Russian
    MAX_SUMMARY_BULLETS: int = 4

    # Background Scheduler
    SYNC_INTERVAL_MINUTES: int = 2
    REMINDER_CHECK_INTERVAL_SECONDS: int = 60

    # Web Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    SECRET_KEY: str = "super-secret-key-change-in-production-12345"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
