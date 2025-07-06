# db_operations/report_order_confirmation.py

import asyncpg
from datetime import date, timedelta, datetime
from collections import namedtuple
import logging
from typing import Optional, List, Dict
from decimal import Decimal

logger = logging.getLogger(__name__)

UnconfirmedOrder = namedtuple(
    "UnconfirmedOrder",
    [
        "order_id",
        "order_date",
        "delivery_date",
        "client_name",
        "address_text",
        "total_amount"
    ]
)

OrderDetail = namedtuple(
    "OrderDetail",
    [
        "product_name",
        "quantity",
        "unit_price",
        "total_item_amount"
    ]
)

# НОВЫЙ namedtuple для отображения неоплаченных накладных (если вы его переместили сюда)
UnpaidInvoice = namedtuple(
    "UnpaidInvoice",
    [
        "order_id",
        "invoice_number",
        "confirmation_date",
        "client_name",
        "total_amount",
        "amount_paid",
        "outstanding_balance", # Рассчитанное поле
        "payment_status",
        "due_date"
    ]
)


async def get_unconfirmed_orders(pool):
    # ... (ваш существующий код) ...
    conn = None
    try:
        conn = await pool.acquire()

        query = """
        SELECT
            o.order_id,
            o.order_date,
            o.delivery_date,
            c.name,
            a.address_text,
            o.total_amount
        FROM
            orders o
        JOIN
            clients c ON o.client_id = c.client_id
        JOIN
            addresses a ON o.address_id = a.address_id
        WHERE
            o.status = 'draft'
        ORDER BY
            o.order_date DESC, o.order_id DESC;
        """
        
        rows = await conn.fetch(query)
        
        unconfirmed_orders = [
            UnconfirmedOrder(
                row['order_id'],
                row['order_date'],
                row['delivery_date'],
                row['name'],
                row['address_text'],
                row['total_amount']
            ) for row in rows
        ]
        
        logger.info(f"Получено {len(unconfirmed_orders)} неподтвержденных заказов.")
        return unconfirmed_orders

    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при получении неподтвержденных заказов: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении неподтвержденных заказов: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)


async def get_unconfirmed_order_full_details(pool, order_id: int) -> Optional[Dict]:
    # ... (ваш существующий код) ...
    conn = None
    try:
        conn = await pool.acquire()
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
                o.order_id = $1 AND o.status = 'draft';
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
                unit_price=item_row['unit_price'],
                total_item_amount=item_row['quantity'] * item_row['unit_price']
            ))
        
        return order_details
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при получении полной информации о неподтвержденном заказе {order_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении полной информации о неподтвержденном заказе {order_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)


async def confirm_order_in_db(pool, order_id: int):
    """
    Подтверждает один заказ в БД, устанавливая статус 'confirmed',
    генерируя номер накладной (дата из delivery_date), устанавливая confirmation_date = delivery_date и due_date.
    """
    conn = None
    try:
        conn = await pool.acquire()

        # Сначала получаем delivery_date для этого заказа
        order_info = await conn.fetchrow("SELECT delivery_date FROM orders WHERE order_id = $1 AND status = 'draft';", order_id)
        if not order_info:
            logger.warning(f"Заказ #{order_id} не найден или уже не в статусе 'draft' для подтверждения.")
            return False

        delivery_date_for_invoice = order_info['delivery_date'] # <--- ПОЛУЧАЕМ ДАТУ ДОСТАВКИ

        # Формируем invoice_number, используя delivery_date
        invoice_number = f"INV-{delivery_date_for_invoice.strftime('%Y%m%d')}-{order_id}" # <--- ИЗМЕНЕНО
        
        # confirmation_date теперь равна delivery_date
        confirmation_date_val = delivery_date_for_invoice 
        
        # Рассчитываем due_date: например, 7 дней после delivery_date (которая теперь confirmation_date)
        due_date_calculated = confirmation_date_val + timedelta(days=7) 

        result = await conn.execute("""
            UPDATE orders
            SET status = 'confirmed',
                invoice_number = $1,
                confirmation_date = $2,
                due_date = $3
            WHERE order_id = $4 AND status = 'draft';
        """, invoice_number, confirmation_date_val, due_date_calculated, order_id)
        
        if result == 'UPDATE 1':
            logger.info(f"Заказ #{order_id} подтвержден, сформирована накладная: {invoice_number}, дата накладной (доставки): {confirmation_date_val}, срок оплаты: {due_date_calculated}")
            return True
        else:
            logger.warning(f"Заказ #{order_id} не был подтвержден (статус не 'draft' или не найден).")
            return False
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при подтверждении заказа #{order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при подтверждении заказа #{order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)


async def cancel_order_in_db(pool, order_id: int):
    # ... (ваш существующий код) ...
    conn = None
    try:
        conn = await pool.acquire()
        
        result = await conn.execute("""
            UPDATE orders
            SET status = 'cancelled'
            WHERE order_id = $1;
        """, order_id)
        
        if result == 'UPDATE 1':
            logger.info(f"Заказ #{order_id} успешно отменен (статус изменен на 'cancelled').")
            return True
        else:
            logger.warning(f"Заказ #{order_id} не был отменен (не найден).")
            return False
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при отмене заказа #{order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при отмене заказа #{order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)


async def confirm_all_orders_in_db(pool, order_ids: list[int]):
    """
    Массовое подтверждение заказов (используя asyncpg и транзакцию),
    устанавливая confirmation_date = delivery_date и due_date,
    и формируя invoice_number на основе delivery_date.
    """
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            for order_id in order_ids:
                # Для каждого заказа получаем delivery_date
                order_info = await conn.fetchrow("SELECT delivery_date FROM orders WHERE order_id = $1 AND status = 'draft';", order_id)
                if not order_info:
                    logger.warning(f"Заказ #{order_id} не найден или уже не в статусе 'draft' для массового подтверждения. Пропускаем.")
                    continue 

                delivery_date_for_invoice = order_info['delivery_date']

                # Формируем invoice_number, используя delivery_date
                invoice_number = f"INV-{delivery_date_for_invoice.strftime('%Y%m%d')}-{order_id}" # <--- ИЗМЕНЕНО
                
                confirmation_date_val = delivery_date_for_invoice
                due_date_calculated = confirmation_date_val + timedelta(days=7)

                await conn.execute("""
                    UPDATE orders
                    SET status = 'confirmed',
                        invoice_number = $1,
                        confirmation_date = $2,
                        due_date = $3
                    WHERE order_id = $4 AND status = 'draft';
                """, invoice_number, confirmation_date_val, due_date_calculated, order_id)
        
        logger.info(f"Все выбранные заказы ({len(order_ids)}) подтверждены. Даты накладных (доставки) и сроки оплаты установлены.")
        return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при массовом подтверждении заказов: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при массовом подтверждении заказов: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)

async def cancel_all_orders_in_db(pool, order_ids: list[int]):
    # ... (ваш существующий код) ...
    conn = None
    try:
        conn = await pool.acquire()
        # Используем транзакцию для массовых операций
        async with conn.transaction():
            for order_id in order_ids:
                await conn.execute("""
                    UPDATE orders
                    SET status = 'cancelled'
                    WHERE order_id = $1;
                """, order_id)
        
        logger.info(f"Все выбранные заказы ({len(order_ids)}) отменены.")
        return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при массовой отмене и удалении заказов: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при массовой отмене и удалении заказов: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)