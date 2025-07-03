from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from datetime import date, timedelta

# Выбор адреса (если у клиента их несколько)
def get_address_keyboard(addresses):
    keyboard = InlineKeyboardMarkup(row_width=1)
    for addr in addresses:
        keyboard.add(InlineKeyboardButton(text=addr['address_text'], callback_data=f"address:{addr['id']}"))
    return keyboard

# Подтверждение или добавление товара
def confirm_product_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_product")],
        [InlineKeyboardButton(text="➕ Добавить ещё", callback_data="add_more_product")]
    ])

# Итог заказа — действия с ним
def order_actions_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Подтвердить и Отправить", callback_data="send_order")],
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_order")],
        [InlineKeyboardButton(text="📅 Изменить дату", callback_data="change_date")],
        [InlineKeyboardButton(text="❌ Отменить заказ", callback_data="cancel_order")]
    ])

# Календарь доставки на 7 дней вперёд
def delivery_date_keyboard(start_date: date): # Убедитесь, что start_date передается
    buttons = []
    # Например, генерируем кнопки на 7 дней вперед
    for i in range(7):
        current_date = start_date + timedelta(days=i)
        buttons.append(
            InlineKeyboardButton(
                text=current_date.strftime("%d.%m"),
                callback_data=f"date:{current_date.isoformat()}"
            )
        )
    
    # Разделим кнопки на строки, например, по 3 кнопки в строке
    inline_keyboard_rows = []
    for i in range(0, len(buttons), 3):
        inline_keyboard_rows.append(buttons[i:i+3])

    # Добавляем кнопку "Назад в корзину"
    inline_keyboard_rows.append([InlineKeyboardButton(text="⬅️ Назад в корзину", callback_data="back_to_cart_main_menu")])

    # ИСПРАВЛЕНИЕ УЖЕ ЕСТЬ: Передайте 'inline_keyboard' как аргумент
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard_rows)


def build_cart_keyboard(cart_len: int) -> InlineKeyboardMarkup:
    rows = []
    if cart_len > 0:
        rows.append([InlineKeyboardButton(text="✏ Изменить строку", callback_data="edit_line")])
        rows.append([InlineKeyboardButton(text="✅ Подтвердить заказ", callback_data="confirm_order")])
    
    # "Изменить дату доставки" может быть всегда, независимо от содержимого корзины
    rows.append([InlineKeyboardButton(text="📅 Изменить дату доставки", callback_data="edit_delivery_date")])

    # Если корзина пуста, то кнопка "Добавить ещё товар" не нужна здесь, 
    # так как show_cart_menu теперь автоматически переводит пользователя к выбору товаров.
    # Если же вы хотите, чтобы эта кнопка всегда была в меню корзины (даже если корзина пуста,
    # и пользователь сам вышел в меню корзины), то можно добавить ее. 
    # Пока оставляем логику, что flow сам переводит.

    return InlineKeyboardMarkup(inline_keyboard=rows)