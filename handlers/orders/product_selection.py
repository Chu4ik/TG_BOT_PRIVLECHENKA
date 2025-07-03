# handlers/orders/product_selection.py
from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache, add_to_cart
from db_operations.db import get_connection
from decimal import Decimal # Импортируем Decimal
from handlers.orders.order_helpers import _send_cart_summary

# Импортируем _send_cart_summary из нового файла
from handlers.orders.order_helpers import _send_cart_summary
# Возможно, вам также потребуется show_cart_menu из order_editor.py для некоторых переходов.
# Если да, то ИМПОРТИРУЙТЕ ЕГО ВНУТРИ ФУНКЦИИ, где он нужен, чтобы не создавать новый цикл.
# from handlers.orders.order_editor import show_cart_menu # НЕ ИМПОРТИРУЙТЕ ЗДЕСЬ НАПРЯМУЮ!

router = Router()

async def send_all_products(message: Message, state: FSMContext):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT product_id, name, price FROM products ORDER BY name") # Добавил price
    products = cur.fetchall()
    cur.close()
    conn.close()

    if not products:
        await message.answer("❌ Товаров пока нет.")
        return

    buttons = [KeyboardButton(text=name) for _, name, _ in products]
    rows = [[btn] for btn in buttons]
    keyboard = ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)

    # Сохраните карту продуктов в контексте FSM
    product_map = {name: {"product_id": product_id, "price": price} for product_id, name, price in products}
    await state.update_data(product_map=product_map)

    await message.answer("📦 Выберите товар:", reply_markup=keyboard)


@router.message(StateFilter(OrderFSM.selecting_product))
async def product_chosen(message: Message, state: FSMContext):
    state_data = await state.get_data()
    product_map = state_data.get("product_map")
    selected_product_name = message.text.strip()

    if selected_product_name not in product_map:
        await message.answer("❌ Неизвестный товар. Пожалуйста, выберите из списка.")
        return

    selected_product_info = product_map[selected_product_name]
    # Сохраняем полную информацию о выбранном товаре, включая цену
    await state.update_data(selected_product={
        "product_id": selected_product_info["product_id"],
        "product_name": selected_product_name,
        "price": selected_product_info["price"] # Сохраняем цену здесь
    })

    await state.set_state(OrderFSM.awaiting_quantity)
    await message.answer(
        f"📦 Товар: <b>{selected_product_name}</b>\n"
        f"🔢 Введите количество для добавления:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove()
    )


@router.message(StateFilter(OrderFSM.awaiting_quantity))
async def quantity_entered(message: Message, state: FSMContext):
    qty_text = message.text.strip()

    if not qty_text.isdigit():
        await message.answer("⚠️ Пожалуйста, введите целое положительное число.")
        return

    qty = int(qty_text)
    if qty <= 0:
        await message.answer("⚠️ Количество должно быть положительным числом.")
        return

    state_data = await state.get_data()
    selected = state_data.get("selected_product")

    if not selected:
        await message.answer("⚠️ Не удалось получить данные о товаре.")
        return

    selected["quantity"] = qty # Добавляем количество к выбранному товару
    user_id = message.from_user.id

    # Add to cart handles checking for duplicates and updating quantity
    # and ensuring 'price' is Decimal.
    cart = order_cache.setdefault(user_id, {}).setdefault("cart", [])

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
        cart.append(selected) # 'selected' уже содержит 'price'
        await message.answer(
            f"✅ Добавлено в заказ: <b>{selected['product_name']}</b> × {qty}",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )

    # После добавления товара предлагаем выбрать следующее действие
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить ещё товар")],
            [KeyboardButton(text="✅ Завершить заказ")]
        ],
        resize_keyboard=True
    )
    await message.answer("Что дальше?", reply_markup=keyboard)
    await state.set_state(OrderFSM.choosing_next_action)


@router.message(StateFilter(OrderFSM.choosing_next_action))
async def handle_next_action(message: Message, state: FSMContext):
    if message.text == "➕ Добавить ещё товар":
        await state.set_state(OrderFSM.selecting_product)
        await send_all_products(message, state)
    elif message.text == "✅ Завершить заказ":
        # Если нужно показать меню редактирования, импортируем show_cart_menu здесь
        from handlers.orders.order_editor import show_cart_menu # <-- Ленивый импорт
        await show_cart_menu(message, state) # Передаем state
        # Состояние будет изменено внутри show_cart_menu на editing_order
    else:
        await message.answer("Неизвестное действие. Пожалуйста, выберите из предложенных вариантов.")
        # Повторно показываем сводку и варианты, если выбор не распознан
        await _send_cart_summary(message, message.from_user.id)
        buttons = [
            [KeyboardButton(text="➕ Добавить ещё товар")],
            [KeyboardButton(text="✅ Завершить заказ")]
        ]
        keyboard = ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
        await message.answer("Что дальше?", reply_markup=keyboard)