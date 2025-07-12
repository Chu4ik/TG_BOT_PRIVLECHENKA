# handlers/reports/my_orders_report.py
import logging
import re
from datetime import date
from decimal import Decimal
from typing import List, Dict, Optional
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from utils.markdown_utils import escape_markdown_v2

from db_operations.report_my_orders import get_my_orders_for_today, get_order_full_details, OrderDetail

router = Router()
logger = logging.getLogger(__name__)

def build_my_orders_keyboard(orders: list) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру со списком заказов пользователя.
    """
    buttons = []
    for order in orders:
        # Экранируем имя клиента для отображения в кнопке
        escaped_client_name = escape_markdown_v2(order.client_name)
        buttons.append([
            InlineKeyboardButton(
                text=f"Заказ №{order.order_id} ({escaped_client_name}) - {order.total_amount:.2f}₴",
                callback_data=f"view_my_order_details_{order.order_id}"
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

@router.message(F.text == "/my_orders")
async def show_my_orders_report(message: Message, state: FSMContext, db_pool):
    """
    Показывает отчет о заказах пользователя за сегодняшний день в виде кнопок.
    """
    user_id = message.from_user.id
    logger.info(f"Пользователь {user_id} запросил отчет о своих заказах за сегодня.")

    orders = await get_my_orders_for_today(db_pool, user_id)

    if not orders:
        report_text = escape_markdown_v2("У вас нет заказов, сформированных сегодня.")
        await message.answer(report_text, parse_mode="MarkdownV2")
        return

    # Сообщение, которое будет отображаться над кнопками
    initial_text = escape_markdown_v2("Выберите заказ, чтобы посмотреть детали:")
    
    keyboard = build_my_orders_keyboard(orders)

    await message.answer(initial_text, reply_markup=keyboard, parse_mode="MarkdownV2")



@router.callback_query(F.data.startswith("view_my_order_details_"))
async def view_my_order_details(callback: CallbackQuery, state: FSMContext, db_pool):
    """
    Показывает полную сводку по выбранному заказу.
    """
    await callback.answer() # Убираем "часики" с кнопки
    
    order_id = int(callback.data.split("_")[-1])
    logger.info(f"Пользователь {callback.from_user.id} запросил детали заказа №{order_id}.")

    order_details = await get_order_full_details(db_pool, order_id)

    if not order_details:
        await callback.message.edit_text(escape_markdown_v2(f"❌ Не удалось найти детали для заказа №{order_id}."), parse_mode="MarkdownV2")
        return

    # Формируем текст сводки заказа
    summary_lines = []
    summary_lines.append(f"*{escape_markdown_v2(f'Сводка заказа №{order_details["order_id"]}:')}*\n")
    summary_lines.append(f"Дата заказа: *{escape_markdown_v2(order_details['order_date'].strftime('%d.%m.%Y'))}*")
    summary_lines.append(f"Дата доставки: *{escape_markdown_v2(order_details['delivery_date'].strftime('%d.%m.%Y'))}*")
    summary_lines.append(f"Клиент: *{escape_markdown_v2(order_details['client_name'])}*")
    summary_lines.append(f"Адрес: *{escape_markdown_v2(order_details['address_text'])}*")
    summary_lines.append(f"Статус: *{escape_markdown_v2(order_details['status'])}*")
    summary_lines.append(escape_markdown_v2("--- ТОВАРЫ ---"))

    if order_details["items"]:
        for i, item in enumerate(order_details["items"]):
            item_line = (
                f"{i+1}\\. {escape_markdown_v2(item.product_name)} "
                f"\\({escape_markdown_v2(f'{item.quantity:.2f}')} ед\\. x "
                f"{escape_markdown_v2(f'{item.unit_price:.2f}')} грн\\.\\) \\= " # <-- ДОБАВЛЕН ОБРАТНЫЙ СЛЕШ ПЕРЕД '='
                f"*{escape_markdown_v2(f'{item.total_item_amount:.2f}')}* грн\\."
            )
            summary_lines.append(item_line)
    else:
        summary_lines.append(escape_markdown_v2("  В этом заказе нет товаров."))

    summary_lines.append(escape_markdown_v2("----------------------------------"))
    summary_lines.append(f"*{escape_markdown_v2(f'ИТОГО: {order_details["total_amount"]:.2f} грн')}*")

    final_summary_text = "\n".join(summary_lines)

    # Кнопка "Назад к моим заказам"
    back_button = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Назад к моим заказам", callback_data="show_my_orders_report")]
    ])

    try:
        await callback.message.edit_text(
            final_summary_text,
            parse_mode="MarkdownV2",
            reply_markup=back_button
        )
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения с деталями заказа {order_id}: {e}", exc_info=True)
        await callback.message.answer(escape_markdown_v2("Произошла ошибка при отображении деталей заказа. Пожалуйста, попробуйте снова."), parse_mode="MarkdownV2")

# Добавляем обработчик для кнопки "Назад к моим заказам"
# Добавляем обработчик для кнопки "Назад к моим заказам"
@router.callback_query(F.data == "show_my_orders_report")
async def back_to_my_orders(callback: CallbackQuery, state: FSMContext, db_pool):
    await callback.answer()
    
    # ПЕРЕМЕНЕНА СТРОКА: Прямо передаем ID пользователя в show_my_orders_report
    # show_my_orders_report ожидает объект Message, поэтому нам нужно будет создать его
    # или, что проще, переделать show_my_orders_report, чтобы он принимал user_id напрямую.
    # Давайте сделаем это: изменим show_my_orders_report, чтобы она могла вызываться с user_id.

    await show_my_orders_report_by_user_id(
        callback.message, # Мы передаем сообщение, чтобы можно было отредактировать его или ответить на него
        state,
        db_pool,
        user_id=callback.from_user.id # Передаем user_id явно
    )

# НОВАЯ ФУНКЦИЯ: show_my_orders_report_by_user_id
# Эта функция будет вызываться как из обработчика /my_orders, так и из "Назад"
async def show_my_orders_report_by_user_id(message: Message, state: FSMContext, db_pool, user_id: Optional[int] = None):
    """
    Показывает отчет о заказах пользователя за сегодняшний день в виде кнопок.
    Может быть вызвана с явным user_id или извлечет его из message.
    """
    if user_id is None:
        user_id = message.from_user.id
    
    logger.info(f"Пользователь {user_id} запросил отчет о своих заказах за сегодня.")

    orders = await get_my_orders_for_today(db_pool, user_id) # Теперь user_id точно корректный

    if not orders:
        report_text = escape_markdown_v2("У вас нет заказов, сформированных сегодня.")
        await message.answer(report_text, parse_mode="MarkdownV2")
        return

    initial_text = escape_markdown_v2("Выберите заказ, чтобы посмотреть детали:")
    keyboard = build_my_orders_keyboard(orders)

    # Вместо message.answer, используем edit_text, если это колбэк,
    # чтобы обновить предыдущее сообщение.
    try:
        await message.edit_text(initial_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    except Exception: # Если сообщение не может быть отредактировано (например, оно старое)
        await message.answer(initial_text, reply_markup=keyboard, parse_mode="MarkdownV2")

# ИЗМЕНЯЕМ существующий декоратор, чтобы он вызывал новую функцию
@router.message(F.text == "/my_orders")
async def show_my_orders_report(message: Message, state: FSMContext, db_pool):
    await show_my_orders_report_by_user_id(message, state, db_pool)