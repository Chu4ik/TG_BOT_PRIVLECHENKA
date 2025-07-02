from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache
from db_operations.db import get_connection
from handlers.orders.product_selection import send_all_products

router = Router()

@router.message(StateFilter(OrderFSM.client_selected))
async def choose_address(message: Message, state: FSMContext):
    state_data = await state.get_data()
    client_name = state_data.get("client_name")

    # Получаем client_id
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT client_id FROM clients WHERE name = %s", (client_name,))
    result = cur.fetchone()

    if not result:
        await message.answer("❌ Клиент не найден в базе данных.")
        return

    client_id = result[0]
    order_cache[message.from_user.id]["client_id"] = client_id

    # Получаем адреса
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

    # Если адрес один — авто-выбор
    if len(rows) == 1:
        address_id, address_text = rows[0]
        order_cache[message.from_user.id]["address_id"] = address_id
        await message.answer(f"✅ Автоматически выбран адрес: {address_text}", reply_markup=ReplyKeyboardRemove())

        await state.set_state(OrderFSM.selecting_product)
        await send_all_products(message)
        return

    # Иначе — показать список
    buttons = [KeyboardButton(text=row[1]) for row in rows]
    rows_markup = [[button] for button in buttons]  # по одной кнопке в строке

    keyboard = ReplyKeyboardMarkup(
        keyboard=rows_markup,
        resize_keyboard=True
    )

    # Сохраняем адреса в FSM
    await state.update_data(address_map={row[1]: row[0] for row in rows})
    await message.answer("🏠 Выберите адрес доставки:", reply_markup=keyboard)
    await state.set_state(OrderFSM.selecting_address)

    print(f"[FSM] Текущее состояние: {await state.get_state()}")

@router.message(StateFilter(OrderFSM.selecting_address))
async def address_chosen(message: Message, state: FSMContext):
    print(f"[FSM] Вошли в address_chosen")
    selected_text = message.text.strip()
    state_data = await state.get_data()
    address_map = state_data.get("address_map", {})
    print(f"[FSM] message.text = {selected_text}")
    print(f"[FSM] address_map.keys() = {list(address_map.keys())}")
    print(f"[FSM] FSM состояние: {await state.get_state()}")

    address_id = address_map.get(selected_text)

    if not address_id:
        await message.answer("❌ Адрес не распознан. Пожалуйста, выбери из списка.")
        return

    user_id = message.from_user.id
    order_cache[user_id]["address_id"] = address_id
    await state.update_data(address_id=address_id)

    await message.answer(f"✅ Адрес выбран: {selected_text}", reply_markup=ReplyKeyboardRemove())
    await state.set_state(OrderFSM.selecting_product)
    await send_all_products(message)