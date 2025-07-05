import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command 
from states.order import OrderFSM 
from db_operations.db import get_unconfirmed_orders, confirm_order_in_db, cancel_order_in_db, confirm_all_orders_in_db, cancel_all_orders_in_db 
from datetime import date
import re
from keyboards.inline_keyboards import create_confirm_report_keyboard

router = Router()
logger = logging.getLogger(__name__)

def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!' 
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)

def build_order_list_keyboard(orders: list) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру для отчета с неподтвержденными заказами.
    Включает кнопки для просмотра отдельных заказов и массовых действий.
    """
    buttons = []
    
    for order_id, order_date, client_name, total_amount in orders:
        escaped_client_name = client_name.replace('_', '\\_').replace('*', '\\*').replace('[', '\\[')
        buttons.append([
            InlineKeyboardButton(text=f"Заказ №{order_id} ({escaped_client_name}) - {total_amount:.2f}₴", 
                                 callback_data=f"view_order_{order_id}")
        ])
    
    if orders: 
        buttons.append([InlineKeyboardButton(text="✅ Подтвердить все заказы", callback_data="confirm_all_orders")])
        buttons.append([InlineKeyboardButton(text="❌ Отменить все заказы", callback_data="cancel_all_orders")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(F.text == "/show_unconfirmed_orders")
@router.callback_query(F.data == "show_unconfirmed_orders")
async def show_unconfirmed_orders_report(callback_or_message, state: FSMContext, db_pool): # <--- ДОБАВЛЕНО: db_pool
    message_object: Message | None = None 

    if isinstance(callback_or_message, CallbackQuery):
        await callback_or_message.answer() 
        message_object = callback_or_message.message
    else: 
        message_object = callback_or_message

    if message_object is None:
        logger.error("Не удалось получить объект сообщения из 'callback_or_message'.")
        if isinstance(callback_or_message, CallbackQuery) and callback_or_message.message:
            await callback_or_message.message.answer("Произошла ошибка при отображении отчета. Пожалуйста, попробуйте еще раз.")
        elif isinstance(callback_or_message, Message):
            await callback_or_message.answer("Произошла ошибка при отображении отчета. Пожалуйста, попробуйте еще раз.")
        return 

    logger.info("Показ отчета о неподтвержденных заказов.")
    
    # ИСПРАВЛЕНИЕ: Передаем db_pool в get_unconfirmed_orders
    unconfirmed_orders = await get_unconfirmed_orders(db_pool) 

    if not unconfirmed_orders:
        report_text = escape_markdown_v2("Нет неподтвержденных заказов.") 
        await message_object.answer(report_text, parse_mode="MarkdownV2") 
        return

    report_text_parts = [] 
    report_text_parts.append(f"*{escape_markdown_v2('Неподтвержденные заказы:')}*\n\n") 

    order_ids = []
    for order in unconfirmed_orders:
        escaped_order_id = escape_markdown_v2(str(order.order_id))
        escaped_order_date = escape_markdown_v2(order.order_date.strftime('%d.%m.%Y'))
        escaped_delivery_date = escape_markdown_v2(order.delivery_date.strftime('%d.%m.%Y'))
        escaped_client_name = escape_markdown_v2(order.client_name)
        escaped_address_text = escape_markdown_v2(order.address_text)
        escaped_total_amount = escape_markdown_v2(f"{order.total_amount:.2f}")

        order_info = (
            f"Заказ №{escaped_order_id} от {escaped_order_date}\n"
            f"Дата доставки: {escaped_delivery_date}\n"
            f"Клиент: {escaped_client_name}\n"
            f"Адрес: {escaped_address_text}\n"
            f"Сумма: {escaped_total_amount} грн\n"
            f"{escape_markdown_v2('----------------------------------')}\n"
        )
        report_text_parts.append(order_info)
        order_ids.append(order.order_id)
    
    report_text = "".join(report_text_parts)

    keyboard = create_confirm_report_keyboard(order_ids)
    
    await message_object.answer(report_text, reply_markup=keyboard, parse_mode="MarkdownV2")


@router.callback_query(F.data == "confirm_all_orders")
async def handle_confirm_all_orders(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ДОБАВЛЕНО: db_pool
    """
    Обрабатывает нажатие на кнопку "Подтвердить все заказы".
    """
    # ИСПРАВЛЕНИЕ: Передаем db_pool в get_unconfirmed_orders
    orders_to_confirm = await get_unconfirmed_orders(db_pool) 
    order_ids = [order[0] for order in orders_to_confirm] 

    if not order_ids:
        await callback.answer("Нет заказов для подтверждения.", show_alert=True)
        return

    # ИСПРАВЛЕНИЕ: Передаем db_pool в confirm_all_orders_in_db
    success = await confirm_all_orders_in_db(db_pool, order_ids) 
    if success:
        await callback.message.edit_text("✅ Все неподтвержденные заказы успешно подтверждены и сформированы накладные!")
    else:
        await callback.message.edit_text("❌ Произошла ошибка при подтверждении всех заказов.")
    await callback.answer()
    # ИСПРАВЛЕНИЕ: Передаем db_pool в show_unconfirmed_orders_report
    await show_unconfirmed_orders_report(callback, state, db_pool) 


@router.callback_query(F.data == "cancel_all_orders")
async def handle_cancel_all_orders(callback: CallbackQuery, state: FSMContext, db_pool): # <--- ДОБАВЛЕНО: db_pool
    """
    Обрабатывает нажатие на кнопку "Отменить все заказы".
    """
    # ИСПРАВЛЕНИЕ: Передаем db_pool в get_unconfirmed_orders
    orders_to_cancel = await get_unconfirmed_orders(db_pool) 
    order_ids = [order[0] for order in orders_to_cancel] 

    if not order_ids:
        await callback.answer("Нет заказов для отмены.", show_alert=True)
        return

    # ИСПРАВЛЕНИЕ: Передаем db_pool в cancel_all_orders_in_db
    success = await cancel_all_orders_in_db(db_pool, order_ids) 
    if success:
        await callback.message.edit_text("🗑️ Все неподтвержденные заказы успешно отменены и удалены.")
    else:
        await callback.message.edit_text("❌ Произошла ошибка при отмене всех заказов.")
    await callback.answer()
    # ИСПРАВЛЕНИЕ: Передаем db_pool в show_unconfirmed_orders_report
    await show_unconfirmed_orders_report(callback, state, db_pool)

@router.callback_query(F.data.startswith("view_order_"))
async def view_individual_order(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик для просмотра деталей отдельного заказа (функционал будет разработан позже).
    """
    order_id = int(callback.data.split("_")[2])
    await callback.answer(f"Просмотр заказа №{order_id} (функционал будет разработан позже)", show_alert=True)