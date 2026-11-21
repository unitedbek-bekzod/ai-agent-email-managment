import asyncio
import logging
from typing import Optional
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.client.default import DefaultBotProperties
from app.config import settings
from app.bot.handlers import router

logger = logging.getLogger("telegram_bot")

bot: Optional[Bot] = None
dp: Optional[Dispatcher] = None
polling_task: Optional[asyncio.Task] = None


def setup_bot() -> Optional[Bot]:
    global bot, dp
    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN topilmadi. Telegram bot faollashtirilmadi. (.env faylda belgilang)")
        return None

    bot = Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    return bot


async def start_bot_polling():
    """Starts aiogram bot polling in the background."""
    global bot, dp, polling_task
    if not settings.TELEGRAM_BOT_TOKEN:
        return

    try:
        if not bot or not dp:
            setup_bot()
        if bot and dp:
            logger.info("Telegram Bot polling ishga tushmoqda...")
            # Delete any existing webhook to avoid conflicts
            await bot.delete_webhook(drop_pending_updates=True)
            polling_task = asyncio.create_task(dp.start_polling(bot))
    except Exception as e:
        logger.error(f"Telegram Bot ishga tushirishda xatolik: {e}")


async def stop_bot_polling():
    """Gracefully shuts down bot polling."""
    global bot, dp, polling_task
    if polling_task and not polling_task.done():
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
    if bot:
        await bot.session.close()
