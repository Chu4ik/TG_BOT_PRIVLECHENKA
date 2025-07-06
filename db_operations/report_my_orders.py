# db_operations/report_my_orders.py
import logging
from datetime import date
from decimal import Decimal
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Определяем класс для удобства работы с данными заказа
class OrderSummary:
    def __init__(self, order_id: int, order_date: date, client_name: str, total_amount: Decimal,
                 delivery_date: date, address_text: str, status: str):
        self.order_id = order_id
        self.order_date = order_date
        self.client_name = client_name
        self.total_amount = total_amount
        self.delivery_date = delivery_date
        self.address_text = address_text
        self.status = status

class OrderDetail:
    def __init__(self, product_name: str, quantity: Decimal, unit_price: Decimal):
        self.product_name = product_name
        self.quantity = quantity
        self.unit_price = unit_price
        self.total_item_amount = quantity * unit_price

async def get_my_orders_for_today(db_pool, telegram_user_id: int) -> List[OrderSummary]:
    """
    Получает список заказов для данного пользователя (сотрудника) за сегодняшний день.
    """
    today = date.today()
    orders = []
    conn = None
    try:
        conn = await db_pool.acquire()
        # Сначала получаем employee_id по telegram_user_id
        employee_row = await conn.fetchrow("SELECT employee_id FROM employees WHERE id_telegram = $1", telegram_user_id)
        if not employee_row:
            logger.warning(f"Employee not found for telegram_user_id: {telegram_user_id}")
            return []
        
        employee_id = employee_row['employee_id']

        # Затем получаем заказы для этого employee_id за сегодняшний день
        rows = await conn.fetch("""
            SELECT
                o.order_id,
                o.order_date,
                c.name,
                o.total_amount,
                o.delivery_date,
                a.address_text,
                o.status
            FROM
                orders o
            JOIN
                clients c ON o.client_id = c.client_id
            JOIN
                addresses a ON o.address_id = a.address_id
            WHERE
                o.employee_id = $1 AND o.order_date = $2
            ORDER BY
                o.order_id DESC;
        """, employee_id, today)

        for row in rows:
            orders.append(OrderSummary(
                order_id=row['order_id'],
                order_date=row['order_date'],
                client_name=row['name'],
                total_amount=row['total_amount'],
                delivery_date=row['delivery_date'],
                address_text=row['address_text'],
                status=row['status']
            ))
    except Exception as e:
        logger.error(f"Ошибка при получении заказов для пользователя {telegram_user_id} за сегодня: {e}", exc_info=True)
    finally:
        if conn:
            await db_pool.release(conn)
    return orders

async def get_order_full_details(db_pool, order_id: int) -> Optional[Dict]:
    """
    Получает полную информацию о конкретном заказе, включая его строки (товары).
    """
    conn = None
    try:
        conn = await db_pool.acquire()
        order_row = await conn.fetchrow("""
            SELECT
                o.order_id,
                o.order_date,
                o.delivery_date,
                c.name,
                a.address_text,
                o.total_amount,
                o.status
            FROM
                orders o
            JOIN
                clients c ON o.client_id = c.client_id
            JOIN
                addresses a ON o.address_id = a.address_id
            WHERE
                o.order_id = $1;
        """, order_id)

        if not order_row:
            return None

        order_details = {
            "order_id": order_row['order_id'],
            "order_date": order_row['order_date'],
            "delivery_date": order_row['delivery_date'],
            "client_name": order_row['name'],
            "address_text": order_row['address_text'],
            "total_amount": order_row['total_amount'],
            "status": order_row['status'],
            "items": []
        }

        item_rows = await conn.fetch("""
            SELECT
                ol.quantity,
                ol.unit_price,
                p.name
            FROM
                order_lines ol
            JOIN
                products p ON ol.product_id = p.product_id
            WHERE
                ol.order_id = $1;
        """, order_id)

        for item_row in item_rows:
            order_details["items"].append(OrderDetail(
                product_name=item_row['name'],
                quantity=item_row['quantity'],
                unit_price=item_row['unit_price']
            ))
        
        return order_details
    except Exception as e:
        logger.error(f"Ошибка при получении полной информации о заказе {order_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            await db_pool.release(conn)