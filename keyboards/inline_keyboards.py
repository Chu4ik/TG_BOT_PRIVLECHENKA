from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

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
def delivery_date_keyboard(dates):
    keyboard = InlineKeyboardMarkup(row_width=2)
    for d in dates:
        keyboard.insert(InlineKeyboardButton(text=d.strftime("%d.%m (%a)"), callback_data=f"date:{d.isoformat()}"))
    return keyboard