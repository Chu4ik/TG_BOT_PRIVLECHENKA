# handlers/orders/order_helpers.py
import re
from datetime import date
from decimal import Decimal

# Функция escape_markdown_v2 УДАЛЕНА ИЗ ЭТОГО ФАЙЛА!

# ИЗМЕНЕНА: Теперь принимает cart_items, delivery_date, client_name, address_text как аргументы.
# Возвращает ЧИСТЫЙ текст без MarkdownV2 форматирования или экранирования.
async def _get_cart_summary_text(cart_items: list, delivery_date: date | None, client_name: str | None = None, address_text: str | None = None) -> str:
    """Возвращает текущую сводку корзины в виде строки (без MarkdownV2 форматирования)."""
    summary_lines = []

    if not cart_items and not delivery_date and not client_name and not address_text:
        return "--- ТОВАРЫ В ЗАКАЗЕ ---\nКорзина пока пуста.\n------------------------"
        
    summary_lines.append("--- СВОДКА ЗАКАЗА ---")

    if client_name:
        summary_lines.append(f"Клиент: {client_name}")
    if address_text:
        summary_lines.append(f"Адрес: {address_text}")

    if delivery_date:
        summary_lines.append(f"Дата доставки: {delivery_date.strftime('%d.%m.%Y')}")
    else:
        summary_lines.append("Дата доставки: Не указана")

    summary_lines.append("\n--- ТОВАРЫ ---")
    
    total_quantity_all_items = 0
    grand_total = Decimal('0.0')

    if not cart_items:
        summary_lines.append("  Корзина пуста.")
    else:
        for i, item in enumerate(cart_items):
            price = item.get('price', Decimal('0.0'))
            item_total = item["quantity"] * price
            total_quantity_all_items += item["quantity"]
            grand_total += item_total
            
            # Здесь текст должен быть чистым, без \\. \\- и т.д.
            summary_lines.append(
                f"{i+1}. {item['product_name']} - {item['quantity']} шт. x {price:.2f}₴ = {item_total:.2f}₴"
            )

    summary_lines.append("------------------------")
    summary_lines.append(f"ИТОГО: {total_quantity_all_items} шт. на сумму {grand_total:.2f}₴")

    return "\n".join(summary_lines)