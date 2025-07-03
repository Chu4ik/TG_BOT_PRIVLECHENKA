# handlers/orders/client_selection.py

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from db_operations.db import get_connection, get_dict_cursor 

from utils.order_cache import order_cache, calculate_default_delivery_date
from handlers.orders.addresses_selection import build_address_keyboard 
from handlers.orders.product_selection import send_all_products 

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "✅ Создать заказ") 
@router.message(F.text == "/new_order") 
async def start_order_process(message: Message, state: FSMContext):
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
            cart=cached_data.get("cart", []),
            delivery_date=cached_data.get("delivery_date"),
            last_cart_message_id=cached_data.get("last_cart_message_id"),
            last_cart_chat_id=cached_data.get("last_cart_chat_id")
        )
        state_data = await state.get_data() 
        current_client_id = state_data.get("client_id")
        current_address_id = state_data.get("address_id")
        current_cart = state_data.get("cart")
        current_delivery_date = state_data.get("delivery_date")
        logger.info(f"FSM-состояние инициализировано из order_cache для пользователя {user_id}")

    if current_delivery_date is None:
        default_date = calculate_default_delivery_date()
        await state.update_data(delivery_date=default_date)
        logger.info(f"Дефолтная дата доставки установлена для пользователя {user_id}: {default_date}")

    if current_client_id:
        conn = get_connection()
        cur = get_dict_cursor(conn) 
        # ИЗМЕНЕНО: id -> address_id, full_address -> address_text
        cur.execute("SELECT address_id, address_text FROM addresses WHERE client_id = %s", (current_client_id,))
        addresses = cur.fetchall()
        cur.close()
        conn.close()

        if addresses:
            if current_address_id and any(addr['address_id'] == current_address_id for addr in addresses): # ИЗМЕНЕНО: id -> address_id
                await message.answer("Клиент и адрес выбраны. Готовы к оформлению заказа.")
                await send_all_products(message, state)
            else:
                await message.answer("Выберите адрес доставки:", reply_markup=build_address_keyboard(addresses))
                await state.set_state(OrderFSM.selecting_address)
        else:
            await message.answer("У этого клиента нет зарегистрированных адресов. Пожалуйста, добавьте адрес или выберите другого клиента.")
            await state.set_state(OrderFSM.entering_client_name)
    else:
        await message.answer("Введите имя или название клиента:")
        await state.set_state(OrderFSM.entering_client_name)


@router.message(StateFilter(OrderFSM.entering_client_name))
async def process_client_name(message: Message, state: FSMContext):
    client_name = message.text
    conn = get_connection()
    cur = get_dict_cursor(conn) 
    cur.execute("SELECT client_id, name FROM clients WHERE name LIKE %s", (f"%{client_name}%",))
    clients = cur.fetchall()
    cur.close()
    conn.close()

    if clients:
        if len(clients) == 1:
            selected_client = clients[0] 
            await state.update_data(client_id=selected_client['client_id'])
            
            conn = get_connection()
            cur = get_dict_cursor(conn) 
            # ИЗМЕНЕНО: id -> address_id, full_address -> address_text
            cur.execute("SELECT address_id, address_text FROM addresses WHERE client_id = %s", (selected_client['client_id'],))
            addresses = cur.fetchall()
            cur.close()
            conn.close()

            if addresses:
                await message.answer("Выберите адрес доставки:", reply_markup=build_address_keyboard(addresses))
                await state.set_state(OrderFSM.selecting_address)
            else:
                await message.answer("У этого клиента нет зарегистрированных адресов. Пожалуйста, добавьте адрес или выберите другого клиента.")
                await state.set_state(OrderFSM.entering_client_name)
        else:
            buttons = [[InlineKeyboardButton(text=c['name'], callback_data=f"client:{c['client_id']}")] for c in clients]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("Найдено несколько клиентов. Выберите одного:", reply_markup=keyboard)
            await state.set_state(OrderFSM.selecting_multiple_clients)
    else:
        await message.answer("Клиент с таким именем не найден. Пожалуйста, попробуйте еще раз или введите другое имя.")


@router.callback_query(StateFilter(OrderFSM.selecting_multiple_clients), F.data.startswith("client:"))
async def select_client_from_list(callback: CallbackQuery, state: FSMContext):
    client_id = int(callback.data.split(":")[1])
    await state.update_data(client_id=client_id)

    conn = get_connection()
    cur = get_dict_cursor(conn) 
    # ИЗМЕНЕНО: id -> address_id, full_address -> address_text
    cur.execute("SELECT address_id, address_text FROM addresses WHERE client_id = %s", (client_id,))
    addresses = cur.fetchall()
    cur.close()
    conn.close()

    await callback.answer(f"Клиент выбран: {callback.message.text}", show_alert=True)
    await callback.message.delete()

    if addresses:
        await callback.message.answer("Выберите адрес доставки:", reply_markup=build_address_keyboard(addresses))
        await state.set_state(OrderFSM.selecting_address)
    else:
        await callback.message.answer("У этого клиента нет зарегистрированных адресов. Пожалуйста, добавьте адрес или выберите другого клиента.")
        await state.set_state(OrderFSM.entering_client_name)