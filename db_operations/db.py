import logging
from collections import namedtuple
import asyncpg
from datetime import date, timedelta
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

logger = logging.getLogger(__name__)

# Объявляем переменную для пула соединений, инициализируем её None
# Эту строку db_pool = None можно удалить, так как пул теперь передается
# или, если вы оставили её для справки, просто знайте, что она не используется
# для текущей архитектуры передачи пула.

async def init_db_pool():
    """Инициализирует пул соединений asyncpg. Вызывается при старте бота."""
    try:
        # Используем локальную переменную 'pool'
        pool = await asyncpg.create_pool(
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            host=DB_HOST,
            port=DB_PORT,
            min_size=5,
            max_size=10,
            timeout=60
        )
        logger.info("Пул соединений asyncpg успешно инициализирован.")
        return pool # Возвращаем локальный 'pool'
    except Exception as e:
        logger.critical(f"Ошибка при инициализации пула соединений asyncpg: {e}", exc_info=True)
        raise # Перевызываем исключение, чтобы остановить запуск бота, если нет подключения к БД

async def close_db_pool(pool): # Теперь 'pool' - это аргумент
    """Закрывает пул соединений asyncpg. Вызывается при остановке бота."""
    if pool:
        await pool.close()
        logger.info("Пул соединений asyncpg успешно закрыт.")


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

async def get_employee_id(pool, telegram_id: int): # Добавили 'pool' как аргумент
    """
    Получает employee_id из таблицы employees по telegram_id пользователя (используя asyncpg).
    """
    conn = None
    try:
        # Получаем соединение из ПЕРЕДАННОГО пула
        conn = await pool.acquire() # Используем 'pool'
        
        # asyncpg использует $1, $2 для параметров вместо %s
        result = await conn.fetchrow("SELECT employee_id FROM employees WHERE id_telegram = $1", telegram_id)
        
        return result['employee_id'] if result else None
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при получении employee_id для telegram_id {telegram_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении employee_id для telegram_id {telegram_id}: {e}", exc_info=True)
        return None
    finally:
        # Важно: всегда возвращайте соединение в пул!
        if conn:
            await pool.release(conn) # Используем 'pool'


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