from collections import defaultdict

# user_id → заказ
order_cache = defaultdict(dict)

def init_order(user_id):
    order_cache[user_id] = {
        "client_id": None,
        "address_id": None,
        "delivery_date": None,
        "cart": []  # список товаров
    }

def add_to_cart(user_id, item):
    order_cache[user_id]["cart"].append(item)

def update_delivery_date(user_id, new_date):
    if user_id not in order_cache:
        init_order(user_id)
    order_cache[user_id]["delivery_date"] = new_date