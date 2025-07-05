import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM

import asyncpg.exceptions 

from utils.order_cache import order_cache, calculate_default_delivery_date
from handlers.orders.addresses_selection import build_address_keyboard 
from handlers.orders.product_selection import send_all_products 
from handlers.orders.order_editor import escape_markdown_v2 

# Если у вас здесь был импорт типа: from db_operations.db import db_pool, УДАЛИТЕ ЕГО!
# db_pool теперь будет передаваться в хэндлеры через аргументы.

router = Router()
logger = logging.getLogger(__name__)


@router.message(F.text == "✅ Создать заказ") 
@router.message(F.text == "/new_order") 
async def start_order_process(message: Message, state: FSMContext, db_pool): # <--- ДОБАВЛЕНО: db_pool как аргумент
    user_id = message.from_user.id
    
    state_data = await state.get_data()
    
    current_client_id = state_data.get("client_id")
    current_address_id = state_data.get("address_id")
    current_cart = state_data.get("cart")
    current_delivery_date = state_data.get("delivery_date")

    # Если данных о заказе нет в кэше FSM, проверяем order_cache
    if not current_client_id and user_id in order_cache:
        cached_data = order_cache[user_id]
        await state.update_data(
            client_id=cached_data.get("client_id"),
            address_id=cached_data.get("address_id"),
            cart=cached_data.get("cart"),
            delivery_date=cached_data.get("delivery_date")
        )
        logger.info(f"Loaded cached order for user {user_id}: {await state.get_data()}")
    
    # Устанавливаем дату доставки по умолчанию, если она еще не установлена (ни из кэша, ни в новом заказе)
    state_data_after_cache_load = await state.get_data() # Получаем обновленные данные после загрузки из кэша
    if not state_data_after_cache_load.get("delivery_date"):
        default_date = calculate_default_delivery_date()
        await state.update_data(delivery_date=default_date)
        logger.info(f"Set default delivery date for user {user_id}: {default_date}")

    await message.answer("Пожалуйста, введите имя или название клиента для поиска:")
    await state.set_state(OrderFSM.entering_client_name)


@router.message(StateFilter(OrderFSM.entering_client_name))
async def process_client_name_input(message: Message, state: FSMContext, db_pool): # <--- ДОБАВЛЕНО: db_pool как аргумент
    client_name_query = message.text.strip()
    conn = None # Инициализируем conn для finally блока
    try:
        # print(f"DEBUG CLIENT_SELECTION: db_pool value BEFORE acquire: {db_pool}") # <--- Можно удалить эту отладочную строку
        conn = await db_pool.acquire() # Получаем соединение из пула
        # Используем await conn.fetch для получения нескольких строк
        # Параметры теперь $1, $2 и т.д.
        clients = await conn.fetch("SELECT client_id, name FROM clients WHERE name ILIKE $1", f"%{client_name_query}%")
        
        if clients:
            if len(clients) == 1:
                client = clients[0] # asyncpg.fetch возвращает Record, доступ по ключу как у словаря
                await state.update_data(client_id=client['client_id'], client_name=client['name'])
                await message.answer(f"✅ Выбран клиент: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2") 
                
                # Второй запрос к БД, используем то же соединение
                addresses = await conn.fetch("SELECT address_id, address_text FROM addresses WHERE client_id = $1", client['client_id'])

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
                    buttons.append([InlineKeyboardButton(text=client['name'], callback_data=f"client:{client['client_id']}")])
                keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
                await message.answer("Найдено несколько клиентов. Выберите одного:", reply_markup=keyboard)
                await state.set_state(OrderFSM.selecting_multiple_clients)
        else:
            await message.answer("Клиент с таким именем не найден. Пожалуйста, попробуйте еще раз или введите другое имя.")
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при поиске клиента: {e}", exc_info=True)
        await message.answer("Произошла ошибка при поиске клиента. Пожалуйста, попробуйте еще раз.")
        await state.clear()
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в process_client_name_input: {e}", exc_info=True)
        await message.answer("Произошла непредвиденная ошибка. Пожалуйста, попробуйте еще раз.")
        await state.clear()
    finally:
        if conn:
            await db_pool.release(conn) # Возвращаем соединение в пул


@router.callback_query(StateFilter(OrderFSM.selecting_multiple_clients), F.data.startswith("client:"))
async def select_client_from_list(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ДОБАВЛЕНО: db_pool как аргумент
    client_id = int(callback.data.split(":")[1])
    conn = None # Инициализируем conn для finally блока
    try:
        conn = await db_pool.acquire() # Получаем соединение из пула
        # Используем await conn.fetchrow для получения одной строки
        client = await conn.fetchrow("SELECT client_id, name FROM clients WHERE client_id = $1", client_id)
        
        if client:
            await state.update_data(client_id=client['client_id'], client_name=client['name'])
            await callback.answer(f"Клиент выбран: {client['name']}", show_alert=True) 
            await callback.message.edit_text(f"✅ Выбран клиент: *{escape_markdown_v2(client['name'])}*", parse_mode="MarkdownV2", reply_markup=None) 
            
            # Второй запрос к БД, используем то же соединение
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
            await db_pool.release(conn) # Возвращаем соединение в пул
    await callback.answer() # Завершаем обработку коллбэка, даже если возникла ошибка