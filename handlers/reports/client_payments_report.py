# handlers/reports/client_payments_report.py

import logging
import re
from datetime import date
from decimal import Decimal
from typing import Optional, List, Dict

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter

# Импортируем все необходимое из db_operations/report_payment_operations
from db_operations.report_payment_operations import ( # <-- Убедитесь, что импорт из report_payment_operations
    get_unpaid_invoices,
    confirm_payment_in_db,
    update_partial_payment_in_db,
    reverse_payment_in_db,
    UnpaidInvoice # Новый namedtuple
)
from states.order import OrderFSM # Убедитесь, что у вас есть этот FSM

router = Router()
logger = logging.getLogger(__name__)

# Убедитесь, что эта функция определена или доступна глобально в вашем проекте
def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
    special_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)

# --- Вспомогательные функции для клавиатуры и форматирования ---

def build_unpaid_invoices_keyboard(invoices: List[UnpaidInvoice]) -> InlineKeyboardMarkup:
    """
    Строит инлайн-клавиатуру для списка неоплаченных накладных.
    """
    buttons = []
    for invoice in invoices:
        # Форматируем текст кнопки: ID_ДД ММ ГГГГ Клиент Сумма
        # Пример: 16_06 07 2025 Клиент 123.45₴
        if invoice.confirmation_date:
            day_part = invoice.confirmation_date.strftime('%d')
            month_year_part = invoice.confirmation_date.strftime('%m %Y')
            date_str_formatted = f"{day_part} {month_year_part}"
        else:
            date_str_formatted = "Н/Д"

        button_text = f"{invoice.order_id}_{date_str_formatted} {invoice.client_name} {invoice.outstanding_balance:.2f}₴" # <--- ИЗМЕНЕНО
        buttons.append([
            InlineKeyboardButton(
                text=escape_markdown_v2(button_text),
                callback_data=f"view_invoice_details_{invoice.order_id}"
            )
        ])
    
    # Кнопки общего действия (если есть)
    buttons.append([
        InlineKeyboardButton(text="🔄 Обновить список", callback_data="refresh_unpaid_invoices"),
        InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main_menu") # Или другая кнопка назад
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_unpaid_invoice_details(invoice: UnpaidInvoice) -> str:
    """
    Форматирует детальное сообщение для одной неоплаченной накладной.
    """
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

    status_map = {
        'unpaid': 'Не оплачено',
        'partially_paid': 'Частично оплачено',
        'paid': 'Оплачено',
        'overdue': 'Просрочено'
    }
    payment_status_display_name = status_map.get(invoice.payment_status, invoice.payment_status)

    text = (
        f"📋 *Детали накладной №{escape_markdown_v2(invoice.invoice_number)}:*\n"
        f"🆔 ID Заказа: `{invoice.order_id}`\n"
        f"📅 Дата накладной: `{confirmation_date_str}`\n"
        f"📅 Срок оплаты: `{due_date_str}`\n"
        f"👤 Клиент: {escape_markdown_v2(invoice.client_name)}\n"
        f"💰 Общая сумма: `{invoice.total_amount:.2f} ₴`\n"
        f"💵 Оплачено: `{invoice.amount_paid:.2f} ₴`\n"
        f"⚠️ Остаток к оплате: `{invoice.outstanding_balance:.2f} ₴`\n"
        f"📊 Статус оплаты: `{escape_markdown_v2(payment_status_display_name)}`"
    )
    return text


def build_invoice_details_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру для детального просмотра накладной с опциями оплаты.
    """
    buttons = [
        [InlineKeyboardButton(text="✅ Оплачено полностью", callback_data=f"confirm_payment_{order_id}")], # <--- ИСПРАВЛЕНО
        [InlineKeyboardButton(text="✍️ Частичная оплата", callback_data=f"partial_payment_{order_id}")],
        [InlineKeyboardButton(text="↩️ Отменить оплату", callback_data=f"reverse_payment_{order_id}")],
        [InlineKeyboardButton(text="⬅️ Назад к списку", callback_data="back_to_unpaid_list")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- ХЕНДЛЕРЫ ДЛЯ ОТЧЕТА "ОПЛАТЫ КЛИЕНТОВ" ---

@router.message(Command("payments")) # Можно использовать /payments или кнопку
@router.message(F.text == "💰 Отчет по оплатам") # Если будет кнопка в главном меню
@router.callback_query(F.data == "back_to_unpaid_list") # <--- Добавляем сюда обработку "Назад к списку"
@router.callback_query(F.data == "refresh_unpaid_invoices") # <--- Добавляем сюда обработку "Обновить список"
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
        # Fallback for error handling
        if is_callback and callback_or_message.message:
            await callback_or_message.message.answer(escape_markdown_v2("Произошла ошибка при отображении отчета. Пожалуйста, попробуйте еще раз."), parse_mode="MarkdownV2")
        elif isinstance(callback_or_message, Message):
            await callback_or_message.answer(escape_markdown_v2("Произошла ошибка при отображении отчета. Пожалуйста, попробуйте еще раз."), parse_mode="MarkdownV2")
        return

    await state.clear() # Очищаем текущее состояние, если вдруг было какое-то активное
    
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

    header_text = escape_markdown_v2("Список неоплаченных накладных:") # <--- Заголовок

    if is_callback:
        try:
            await message_object.edit_text(header_text, reply_markup=keyboard, parse_mode="MarkdownV2")
        except Exception as e:
            logger.warning(f"Не удалось отредактировать сообщение (вероятно, слишком старое) при возврате к списку: {e}")
            await message_object.answer(header_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    else:
        await message_object.answer(header_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    
    await state.set_state(OrderFSM.viewing_unpaid_invoices_list)


@router.callback_query(F.data.startswith("view_invoice_details_"), StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def view_invoice_details(callback: CallbackQuery, state: FSMContext, db_pool):
    order_id = int(callback.data.split("view_invoice_details_")[1])
    
    # Получаем детали только для этой накладной
    # Придется написать новую функцию в db_operations или использовать get_unpaid_invoices и фильтровать.
    # Проще всего получить одну запись, как это делалось для OrderDetail
    conn = None
    invoice = None
    try:
        conn = await db_pool.acquire()
        record = await conn.fetchrow("""
            SELECT
                o.order_id,
                o.invoice_number,
                o.confirmation_date,
                c.name AS client_name,
                o.total_amount,
                o.amount_paid,
                (o.total_amount - o.amount_paid) AS outstanding_balance,
                o.payment_status,
                o.due_date
            FROM
                orders o
            JOIN
                clients c ON o.client_id = c.client_id
            WHERE
                o.order_id = $1;
        """, order_id)
        if record:
            invoice = UnpaidInvoice(**record)
    except Exception as e:
        logger.error(f"Ошибка при получении деталей накладной #{order_id}: {e}", exc_info=True)
        await callback.answer("Ошибка при загрузке деталей накладной.", show_alert=True)
        if conn: await db_pool.release(conn)
        return
    finally:
        if conn:
            await db_pool.release(conn)

    if invoice:
        await state.update_data(current_invoice_id=order_id) # Сохраняем ID для дальнейших действий
        details_text = format_unpaid_invoice_details(invoice)
        keyboard = build_invoice_details_keyboard(order_id)
        
        await callback.message.edit_text(details_text, reply_markup=keyboard, parse_mode="MarkdownV2")
    else:
        await callback.answer("Накладная не найдена.", show_alert=True)
    
    await callback.answer() # Закрываем индикатор загрузки


@router.callback_query(F.data.startswith("confirm_payment_"), StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def handle_confirm_payment(callback: CallbackQuery, state: FSMContext, db_pool):
    order_id = int(callback.data.split("confirm_payment_")[1])
    
    success = await confirm_payment_in_db(db_pool, order_id)
    if success:
        await callback.answer("✅ Оплата подтверждена!", show_alert=True)
        # Обновляем сообщение или возвращаемся к списку
        await show_client_payments_report(callback.message, state, db_pool) # Обновляем список отчета
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
        partial_amount = Decimal(amount_text)
        if partial_amount < 0:
            await message.answer(escape_markdown_v2("Сумма не может быть отрицательной. Введите корректное значение:"), parse_mode="MarkdownV2")
            return
    except Exception:
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
        await show_client_payments_report(message, state, db_pool) # Обновляем список отчета
    else:
        await message.answer(escape_markdown_v2("❌ Ошибка при обновлении частичной оплаты."), parse_mode="MarkdownV2")
        await state.clear() # В случае ошибки лучше сбросить состояние
    await state.clear() # Сбрасываем состояние после обработки ввода

@router.callback_query(F.data.startswith("reverse_payment_"), StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def handle_reverse_payment(callback: CallbackQuery, state: FSMContext, db_pool):
    order_id = int(callback.data.split("reverse_payment_")[1])
    
    success = await reverse_payment_in_db(db_pool, order_id)
    if success:
        await callback.answer("↩️ Оплата отменена/сброшена.", show_alert=True)
        await show_client_payments_report(callback.message, state, db_pool) # Обновляем список отчета
    else:
        await callback.answer("❌ Ошибка отмены оплаты.", show_alert=True)
    await callback.answer()

# Хендлер для кнопки "Назад к списку"
@router.callback_query(F.data == "back_to_unpaid_list", StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def back_to_unpaid_list_handler(callback: CallbackQuery, state: FSMContext, db_pool):
    await show_client_payments_report(callback.message, state, db_pool)
    await callback.answer()

# Хендлер для кнопки "Обновить список"
@router.callback_query(F.data == "refresh_unpaid_invoices", StateFilter(OrderFSM.viewing_unpaid_invoices_list))
async def refresh_unpaid_invoices_handler(callback: CallbackQuery, state: FSMContext, db_pool):
    await show_client_payments_report(callback.message, state, db_pool)
    await callback.answer("Список обновлен!", show_alert=False)

# Хендлер для кнопки "Назад к главному меню" (если будет такая кнопка)
@router.callback_query(F.data == "back_to_main_menu")
async def back_to_main_menu_from_payments(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer(escape_markdown_v2("Вы вернулись в главное меню."), parse_mode="MarkdownV2")
    await callback.answer()