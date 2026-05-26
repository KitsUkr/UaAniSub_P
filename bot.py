import asyncio
import logging
import logging.handlers
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiohttp import web

import monobank
import webhook
from config import (
    BOT_TOKEN,
    MONO_JAR_SEND_ID,
    MONO_TOKEN,
    WEBHOOK_HOST,
    WEBHOOK_PATH,
    WEBHOOK_PORT,
    WEBHOOK_URL,
)
from database import close_db, expire_old_pending_payments, init_db
from handlers import admin, user

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.handlers.RotatingFileHandler(
            "bot.log",
            encoding="utf-8",
            maxBytes=5_000_000,
            backupCount=3,
        ),
    ],
)
logger = logging.getLogger(__name__)


async def _expiry_loop(interval_sec: int = 600) -> None:
    """Періодично позначає прострочені pending-платежі як expired."""
    while True:
        try:
            n = await expire_old_pending_payments()
            if n:
                logger.info("Позначено %d прострочених платежів як expired", n)
        except Exception as exc:
            logger.exception("Помилка в expiry loop: %s", exc)
        await asyncio.sleep(interval_sec)


async def main():
    logger.info("Ініціалізація...")

    await init_db()
    logger.info("База даних ініціалізована")

    await monobank.init(MONO_TOKEN, MONO_JAR_SEND_ID)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    dp = Dispatcher()
    dp.include_router(admin.router)
    dp.include_router(user.router)

    app = webhook.build_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    logger.info(
        "Webhook слухає %s:%d, шлях %s",
        WEBHOOK_HOST, WEBHOOK_PORT, WEBHOOK_PATH,
    )

    # Реєструємо URL у Monobank. Якщо не вдалося — попереджаємо, але не падаємо
    # (могло вже бути встановлено раніше або є rate-limit 60 сек).
    try:
        await monobank.set_webhook(WEBHOOK_URL)
    except Exception as exc:
        logger.warning(
            "Не вдалося зареєструвати webhook (%s). "
            "Якщо URL вже встановлено раніше — це нормально. "
            "Інакше перевірте доступність URL ззовні.",
            exc,
        )

    expiry_task = asyncio.create_task(_expiry_loop())

    logger.info("Бот запущено! Очікування повідомлень...")
    try:
        await dp.start_polling(
            bot,
            allowed_updates=[
                "message",
                "callback_query",
                "my_chat_member",
            ],
        )
    finally:
        expiry_task.cancel()
        await runner.cleanup()
        await bot.session.close()
        await monobank.close()
        await close_db()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот зупинено")
