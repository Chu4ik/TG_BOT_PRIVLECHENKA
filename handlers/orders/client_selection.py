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
from handlers.orders.order_editor import escape_markdown_v2 # ДОБАВЛЕН ИМПОРТ

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
            cart=cached_data.get("cart"),
            delivery_date=cached_data.get("delivery_date")
        )
        logger.info(f"Loaded cached order for user {user_id}: {await state.get_data()}")

    await message.answer("Пожалуйста, введите имя или название клиента для поиска:")
    await state.set_state(OrderFSM.entering_client_name)


@router.message(StateFilter(OrderFSM.entering_client_name))
async def process_client_name_input(message: Message, state: FSMContext):
    client_name_query = message.text.strip()
    conn = get_connection()
    cur = get_dict_cursor(conn)
    cur.execute("SELECT client_id, name FROM clients WHERE name ILIKE %s", (f"%{client_name_query}%",))
    clients = cur.fetchall()
    cur.close()
    conn.close()

    if clients:
        if len(clients) == 1:
            client = clients[0]
            await state.update_data(client_id=client['client_id'], client_name=client['name'])
            await message.answer(f"✅ Выбран клиент: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2") # ДОБАВЛЕНО СООБЩЕНИЕ
            # Переходим к выбору адреса, вызывая show_addresses_for_client
            # Это предполагает, что show_addresses_for_client находится в addresses_selection.py
            # или должна быть импортирована. Если show_addresses_for_client нет,
            # то здесь нужно будет реализовать логику показа адресов или вызвать build_address_keyboard
            
            # ВНИМАНИЕ: Предполагается, что show_addresses_for_client вызывается здесь
            # Если такой функции нет, то это место, где должна быть логика получения адресов
            # и вызова build_address_keyboard, а затем установка состояния selecting_address.
            conn = get_connection()
            cur = get_dict_cursor(conn) 
            cur.execute("SELECT address_id, address_text FROM addresses WHERE client_id = %s", (client['client_id'],))
            addresses = cur.fetchall()
            cur.close()
            conn.close()

            if addresses:
                await message.answer("Выберите адрес доставки:", reply_markup=build_address_keyboard(addresses))
                await state.set_state(OrderFSM.selecting_address)
            else:
                await message.answer(f"Для клиента *{escape_markdown_v2(client['name'])}* не найдено адресов. Пожалуйста, добавьте адрес вручную или выберите другого клиента.", parse_mode="MarkdownV2")
                # Здесь можно вернуться в главное меню или предложить добавить новый адрес
                # from handlers.main_menu import show_main_menu # Для возврата в главное меню
                # await show_main_menu(message, state) # Если show_main_menu не вызывает циклический импорт
                await state.clear() # Или просто очистить состояние
                await message.answer("Вы можете начать новый заказ.")


        else:
            buttons = []
            for client in clients:
                buttons.append([InlineKeyboardButton(text=client['name'], callback_data=f"client:{client['client_id']}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            await message.answer("Найдено несколько клиентов. Выберите одного:", reply_markup=keyboard)
            await state.set_state(OrderFSM.selecting_multiple_clients)
    else:
        await message.answer("Клиент с таким именем не найден. Пожалуйста, попробуйте еще раз или введите другое имя.")


@router.callback_query(StateFilter(OrderFSM.selecting_multiple_clients), F.data.startswith("client:"))
async def select_client_from_list(callback: CallbackQuery, state: FSMContext):
    client_id = int(callback.data.split(":")[1])
    
    conn = get_connection()
    cur = get_dict_cursor(conn) 
    cur.execute("SELECT client_id, name FROM clients WHERE client_id = %s", (client_id,))
    client = cur.fetchone()
    cur.close()
    conn.close()

    if client:
        await state.update_data(client_id=client['client_id'], client_name=client['name'])
        await callback.answer(f"Клиент выбран: {client['name']}", show_alert=True) # Оповещение
        await callback.message.edit_text(f"✅ Выбран клиент: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2", reply_markup=None) # ДОБАВЛЕНО СООБЩЕНИЕ И УДАЛЕНИЕ КНОПОК
        
        # Получаем адреса для выбранного клиента
        conn = get_connection()
        cur = get_dict_cursor(conn) 
        cur.execute("SELECT address_id, address_text FROM addresses WHERE client_id = %s", (client_id,))
        addresses = cur.fetchall()
        cur.close()
        conn.close()

        if addresses:
            await callback.message.answer("Выберите адрес доставки:", reply_markup=build_address_keyboard(addresses))
            await state.set_state(OrderFSM.selecting_address)
        else:
            await callback.message.answer(f"Для клиента *{escape_markdown_v2(client['name'])}* не найдено адресов. Пожалуйста, добавьте адрес вручную или выберите другого клиента.", parse_mode="MarkdownV2")
            # Можно вернуться в главное меню
            # from handlers.main_menu import show_main_menu
            # await show_main_menu(callback.message, state)
            await state.clear() # Или просто очистить состояние
            await callback.message.answer("Вы можете начать новый заказ.")
    else:
        await callback.answer("Ошибка при выборе клиента. Попробуйте снова.", show_alert=True)
    await callback.answer() # Закрываем уведомление о нажатии кнопки