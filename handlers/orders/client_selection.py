from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import init_order
from db_operations.db import get_connection
from handlers.orders.addresses_selection import choose_address

router = Router()

@router.message(F.text.in_({"✅ Создать заказ", "/order"}))
async def start_order(message: Message, state: FSMContext):
    init_order(message.from_user.id)
    await message.answer("🔍 Введите часть имени клиента:")
    await state.set_state(OrderFSM.selecting_client)

@router.message(StateFilter(OrderFSM.selecting_client))
async def search_clients(message: Message, state: FSMContext):
    print(f"FSM state: {await state.get_state()}")
    query = message.text.lower()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM clients WHERE LOWER(name) LIKE %s", (f"%{query}%",))
    clients = [row[0] for row in cur.fetchall()]
    if not clients:
        print("Нет клиентов по запросу")
    else:
        print(f"Нашёл: {clients}")
    cur.close()
    conn.close()

    if clients:
        buttons = [KeyboardButton(text=name) for name in clients]
        rows = [[button] for button in buttons]  # по одной кнопке в строке

        # Или по 2 кнопки в строке:
        # rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]

        keyboard = ReplyKeyboardMarkup(
            keyboard=rows,
            resize_keyboard=True
        )

        await message.answer("👤 Выберите клиента:", reply_markup=keyboard)
        await state.set_state(OrderFSM.client_selected)
    else:
        keyboard = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🔁 Новый поиск"), KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True
        )

        await message.answer("😕 Клиенты не найдены. Попробуйте снова или отмените.", reply_markup=keyboard)

@router.message(StateFilter(OrderFSM.client_selected))
async def client_chosen(message: Message, state: FSMContext):
    await state.update_data(client_name=message.text)
    await message.answer(f"✅ Клиент выбран: {message.text}", reply_markup=ReplyKeyboardRemove())
    await choose_address(message, state)

