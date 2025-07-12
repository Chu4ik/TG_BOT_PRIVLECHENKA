# handlers/reports/inventory_report.py

import logging
import re
from typing import List

from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
from utils.markdown_utils import escape_markdown_v2

# Импортируем функции из нового файла операций с продуктами
from db_operations.product_operations import get_all_product_stock, ProductStockItem

router = Router()
logger = logging.getLogger(__name__)

@router.message(Command("inventory_report"))
async def show_inventory_report(message: Message, db_pool):
    """
    Показывает отчет о текущих остатках товаров на складе.
    """
    stock_items = await get_all_product_stock(db_pool)
    
    report_parts = []
    report_parts.append(f"📦 *Текущие остатки товаров на складе:*\n\n")
    
    if not stock_items:
        report_parts.append(escape_markdown_v2("На складе нет товаров или не удалось получить данные."))
    else:
        for i, item in enumerate(stock_items):
            report_parts.append(
                f"*{i+1}\\. {escape_markdown_v2(item.name)}*\n"
                f"   Остаток: `{item.current_stock}` ед\\.\n"
                # Удалена строка с ценой себестоимости
                f"{escape_markdown_v2('----------------------------------')}\n"
            )
        
    final_report_text = "".join(report_parts)
    
    await message.answer(final_report_text, parse_mode="MarkdownV2")