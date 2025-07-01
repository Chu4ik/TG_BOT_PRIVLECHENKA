from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache
from handlers.orders.category_selection import show_categories
from db_operations.db import get_connection

router = Router()

@router.message(StateFilter(OrderFSM.client_selected))
async def choose_address(message: Message, state: FSMContext):
    state_data = await state.get_data()
    client_name = state_data.get("client_name")

    # Подключение к базе и запрос client_id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT client_id FROM clients WHERE name = %s", (client_name,))
    result = cur.fetchone()

    if not result:
        await message.answer("❌ Клиент не найден в базе данных.")
        return

    client_id = result[0]
    order_cache[message.from_user.id]["client_id"] = client_id

    # Запрашиваем адреса
    cur.execute("""
        SELECT address_id, address_text 
        FROM addresses 
        WHERE client_id = %s
    """, (client_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        await message.answer("⚠️ У клиента нет указанных адресов.")
        return

    # Показываем клавиатуру
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True).add(
        *[KeyboardButton(text=row[1]) for row in rows]
    )

    # Сохраняем список адресов в FSM на случай поиска ID позже
    await state.update_data(address_map={row[1]: row[0] for row in rows})
    await message.answer("🏠 Выберите адрес доставки:", reply_markup=keyboard)
    await state.set_state(OrderFSM.selecting_address)

@router.message(StateFilter(OrderFSM.selecting_address))
async def address_chosen(message: Message, state: FSMContext):
    selected_text = message.text
    state_data = await state.get_data()
    address_map = state_data.get("address_map", {})

    address_id = address_map.get(selected_text)

    if not address_id:
        await message.answer("❌ Адрес не распознан. Пожалуйста, выбери из списка.")
        return

    user_id = message.from_user.id
    order_cache[user_id]["address_id"] = address_id

    await message.answer(f"✅ Адрес выбран: {selected_text}", reply_markup=ReplyKeyboardRemove())
    await state.set_state(OrderFSM.selecting_category)

    await show_categories(message, state)