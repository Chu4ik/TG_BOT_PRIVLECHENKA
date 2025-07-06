import asyncpg
from datetime import date, timedelta
from collections import namedtuple
import logging
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

async def get_unconfirmed_orders(pool): # Добавили 'pool' как аргумент
    conn = None
    try:
        # Получаем соединение из ПЕРЕДАННОГО пула
        conn = await pool.acquire() # Используем 'pool'

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
        
        rows = await conn.fetch(query) # asyncpg.fetch возвращает список Record объектов
        
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
            await pool.release(conn) # Используем 'pool'


async def confirm_order_in_db(pool, order_id: int): # Добавили 'pool' как аргумент
    """
    Подтверждает один заказ в БД, устанавливая статус 'confirmed'
    и генерируя номер накладной (используя asyncpg).
    """
    conn = None
    try:
        conn = await pool.acquire() # Используем 'pool'
        
        invoice_number = f"INV-{date.today().strftime('%Y%m%d')}-{order_id}"
        
        # asyncpg.execute используется для операций INSERT, UPDATE, DELETE
        await conn.execute("""
            UPDATE orders
            SET status = 'confirmed', invoice_number = $1
            WHERE order_id = $2;
        """, invoice_number, order_id)
        
        logger.info(f"Заказ #{order_id} подтвержден и сформирована накладная: {invoice_number}")
        return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при подтверждении заказа #{order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при подтверждении заказа #{order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn) # Используем 'pool'


async def cancel_order_in_db(pool, order_id: int): # Добавили 'pool' как аргумент
    """
    Отменяет один заказ, удаляя его из БД (используя asyncpg).
    """
    conn = None
    try:
        conn = await pool.acquire() # Используем 'pool'
        
        await conn.execute("""
            DELETE FROM orders
            WHERE order_id = $1;
        """, order_id)
        
        logger.info(f"Заказ #{order_id} отменен и удален из БД.")
        return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при отмене и удалении заказа #{order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при отмене и удалении заказа #{order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn) # Используем 'pool'


async def confirm_all_orders_in_db(pool, order_ids: list[int]): # Добавили 'pool' как аргумент
    """
    Массовое подтверждение заказов (используя asyncpg и транзакцию).
    """
    conn = None
    try:
        conn = await pool.acquire() # Используем 'pool'
        # Используем транзакцию для массовых операций
        async with conn.transaction():
            for order_id in order_ids:
                invoice_number = f"INV-{date.today().strftime('%Y%m%d')}-{order_id}"
                await conn.execute("""
                    UPDATE orders
                    SET status = 'confirmed', invoice_number = $1
                    WHERE order_id = $2;
                """, invoice_number, order_id)
        
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
            await pool.release(conn) # Используем 'pool'


async def cancel_all_orders_in_db(pool, order_ids: list[int]): # Добавили 'pool' как аргумент
    """
    Массовая отмена заказов и их удаление из БД (используя asyncpg и транзакцию).
    """
    conn = None
    try:
        conn = await pool.acquire() # Используем 'pool'
        # Используем транзакцию для массовых операций
        async with conn.transaction():
            for order_id in order_ids:
                await conn.execute("""
                    DELETE FROM orders
                    WHERE order_id = $1;
                """, order_id)
        
        logger.info(f"Все выбранные заказы ({len(order_ids)}) отменены и удалены.")
        return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при массовой отмене и удалении заказов: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при массовой отмене и удалении заказов: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn) # Используем 'pool'