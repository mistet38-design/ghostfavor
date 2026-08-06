import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import BOT_TOKEN
from database.session import init_db
from handlers import admin, exchange, listings, profile, report, start, wallet
from services.middleware import BanCheckMiddleware, ThrottlingMiddleware
from services.scheduler import demarrer_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN n'est pas défini.")

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="Markdown"))

    # MemoryStorage = OK pour un seul worker. Pour plusieurs instances,
    # remplacer par RedisStorage (voir README, section "Scalabilité").
    dp = Dispatcher(storage=MemoryStorage())

    dp.update.outer_middleware(BanCheckMiddleware())
    dp.update.outer_middleware(ThrottlingMiddleware())

    dp.include_router(start.router)
    dp.include_router(listings.router)
    dp.include_router(exchange.router)
    dp.include_router(wallet.router)
    dp.include_router(report.router)
    dp.include_router(profile.router)
    dp.include_router(admin.router)

    scheduler = demarrer_scheduler(bot)

    logger.info("QuietSwap démarré...")
    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
