import re
from datetime import date
from decimal import Decimal

from aiogram.types import Message
from states.order import OrderFSM
from utils.order_cache import order_cache


def escape_markdown_v2(text: str) -> str:
    """
    Экранирует специальные символы MarkdownV2 в тексте.
    Использует метод replace() для надежного экранирования каждого символа.
    """
    # Сначала экранируем обратную косую черту, чтобы избежать проблем с последующими заменами
    text = text.replace("\\", "\\\\")

    # Перечень всех остальных специальных символов MarkdownV2, которые нужно экранировать
    special_chars = "_*[]()~`>#+-=|{}.!"

    for char in special_chars:
        text = text.replace(char, f"\\{char}")
    return text


async def _send_cart_summary(message: Message, user_id: int):
    """Отправляет пользователю текущую сводку корзины с ценами и общей суммой."""
    user_order_data = order_cache.get(user_id, {})
    cart_items = user_order_data.get("cart", [])
    delivery_date = user_order_data.get("delivery_date")

    # Обработка случая пустой корзины с учетом даты доставки
    if not cart_items and not delivery_date:
        # Экранируем весь статический текст, который может содержать спецсимволы
        empty_cart_message = escape_markdown_v2("--- ТОВАРЫ В ЗАКАЗЕ ---\nКорзина пока пуста.\n------------------------\n")
        await message.answer(empty_cart_message, parse_mode="MarkdownV2")
        return

    # Собираем строки сводки с обычным текстом.
    # Экранирование будет применено один раз ко всему сообщению в конце.
    summary_lines = ["--- СВОДКА ЗАКАЗА ---"]

    if delivery_date:
        # **Дата доставки:** будет обработано escape_markdown_v2, а дата - это обычный текст.
        summary_lines.append(f"📅 **Дата доставки:** {delivery_date.strftime('%d.%m.%Y')}")
    else:
        summary_lines.append("📅 **Дата доставки:** Не указана")

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
            # Формируем строку без ручного экранирования.
            # escape_markdown_v2 обработает дефисы, точки и другие спецсимволы автоматически.
            summary_lines.append(f"{i+1}. {item['product_name']} - {item['quantity']} шт. x {price:.2f}₴ = {item_total:.2f}₴")

    # Добавляем разделитель и итоговую сумму
    summary_lines.append("------------------------")
    summary_lines.append(f"*ИТОГО:* {total_quantity_all_items} шт. на сумму {grand_total:.2f}₴")
    summary_lines.append("------------------------")

    final_summary_text = "\n".join(summary_lines)
    
    # Применяем escape_markdown_v2 один раз ко всему собранному тексту
    escaped_summary_text = escape_markdown_v2(final_summary_text)
    
    await message.answer(escaped_summary_text, parse_mode="MarkdownV2")