# handlers/orders/order_editor.py
import logging
from decimal import Decimal
from datetime import date, timedelta
import re 

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

from handlers.orders.order_helpers import _get_cart_summary_text 
from utils.order_cache import order_cache
from keyboards.inline_keyboards import build_cart_keyboard, delivery_date_keyboard, build_edit_item_menu_keyboard # ИМПОРТИРУЕМ build_edit_item_menu_keyboard
from states.order import OrderFSM

def escape_markdown_v2(text: str) -> str:
    """
    Helper function to escape telegram markup symbols in MarkdownV2.
    Escapes characters: _, *, [, ], (, ), ~, `, >, #, +, -, =, |, {, }, ., !
    """
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(["\\" + char if char in escape_chars else char for char in text])

router = Router()
logger = logging.getLogger(__name__)

async def show_cart_menu(message: Message, state: FSMContext):
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
        elif line.startswith("  Корзина пуста."):
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


@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])
    delivery_date = state_data.get("delivery_date")
    client_name = state_data.get("client_name") 
    address_text = state_data.get("address_text") 

    if not cart_items:
        await callback.answer("Ваша корзина пуста. Добавьте товары перед подтверждением.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    if not delivery_date:
        await callback.answer("Пожалуйста, выберите дату доставки перед подтверждением заказа.", show_alert=True)
        await edit_delivery_date(callback, state)
        return

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
        elif line.startswith("  Корзина пуста."):
            formatted_summary_lines.append(line)
        elif re.match(r"^\d+\.", line):
            formatted_summary_lines.append(line)
        else:
            formatted_summary_lines.append(line)

    pre_escaped_text_for_confirm = "\n".join(formatted_summary_lines)
    escaped_summary_text = escape_markdown_v2(pre_escaped_text_for_confirm)

    final_message = (
        f"{escape_markdown_v2('✅ Ваш заказ подтвержден!')}\n\n"
        f"{escaped_summary_text}\n\n"
        f"{escape_markdown_v2('Мы свяжемся с вами для уточнения деталей.')}"
    )

    await callback.message.edit_text(
        final_message,
        parse_mode="MarkdownV2",
        reply_markup=None 
    )
    await callback.answer("Заказ подтвержден!", show_alert=True)
    await state.clear() 


@router.callback_query(F.data.startswith("edit_quantity:"))
async def edit_cart_item_quantity(callback: CallbackQuery, state: FSMContext):
    # Эта функция теперь будет использоваться только для прямого изменения количества
    # или удаления товара, если мы перейдем к выбору конкретного товара.
    # Пока оставляем ее как есть, но будем помнить, что ее логика может быть изменена
    # для работы с новым меню "Изменить строку".
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
        await show_cart_menu(callback.message, state) 
    else:
        await callback.answer("Ошибка: Товар не найден.", show_alert=True)
    await callback.answer()


@router.callback_query(F.data == "edit_delivery_date")
async def edit_delivery_date(callback: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import delivery_date_keyboard 
    
    today = date.today()
    keyboard = delivery_date_keyboard(today)
    
    await callback.message.edit_text(
        "Выберите новую дату доставки:",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.change_delivery_date)
    await callback.answer()


@router.callback_query(StateFilter(OrderFSM.change_delivery_date), F.data.startswith("date:"))
async def process_new_delivery_date(callback: CallbackQuery, state: FSMContext):
    selected_date_str = callback.data.split(":")[1]
    selected_date = date.fromisoformat(selected_date_str)
    
    await state.update_data(delivery_date=selected_date)
    await callback.answer(f"Дата доставки установлена на {selected_date.strftime('%d.%m.%Y')}", show_alert=True)
    
    await show_cart_menu(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "back_to_cart_main_menu")
async def back_to_cart_main_menu(callback: CallbackQuery, state: FSMContext):
    # Этот хэндлер теперь используется и для кнопки "Назад к корзине" из меню редактирования строки
    await show_cart_menu(callback.message, state)
    await callback.answer()


# НОВЫЙ ХЭНДЛЕР: Обработка нажатия на кнопку "Изменить строку"
@router.callback_query(F.data == "edit_cart_item_menu")
async def show_edit_item_menu(callback: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if not cart_items:
        await callback.answer("Корзина пуста, нет товаров для изменения.", show_alert=True)
        await show_cart_menu(callback.message, state) # Вернуть в основное меню корзины
        return

    keyboard = build_edit_item_menu_keyboard()
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.editing_item_selection) # Устанавливаем новое состояние
    await callback.answer()


# НОВЫЙ ХЭНДЛЕР: Обработка нажатия на "Удалить товар"
@router.callback_query(StateFilter(OrderFSM.editing_item_selection), F.data == "delete_item_prompt")
async def prompt_delete_item(callback: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if not cart_items:
        await callback.answer("Корзина пуста, нет товаров для удаления.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    buttons = []
    for i, item in enumerate(cart_items):
        # Используем callback_data, который существующий хэндлер edit_cart_item_quantity уже понимает
        buttons.append([InlineKeyboardButton(text=f"🗑️ {item['product_name']}", callback_data=f"edit_quantity:remove:{i}")])
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_edit_item_menu")]) # Кнопка назад к меню "Изменить строку"

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        "Выберите товар для удаления:",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.deleting_item) # Новое состояние для удаления
    await callback.answer()


# НОВЫЙ ХЭНДЛЕР: Обработка нажатия на "Изменить количество"
@router.callback_query(StateFilter(OrderFSM.editing_item_selection), F.data == "change_quantity_prompt")
async def prompt_change_quantity(callback: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if not cart_items:
        await callback.answer("Корзина пуста, нет товаров для изменения количества.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    buttons = []
    for i, item in enumerate(cart_items):
        # Кнопки для выбора товара, количество которого нужно изменить
        buttons.append([InlineKeyboardButton(text=f"🔢 {item['product_name']}", callback_data=f"select_item_for_quantity:{i}")])
    buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_edit_item_menu")]) # Кнопка назад к меню "Изменить строку"

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        "Выберите товар, количество которого хотите изменить:",
        reply_markup=keyboard
    )
    await state.set_state(OrderFSM.selecting_item_for_quantity) # Новое состояние для выбора товара для изменения количества
    await callback.answer()


# НОВЫЙ ХЭНДЛЕР: Выбор товара для изменения количества
@router.callback_query(StateFilter(OrderFSM.selecting_item_for_quantity), F.data.startswith("select_item_for_quantity:"))
async def select_item_for_quantity(callback: CallbackQuery, state: FSMContext):
    item_index = int(callback.data.split(":")[1])
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if 0 <= item_index < len(cart_items):
        product_name = cart_items[item_index]["product_name"]
        current_quantity = cart_items[item_index]["quantity"]
        
        # Сохраняем индекс выбранного товара для последующего изменения количества
        await state.update_data(item_index_to_edit=item_index)

        await callback.message.edit_text(
            f"Товар: *{escape_markdown_v2(product_name)}*\nТекущее количество: *{current_quantity}*\n\nВведите новое количество:",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="↩️ Отмена", callback_data="back_to_edit_item_menu")]
            ])
        )
        await state.set_state(OrderFSM.entering_new_quantity) # Новое состояние для ввода количества
    else:
        await callback.answer("Ошибка: Товар не найден.", show_alert=True)
        await show_edit_item_menu(callback, state) # Вернуться в меню "Изменить строку"
    await callback.answer()

# НОВЫЙ ХЭНДЛЕР: Ввод нового количества
@router.message(StateFilter(OrderFSM.entering_new_quantity))
async def process_new_quantity_input(message: Message, state: FSMContext):
    user_id = message.from_user.id
    state_data = await state.get_data()
    cart_items = state_data.get('cart', [])
    item_index = state_data.get('item_index_to_edit')

    logger.info(f"User {user_id}: In process_new_quantity_input.")
    logger.info(f"State data: {state_data}") # ВНИМАНИЕ: может содержать много данных, используйте осторожно в продакшене
    logger.info(f"item_index from state: {item_index}")
    logger.info(f"cart_items from state (first 3 items): {cart_items[:3]} (total: {len(cart_items)} items)")

    if item_index is None or not (0 <= item_index < len(cart_items)):
        logger.error(f"User {user_id}: Invalid item_index ({item_index}) or cart_items length ({len(cart_items)}) in process_new_quantity_input.")
        await message.answer("❌ Произошла ошибка при изменении количества. Пожалуйста, попробуйте снова.")
        await show_cart_menu(message, state)
        return

    try:
        new_quantity = int(message.text)
        if new_quantity <= 0:
            await message.answer("❌ Количество должно быть положительным числом. Попробуйте ещё раз.")
            return

        # Обновляем количество в корзине
        cart_items[item_index]['quantity'] = new_quantity
        await state.update_data(cart=cart_items)

        # Отправляем подтверждение
        # ИСПРАВЛЕНО: Экранируем последнюю точку
        await message.answer(
            f"Количество для *{escape_markdown_v2(cart_items[item_index]['product_name'])}* изменено на *{new_quantity}*\\.",
            parse_mode="MarkdownV2"
        )
        
        # Возвращаемся в главное меню корзины
        await show_cart_menu(message, state)

    except ValueError:
        await message.answer("❌ Неверный формат количества. Введите целое число.")
    except Exception as e:
        logger.error(f"Ошибка при обработке нового количества: {e}")
        await message.answer("Произошла ошибка при изменении количества. Пожалуйста, попробуйте снова.")


# НОВЫЙ ХЭНДЛЕР: Кнопка "Назад" из меню удаления/изменения количества
@router.callback_query(F.data == "back_to_edit_item_menu")
async def back_to_edit_item_menu(callback: CallbackQuery, state: FSMContext):
    await show_edit_item_menu(callback, state) # Возвращаемся в меню "Изменить строку"
    await callback.answer()