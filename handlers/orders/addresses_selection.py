# handlers/orders/addresses_selection.py

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from db_operations.db import get_connection, get_dict_cursor # Убедитесь, что get_dict_cursor импортирован

# Ленивый импорт для product_selection, чтобы избежать циклических зависимостей
from handlers.orders.product_selection import send_all_products

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
    
    await state.update_data(address_id=address_id) 

    await callback.message.edit_text("Адрес доставки выбран. Начните добавлять товары в корзину.")
    await callback.answer("Адрес выбран.", show_alert=True)

    from handlers.orders.product_selection import send_all_products
    await send_all_products(callback.message, state)