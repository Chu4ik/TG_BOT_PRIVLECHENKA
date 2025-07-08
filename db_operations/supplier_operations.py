# handlers/reports/supplier_reports.py

import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import List

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command

# Импортируем функции из нового файла операций с поставщиками
from db_operations.supplier_operations import (
    get_incoming_deliveries_for_date,
    get_supplier_payments_for_date,
    IncomingDeliveryReportItem,
    SupplierPaymentReportItem
)

router = Router()
logger = logging.getLogger(__name__)

# Убедитесь, что эта функция определена или доступна глобально в вашем проекте
def escape_markdown_v2(text: str) -> str:
    """Escapes special characters for MarkdownV2."""
    # ИСПРАВЛЕНО: Добавлен обратный слэш '\' в список специальных символов
    special_chars = r'_*[]()~`>#+-=|{}.!\'\\'
    return re.sub(f"([{re.escape(special_chars)}])", r"\\\1", text)

@router.message(Command("incoming_deliveries_today"))
async def show_incoming_deliveries_report(message: Message, db_pool):
    """
    Показывает отчет о поступлениях товара от поставщиков за сегодня.
    """
    today = date.today()
    today_str = today.strftime('%d.%m.%Y')
    
    deliveries = await get_incoming_deliveries_for_date(db_pool, today)
    
    report_parts = []
    report_parts.append(f"📦 *Отчет о поступлениях товара за {escape_markdown_v2(today_str)}:*\n\n")
    
    total_cost_of_deliveries = Decimal('0.00')

    if not deliveries:
        report_parts.append(escape_markdown_v2("За сегодня нет поступлений товара."))
    else:
        for i, item in enumerate(deliveries):
            report_parts.append(
                f"*{i+1}\\. Поступление ID {item.delivery_id}*\n"
                f"   Поставщик: {escape_markdown_v2(item.supplier_name)}\n"
                f"   Товар: {escape_markdown_v2(item.product_name)}\n"
                f"   Кол-во: `{item.quantity}` ед\\. по `{item.unit_cost:.2f} ₴`\n"
                f"   Общая стоимость: `{item.total_cost:.2f} ₴`\n"
                f"{escape_markdown_v2('----------------------------------')}\n"
            )
            total_cost_of_deliveries += item.total_cost
        
        report_parts.append(f"*ИТОГО ПОСТУПЛЕНИЙ ЗА СЕГОДНЯ: `{total_cost_of_deliveries:.2f} ₴`*")

    final_report_text = "".join(report_parts)
    
    await message.answer(final_report_text, parse_mode="MarkdownV2")


@router.message(Command("supplier_payments_today"))
async def show_supplier_payments_report(message: Message, db_pool):
    """
    Показывает отчет об оплатах поставщикам за сегодня.
    """
    today = date.today()
    today_str = today.strftime('%d.%m.%Y')
    
    payments = await get_supplier_payments_for_date(db_pool, today)
    
    report_parts = []
    report_parts.append(f"💸 *Отчет об оплатах поставщикам за {escape_markdown_v2(today_str)}:*\n\n")
    
    total_paid_amount = Decimal('0.00')

    if not payments:
        report_parts.append(escape_markdown_v2("За сегодня нет оплат поставщикам."))
    else:
        for i, payment in enumerate(payments):
            delivery_info = f" (Поставка ID: `{payment.delivery_id}`)" if payment.delivery_id else ""
            report_parts.append(
                f"*{i+1}\\. Оплата ID {payment.payment_id}*\n"
                f"   Поставщик: {escape_markdown_v2(payment.supplier_name)}\n"
                f"   Сумма: `{payment.amount:.2f} ₴`\n"
                f"   Метод: {escape_markdown_v2(payment.payment_method)}{escape_markdown_v2(delivery_info)}\n"
                f"   Дата оплаты: `{payment.payment_date.strftime('%Y-%m-%d')}`\n"
                f"{escape_markdown_v2('----------------------------------')}\n"
            )
            total_paid_amount += payment.amount
        
        report_parts.append(f"*ИТОГО ОПЛАЧЕНО ПОСТАВЩИКАМ ЗА СЕГОДНЯ: `{total_paid_amount:.2f} ₴`*")

    final_report_text = "".join(report_parts)
    
    await message.answer(final_report_text, parse_mode="MarkdownV2")