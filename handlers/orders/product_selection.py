from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache 
from db_operations.db import get_connection, get_dict_cursor # Убедитесь, что get_dict_cursor импортирован
from decimal import Decimal

from handlers.orders.order_helpers import _get_cart_summary_text 

router = Router()

async def send_all_products(message: Message, state: FSMContext):
    conn = get_connection()
    cur = get_dict_cursor(conn) # ИЗМЕНЕНО: используем get_dict_cursor
    cur.execute("SELECT product_id, name, price FROM products ORDER BY name") # Здесь 'name' и 'price' уже корректны
    products = cur.fetchall()
    cur.close()
    conn.close()

    if not products:
        await message.answer("❌ Товаров пока нет. Пожалуйста, попробуйте позже.")
        return

    product_buttons = []
    for product in products:
        # Здесь product['name'] и product['price'] будут работать, так как cur возвращает dict-подобные объекты
        product_buttons.append([KeyboardButton(text=f"{product['name']} ({product['price']:.2f}₴)")])

    keyboard = ReplyKeyboardMarkup(keyboard=product_buttons, resize_keyboard=True)
    await message.answer("Выберите товар:", reply_markup=keyboard)
    await state.set_state(OrderFSM.selecting_product)


@router.message(StateFilter(OrderFSM.selecting_product))
async def process_product_selection(message: Message, state: FSMContext):
    conn = get_connection()
    cur = get_dict_cursor(conn) # ИЗМЕНЕНО: используем get_dict_cursor
    # Здесь message.text.split('(')[0].strip() используется для получения имени, это нормально
    cur.execute("SELECT product_id, name, price FROM products WHERE name = %s", (message.text.split('(')[0].strip(),))
    selected_product = cur.fetchone()
    cur.close()
    conn.close()

    if selected_product:
        await state.update_data(selected_product=selected_product)
        await message.answer("Введите количество:", reply_markup=ReplyKeyboardRemove())
        await state.set_state(OrderFSM.entering_quantity)
    else:
        await message.answer("Неизвестный товар. Пожалуйста, выберите из списка.")


@router.message(StateFilter(OrderFSM.entering_quantity))
async def process_quantity_input(message: Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity <= 0:
            raise ValueError("Количество должно быть положительным.")

        data = await state.get_data()
        selected_product = data.get("selected_product")
        cart = data.get("cart", []) # Получаем текущую корзину из FSM-состояния

        if not selected_product:
            await message.answer("Ошибка: товар не выбран. Начните сначала.", reply_markup=ReplyKeyboardRemove())
            await state.clear() # Очищаем состояние
            return

        # Проверяем, есть ли уже такой товар в корзине
        item_found_and_updated = False
        for item in cart:
            if item["product_id"] == selected_product["product_id"]:
                item["quantity"] += quantity # Увеличиваем количество
                item_found_and_updated = True
                break
        
        if not item_found_and_updated:
            # Если товара нет, добавляем новую позицию
            new_item = {
                "product_id": selected_product["product_id"],
                "product_name": selected_product["name"],
                "quantity": quantity,
                "price": selected_product["price"]
            }
            cart.append(new_item)
        
        # ОБЯЗАТЕЛЬНО ОБНОВЛЯЕМ FSM-СОСТОЯНИЕ с новой корзиной после любых изменений
        await state.update_data(cart=cart) 

        # Отправляем подтверждение добавления товара
        await message.answer(
            f"✅ Добавлено в заказ: <b>{selected_product['name']}</b> × {quantity}",
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

    except ValueError:
        await message.answer("❌ Неверное количество. Введите целое положительное число.")
    except Exception as e:
        await message.answer(f"Произошла ошибка: {e}. Пожалуйста, попробуйте снова.")


@router.message(StateFilter(OrderFSM.choosing_next_action))
async def handle_next_action(message: Message, state: FSMContext):
    if message.text == "➕ Добавить ещё товар":
        await state.set_state(OrderFSM.selecting_product)
        await send_all_products(message, state)
    elif message.text == "✅ Завершить заказ":
        # ЛЕНИВЫЙ ИМПОРТ: Импортируем show_cart_menu здесь
        from handlers.orders.order_editor import show_cart_menu 
        await show_cart_menu(message, state)
    else:
        await message.answer("Неизвестное действие. Пожалуйста, выберите из предложенных вариантов.")
        # ЛЕНИВЫЙ ИМПОРТ: Импортируем show_cart_menu здесь
        from handlers.orders.order_editor import show_cart_menu 
        await show_cart_menu(message, state)