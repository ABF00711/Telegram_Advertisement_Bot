import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import router
from config import BOT_TOKEN, LOG_DIR
from database.database import init_db
from scheduler.manager import set_bot, shutdown_scheduler, start_scheduler
from telegram.channel_manager import sync_channels
from telegram.user_client import connect_user_account, get_client

logger = logging.getLogger(__name__)


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
        ],
    )
    logging.getLogger("telethon").setLevel(logging.WARNING)


async def main() -> None:
    setup_logging()
    await init_db()

    bot = Bot(token=BOT_TOKEN)
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher.include_router(router)
    set_bot(bot)

    try:
        await connect_user_account()
        try:
            summary = await sync_channels()
            logger.info(
                "Startup channel sync: %s found, %s can post",
                summary["total"],
                summary["postable"],
            )
        except Exception:
            logger.exception("Could not refresh channels at startup. Use /channels after the bot is up.")

        await start_scheduler()
        logger.info("Management bot is polling")
        await dispatcher.start_polling(bot)
    finally:
        shutdown_scheduler()
        current = get_client()
        if current.is_connected():
            await current.disconnect()
        await bot.session.close()
        logger.info("Application stopped")


if __name__ == "__main__":
    asyncio.run(main())
