# handlers/reports/client_payments_report.py

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Optional, List, Dict

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter

# ИМПОРТИРУЕМ ИЗМЕНЕННУЮ ФУНКЦИЮ ЭКРАНИРОВАНИЯ
from utils.markdown_utils import escape_markdown_v2 # <-- ИСПРАВЛЕНО: используем встроенный aiogram.utils.markdown


from db_operations.report_payment_operations import (
    get_unpaid_invoices,
    confirm_payment_in_db,
    update_partial_payment_in_db,
    reverse_payment_in_db,
    get_today_paid_invoices,
    get_single_unpaid_invoice_details,
    UnpaidInvoice,
    TodayPaidInvoice
)
from states.order import OrderFSM 


router = Router()
logger = logging.getLogger(__name__)

# --- Вспомогательные функции для клавиатуры и форматирования ---

def build_unpaid_invoices_keyboard(invoices: List[UnpaidInvoice]) -> InlineKeyboardMarkup:
    """
    Строит инлайн-клавиатуру для списка неоплаченных накладных.
    Отображает только номер заказа и имя клиента.
    """
    buttons = []
    for invoice in invoices:
        # ИСПРАВЛЕНО ЗДЕСЬ: Максимально упрощенный текст кнопки для отладки
        # Убираем все форматирование, кроме ID и имени клиента
        button_text = (
            f"Заказ №{str(invoice.order_id)} {invoice.client_name}"
        )
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(button_text), # Экранируем ВЕСЬ текст кнопки
                callback_data=f"view_invoice_details_{invoice.order_id}"
            )
        ])
    
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_unpaid_invoices"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main_menu")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_invoice_details_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру для детального просмотра накладной с опциями оплаты.
    """
    buttons = [
        [InlineKeyboardButton(text="✅ Оплачено полностью", callback_data=f"confirm_payment_{order_id}")],
        [InlineKeyboardButton(text="✍️ Частичная оплата", callback_data=f"partial_payment_{order_id}")],
        [InlineKeyboardButton(text="↩️ Отменить оплату", callback_data=f"reverse_payment_{order_id}")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="back_to_unpaid_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Определение функции format_unpaid_invoice_details
def format_unpaid_invoice_details(invoice: UnpaidInvoice) -> str:
    """
    Форматирует детальное сообщение для одной неоплаченной накладной,
    включая детали платежей и возвратов.
    Каждое переменное значение экранируется.
    """
    # Экранируем каждый элемент данных из NamedTuple, чтобы избежать ошибок
    invoice_number_escaped = escape_markdown_v2(invoice.invoice_number)
    order_id_escaped = escape_markdown_v2(str(invoice.order_id)) 
    client_name_escaped = escape_markdown_v2(invoice.client_name)
    payment_status_display_name = {
        'unpaid': 'Не оплачено',
        'partially_paid': 'Частично оплачено',
        'paid': 'Оплачено',
        'overdue': 'Просрочено'
    }.get(invoice.payment_status, invoice.payment_status)
    payment_status_display_name_escaped = escape_markdown_v2(payment_status_display_name)

    confirmation_date_str = (
        invoice.confirmation_date.strftime('%Y-%m-%d')
        if invoice.confirmation_date
        else "Не указана"
    )
    due_date_str = (
        invoice.due_date.strftime('%Y-%m-%d')
        if invoice.due_date
        else "Не указана"
    )

    # ИСПРАВЛЕНО ЗДЕСЬ: Экранируем КАЖДУЮ СТРОКУ, которая может содержать спецсимволы
    # Даже если она содержит уже форматирование MarkdownV2, escape_markdown_v2 должна справиться
    # с экранированием остальных спецсимволов.
    
    text_parts = []
    # Заголовок
    text_parts.append(escape_markdown_v2(f"📋 *Детали накладной №{invoice_number_escaped}:*\n")) # Экранируем всю строку
    # ID Заказа
    text_parts.append(f"🆔 ID Заказа: `{order_id_escaped}`\n") 
    # Даты
    text_parts.append(f"📅 Дата накладной: `{escape_markdown_v2(confirmation_date_str)}`\n") 
    text_parts.append(f"📅 Срок оплаты: `{escape_markdown_v2(due_date_str)}`\n") 
    # Клиент
    text_parts.append(f"👤 Клиент: {client_name_escaped}\n")
    # Суммы
    text_parts.append(f"💰 Общая сумма заказа: `{escape_markdown_v2(f'{invoice.total_amount:.2f}')} ₴`\n")
    text_parts.append(f"💵 Всего оплачено (поступления): `{escape_markdown_v2(f'{invoice.total_payments_received:.2f}')} ₴`\n")
    
    if invoice.total_credits_issued > 0:
        text_parts.append(f"↩️ Сумма возвратов: `{escape_markdown_v2(f'{invoice.total_credits_issued:.2f}')} ₴`\n")
    
    # Остаток и статус
    text_parts.append(
        f"⚠️ *Актуальный остаток к оплате: `{escape_markdown_v2(f'{invoice.actual_outstanding_balance:.2f}')} ₴`*\n"
        f"📊 Статус оплаты (из накладной): `{payment_status_display_name_escaped}`"
    )
    return "".join(text_parts)


# --- ХЕНДЛЕРЫ ДЛЯ ОТЧЕТА "ОПЛАТЫ КЛИЕНТОВ" ---

@router.message(Command("payments")) 
@router.message(F.text == "💰 Отчет по оплатам") 
@router.callback_query(F.data == "back_to_unpaid_list")
@router.callback_query(F.data == "refresh_unpaid_invoices")
async def show_client_payments_report(callback_or_message, state: FSMContext, db_pool):
    """
    Показывает список неоплаченных накладных.
    """
    message_object: Message | None = None
    is_callback = isinstance(callback_or_message, CallbackQuery)

    if is_callback:
        await callback_or_message.answer()
        message_object = callback_or_message.message
    else:
        message_object = callback_or_message

    if message_object is None:
        logger.error("Не удалось получить объект сообщения из 'callback_or_message'.")
        if is_callback and callback_or_message.message:
            await callback_or_message.message.answer(escape_markdown_v2("Произошла ошибка при отображении отчета. Пожалуйста, попробуйте еще раз."), parse_mode="MarkdownV2")
        elif isinstance(callback_or_message, Message):
            await callback_or_message.answer(escape_markdown_v2("Произошла ошибка при отображении отчета. Пожалуйста, попробуйте еще раз."), parse_mode="MarkdownV2")
        return

    await state.clear()
    
    invoices = await get_unpaid_invoices(db_pool)

    keyboard = build_unpaid_invoices_keyboard(invoices)

    if not invoices:
        report_text = escape_markdown_v2("Нет неоплаченных накладных.")
        
        if is_callback:
            try:
                await message_object.edit_text(report_text, parse_mode="MarkdownV2")
            except Exception as e:
                logger.warning(f"Не удалось отредактировать сообщение для пустого отчета (вероятно, сообщение слишком старое): {e}")
                await message_object.answer(report_text, parse_mode="MarkdownV2")
        else:
            await message_object.answer(report_text, parse_mode="MarkdownV2")
        return

    header_text = escape_markdown_v2("Список неоплаченных накладных:")

    if is_callback:
        try:
            await message_object.edit_text(header_text, reply_markup=keyboard, parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение (вероятно, слишком старое) при возврате к списку: {e}")
            await message_object.answer(header_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    else:
        await message_object.answer(header_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    
    await state.set_state(OrderFSM.viewing_unpaid_invoices_list)


@router.message(Command("financial_report_today"))
async def show_financial_report_today(message: Message, db_pool):
    """
    Показывает финансовый отчет за сегодня: все оплаченные накладные и общая сумма.
    """
    today = date.today()
    today_str = today.strftime('%d.%m.%Y')
    
    paid_invoices = await get_today_paid_invoices(db_pool)
    
    report_parts = []
    report_parts.append(f"📊 *Финансовый отчет за {escape_markdown_v2(today_str)}:*\n\n")
    
    total_paid_amount = Decimal('0.00')

    if not paid_invoices:
        report_parts.append(escape_markdown_v2("За сегодня нет подтвержденных оплат по накладным."))
    else:
        for i, invoice in enumerate(paid_invoices):
            report_parts.append(
                f"*{i+1}\\. Накладная №{escape_markdown_v2(invoice.invoice_number)}*\n"
                f"   Клиент: {escape_markdown_v2(invoice.client_name)}\n"
                f"   Сумма оплаты: `{escape_markdown_v2(f'{invoice.amount_paid:.2f}')} ₴`\n"
                f"   Дата оплаты: `{escape_markdown_v2(invoice.actual_payment_date.strftime('%Y-%m-%d'))}`\n"
                f"{escape_markdown_v2('----------------------------------')}\n"
            )
            total_paid_amount += invoice.amount_paid
        
        report_parts.append(f"*ИТОГО ОПЛАЧЕНО ЗА СЕГОДНЯ: `{escape_markdown_v2(f'{total_paid_amount:.2f}')} ₴`*")

    final_report_text = "".join(report_parts)
    
    await message.answer(final_report_text, parse_mode="MarkdownV2")


@router.callback_query(F.data.startswith("view_invoice_details_"), StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def view_invoice_details(callback: CallbackQuery, state: FSMContext, db_pool):
    order_id = int(callback.data.split("view_invoice_details_")[1])
    
    invoice = await get_single_unpaid_invoice_details(db_pool, order_id)

    if invoice:
        await state.update_data(current_invoice_id=order_id)
        details_text_raw = format_unpaid_invoice_details(invoice) # Получаем необработанный текст
        
        # --- НОВОЕ: Оборачиваем весь текст в обратные апострофы, чтобы избежать ошибок парсинга MarkdownV2 ---
        # Это крайняя мера, чтобы гарантировать, что все символы будут отображаться буквально.
        details_text_safe = f"```\n{details_text_raw}\n```" 
        # --- КОНЕЦ НОВОГО ---

        keyboard = build_invoice_details_keyboard(order_id)
        
        # Отправляем сообщение с parse_mode="MarkdownV2", но текст уже в "inline code"
        await callback.message.edit_text(details_text_safe, reply_markup=keyboard, parse_mode="MarkdownV2")
    else:
        await callback.answer("Накладная не найдена.", show_alert=True)
    
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_payment_"), StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def handle_confirm_payment(callback: CallbackQuery, state: FSMContext, db_pool):
    order_id = int(callback.data.split("confirm_payment_")[1])
    
    success = await confirm_payment_in_db(db_pool, order_id)
    if success:
        await callback.answer("✅ Оплата подтверждена!", show_alert=True)
        await show_client_payments_report(callback.message, state, db_pool)
    else:
        await callback.answer("❌ Ошибка подтверждения оплаты.", show_alert=True)
    await callback.answer()

@router.callback_query(F.data.startswith("partial_payment_"), StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def handle_partial_payment_input(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split("partial_payment_")[1])
    await state.update_data(order_to_partial_pay=order_id)
    
    await callback.message.edit_text(escape_markdown_v2("Введите сумму частичной оплаты:"), parse_mode="MarkdownV2")
    await state.set_state(OrderFSM.entering_partial_payment_amount)
    await callback.answer()

@router.message(StateFilter(OrderFSM.entering_partial_payment_amount))
async def process_partial_payment_amount(message: Message, state: FSMContext, db_pool):
    amount_text = message.text.strip()
    try:
        # ИСПРАВЛЕНО ЗДЕСЬ: Заменяем запятые на точки
        partial_amount = Decimal(amount_text.replace(',', '.'))
        if partial_amount < 0:
            await message.answer(escape_markdown_v2("Сумма не может быть отрицательной. Введите корректное значение:"), parse_mode="MarkdownV2")
            return
    except Exception: # Ловим более общее исключение, так как Decimal может вызвать InvalidOperation
        await message.answer(escape_markdown_v2("Неверный формат суммы. Пожалуйста, введите число (например, 100.50):"), parse_mode="MarkdownV2")
        return

    data = await state.get_data()
    order_id = data.get("order_to_partial_pay")

    if not order_id:
        await message.answer(escape_markdown_v2("Произошла ошибка: не удалось определить накладную для частичной оплаты."), parse_mode="MarkdownV2")
        await state.clear()
        return

    success = await update_partial_payment_in_db(db_pool, order_id, partial_amount)
    if success:
        await message.answer(escape_markdown_v2(f"✅ Частичная оплата в размере `{partial_amount:.2f}` грн для накладной #{order_id} обновлена."), parse_mode="MarkdownV2")
        await show_client_payments_report(message, state, db_pool)
    else:
        await message.answer(escape_markdown_v2("❌ Ошибка при обновлении частичной оплаты."), parse_mode="MarkdownV2")
        await state.clear()
    await state.clear()

@router.callback_query(F.data.startswith("reverse_payment_"), StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def handle_reverse_payment(callback: CallbackQuery, state: FSMContext, db_pool):
    order_id = int(callback.data.split("reverse_payment_")[1])
    
    success = await reverse_payment_in_db(db_pool, order_id)
    if success:
        await callback.answer("↩️ Оплата отменена/сброшена.", show_alert=True)
        await show_client_payments_report(callback.message, state, db_pool)
    else:
        await callback.answer("❌ Ошибка отмены оплаты.", show_alert=True)
    await callback.answer()

@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_from_payments(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(escape_markdown_v2("Вы вернулись в главное меню."), parse_mode="MarkdownV2")
    await callback.answer()