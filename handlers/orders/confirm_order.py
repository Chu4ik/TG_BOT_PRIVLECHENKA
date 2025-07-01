from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache
from db_operations.db import get_connection
from datetime import date, timedelta

router = Router()

@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    order_data = order_cache.get(user_id)

    if not order_data or not order_data.get("cart"):
        await callback.answer("Корзина пуста.", show_alert=True)
        return

    client_id = order_data.get("client_id")
    address_id = order_data.get("address_id")
    delivery_date = order_data.get("delivery_date") or get_default_delivery_date()
    cart = order_data["cart"]

    total = sum(item["quantity"] * item["unit_price"] for item in cart)
    employee_id = get_employee_id(user_id)  # реализация зависит от контекста

    conn = get_connection()
    cur = conn.cursor()

    # 🧾 1. Создаём заказ
    cur.execute("""
        INSERT INTO orders (order_date, delivery_date, employee_id, client_id, address_id, total_amount, status)
        VALUES (%s, %s, %s, %s, %s, %s, 'confirmed')
        RETURNING order_id;
    """, (date.today(), delivery_date, employee_id, client_id, address_id, total))
    order_id = cur.fetchone()[0]

    # 📦 2. Вставляем строки заказа
    for item in cart:
        cur.execute("""
            INSERT INTO order_lines (order_id, product_id, quantity, unit_price)
            VALUES (%s, %s, %s, %s)
        """, (order_id, item["product_id"], item["quantity"], item["unit_price"]))

    conn.commit()
    cur.close()
    conn.close()

    # 🧹 3. Очищаем корзину
    order_cache.pop(user_id, None)
    await state.clear()

    await callback.message.edit_text(f"✅ Заказ #{order_id} сохранён. Общая сумма: <b>{total:.2f}₴</b>", parse_mode="HTML")

def get_default_delivery_date():
    today = date.today()
    return today + (timedelta(days=3) if today.weekday() == 4 else timedelta(days=1))

def get_employee_id(telegram_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT employee_id FROM employees WHERE id_telegram = %s", (telegram_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result[0] if result else None