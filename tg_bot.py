import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import TELEGRAM_TOKEN

from handlers.main_menu import router as menu_router
from handlers.orders.client_selection import router as client_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Создание бота и диспетчера
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# Подключение роутеров
dp.include_routers(
    menu_router,
    client_router,
    # добавляй остальные по мере написания
)

# Основная точка запуска
async def main():
    logging.info("🚀 Бот запускается...")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logging.warning("⏹️ Бот был остановлен вручную (Ctrl+C)")
    except Exception as e:
        logging.exception(f"❌ Неожиданная ошибка: {e}")
    finally:
        logging.info("🧹 Завершение работы бота...")

