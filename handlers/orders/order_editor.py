# handlers/orders/order_editor.py
import logging
from decimal import Decimal
from datetime import date, timedelta
import re # <-- ДОБАВЬТЕ ЭТОТ ИМПОРТ ДЛЯ РЕГУЛЯРНЫХ ВЫРАЖЕНИЙ

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import StateFilter
from aiogram.exceptions import TelegramBadRequest

from handlers.orders.order_helpers import _get_cart_summary_text # Убедитесь, что здесь нет escape_markdown_v2
from utils.order_cache import order_cache
from keyboards.inline_keyboards import build_cart_keyboard, delivery_date_keyboard
from states.order import OrderFSM

# --- ТОЧНАЯ ИСПРАВЛЕННАЯ ФУНКЦИЯ escape_markdown_v2 (должна быть здесь) ---
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

    # Получаем необработанный текст сводки БЕЗ какого-либо форматирования или экранирования
    raw_summary_content = await _get_cart_summary_text(cart_items, delivery_date)
    logger.debug(f"RAW content text (from order_helpers): '{raw_summary_content}'")
    
    # Теперь применяем MarkdownV2 форматирование (например, жирный шрифт)
    # и только ПОТОМ экранируем все спецсимволы ОДИН РАЗ
    
    formatted_summary_lines = []
    lines = raw_summary_content.split('\n')
    
    for line in lines:
        if line.startswith("---"):
            formatted_summary_lines.append(line) # Не форматируем разделители
        elif line.startswith("Дата доставки:"):
            # Форматируем дату доставки жирным шрифтом
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("--- ТОВАРЫ ---"):
            formatted_summary_lines.append(line) # Не форматируем заголовок
        elif line.startswith("ИТОГО:"):
            # Форматируем итоговую сумму жирным шрифтом
            formatted_summary_lines.append(f"*{line}*")
        elif line.startswith("  Корзина пуста."):
            formatted_summary_lines.append(line)
        # Если строка начинается с цифры и точки (например, "1. Продукт"), это строка товара.
        # Для строк товаров не требуется дополнительное форматирование жирным,
        # так как _get_cart_summary_text уже дает нужный формат.
        elif re.match(r"^\d+\.", line): # Используем regex для определения строк товаров
            formatted_summary_lines.append(line)
        else: # Для любых других строк, которые могут появиться
            formatted_summary_lines.append(line)

    # Объединяем строки в единый текст, готовый к экранированию
    pre_escaped_text = "\n".join(formatted_summary_lines)
    logger.debug(f"PRE-ESCAPED text (after MarkdownV2 formatting): '{pre_escaped_text}'")

    # Теперь применяем экранирование ко ВСЕМУ тексту ОДИН РАЗ
    summary_text = escape_markdown_v2(pre_escaped_text)
    logger.debug(f"ESCAPED summary text (final for Telegram): '{summary_text}'")

    markup = build_cart_keyboard(len(cart_items))

    previous_message_id = state_data.get("last_cart_message_id")
    actual_message_obj = message
    edited_successfully = False

    if previous_message_id:
        try:
            await message.bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=previous_message_id,
                text=summary_text,
                reply_markup=markup,
                parse_mode="MarkdownV2"
            )
            edited_successfully = True
            logger.debug(f"Successfully edited previous cart message {previous_message_id}")
        except TelegramBadRequest as e:
            logger.warning(f"Failed to edit message {previous_message_id}: {e}. Sending new message.")
        except Exception as e:
            logger.error(f"An unexpected error occurred while editing message {previous_message_id}: {e}")

    if not edited_successfully:
        sent_message = await actual_message_obj.answer(
            summary_text,
            reply_markup=markup,
            parse_mode="MarkdownV2"
        )
        await state.update_data(last_cart_message_id=sent_message.message_id)
        logger.debug(f"Sent new cart message {sent_message.message_id}")

    if not cart_items:
        await state.set_state(OrderFSM.selecting_product)
        from handlers.orders.product_selection import send_all_products
        await send_all_products(message, state)
    else:
        await state.set_state(OrderFSM.editing_order)


@router.callback_query(F.data == "edit_line")
async def edit_line(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])

    if not cart_items:
        await callback.answer("Ваша корзина пуста, нечего редактировать.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    keyboard_buttons = []
    for idx, item in enumerate(cart_items):
        # Здесь мы формируем текст для кнопки, он не требует MarkdownV2 экранирования
        button_text = f"❌ {item['product_name']} ({item['quantity']} шт.)"
        callback_data = f"remove_line:{item['product_id']}"
        keyboard_buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    keyboard_buttons.append([InlineKeyboardButton(text="⬅️ Назад в корзину", callback_data="back_to_cart_menu")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

    # Текст сообщения должен быть экранирован перед отправкой
    message_text_raw = "Выберите строку для удаления:"
    message_text_escaped = escape_markdown_v2(message_text_raw)
    await callback.message.edit_text(message_text_escaped, reply_markup=markup, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.editing_item)


@router.callback_query(StateFilter(OrderFSM.editing_item), F.data.startswith("remove_line:"))
async def remove_product_line(callback: CallbackQuery, state: FSMContext):
    product_id_to_remove = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    
    state_data = await state.get_data()
    cart = state_data.get("cart", [])
    
    item_index_to_remove = next((i for i, item in enumerate(cart) if item["product_id"] == product_id_to_remove), None)

    if item_index_to_remove is not None:
        removed_item = cart.pop(item_index_to_remove)
        await state.update_data(cart=cart)
        
        order_cache[user_id]["cart"] = cart 

        logger.debug(f"[DEBUG] remove_product_line called for user_id: {user_id}. Current cart: {cart}")
        # Текст для alert не требует MarkdownV2
        await callback.answer(f"🗑 Строка с товаром '{removed_item['product_name']}' удалена.", show_alert=True)
        logger.debug(f"[DEBUG] remove_product_line completed for user_id: {user_id}. After removal: {cart}")
    else:
        await callback.answer("⚠️ Ошибка при удалении строки.", show_alert=True)

    await show_cart_menu(callback.message, state)
    await state.set_state(OrderFSM.editing_order)
    current_cart_for_debug = (await state.get_data()).get('cart', [])
    print(f"[DEBUG] remove_product_line completed for user_id: {user_id}. After removal: {current_cart_for_debug}")


@router.callback_query(F.data == "back_to_cart_menu")
async def back_to_cart_menu(callback: CallbackQuery, state: FSMContext):
    await show_cart_menu(callback.message, state)
    await state.set_state(OrderFSM.editing_order)


@router.callback_query(F.data == "edit_delivery_date")
async def edit_delivery_date(callback: CallbackQuery, state: FSMContext):
    today = date.today()
    dates = []
    for i in range(1, 8):
        d = today + timedelta(days=i)
        if d.weekday() < 5:
            dates.append(d)
    
    markup = delivery_date_keyboard(today)
    
    # Текст сообщения должен быть экранирован перед отправкой
    message_text_raw = "Выберите новую дату доставки:"
    message_text_escaped = escape_markdown_v2(message_text_raw)
    await callback.message.edit_text(message_text_escaped, reply_markup=markup, parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.change_delivery_date)


@router.callback_query(StateFilter(OrderFSM.change_delivery_date), F.data.startswith("date:"))
async def process_delivery_date_selection(callback: CallbackQuery, state: FSMContext):
    selected_date_str = callback.data.split(":")[1]
    selected_date = date.fromisoformat(selected_date_str)
    
    user_id = callback.from_user.id
    await state.update_data(delivery_date=selected_date)
    order_cache[user_id]["delivery_date"] = selected_date

    # Текст для alert не требует MarkdownV2
    await callback.answer(f"Дата доставки установлена на {selected_date.strftime('%d.%m.%Y')}", show_alert=True)
    await show_cart_menu(callback.message, state)


@router.callback_query(F.data == "confirm_order")
async def confirm_order(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    state_data = await state.get_data()
    cart_items = state_data.get("cart", [])
    delivery_date = state_data.get("delivery_date")

    if not cart_items:
        await callback.answer("Ваша корзина пуста. Добавьте товары перед подтверждением.", show_alert=True)
        await show_cart_menu(callback.message, state)
        return

    if not delivery_date:
        await callback.answer("Пожалуйста, выберите дату доставки перед подтверждением заказа.", show_alert=True)
        await edit_delivery_date(callback, state)
        return

    # Получаем необработанный текст сводки
    raw_summary_content = await _get_cart_summary_text(cart_items, delivery_date)

    # Применяем MarkdownV2 форматирование, как в show_cart_menu
    formatted_summary_lines = []
    lines = raw_summary_content.split('\n')
    for line in lines:
        if line.startswith("---"):
            formatted_summary_lines.append(line)
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

    # Исправляем \\n на обычный \n, так как escape_markdown_v2 уже все экранирует
    final_message = (
        f"{escape_markdown_v2('✅ Ваш заказ подтвержден!')}\n\n"
        f"{escaped_summary_text}\n\n"
        f"{escape_markdown_v2('Мы свяжемся с вами для уточнения деталей.')}"
    )

    await callback.message.edit_text(
        final_message, # Используем новую переменную final_message
        parse_mode="MarkdownV2",
        reply_markup=None
    )
    await callback.answer("Заказ подтвержден!", show_alert=True)
    await state.clear()