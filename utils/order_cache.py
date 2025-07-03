# utils/order_cache.py

from collections import defaultdict
from datetime import date, timedelta

# Вспомогательная функция для расчета дефолтной даты доставки
def calculate_default_delivery_date() -> date:
    today = date.today()
    if today.weekday() == 4: # Пятница
        return today + timedelta(days=3)
    else:
        return today + timedelta(days=1)

# order_cache теперь defaultdict, который автоматически инициализирует новые записи
order_cache = defaultdict(lambda: {
    "cart": [],
    "delivery_date": None, # FSM будет инициализировать это по умолчанию, если нужно
    "last_cart_message_id": None,
    "last_cart_chat_id": None,
    "client_id": None, # Добавлены для полноты
    "address_id": None # Добавлены для полноты
})

# Эти функции теперь в основном заглушки или для сохранения данных FSM в постоянный кэш
def add_to_cart(user_id, item):
    pass

def update_delivery_date(user_id, new_date):
    pass

def save_order_to_cache(user_id: int, cart_items: list, delivery_date: date, message_id: int, chat_id: int, client_id: int | None = None, address_id: int | None = None):
    """Сохраняет полные данные FSM-заказа в постоянный кэш."""
    order_cache[user_id]["cart"] = cart_items
    order_cache[user_id]["delivery_date"] = delivery_date
    order_cache[user_id]["last_cart_message_id"] = message_id
    order_cache[user_id]["last_cart_chat_id"] = chat_id
    order_cache[user_id]["client_id"] = client_id
    order_cache[user_id]["address_id"] = address_id