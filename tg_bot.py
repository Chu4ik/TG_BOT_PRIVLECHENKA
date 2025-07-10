# tg_bot/main.py

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand 
from config import TELEGRAM_TOKEN
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties 
from aiogram.types import Message, ReplyKeyboardRemove

# Импортируем функции для работы с пулом базы данных
from db_operations import init_db_pool, close_db_pool, get_employee_id

# Импортируем все роутеры из общего списка
from handlers import order_routers # order_routers уже содержит все необходимые роутеры

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
# order_routers уже содержит main_menu.router и add_delivery_handler.router,
# поэтому нет необходимости включать их отдельно.
dp.include_routers(
    *order_routers, # <--- ИСПРАВЛЕНО: Удалены дублирующиеся роутеры
)

# Функция для установки команд бокового меню
async def set_main_menu_commands(bot: Bot):
    """
    Устанавливает команды для бокового меню (меню-гамбургера).
    """
    commands = [
        BotCommand(command="/new_order", description="➕ Создать новый заказ"),
        BotCommand(command="/my_orders", description="📄 Посмотреть мои заказы"),
        BotCommand(command="/show_unconfirmed_orders", description="📝 Показать draft заказы"),
        BotCommand(command="/payments", description="💰 Оплаты клиентов"),
        BotCommand(command="/financial_report_today", description="📊 Отчет об оплатах за сегодня"),
        BotCommand(command="/add_delivery", description="🚚 Добавить поступление товара"),
        BotCommand(command="/inventory_report", description="📈 Отчет об остатках товара"),
        BotCommand(command="/edit_order_admin", description="✍️ Редактировать заказ")
    ]
    await bot.set_my_commands(commands)
    logging.info("Основные команды меню установлены.")

# Функція для коректного закриття пула БД
async def on_shutdown_cleanup(dispatcher: Dispatcher):
    """
    Хук, который выполняется при завершении работы диспетчера для закрытия пула БД.
    """
    logging.info("🧹 Выполняем cleanup при завершении работы...")
    db_pool = dispatcher.get("db_pool") # Получаем пул из контекста диспетчера
    if db_pool:
        await close_db_pool(db_pool)
        logging.info("Пул базы данных asyncpg успешно закрыт.")
    else:
        logging.warning("Пул базы данных не найден в контексте диспетчера при завершении работы.")


# Основная точка запуска
async def main():
    logging.info("🚀 Бот запускается...")
    db_pool = None 

    try:
        logging.info("Инициализация пула базы данных...")
        db_pool = await init_db_pool()
        logging.info("Пул базы данных инициализирован.")

        dp["db_pool"] = db_pool

        await set_main_menu_commands(bot) 

        dp.shutdown.register(on_shutdown_cleanup) 

        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except asyncio.CancelledError:
        logging.warning("⏹️ Бот был остановлен вручную (Ctrl+C)")
    except Exception as e:
        logging.exception(f"❌ Неожиданная ошибка: {e}")
    finally:
        logging.info("🧹 Завершение работы бота...")
        await bot.session.close()