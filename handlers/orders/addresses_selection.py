# handlers/orders/addresses_selection.py

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
import asyncpg.exceptions # Добавляем импорт для асинхронных ошибок БД

# Ленивый импорт для product_selection, чтобы избежать циклических зависимостей
from handlers.orders.product_selection import send_all_products
from handlers.orders.order_editor import escape_markdown_v2 

router = Router()
logger = logging.getLogger(__name__)

def build_address_keyboard(addresses: list) -> InlineKeyboardMarkup:
    """Строит клавиатуру с адресами для выбора."""
    buttons = []
    for addr in addresses:
        buttons.append([InlineKeyboardButton(text=addr['address_text'], callback_data=f"address:{addr['address_id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
@router.callback_query(F.data.startswith("address:"))
async def process_address_selection(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ДОБАВЬТЕ db_pool СЮДА
    address_id = int(callback.data.split(":")[1])
    conn = None
    try:
        conn = await db_pool.acquire() # Эта строка (или похожая) требует 'pool'
        # Получаем данные адреса, чтобы сохранить client_id, address_id и т.д.
        # Вероятно, это запрос, который был у вас на строке 57
        address_info = await conn.fetchrow("SELECT client_id, address_text FROM addresses WHERE address_id = $1", address_id)
        
        if address_info:
            await state.update_data(address_id=address_id, address_text=address_info['address_text'])
            await callback.answer(f"Адрес выбран: {address_info['address_text']}", show_alert=True)
            await callback.message.edit_text(f"✅ Выбран адрес: *{address_info['address_text']}*", parse_mode="MarkdownV2", reply_markup=None)
            
            # Переходим к следующему состоянию, например, выбору продукта
            await send_all_products(callback.message, state, db_pool) # Пример, передайте db_pool, если send_all_products его использует
            await state.set_state(OrderFSM.selecting_product) # Пример состояния
        else:
            await callback.answer("Ошибка при выборе адреса. Попробуйте снова.", show_alert=True)

    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при выборе адреса: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при выборе адреса. Попробуйте снова.", show_alert=True)
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в process_address_selection: {e}", exc_info=True)
        await callback.answer("Произошла непредвиденная ошибка. Попробуйте снова.", show_alert=True)
    finally:
        if conn:
            await db_pool.release(conn) # Используйте db_pool и здесь
    await callback.answer()

# Любые другие функции в этом файле, которые напрямую запрашивают базу данных, также нуждаются в 'pool' в качестве аргумента.
# Например, если у вас есть вспомогательная функция для получения адресов:
async def get_addresses_from_db(pool, client_id: int): # <--- ДОБАВЬТЕ pool СЮДА
    conn = None
    try:
        conn = await pool.acquire()
        addresses = await conn.fetch("SELECT address_id, address_text FROM addresses WHERE client_id = $1", client_id)
        return addresses
    finally:
        if conn:
            await pool.release(conn)