# handlers/orders/product_selection.py
import logging
from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter
from states.order import OrderFSM
from utils.order_cache import order_cache 

import asyncpg.exceptions # Оставляем для обработки специфических ошибок БД

from decimal import Decimal
# Проблемная строка ниже УДАЛЕНА!
# import db_operations.db 

from handlers.orders.order_helpers import _get_cart_summary_text 

router = Router()
logger = logging.getLogger(__name__)

async def send_all_products(message: Message, state: FSMContext, db_pool):
    conn = None 
    products = [] 
    try:
        conn = await db_pool.acquire()
        products = await conn.fetch("SELECT product_id, name, price FROM products ORDER BY name")
        
        if not products:
            await message.answer("❌ Товаров пока нет. Пожалуйста, попробуйте позже.")
            return

        product_buttons = []
        for product in products:
            product_buttons.append([KeyboardButton(text=f"{product['name']} ({product['price']:.2f}₴)")])

        keyboard = ReplyKeyboardMarkup(keyboard=product_buttons, resize_keyboard=True)
        await message.answer("Выберите товар:", reply_markup=keyboard)
        await state.set_state(OrderFSM.selecting_product)
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении списка товаров: {e}", exc_info=True)
        await message.answer("Произошла ошибка при загрузке товаров. Пожалуйста, попробуйте позже.")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в send_all_products: {e}", exc_info=True)
        await message.answer("Произошла непредвиденная ошибка при загрузке товаров. Пожалуйста, попробуйте позже.")
    finally:
        if conn:
            await db_pool.release(conn)


@router.message(StateFilter(OrderFSM.selecting_product))
async def process_product_selection(message: Message, state: FSMContext, db_pool):
    conn = None 
    try:
        conn = await db_pool.acquire()
        
        product_name_from_msg = message.text.split('(')[0].strip()
        selected_product = await conn.fetchrow("SELECT product_id, name, price FROM products WHERE name = $1", product_name_from_msg)
        
        if selected_product:
            await state.update_data(selected_product=selected_product)
            await message.answer("Введите количество:", reply_markup=ReplyKeyboardRemove())
            await state.set_state(OrderFSM.entering_quantity)
        else:
            await message.answer("Неизвестный товар. Пожалуйста, выберите из списка.")
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при выборе товара: {e}", exc_info=True)
        await message.answer("Произошла ошибка при выборе товара. Пожалуйста, попробуйте еще раз.")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в process_product_selection: {e}", exc_info=True)
        await message.answer("Произошла непредвиденная ошибка при выборе товара. Пожалуйста, попробуйте еще раз.")
    finally:
        if conn:
            await db_pool.release(conn)


@router.message(StateFilter(OrderFSM.entering_quantity))
async def process_quantity_input(message: Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity <= 0:
            raise ValueError("Количество должно быть положительным.")

        data = await state.get_data()
        selected_product = data.get("selected_product")
        cart = data.get("cart", []) 

        if not selected_product:
            await message.answer("Ошибка: товар не выбран. Начните сначала.", reply_markup=ReplyKeyboardRemove())
            await state.clear() 
            return

        item_found_and_updated = False
        for item in cart:
            if item["product_id"] == selected_product["product_id"]:
                item["quantity"] += quantity 
                item_found_and_updated = True
                break
        
        if not item_found_and_updated:
            new_item = {
                "product_id": selected_product["product_id"],
                "product_name": selected_product["name"],
                "quantity": quantity,
                "price": selected_product["price"]
            }
            cart.append(new_item)
        
        await state.update_data(cart=cart) 

        await message.answer(
            f"✅ Добавлено в заказ: <b>{selected_product['name']}</b> × {quantity}",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove()
        )
            
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
async def handle_next_action(message: Message, state: FSMContext, db_pool):
    if message.text == "➕ Добавить ещё товар":
        await state.set_state(OrderFSM.selecting_product)
        await send_all_products(message, state, db_pool)
    elif message.text == "✅ Завершить заказ":
        from handlers.orders.order_editor import show_cart_menu 
        await show_cart_menu(message, state, db_pool)
    else:
        await message.answer("Неизвестное действие. Пожалуйста, выберите из предложенных вариантов.")
        from handlers.orders.order_editor import show_cart_menu 
        await show_cart_menu(message, state, db_pool)