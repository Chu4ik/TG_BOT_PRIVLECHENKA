# handlers/orders/product_selection.py
import logging
import re # <--- ДОБАВЛЕНО: для escape_markdown_v2
from aiogram import Router, F
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters import StateFilter, Command
from states.order import OrderFSM
from utils.order_cache import order_cache 

import asyncpg.exceptions

from decimal import Decimal

from handlers.orders.order_helpers import _get_cart_summary_text 

router = Router()
logger = logging.getLogger(__name__)

def escape_markdown_v2(text: str) -> str:
    """
    Экранирует все специальные символы для MarkdownV2.
    Эта функция гарантирует, что каждый специальный символ будет правильно экранирован
    путем построения новой строки, обрабатывая каждый символ по очереди.
    """
    if text is None:
        logger.error("escape_markdown_v2 received NoneType text. Returning empty string.")
        return ""

    # Важно: сначала экранируем обратный слэш, чтобы избежать двойного экранирования
    # уже добавленных обратных слэшей.
    text = text.replace('\\', '\\\\')

    # Остальные специальные символы MarkdownV2
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']

    escaped_text_parts = []
    for char in text:
        if char in special_chars:
            escaped_text_parts.append('\\' + char)
        else:
            escaped_text_parts.append(char)
    return "".join(escaped_text_parts)


# Хендлер для команды /new_order, который инициирует процесс создания заказа
@router.message(Command("new_order"))
async def cmd_new_order(message: Message, state: FSMContext, db_pool):
    """
    Начинает процесс создания нового заказа.
    """
    await state.clear() # Очищаем предыдущее состояние
    await state.update_data(cart=[]) # Инициализируем пустую корзину
    
    # Удаляем любую предыдущую ReplyKeyboardMarkup
    await message.answer("Начинаем новый заказ...", reply_markup=ReplyKeyboardRemove())
    
    # Переходим к выбору клиента
    from handlers.orders.client_selection import send_client_selection_keyboard
    await send_client_selection_keyboard(message, state, db_pool)


async def send_all_products(message: Message, state: FSMContext, db_pool):
    conn = None 
    products = [] 
    try:
        conn = await db_pool.acquire()
        products = await conn.fetch("SELECT product_id, name, price FROM products ORDER BY name")
        
        if not products:
            await message.answer("❌ Товаров пока нет. Пожалуйста, попробуйте позже.", reply_markup=ReplyKeyboardRemove())
            await state.clear()
            return

        product_buttons = []
        for product in products:
            # Используем InlineKeyboardButton для выбора продукта
            # Экранируем имя продукта и цену для корректного отображения в кнопке
            button_text = escape_markdown_v2(f"{product['name']} ({product['price']:.2f}₴)")
            product_buttons.append([InlineKeyboardButton(text=button_text, callback_data=f"select_product_{product['product_id']}")])

        # Отправляем InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup(inline_keyboard=product_buttons)
        await message.answer("Выберите товар:", reply_markup=keyboard)
        await state.set_state(OrderFSM.selecting_product)
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении списка товаров: {e}", exc_info=True)
        await message.answer("Произошла ошибка при загрузке товаров. Пожалуйста, попробуйте позже.", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в send_all_products: {e}", exc_info=True)
        await message.answer("Произошла непредвиденная ошибка при загрузке товаров. Пожалуйста, попробуйте позже.", reply_markup=ReplyKeyboardRemove())
    finally:
        if conn:
            await db_pool.release(conn)


@router.callback_query(F.data.startswith("select_product_"), StateFilter(OrderFSM.selecting_product))
async def process_product_selection(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    conn = None 
    try:
        conn = await db_pool.acquire()
        
        product_id = int(callback.data.split("_")[2])
        selected_product = await conn.fetchrow("SELECT product_id, name, price FROM products WHERE product_id = $1", product_id)
        
        if selected_product:
            await state.update_data(selected_product=selected_product)
            # Экранируем имя продукта перед использованием в MarkdownV2
            product_name_escaped = escape_markdown_v2(selected_product['name'])
            await callback.message.edit_text(f"Введите количество для *{product_name_escaped}*:", parse_mode="MarkdownV2")
            await state.set_state(OrderFSM.entering_quantity)
        else:
            await callback.message.edit_text("Неизвестный товар. Пожалуйста, выберите из списка.", parse_mode="MarkdownV2")
            await send_all_products(callback.message, state, db_pool)
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при выборе товара: {e}", exc_info=True)
        await callback.message.edit_text("Произошла ошибка при выборе товара. Пожалуйста, попробуйте еще раз.", parse_mode="MarkdownV2")
    except Exception as e:
        logger.error(f"Непредвиденная ошибка в process_product_selection: {e}", exc_info=True)
        await callback.message.edit_text("Произошла непредвиденная ошибка при выборе товара. Пожалуйста, попробуйте еще раз.", parse_mode="MarkdownV2")
    finally:
        if conn:
            await db_pool.release(conn)


@router.message(StateFilter(OrderFSM.entering_quantity))
async def process_quantity_input(message: Message, state: FSMContext):
    try:
        quantity = int(message.text)
        if quantity <= 0:
            await message.answer("❌ Неверное количество. Введите целое положительное число.")
            return

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

        # Отправляем сообщение об успешном добавлении
        # Экранируем имя продукта перед использованием в MarkdownV2
        product_name_escaped_for_confirm = escape_markdown_v2(selected_product['name'])
        await message.answer(
            f"✅ Добавлено в заказ: *{product_name_escaped_for_confirm}* × {quantity}",
            parse_mode="MarkdownV2"
        )
            
        # Создаем InlineKeyboardMarkup для следующих действий
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить ещё товар", callback_data="add_more_products")],
                [InlineKeyboardButton(text="✅ Завершить заказ", callback_data="finish_order_creation")]
            ]
        )
        await message.answer("Что дальше?", reply_markup=keyboard)
        await state.set_state(OrderFSM.choosing_next_action)

    except ValueError:
        await message.answer("❌ Неверное количество. Введите целое положительное число.")
    except Exception as e:
        logger.error(f"Ошибка в process_quantity_input: {e}", exc_info=True)
        await message.answer(f"Произошла ошибка: {e}. Пожалуйста, попробуйте снова.")


@router.callback_query(F.data.in_({"add_more_products", "finish_order_creation"}), StateFilter(OrderFSM.choosing_next_action))
async def handle_next_action(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    
    if callback.data == "add_more_products":
        await state.set_state(OrderFSM.selecting_product)
        await send_all_products(callback.message, state, db_pool)
    elif callback.data == "finish_order_creation":
        from handlers.orders.order_editor import show_cart_menu 
        await show_cart_menu(callback.message, state, db_pool)
    else:
        await callback.message.answer("Неизвестное действие. Пожалуйста, выберите из предложенных вариантов.")
        from handlers.orders.order_editor import show_cart_menu 
        await show_cart_menu(callback.message, state, db_pool)
