# tg_bot/tg_bot.py

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand 
from config import TELEGRAM_TOKEN
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties 

# Импортируем функции для работы с пулом базы данных
from db_operations import init_db_pool, close_db_pool, get_employee_id

# Импортируем все роутеры из общего списка
from handlers import order_routers
from handlers.reports import order_confirmation_report
from handlers.reports import my_orders_report
from handlers.reports import client_payments_report # <--- Убедитесь, что этот роутер импортирован

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# Создание бота
bot = Bot(
    token=TELEGRAM_TOKEN, 
    default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN_V2)
)

# Создание диспетчера
dp = Dispatcher(storage=MemoryStorage())

# Подключение всех роутеров из списка order_routers
# Убедитесь, что все ваши роутеры здесь явно перечислены или корректно импортируются через order_routers
dp.include_routers(
    *order_routers,
)

# Функция для установки команд бокового меню
async def set_main_menu_commands(bot: Bot):
    """
    Устанавливает команды для бокового меню (меню-гамбургера).
    """
    commands = [
        BotCommand(command="/start", description="Начать работу с ботом"),
        BotCommand(command="/new_order", description="Создать новый заказ"),
        BotCommand(command="/my_orders", description="Посмотреть мои заказы"),
        BotCommand(command="/show_unconfirmed_orders", description="Показать draft заказы"),
        BotCommand(command="/payments", description="💰 Оплаты клиентов"),
        BotCommand(command="/financial_report_today", description="📊 Отчет об оплатах за сегодня"),
        BotCommand(command="/incoming_deliveries_today", description="📦 Поступления товара за сегодня"),
        BotCommand(command="/supplier_payments_today", description="💸 Оплаты поставщикам за сегодня")
    ]
    await bot.set_my_commands(commands)
    logging.info("Основные команды меню установлены.")

# НОВАЯ ФУНКЦИЯ ДЛЯ КОРРЕКТНОГО ЗАКРЫТИЯ ПУЛА БД
async def on_shutdown_cleanup(dispatcher: Dispatcher):
    """
    Хук, который выполняется при завершении работы диспетчера для закрытия пула БД.
    """
    logging.info("🧹 Выполняем cleanup при завершении работы...")
    db_pool = dispatcher.get("db_pool") # Получаем пул из контекста диспетчера
    if db_pool:
        await close_db_pool(db_pool) # <-- ВОТ ЗДЕСЬ МЫ ЕГО ДОЖИДАЕМСЯ
        logging.info("Пул базы данных asyncpg успешно закрыт.")
    else:
        logging.warning("Пул базы данных не найден в контексте диспетчера при завершении работы.")


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
        # !!! ИЗМЕНИТЕ ЭТУ СТРОКУ !!!
        # Было: dp.shutdown.register(lambda: close_db_pool(db_pool))
        # Стало:
        dp.shutdown.register(on_shutdown_cleanup) # <--- РЕГИСТРИРУЕМ НОВУЮ ФУНКЦИЮ

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