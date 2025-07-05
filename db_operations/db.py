import psycopg2
import psycopg2.extras
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
from datetime import date, timedelta
import logging
from collections import namedtuple
import asyncpg

logger = logging.getLogger(__name__)

def get_connection():
    """Устанавливает и возвращает соединение с базой данных PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Ошибка подключения к базе данных: {e}")
        raise # Важно повторно вызвать исключение для обработки в вызывающем коде

def get_dict_cursor(conn):
    """Возвращает курсор, который извлекает строки как словари."""
    return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

def get_employee_id(telegram_id: int):
    """
    Получает employee_id из таблицы employees по telegram_id пользователя.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT employee_id FROM employees WHERE id_telegram = %s", (telegram_id,))
        result = cur.fetchone()
        cur.close()
        conn.close()
        return result[0] if result else None
    except psycopg2.Error as e:
        logger.error(f"Ошибка при получении employee_id для telegram_id {telegram_id}: {e}")
        return None
    finally:
        if cur: cur.close()
        if conn: conn.close()

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

async def get_unconfirmed_orders():
    conn = None
    try:
        conn = await asyncpg.connect(
            user=DB_USER,        
            password=DB_PASSWORD, 
            database=DB_NAME,     
            host=DB_HOST,         
            port=DB_PORT         
        )

        # Предполагается, что вы уже исправили `c.client_name` на `c.name` или другое правильное имя
        # в SELECT-запросе, как мы обсуждали ранее.
        query = """
        SELECT
            o.order_id,
            o.order_date,
            o.delivery_date,
            c.name, -- ИЛИ c.client_name, если так называется столбец в вашей БД. Важно, чтобы здесь было фактическое имя.
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

        # Получаем строки как кортежи
        rows = await conn.fetch(query)
        unconfirmed_orders = [
            UnconfirmedOrder(
                row['order_id'], 
                row['order_date'], 
                row['delivery_date'], 
                row['name'], # Или 'client_name', в зависимости от вашего SELECT
                row['address_text'], 
                row['total_amount']
            ) for row in rows
        ]
        
         # Преобразуем каждый кортеж в объект UnconfirmedOrder

        logger.info(f"Получено {len(unconfirmed_orders)} неподтвержденных заказов.")
        return unconfirmed_orders

    except Exception as e:
        logger.error(f"Ошибка при получении неподтвержденных заказов: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await conn.close()

async def confirm_order_in_db(order_id: int):
    """
    Подтверждает один заказ в БД, устанавливая статус 'confirmed'
    и генерируя номер накладной.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        # Простая генерация номера накладной (можно усложнить)
        invoice_number = f"INV-{date.today().strftime('%Y%m%d')}-{order_id}"
        cur.execute("""
            UPDATE orders
            SET status = 'confirmed', invoice_number = %s
            WHERE order_id = %s;
        """, (invoice_number, order_id))
        conn.commit()
        logger.info(f"Заказ #{order_id} подтвержден и сформирована накладная: {invoice_number}")
        return True
    except psycopg2.Error as e:
        logger.error(f"Ошибка при подтверждении заказа #{order_id}: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def cancel_order_in_db(order_id: int):
    """
    Отменяет один заказ, удаляя его из БД.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM orders
            WHERE order_id = %s;
        """, (order_id,))
        conn.commit()
        logger.info(f"Заказ #{order_id} отменен и удален из БД.")
        return True
    except psycopg2.Error as e:
        logger.error(f"Ошибка при отмене и удалении заказа #{order_id}: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def confirm_all_orders_in_db(order_ids: list[int]):
    """
    Массовое подтверждение заказов.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        for order_id in order_ids:
            invoice_number = f"INV-{date.today().strftime('%Y%m%d')}-{order_id}"
            cur.execute("""
                UPDATE orders
                SET status = 'confirmed', invoice_number = %s
                WHERE order_id = %s;
            """, (invoice_number, order_id))
        conn.commit()
        logger.info(f"Все выбранные заказы ({len(order_ids)}) подтверждены.")
        return True
    except psycopg2.Error as e:
        logger.error(f"Ошибка при массовом подтверждении заказов: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()

async def cancel_all_orders_in_db(order_ids: list[int]):
    """
    Массовая отмена заказов и их удаление из БД.
    """
    conn = None
    cur = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        for order_id in order_ids:
            cur.execute("""
                DELETE FROM orders
                WHERE order_id = %s;
            """, (order_id,))
        conn.commit()
        logger.info(f"Все выбранные заказы ({len(order_ids)}) отменены и удалены.")
        return True
    except psycopg2.Error as e:
        logger.error(f"Ошибка при массовой отмене и удалении заказов: {e}")
        if conn: conn.rollback()
        return False
    finally:
        if cur: cur.close()
        if conn: conn.close()