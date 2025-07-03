# utils/order_cache.py

from collections import defaultdict
from datetime import date, timedelta

order_cache = defaultdict(dict)

def calculate_default_delivery_date() -> date:
    today = date.today()
    if today.weekday() == 4: # Пятница
        return today + timedelta(days=3)
    else:
        return today + timedelta(days=1)

def init_order(user_id):
    """
    Инициализирует ключи по умолчанию для заказа пользователя, если они отсутствуют.
    Не перезаписывает существующие данные.
    """
    user_order_data = order_cache[user_id] # defaultdict гарантирует, что order_cache[user_id] будет dict

    if "client_id" not in user_order_data:
        user_order_data["client_id"] = None
    if "address_id" not in user_order_data:
        user_order_data["address_id"] = None
    if "delivery_date" not in user_order_data:
        user_order_data["delivery_date"] = calculate_default_delivery_date()
    if "cart" not in user_order_data:
        user_order_data["cart"] = []

def add_to_cart(user_id, item):
    """Добавляет товар в корзину или обновляет его количество."""
    # Убедимся, что структура заказа инициализирована, если она еще не существует
    if user_id not in order_cache: # <-- ДОБАВЛЕНО/ИСПРАВЛЕНО УСЛОВИЕ
        init_order(user_id)

    cart = order_cache[user_id].get("cart", [])
    if not isinstance(cart, list):
        cart = []
        order_cache[user_id]["cart"] = cart

    existing_item = next((i for i in cart if i["product_id"] == item["product_id"]), None)

    if existing_item:
        existing_item["quantity"] += item["quantity"]
    else:
        cart.append(item)

def update_delivery_date(user_id, new_date):
    """Обновляет дату доставки для пользователя."""
    if user_id not in order_cache: # <-- ДОБАВЛЕНО/ИСПРАВЛЕНО УСЛОВИЕ
        init_order(user_id)
    order_cache[user_id]["delivery_date"] = new_date

def store_address(user_id: int, address_id: int):
    """Сохраняет ID адреса для пользователя."""
    if user_id not in order_cache: # <-- ДОБАВЛЕНО/ИСПРАВЛЕНО УСЛОВИЕ
        init_order(user_id)
    order_cache[user_id]["address_id"] = address_id

def get_order_data(user_id: int) -> dict:
    """Возвращает все данные заказа для указанного пользователя."""
    return order_cache.get(user_id, {})

def clear_user_order(user_id: int):
    """Полностью очищает данные заказа для пользователя."""
    if user_id in order_cache:
        del order_cache[user_id]