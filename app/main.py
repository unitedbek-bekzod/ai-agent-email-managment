import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.config import settings
from app.db import init_db, AsyncSessionLocal
from app.services.mock_data import seed_initial_demo_data
from app.bot.bot import setup_bot, start_bot_polling, stop_bot_polling
from app.services.scheduler import start_scheduler, stop_scheduler, scheduler
from app.web.routes import router as web_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("email_agent_app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    logger.info("Initializing Database...")
    await init_db()

    # Seed demo data if database is fresh
    async with AsyncSessionLocal() as session:
        seeded = await seed_initial_demo_data(session)
        if seeded:
            logger.info("Demo user, preferences and analyzed emails successfully seeded!")

    # Start Telegram Bot if configured
    if settings.TELEGRAM_BOT_TOKEN:
        logger.info("Starting Telegram Bot Polling...")
        await start_bot_polling()
    else:
        logger.info("TELEGRAM_BOT_TOKEN not provided. Bot polling skipped. (Set token in .env to enable Telegram bot)")

    # Start Background Scheduler (Email Sync & Reminders)
    logger.info("Starting APScheduler background tasks...")
    start_scheduler()

    yield

    # Shutdown sequence
    logger.info("Shutting down application...")
    stop_scheduler()
    await stop_bot_polling()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Agentic AI Email Management and Telegram Bot Platform",
    lifespan=lifespan
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Web and API routes
app.include_router(web_router)


@app.get("/health")
async def health_check():
    from app.services.scheduler import scheduler
    return {
        "status": "healthy",
        "version": settings.VERSION,
        "bot_configured": bool(settings.TELEGRAM_BOT_TOKEN),
        "scheduler_running": bool(scheduler and scheduler.running),
        "llm_provider": settings.DEFAULT_LLM_PROVIDER
    }


def main():
    """CLI launcher."""
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )


if __name__ == "__main__":
    main()
