from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache, add_to_cart
from db_operations.db import get_connection

router = Router()

async def send_all_products(message: Message):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT product_id, name FROM products ORDER BY name")
    products = cur.fetchall()
    cur.close()
    conn.close()

    if not products:
        await message.answer("❌ Товаров пока нет.")
        return

    buttons = [KeyboardButton(text=name) for _, name in products]
    rows = [[btn] for btn in buttons]
    keyboard = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

    await message.answer("📦 Выберите товар:", reply_markup=keyboard)

@router.message(StateFilter(OrderFSM.selecting_product))
async def show_all_products(message: Message, state: FSMContext):
    await send_all_products(message)

@router.message(StateFilter(OrderFSM.selecting_product))
async def product_chosen(message: Message, state: FSMContext):
    state_data = await state.get_data()
    product_map = state_data.get("product_map", {})

    product_name = message.text
    product_id = product_map.get(product_name)

    if not product_id:
        await message.answer("⚠️ Пожалуйста, выбери товар из списка.")
        return

    await state.update_data({
        "product_id": product_id,
        "product_name": product_name
    })

    await message.answer(
        f"📦 Товар: <b>{product_name}</b>\n"
        f"🔢 Введите количество для добавления:",
        parse_mode="HTML"
    )
    await state.set_state(OrderFSM.awaiting_quantity)

@router.message(StateFilter(OrderFSM.awaiting_quantity))
async def quantity_entered(message: Message, state: FSMContext):
    print(f"[FSM] Текущее состояние: {await state.get_state()}") 
    try:
        qty = int(message.text)
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("🔢 Введите целое положительное число.")
        return

    state_data = await state.get_data()
    selected = state_data.get("selected_product")

    if not selected:
        await message.answer("⚠️ Не удалось получить данные о товаре.")
        return

    selected["quantity"] = qty
    user_id = message.from_user.id

    # Инициализация корзины, если её нет
    if "cart" not in order_cache[user_id]:
        order_cache[user_id]["cart"] = []

    cart = order_cache[user_id]["cart"]

    # ⛔ Проверка на дубликат
    existing = next((item for item in cart if item["product_id"] == selected["product_id"]), None)

    if existing:
        existing["quantity"] += qty
        await message.answer(
            f"🔁 Товар <b>{selected['product_name']}</b> уже был в заказе.\n"
            f"📦 Количество обновлено до <b>{existing['quantity']}</b>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        cart.append(selected)
        await message.answer(
            f"✅ Добавлено в заказ: <b>{selected['product_name']}</b> × {qty}",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )

    await state.set_state(OrderFSM.editing_order)

    # Переход в редактор
    try:
        from handlers.orders.order_editor import show_cart_menu
        await show_cart_menu(message, state)
    except Exception:
        await message.answer("⚠️ Не удалось загрузить редактор заказа.")