from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache, add_to_cart
from db_operations.db import get_connection

router = Router()

@router.message(StateFilter(OrderFSM.selecting_product))
async def show_products(message: Message, state: FSMContext, category_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT product_id, name, price
                FROM products
                WHERE category_id = %s
                ORDER BY name
                """,
                (category_id,)
            )
            products = cur.fetchall()
    finally:
        conn.close()

    if not products:
        await message.answer("🚫 В данной категории нет товаров.")
        return

    # формируем сопоставление и клавиатуру
    product_map = {}
    buttons = []

    for product_id, name, price in products:
        product_map[name] = (product_id, price)
        buttons.append(KeyboardButton(text=name))

    keyboard = ReplyKeyboardMarkup(resize_keyboard=True).add(*buttons)

    await state.update_data(product_map=product_map)
    await message.answer("🛒 Выберите товар:", reply_markup=keyboard)

@router.message(StateFilter(OrderFSM.selecting_product))
async def product_chosen(message: Message, state: FSMContext):
    state_data = await state.get_data()
    product_map = state_data.get("product_map", {})

    product_name = message.text
    product = product_map.get(product_name)

    if not product:
        await message.answer("⚠️ Пожалуйста, выберите товар из списка.")
        return

    product_id, price = product

    await state.update_data(selected_product={
        "product_id": product_id,
        "product_name": product_name,
        "unit_price": price
    })

    await message.answer(f"📦 Товар: <b>{product_name}</b>\n💰 Цена за единицу: {price}\n\nВведите количество:", parse_mode="HTML")
    await state.set_state(OrderFSM.awaiting_quantity)

@router.message(StateFilter(OrderFSM.awaiting_quantity))
async def quantity_entered(message: Message, state: FSMContext):
    try:
        qty = int(message.text)
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("🔢 Введите целое положительное число.")
        return

    state_data = await state.get_data()
    selected = state_data.get("selected_product")
    selected["quantity"] = qty

    user_id = message.from_user.id
    cart = order_cache[user_id]["cart"]

    # ⛔ Проверка: уже есть такой товар в корзине?
    existing = next((item for item in cart if item["product_id"] == selected["product_id"]), None)

    if existing:
        existing["quantity"] += qty  # просто увеличиваем
        await message.answer(
            f"🔁 Товар <b>{selected['product_name']}</b> уже был в корзине.\n"
            f"📦 Количество обновлено до <b>{existing['quantity']}</b>",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        add_to_cart(user_id, selected)
        await message.answer(
            f"✅ Добавлено в заказ: <b>{selected['product_name']}</b> × {qty}",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )

    await state.set_state(OrderFSM.editing_order)
    from handlers.orders.order_editor import show_cart_menu
    await show_cart_menu(message, state)