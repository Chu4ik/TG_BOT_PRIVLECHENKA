import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
import re

import asyncpg.exceptions 

from utils.order_cache import order_cache, calculate_default_delivery_date
from handlers.orders.addresses_selection import build_address_keyboard 
from handlers.orders.product_selection import send_all_products 
# from handlers.orders.order_editor import escape_markdown_v2 # <- Если escape_markdown_v2 определена ниже, этот импорт не нужен

router = Router()
logger = logging.getLogger(__name__)

# Убедитесь, что эта функция определена или импортирована корректно
def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!' 
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)

@router.message(F.text == "✅ Создать заказ") 
@router.message(F.text == "/new_order") 
async def start_order_process(message: Message, state: FSMContext, db_pool):
    user_id = message.from_user.id
    
    state_data = await state.get_data()
    
    current_client_id = state_data.get("client_id")
    current_address_id = state_data.get("address_id")
    current_cart = state_data.get("cart")
    current_delivery_date = state_data.get("delivery_date")

    if not current_client_id and user_id in order_cache:
        cached_data = order_cache[user_id]
        await state.update_data(
            client_id=cached_data.get("client_id"),
            address_id=cached_data.get("address_id"),
            cart=cached_data.get("cart"),
            delivery_date=cached_data.get("delivery_date")
        )
        logger.info(f"Loaded cached order for user {user_id}: {await state.get_data()}")
    
    state_data_after_cache_load = await state.get_data()
    if not state_data_after_cache_load.get("delivery_date"):
        default_date = calculate_default_delivery_date()
        await state.update_data(delivery_date=default_date)
        logger.info(f"Set default delivery date for user {user_id}: {default_date}")

    await message.answer("Пожалуйста, введите имя или название клиента для поиска:")
    await state.set_state(OrderFSM.entering_client_name)


@router.message(StateFilter(OrderFSM.entering_client_name))
async def process_client_name_input(message: Message, state: FSMContext, db_pool):
    client_name_query = message.text.strip()
    conn = None 
    try:
        conn = await db_pool.acquire() 
        clients = await conn.fetch("SELECT client_id, name FROM clients WHERE name ILIKE $1", f"%{client_name_query}%")
        
        if clients:
            if len(clients) == 1:
                client = clients[0] 
                await state.update_data(client_id=client['client_id'], client_name=client['name']) # <-- ИЗМЕНЕНО: client['client_id'], client['name']
                await message.answer(f"✅ Выбран клиент: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2") # <-- ИЗМЕНЕНО: client['name']
                
                addresses = await conn.fetch("SELECT address_id, address_text FROM addresses WHERE client_id = $1", client['client_id']) # <-- ИЗМЕНЕНО: client['client_id']

                if addresses:
                    await message.answer("Выберите адрес доставки:", reply_markup=build_address_keyboard(addresses))
                    await state.set_state(OrderFSM.selecting_address)
                else:
                    await message.answer(f"Для клиента *{escape_markdown_v2(client['name'])}* не найдено адресов. Пожалуйста, добавьте адрес вручную или выберите другого клиента.", parse_mode="MarkdownV2")
                    await state.clear()
                    await message.answer("Вы можете начать новый заказ.")
            else:
                buttons = []
                for client in clients:
                    escaped_client_name = escape_markdown_v2(client['name']) # <-- ИЗМЕНЕНО: client['name']
                    buttons.append([InlineKeyboardButton(text=escaped_client_name, callback_data=f"select_client_{client['client_id']}")]) # <-- ИЗМЕНЕНО: client['client_id']
                keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                await message.answer(escape_markdown_v2("Найдено несколько клиентов. Выберите одного:"), reply_markup=keyboard, parse_mode="MarkdownV2")
                await state.set_state(OrderFSM.selecting_multiple_clients)
        else:
            await message.answer("Клиент с таким именем не найден. Пожалуйста, попробуйте еще раз или введите другое имя.")
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при поиске клиента: {e}", exc_info=True)
        await message.answer("Произошла ошибка при поиске клиента. Пожалуйста, попробуйте еще раз.")
        await state.clear()
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в process_client_name_input: {e}", exc_info=True)
        await message.answer(escape_markdown_v2("Произошла непредвиденная ошибка. Пожалуйста, попробуйте еще раз."), parse_mode="MarkdownV2")
        await state.clear()
    finally:
        if conn:
            await db_pool.release(conn)


@router.callback_query(StateFilter(OrderFSM.selecting_multiple_clients), F.data.startswith("select_client_"))
async def select_client_from_list(callback: CallbackQuery, state: FSMContext, db_pool):
    client_id = int(callback.data.split("select_client_")[1])
    conn = None 
    try:
        conn = await db_pool.acquire() 
        client = await conn.fetchrow("SELECT client_id, name FROM clients WHERE client_id = $1", client_id)
        
        if client:
            await state.update_data(client_id=client['client_id'], client_name=client['name']) # <-- ИЗМЕНЕНО: client['client_id'], client['name']
            await callback.answer(f"Клиент выбран: {client['name']}", show_alert=True) # <-- ИЗМЕНЕНО: client['name']
            await callback.message.edit_text(f"✅ Выбран клиент: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2", reply_markup=None) # <-- ИЗМЕНЕНО: client['name']
            
            addresses = await conn.fetch("SELECT address_id, address_text FROM addresses WHERE client_id = $1", client_id)

            if addresses:
                await callback.message.answer("Выберите адрес доставки:", reply_markup=build_address_keyboard(addresses))
                await state.set_state(OrderFSM.selecting_address)
            else:
                await callback.message.answer(f"Для клиента *{escape_markdown_v2(client['name'])}* не найдено адресов. Пожалуйста, добавьте адрес вручную или выберите другого клиента.", parse_mode="MarkdownV2")
                await state.clear()
                await callback.message.answer("Вы можете начать новый заказ.")
        else:
            await callback.answer("Ошибка при выборе клиента. Попробуйте снова.", show_alert=True)
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при выборе клиента из списка: {e}", exc_info=True)
        await callback.answer("Произошла ошибка при выборе клиента. Попробуйте снова.", show_alert=True)
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в select_client_from_list: {e}", exc_info=True)
        await callback.answer("Произошла непредвиденная ошибка. Попробуйте снова.", show_alert=True)
    finally:
        if conn:
            await db_pool.release(conn) 
    await callback.answer()