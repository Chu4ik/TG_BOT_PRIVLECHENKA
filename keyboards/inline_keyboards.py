# keyboards/inline_keyboards.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from datetime import date, timedelta

def build_cart_keyboard(cart_items_count: int) -> InlineKeyboardMarkup:
    """
    Строит клавиатуру для корзины.
    Добавляет кнопку "Изменить строку", если в корзине есть товары.
    """
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add_product")],
        [InlineKeyboardButton(text="📅 Изменить дату доставки", callback_data="edit_delivery_date")],
        [InlineKeyboardButton(text="✅ Подтвердить заказ", callback_data="confirm_order")],
    ]

    if cart_items_count > 0:
        # Добавляем кнопку "Изменить строку" только если есть товары в корзине
        buttons.insert(1, [InlineKeyboardButton(text="✏️ Изменить строку", callback_data="edit_cart_item_menu")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_edit_item_menu_keyboard() -> InlineKeyboardMarkup:
    
    """
    Строит клавиатуру для меню "Изменить строку".
    """
    buttons = [
        [InlineKeyboardButton(text="🗑️ Удалить товар", callback_data="delete_item_prompt")],
        [InlineKeyboardButton(text="🔢 Изменить количество", callback_data="change_quantity_prompt")],
        [InlineKeyboardButton(text="↩️ Назад к корзине", callback_data="back_to_cart_main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def delivery_date_keyboard(start_date: date) -> InlineKeyboardMarkup:
    """
    Генерирует инлайн-клавиатуру с датами для выбора даты доставки.
    start_date - дата, с которой начинается генерация (обычно сегодня).
    """
    keyboard_buttons = []
    
    # Добавляем кнопки для следующих 7 дней
    for i in range(7):
        current_date = start_date + timedelta(days=i)
        day_of_week = ""
        if i == 0:
            day_of_week = " (Сегодня)"
        elif i == 1:
            day_of_week = " (Завтра)"
        
        # Форматируем дату для отображения и callback_data
        button_text = f"{current_date.strftime('%d.%m')}{day_of_week}"
        callback_data = f"date:{current_date.isoformat()}"
        
        keyboard_buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    # Добавляем кнопку для отмены или возврата, если нужно
    keyboard_buttons.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back_to_cart_main_menu")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

def create_confirm_report_keyboard(order_ids: list[int]) -> InlineKeyboardMarkup:
    """
    Создает инлайн-клавиатуру для отчета о неподтвержденных заказах.
    Включает кнопки для подтверждения/отмены всех заказов и для каждого отдельного заказа.
    """
    keyboard_buttons = []

    # Кнопки для всех заказов
    keyboard_buttons.append([
        InlineKeyboardButton(text="✅ Подтвердить все", callback_data="confirm_all_orders"),
        InlineKeyboardButton(text="❌ Отменить все", callback_data="cancel_all_orders")
    ])

    # Кнопки для каждого отдельного заказа
    for order_id in order_ids:
        keyboard_buttons.append([
            InlineKeyboardButton(text=f"✅ Подтвердить Заказ #{order_id}", callback_data=f"confirm_order_{order_id}"),
            InlineKeyboardButton(text=f"❌ Отменить Заказ #{order_id}", callback_data=f"cancel_order_{order_id}")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)