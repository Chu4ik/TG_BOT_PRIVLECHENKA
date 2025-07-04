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
from keyboards.inline_keyboards import build_cart_keyboard, delivery_date_keyboard
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
    client_name = state_data.get("client_name") # Получаем имя клиента
    address_text = state_data.get("address_text") # Получаем адрес

    # Проверяем, есть ли предыдущее сообщение корзины для редактирования
    last_cart_message_id = state_data.get("last_cart_message_id")
    last_cart_chat_id = state_data.get("last_cart_chat_id")

    # Передаем client_name и address_text в функцию сводки
    raw_summary_content = await _get_cart_summary_text(cart_items, delivery_date, client_name, address_text)

    # Применяем MarkdownV2 форматирование
    formatted_summary_lines = []
    lines = raw_summary_content.split('\n')
    for line in lines:
        if line.startswith("---"):
            formatted_summary_lines.append(line)
        elif line.startswith("Клиент:"): # Добавляем форматирование для клиента
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("Адрес:"): # Добавляем форматирование для адреса
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("Дата доставки:"):
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("--- ТОВАРЫ ---"):
            formatted_summary_lines.append(line)
        elif line.startswith("ИТОГО:"):
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("  Корзина пуста."):
            formatted_summary_lines.append(line)
        elif re.match(r"^\d+\.", line): # Форматирование для строк товаров (например, 1. Товар - X шт.)
            formatted_summary_lines.append(line)
        else:
            formatted_summary_lines.append(line)

    pre_escaped_text = "\n".join(formatted_summary_lines)
    summary_text_escaped = escape_markdown_v2(pre_escaped_text)

    # Строим клавиатуру
    keyboard = build_cart_keyboard(len(cart_items))

    try:
        # Пытаемся отредактировать предыдущее сообщение
        if last_cart_message_id and last_cart_chat_id:
            await message.bot.edit_message_text(
                chat_id=last_cart_chat_id,
                message_id=last_cart_message_id,
                text=summary_text_escaped,
                reply_markup=keyboard,
                parse_mode="MarkdownV2"
            )
        else:
            # Отправляем новое сообщение, если предыдущего нет или не удалось отредактировать
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
    client_name = state_data.get("client_name") # Получаем имя клиента
    address_text = state_data.get("address_text") # Получаем адрес

    if not cart_items:
        await callback.answer("Ваша корзина пуста. Добавьте товары перед подтверждением.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    if not delivery_date:
        await callback.answer("Пожалуйста, выберите дату доставки перед подтверждением заказа.", show_alert=True)
        await edit_delivery_date(callback, state)
        return

    # На этом этапе, сохраняем данные заказа из FSM-состояния в order_cache и/или в БД
    # from utils.order_cache import save_order_to_cache
    # save_order_to_cache(user_id, cart_items, delivery_date, state_data.get("last_cart_message_id"), callback.message.chat.id, client_id=state_data.get("client_id"), address_id=state_data.get("address_id"))


    # Передаем client_name и address_text в функцию сводки
    raw_summary_content = await _get_cart_summary_text(cart_items, delivery_date, client_name, address_text)
    
    # Применяем MarkdownV2 форматирование
    formatted_summary_lines = []
    lines = raw_summary_content.split('\n')
    for line in lines:
        if line.startswith("---"):
            formatted_summary_lines.append(line)
        elif line.startswith("Клиент:"): # Добавляем форматирование для клиента
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("Адрес:"): # Добавляем форматирование для адреса
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
        reply_markup=None # Убираем кнопки после подтверждения
    )
    await callback.answer("Заказ подтвержден!", show_alert=True)
    await state.clear() # Очищаем состояние после подтверждения заказа


@router.callback_query(F.data.startswith("edit_quantity:"))
async def edit_cart_item_quantity(callback: CallbackQuery, state: FSMContext):
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
        await show_cart_menu(callback.message, state) # Обновляем отображение корзины
    else:
        await callback.answer("Ошибка: Товар не найден.", show_alert=True)
    await callback.answer()


@router.callback_query(F.data == "edit_delivery_date")
async def edit_delivery_date(callback: CallbackQuery, state: FSMContext):
    from keyboards.inline_keyboards import delivery_date_keyboard # Ленивый импорт
    
    # Определяем текущую дату для генерации клавиатуры
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
    
    # После выбора даты, возвращаемся в меню корзины
    await show_cart_menu(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "back_to_cart_main_menu")
async def back_to_cart_main_menu(callback: CallbackQuery, state: FSMContext):
    await show_cart_menu(callback.message, state)
    await callback.answer()