# handlers/orders/order_editor.py
import logging
from decimal import Decimal
from datetime import date, timedelta
import re 
from utils.markdown_utils import escape_markdown_v2

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

# ОБНОВЛЕННЫЕ ИМПОРТЫ
from handlers.orders.order_helpers import _get_cart_summary_text 
from utils.order_cache import order_cache 

# Теперь импортируем только get_employee_id. db_pool будет передаваться.
from db_operations import get_employee_id # <--- ИЗМЕНЕНО
import asyncpg.exceptions # Добавляем импорт для асинхронных ошибок БД

from keyboards.inline_keyboards import build_cart_keyboard, delivery_date_keyboard, build_edit_item_menu_keyboard
from states.order import OrderFSM

router = Router()
logger = logging.getLogger(__name__)

# Добавили db_pool как аргумент функции
async def show_cart_menu(message: Message, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    """
    Показывает меню корзины с текущей сводкой.
    Пытается редактировать предыдущее сообщение корзины, если возможно, иначе отправляет новое.
    Данные корзины берутся из FSM-состояния.
    """
    user_id = message.from_user.id
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])
    delivery_date = state_data.get("delivery_date")
    client_name = state_data.get("client_name") 
    address_text = state_data.get("address_text") 

    last_cart_message_id = state_data.get("last_cart_message_id")
    last_cart_chat_id = state_data.get("last_cart_chat_id")

    raw_summary_content = await _get_cart_summary_text(cart_items, delivery_date, client_name, address_text)

    formatted_summary_lines = []
    lines = raw_summary_content.split('\n')
    for line in lines:
        if line.startswith("---"):
            formatted_summary_lines.append(line)
        elif line.startswith("Клиент:"): 
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("Адрес:"): 
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("Дата доставки:"):
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("--- ТОВАРЫ ---"):
            formatted_summary_lines.append(line)
        elif line.startswith("ИТОГО:"):
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("  Корзина пуста."):
            formatted_summary_lines.append(line)
        elif re.match(r"^\d+\.", line): 
            formatted_summary_lines.append(line)
        else:
            formatted_summary_lines.append(line)

    pre_escaped_text = "\n".join(formatted_summary_lines)
    summary_text_escaped = escape_markdown_v2(pre_escaped_text)

    # Строим клавиатуру, передавая количество товаров для условного отображения кнопки "Изменить строку"
    keyboard = build_cart_keyboard(len(cart_items))

    try:
        if last_cart_message_id and last_cart_chat_id:
            await message.bot.edit_message_text(
                chat_id=last_cart_chat_id,
                message_id=last_cart_message_id,
                text=summary_text_escaped,
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
        else:
            sent_message = await message.answer(
                summary_text_escaped,
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
            await state.update_data(last_cart_message_id=sent_message.message_id, last_cart_chat_id=sent_message.chat.id)

    except TelegramBadRequest as e:
        logger.warning(f"TelegramBadRequest when editing cart message: {e}. Sending new message.")
        sent_message = await message.answer(
            summary_text_escaped,
            reply_markup=keyboard,
            parse_mode="MarkdownV2"
        )
        await state.update_data(last_cart_message_id=sent_message.message_id, last_cart_chat_id=sent_message.chat.id)
    except Exception as e:
        logger.error(f"Error in show_cart_menu: {e}")
        await message.answer("Произошла ошибка при отображении корзины. Пожалуйста, попробуйте снова.")

    await state.set_state(OrderFSM.editing_order)


# Добавили db_pool как аргумент функции
@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext, db_pool):
    user_id = callback.from_user.id
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])
    delivery_date = state_data.get("delivery_date")
    client_id = state_data.get("client_id")
    address_id = state_data.get("address_id")
    client_name = state_data.get("client_name") 
    address_text = state_data.get("address_text") 
    
    # Получаем ID редактируемого заказа и его оригинальный статус
    editing_order_id = state_data.get("editing_order_id")
    original_order_status = state_data.get("original_order_status") 

    # --- ПРОВЕРКИ НА ПОЛНОТУ ДАННЫХ (Обязательны для любого заказа) ---
    if not cart_items:
        await callback.answer("Ваша корзина пуста. Добавьте товары перед подтверждением.", show_alert=True)
        await show_cart_menu(callback.message, state, db_pool)
        return

    if not delivery_date:
        await callback.answer("Пожалуйста, выберите дату доставки перед подтверждением заказа.", show_alert=True)
        await edit_delivery_date(callback, state, db_pool)
        return
        
    if not client_id:
        await callback.answer("Пожалуйста, выберите клиента для заказа.", show_alert=True)
        return

    if not address_id:
        await callback.answer("Пожалуйста, выберите адрес доставки для заказа.", show_alert=True)
        return
    # --- КОНЕЦ ПРОВЕРОК ---

    # Вычисляем общую сумму заказа
    total = sum(item["quantity"] * item["price"] for item in cart_items)
    
    # Получаем ID сотрудника
    employee_id = await get_employee_id(db_pool, user_id) 

    if employee_id is None:
        logger.error(f"Не удалось получить employee_id для пользователя {user_id}. Заказ не сохранен.")
        await callback.answer("Ошибка: Не удалось определить сотрудника. Заказ не может быть сохранен.", show_alert=True)
        await callback.message.edit_text(
            f"{escape_markdown_v2('❌ Ошибка при подтверждении заказа: Не удалось определить сотрудника. Пожалуйста, обратитесь к администратору.')}",
            parse_mode="MarkdownV2",
            reply_markup=None
        )
        await state.clear() 
        return

    conn = None 
    try:
        conn = await db_pool.acquire()
        async with conn.transaction(): # Используем асинхронную транзакцию
            if editing_order_id: # Если редактируем существующий заказ
                logger.info(f"Обновление существующего заказа #{editing_order_id} пользователем {user_id}.")
                
                # Обновляем основные поля заказа
                await conn.execute("""
                    UPDATE orders
                    SET delivery_date = $1, client_id = $2, address_id = $3, total_amount = $4, status = $5
                    WHERE order_id = $6;
                """, delivery_date, client_id, address_id, total, original_order_status, editing_order_id)
                
                # Удаляем все старые строки заказа
                await conn.execute("DELETE FROM order_lines WHERE order_id = $1;", editing_order_id)

                # Вставляем все новые/измененные строки заказа
                for item in cart_items:
                    await conn.execute("""
                        INSERT INTO order_lines (order_id, product_id, quantity, unit_price)
                        VALUES ($1, $2, $3, $4)
                    """, editing_order_id, item["product_id"], item["quantity"], item["price"])
                
                order_id_for_message = editing_order_id # Используем ID существующего заказа для сообщения
                text_to_send = f"✅ *Заказ №{order_id_for_message}* успешно *обновлен* в базе данных.\nОбщая сумма: *{total:.2f}* грн.\n"

            else: # Если создаем новый заказ
                logger.info(f"Создание нового заказа пользователем {user_id}.")
                
                # Вставка в таблицу orders с начальным статусом 'draft'
                order_row = await conn.fetchrow("""
                    INSERT INTO orders (order_date, delivery_date, employee_id, client_id, address_id, total_amount, status)
                    VALUES ($1, $2, $3, $4, $5, $6, 'draft')
                    RETURNING order_id;
                """, date.today(), delivery_date, employee_id, client_id, address_id, total)
                order_id_for_message = order_row['order_id'] # Получаем ID нового заказа

                # Вставка строк заказа
                for item in cart_items:
                    await conn.execute("""
                        INSERT INTO order_lines (order_id, product_id, quantity, unit_price)
                        VALUES ($1, $2, $3, $4)
                    """, order_id_for_message, item["product_id"], item["quantity"], item["price"])
                
                text_to_send = f"✅ *Заказ №{order_id_for_message}* успешно *сформирован* и сохранен в базе данных.\nОбщая сумма: *{total:.2f}* грн.\n"

        # --- Общий код после успешной транзакции (для обоих случаев: новый или обновленный) ---
        await callback.answer("✅ Операция с заказом успешно завершена!", show_alert=False) 
        escaped_text_to_send = escape_markdown_v2(text_to_send)
        await callback.message.edit_text(
            escaped_text_to_send,
            parse_mode="MarkdownV2",
            reply_markup=None 
        )

        order_cache.pop(user_id, None) 
        await state.clear()

    except asyncpg.exceptions.PostgresError as e: 
        logger.error(f"Ошибка БД при сохранении/обновлении заказа для пользователя {user_id} (заказ ID {editing_order_id or 'новый'}): {e}", exc_info=True)
        await callback.answer("Произошла ошибка при сохранении заказа. Пожалуйста, попробуйте снова.", show_alert=True)
        await callback.message.edit_text(
            f"{escape_markdown_v2('❌ Произошла ошибка при сохранении/обновлении заказа в базу данных. Пожалуйста, попробуйте снова или обратитесь к администратору.')}",
            parse_mode="MarkdownV2",
            reply_markup=None
        )
        await state.clear() 
        return 
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при сохранении/обновлении заказа для пользователя {user_id} (заказ ID {editing_order_id or 'новый'}): {e}", exc_info=True)
        await callback.answer("Произошла непредвиденная ошибка при сохранении заказа. Пожалуйста, попробуйте снова.", show_alert=True)
        await callback.message.edit_text(
            f"{escape_markdown_v2('❌ Произошла непредвиденная ошибка при сохранении/обновлении заказа в базу данных. Пожалуйста, попробуйте снова или обратитесь к администратору.')}",
            parse_mode="MarkdownV2",
            reply_markup=None
        )
        await state.clear() 
        return
    finally:
        if conn:
            await db_pool.release(conn)


# Добавили db_pool как аргумент функции
@router.callback_query(F.data.startswith("edit_quantity:"))
async def edit_cart_item_quantity(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("Неверные данные для редактирования количества.", show_alert=True)
        return

    action = parts[1]
    item_index = int(parts[2])

    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if 0 <= item_index < len(cart_items):
        current_quantity = cart_items[item_index]["quantity"]
        if action == "increase":
            cart_items[item_index]["quantity"] += 1
        elif action == "decrease":
            if current_quantity > 1:
                cart_items[item_index]["quantity"] -= 1
            else:
                await callback.answer("Количество не может быть меньше 1. Используйте 'Удалить' для полного удаления.", show_alert=True)
                await callback.answer()
                return
        elif action == "remove":
            product_name_to_remove = cart_items[item_index]["product_name"]
            cart_items.pop(item_index)
            await callback.answer(f"Товар '{product_name_to_remove}' удален из корзины.", show_alert=True)
        
        await state.update_data(cart=cart_items)
        await show_cart_menu(callback.message, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
    else:
        await callback.answer("Ошибка: Товар не найден.", show_alert=True)
    await callback.answer()


# Добавили db_pool как аргумент функции
@router.callback_query(F.data == "edit_delivery_date")
async def edit_delivery_date(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    from keyboards.inline_keyboards import delivery_date_keyboard 
    
    today = date.today()
    keyboard = delivery_date_keyboard(today)
    
    await callback.message.edit_text(
        "Выберите новую дату доставки:",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.change_delivery_date)
    await callback.answer()


# Добавили db_pool как аргумент функции
@router.callback_query(StateFilter(OrderFSM.change_delivery_date), F.data.startswith("date:"))
async def process_new_delivery_date(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    selected_date_str = callback.data.split(":")[1]
    selected_date = date.fromisoformat(selected_date_str)
    
    await state.update_data(delivery_date=selected_date)
    await callback.answer(f"Дата доставки установлена на {selected_date.strftime('%d.%m.%Y')}", show_alert=True)
    
    await show_cart_menu(callback.message, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
    await callback.answer()


# Добавили db_pool как аргумент функции
@router.callback_query(F.data == "back_to_cart_main_menu")
async def back_to_cart_main_menu(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    await show_cart_menu(callback.message, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
    await callback.answer()


# Добавили db_pool как аргумент функции
@router.callback_query(F.data == "edit_cart_item_menu")
async def show_edit_item_menu(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if not cart_items:
        await callback.answer("Корзина пуста, нет товаров для изменения.", show_alert=True)
        await show_cart_menu(callback.message, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
        return

    keyboard = build_edit_item_menu_keyboard()
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.editing_item_selection) # Устанавливаем новое состояние
    await callback.answer()


# Добавили db_pool как аргумент функции
@router.callback_query(StateFilter(OrderFSM.editing_item_selection), F.data == "delete_item_prompt")
async def prompt_delete_item(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if not cart_items:
        await callback.answer("Корзина пуста, нет товаров для удаления.", show_alert=True)
        await show_cart_menu(callback.message, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
        return

    buttons = []
    for i, item in enumerate(cart_items):
        buttons.append([InlineKeyboardButton(text=f"🗑️ {item['product_name']}", callback_data=f"edit_quantity:remove:{i}")])
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_edit_item_menu")]) 

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        "Выберите товар для удаления:",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.deleting_item) 
    await callback.answer()


# Добавили db_pool как аргумент функции
@router.callback_query(StateFilter(OrderFSM.editing_item_selection), F.data == "change_quantity_prompt")
async def prompt_change_quantity(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if not cart_items:
        await callback.answer("Корзина пуста, нет товаров для изменения количества.", show_alert=True)
        await show_cart_menu(callback.message, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
        return

    buttons = []
    for i, item in enumerate(cart_items):
        buttons.append([InlineKeyboardButton(text=f"🔢 {item['product_name']}", callback_data=f"select_item_for_quantity:{i}")])
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_edit_item_menu")]) 

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        "Выберите товар, количество которого хотите изменить:",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.selecting_item_for_quantity) 
    await callback.answer()


# Добавили db_pool как аргумент функции
@router.callback_query(StateFilter(OrderFSM.selecting_item_for_quantity), F.data.startswith("select_item_for_quantity:"))
async def select_item_for_quantity(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    item_index = int(callback.data.split(":")[1])
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if 0 <= item_index < len(cart_items):
        product_name = cart_items[item_index]["product_name"]
        current_quantity = cart_items[item_index]["quantity"]
        
        await state.update_data(item_index_to_edit=item_index)

        await callback.message.edit_text(
            f"Товар: *{escape_markdown_v2(product_name)}*\nТекущее количество: *{current_quantity}*\n\nВведите новое количество:",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Отмена", callback_data="back_to_edit_item_menu")]
            ])
        )
        await state.set_state(OrderFSM.entering_new_quantity) 
    else:
        await callback.answer("Ошибка: Товар не найден.", show_alert=True)
        await show_edit_item_menu(callback, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
    await callback.answer()

# Добавили db_pool как аргумент функции
@router.message(StateFilter(OrderFSM.entering_new_quantity))
async def process_new_quantity_input(message: Message, state: FSMContext, db_pool):
    user_id = message.from_user.id
    state_data = await state.get_data()
    cart_items = state_data.get('cart', [])
    item_index = state_data.get('item_index_to_edit')

    logger.info(f"User {user_id}: In process_new_quantity_input.")
    logger.info(f"State data: {state_data}") 
    logger.info(f"item_index from state: {item_index}")
    logger.info(f"cart_items from state (first 3 items): {cart_items[:3]} (total: {len(cart_items)} items)")

    if item_index is None or not (0 <= item_index < len(cart_items)):
        logger.error(f"User {user_id}: Invalid item_index ({item_index}) or cart_items length ({len(cart_items)}) in process_new_quantity_input.")
        await message.answer("❌ Произошла ошибка при изменении количества. Пожалуйста, попробуйте снова.")
        await show_cart_menu(message, state, db_pool)
        return

    try:
        new_quantity = int(message.text)
        if new_quantity < 0: 
            await message.answer("❌ Количество не может быть отрицательным. Попробуйте ещё раз.")
            return
        
        # --- УДАЛЯЕМ ВСЮ ЛОГИКУ ПРОВЕРКИ И КОРРЕКЦИИ ОСТАТКОВ ЗДЕСЬ ---
        # product_id = cart_items[item_index]["product_id"]
        # available_stock = await get_product_current_stock(db_pool, product_id)
        # ... (весь if/elif/else блок, который был здесь для проверки остатков) ...
        # --- КОНЕЦ УДАЛЯЕМОЙ ЛОГИКИ ---

        if new_quantity == 0:
            # Если введено 0, удаляем товар
            product_name_to_remove = cart_items[item_index]["product_name"]
            cart_items.pop(item_index) 
            await message.answer(f"🗑️ Товар *{escape_markdown_v2(product_name_to_remove)}* удален из заказа.", parse_mode="MarkdownV2")
        else:
            cart_items[item_index]['quantity'] = new_quantity # Если все в порядке, устанавливаем новое количество
            await message.answer(
                f"Количество для *{escape_markdown_v2(cart_items[item_index]['product_name'])}* изменено на *{new_quantity}*\\.",
                parse_mode="MarkdownV2"
            )

        await state.update_data(cart=cart_items)
        
        # Обновляем сообщение корзины
        await show_cart_menu(message, state, db_pool) 

    except ValueError:
        await message.answer("❌ Неверный формат количества. Введите целое число.")
    except Exception as e:
        logger.error(f"Ошибка при обработке нового количества: {e}", exc_info=True)
        await message.answer("Произошла ошибка при изменении количества. Пожалуйста, попробуйте снова.")


# Добавили db_pool как аргумент функции
@router.callback_query(F.data == "back_to_edit_item_menu")
async def back_to_edit_item_menu(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    await show_edit_item_menu(callback, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
    await callback.answer()

# Добавили db_pool как аргумент функции
@router.callback_query(F.data == "add_product")
async def handle_add_product_from_cart(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ИЗМЕНЕНО
    user_id = callback.from_user.id
    logger.info(f"User {user_id}: Entering handle_add_product_from_cart handler for 'add_product' callback.")
    
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as e:
        logger.warning(f"Could not edit message reply markup in handle_add_product_from_cart: {e}")
        pass 
    
    from handlers.orders.product_selection import send_all_products
    
    await state.set_state(OrderFSM.selecting_product) 
    await send_all_products(callback.message, state, db_pool) # <--- ПЕРЕДАЛИ db_pool
    await callback.answer()