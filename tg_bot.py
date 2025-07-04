import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand # <-- ДОДАЙТЕ ЦЕЙ ІМПОРТ
from config import TELEGRAM_TOKEN

# Імпортуємо всі роутери з загального списку
from handlers import order_routers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Створення бота
bot = Bot(token=TELEGRAM_TOKEN)

# Створення диспетчера
dp = Dispatcher(storage=MemoryStorage())

# Підключення всіх роутерів з списку order_routers
dp.include_routers(
    *order_routers
)

# Функція для встановлення команд бокового меню
async def set_main_menu_commands(bot: Bot):
    """
    Устанавливает команды для бокового меню (меню-гамбургера).
    """
    commands = [
        BotCommand(command="/start", description="Начать работу с ботом"),
        BotCommand(command="/new_order", description="Создать новый заказ"),
        BotCommand(command="/my_orders", description="Посмотреть мои заказы"),
        # Добавьте другие команды, если они у вас есть, например:
        # BotCommand(command="/help", description="Получить помощь")
    ]
    await bot.set_my_commands(commands)
    logging.info("Основные команды меню установлены.")


# Основная точка запуска
async def main():
    logging.info("🚀 Бот запускается...")

    try:
        # Устанавливаем команды главного меню перед запуском polling
        await set_main_menu_commands(bot) # <-- ВИКЛИК ФУНКЦІЇ ТУТ!

        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logging.warning("⏹️ Бот был остановлен вручную (Ctrl+C)")
    except Exception as e:
        logging.exception(f"❌ Неожиданная ошибка: {e}")
    finally:
        logging.info("🧹 Завершение работы бота...")

