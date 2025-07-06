# db_operations/report_order_confirmation.py

import asyncpg
from datetime import date, timedelta, datetime # Добавляем datetime для confirm_order_in_db
from collections import namedtuple
import logging
from typing import Optional, List, Dict # Добавляем List, Dict, Optional для типизации

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

# Новый namedtuple для деталей позиции заказа
OrderDetail = namedtuple(
    "OrderDetail",
    [
        "product_name",
        "quantity",
        "unit_price",
        "total_item_amount"
    ]
)


async def get_unconfirmed_orders(pool):
    # ... (существующий код get_unconfirmed_orders) ...
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
    """
    Получает полную информацию о конкретном неподтвержденном заказе, включая его строки (товары).
    """
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
                o.order_id = $1 AND o.status = 'draft'; -- Убедимся, что это черновик
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
                total_item_amount=item_row['quantity'] * item_row['unit_price'] # Расчет здесь
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
    Подтверждает один заказ в БД, устанавливая статус 'confirmed'
    и генерируя номер накладной (используя asyncpg).
    """
    conn = None
    try:
        conn = await pool.acquire()
        
        invoice_number = f"INV-{date.today().strftime('%Y%m%d')}-{order_id}"
        
        # asyncpg.execute используется для операций INSERT, UPDATE, DELETE
        # Добавляем confirmation_date
        result = await conn.execute("""
            UPDATE orders
            SET status = 'confirmed', invoice_number = $1, confirmation_date = $2
            WHERE order_id = $3 AND status = 'draft';
        """, invoice_number, datetime.now(), order_id)
        
        if result == 'UPDATE 1':
            logger.info(f"Заказ #{order_id} подтвержден и сформирована накладная: {invoice_number}")
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
    """
    Отменяет один заказ, устанавливая статус 'cancelled'.
    """
    conn = None
    try:
        conn = await pool.acquire()

        # Изменяем статус заказа на 'cancelled'
        result = await conn.execute("""
            UPDATE orders
            SET status = 'cancelled'
            WHERE order_id = $1; -- Убираем проверку на 'draft', чтобы можно было отменить любой заказ
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
    Массовое подтверждение заказов (используя asyncpg и транзакцию).
    """
    conn = None
    try:
        conn = await pool.acquire()
        # Используем транзакцию для массовых операций
        async with conn.transaction():
            for order_id in order_ids:
                invoice_number = f"INV-{date.today().strftime('%Y%m%d')}-{order_id}"
                # Добавляем confirmation_date
                await conn.execute("""
                    UPDATE orders
                    SET status = 'confirmed', invoice_number = $1, confirmation_date = $2
                    WHERE order_id = $3 AND status = 'draft';
                """, invoice_number, datetime.now(), order_id)
        
        logger.info(f"Все выбранные заказы ({len(order_ids)}) подтверждены.")
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
    """
    Массовая отмена заказов, устанавливая статус 'cancelled'.
    """
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            for order_id in order_ids:
                await conn.execute("""
                    UPDATE orders
                    SET status = 'cancelled'
                    WHERE order_id = $1; -- Убираем проверку на 'draft'
                """, order_id)

        logger.info(f"Все выбранные заказы ({len(order_ids)}) успешно отменены.")
        return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при массовой отмене заказов: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при массовой отмене заказов: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)