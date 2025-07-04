# handlers/orders/addresses_selection.py

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from db_operations.db import get_connection, get_dict_cursor 

# Ленивый импорт для product_selection, чтобы избежать циклических зависимостей
from handlers.orders.product_selection import send_all_products
from handlers.orders.order_editor import escape_markdown_v2 # ДОБАВЛЕН ИМПОРТ

router = Router()
logger = logging.getLogger(__name__)

def build_address_keyboard(addresses: list) -> InlineKeyboardMarkup:
    """Строит клавиатуру с адресами для выбора."""
    buttons = []
    for addr in addresses:
        # ИЗМЕНЕНО: addr['full_address'] -> addr['address_text'], addr['id'] -> addr['address_id']
        buttons.append([InlineKeyboardButton(text=addr['address_text'], callback_data=f"address:{addr['address_id']}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.callback_query(StateFilter(OrderFSM.selecting_address), F.data.startswith("address:"))
async def process_address_selection(callback: CallbackQuery, state: FSMContext):
    address_id = int(callback.data.split(":")[1])
    
    conn = get_connection()
    cur = get_dict_cursor(conn)
    cur.execute("SELECT address_id, address_text FROM addresses WHERE address_id = %s", (address_id,))
    address = cur.fetchone()
    cur.close()
    conn.close()

    if address:
        await state.update_data(address_id=address['address_id'], address_text=address['address_text']) # Сохраняем address_text в состояние
        
        await callback.message.edit_text(
            f"✅ Выбран адрес: *{escape_markdown_v2(address['address_text'])}*",
            parse_mode="MarkdownV2",
            reply_markup=None # Убираем кнопки адресов
        ) # ИЗМЕНЕНО: Теперь сообщение включает выбранный адрес и убирает кнопки
        
        # Теперь переходим к следующему шагу: выбор товаров
        await send_all_products(callback.message, state)
    else:
        await callback.answer("Ошибка при выборе адреса. Попробуйте снова.", show_alert=True)
    await callback.answer()