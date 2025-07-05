import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand 
from config import TELEGRAM_TOKEN

# Импортируем функции для работы с пулом базы данных
from db_operations.db import init_db_pool, close_db_pool 

# Импортируем все роутеры из общего списка
from handlers import order_routers
from handlers.reports import order_confirmation_report

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
        BotCommand(command="/show_unconfirmed_orders", description="Показать draft заказы"),
        # Добавьте другие команды, если они у вас есть
    ]
    await bot.set_my_commands(commands)
    logging.info("Основные команды меню установлены.")


# Основная точка запуска
async def main():
    logging.info("🚀 Бот запускается...")
    db_pool = None # Объявляем здесь, чтобы быть уверенными

    try:
        # Инициализация пула базы данных ДО запуска polling
        logging.info("Инициализация пула базы данных...")
        db_pool = await init_db_pool() # <--- СОХРАНЯЕМ ВОЗВРАЩЕННЫЙ ПУЛ
        logging.info("Пул базы данных инициализирован.")

        # Передаем пул в контекст диспетчера
        dp["db_pool"] = db_pool # <--- ДОБАВЛЕНО: ПЕРЕДАЕМ ПУЛ В КОНТЕКСТ ДИСПЕТЧЕРА

        # Устанавливаем команды главного меню перед запуском polling
        await set_main_menu_commands(bot) 

        # Регистрируем хук для закрытия пула при остановке бота
        # Используем лямбда-функцию, чтобы передать pool как аргумент
        dp.shutdown.register(lambda: close_db_pool(db_pool)) # <--- ИЗМЕНЕНО

        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logging.warning("⏹️ Бот был остановлен вручную (Ctrl+C)")
    except Exception as e:
        logging.exception(f"❌ Неожиданная ошибка: {e}")
    finally:
        logging.info("🧹 Завершение работы бота...")
        # Закрываем сессию бота при завершении работы
        await bot.session.close()

