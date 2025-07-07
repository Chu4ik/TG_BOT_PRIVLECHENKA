# db_operations/report_payment_operations.py

import asyncpg
import logging
from typing import Optional, List, Dict
from datetime import datetime, date, timedelta
from collections import namedtuple
from decimal import Decimal

logger = logging.getLogger(__name__)

# НОВЫЙ namedtuple для отображения неоплаченных накладных
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

# НОВЫЙ namedtuple для отображения оплаченных накладных сегодня
TodayPaidInvoice = namedtuple(
    "TodayPaidInvoice",
    [
        "order_id",
        "invoice_number",
        "client_name",
        "total_amount",
        "amount_paid",
        "actual_payment_date" # <--- ИЗМЕНЕНО: Используем actual_payment_date
    ]
)

# --- НОВЫЕ ФУНКЦИИ БД ДЛЯ УПРАВЛЕНИЯ ОПЛАТАМИ ---

async def get_unpaid_invoices(pool) -> List[UnpaidInvoice]:
    """
    Получает список накладных со статусом оплаты 'unpaid' или 'partially_paid'.
    """
    conn = None
    try:
        conn = await pool.acquire()
        query = """
        SELECT
            o.order_id,
            o.invoice_number,
            o.confirmation_date,
            c.name AS client_name,
            o.total_amount,
            o.amount_paid,
            (o.total_amount - o.amount_paid) AS outstanding_balance,
            o.payment_status,
            o.due_date
        FROM
            orders o
        JOIN
            clients c ON o.client_id = c.client_id
        WHERE
            o.status = 'confirmed'
            AND o.payment_status IN ('unpaid', 'partially_paid', 'overdue')
        ORDER BY
            o.confirmation_date ASC, o.order_id ASC;
        """
        records = await conn.fetch(query)
        return [UnpaidInvoice(**r) for r in records]
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении списка неоплаченных накладных: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении списка неоплаченных накладных: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def confirm_payment_in_db(pool, order_id: int) -> bool:
    """
    Подтверждает полную оплату для накладной, обновляя amount_paid, payment_status и actual_payment_date.
    """
    conn = None
    try:
        conn = await pool.acquire()
        total_amount_record = await conn.fetchrow("SELECT total_amount FROM orders WHERE order_id = $1", order_id)
        if not total_amount_record:
            logger.warning(f"Накладная #{order_id} не найдена для подтверждения оплаты.")
            return False

        total_amount = total_amount_record['total_amount']
        
        # Обновляем actual_payment_date на текущее время
        current_datetime = datetime.now() # <--- НОВОЕ: Текущая дата и время оплаты

        result = await conn.execute("""
            UPDATE orders
            SET payment_status = 'paid',
                amount_paid = $1,
                actual_payment_date = $2 -- <--- НОВОЕ: Обновляем actual_payment_date
            WHERE order_id = $3 AND status = 'confirmed';
        """, total_amount, current_datetime, order_id) # <--- НОВОЕ: Передаем current_datetime

        if result == 'UPDATE 1':
            logger.info(f"Оплата по накладной #{order_id} полностью подтверждена. Дата оплаты: {current_datetime}")
            return True
        else:
            logger.warning(f"Оплата по накладной #{order_id} не была подтверждена (статус не 'confirmed' или не найдена).")
            return False
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при подтверждении оплаты накладной #{order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при подтверждении оплаты накладной #{order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)

async def update_partial_payment_in_db(pool, order_id: int, new_amount_paid: Decimal) -> bool:
    """
    Обновляет частичную оплату для накладной, корректируя amount_paid, payment_status и actual_payment_date.
    """
    conn = None
    try:
        conn = await pool.acquire()
        current_data = await conn.fetchrow("SELECT total_amount, amount_paid FROM orders WHERE order_id = $1", order_id)
        if not current_data:
            logger.warning(f"Накладная #{order_id} не найдена для частичной оплаты.")
            return False

        total_amount = current_data['total_amount']
        current_amount_paid = current_data['amount_paid']

        if new_amount_paid < 0:
            logger.warning(f"Попытка установить отрицательную сумму оплаты для накладной #{order_id}.")
            return False

        new_payment_status = 'unpaid'
        current_datetime = None # <--- НОВОЕ: Инициализируем None
        if new_amount_paid == total_amount:
            new_payment_status = 'paid'
            current_datetime = datetime.now() # <--- НОВОЕ: Устанавливаем дату оплаты при полной оплате
        elif new_amount_paid > 0 and new_amount_paid < total_amount:
            new_payment_status = 'partially_paid'
            current_datetime = datetime.now() # <--- НОВОЕ: Устанавливаем дату оплаты при частичной оплате
        elif new_amount_paid > total_amount:
            logger.warning(f"Попытка оплатить больше, чем total_amount для накладной #{order_id}.")
            new_amount_paid = total_amount
            new_payment_status = 'paid'
            current_datetime = datetime.now() # <--- НОВОЕ: Устанавливаем дату оплаты при "переплате"

        result = await conn.execute("""
            UPDATE orders
            SET payment_status = $1,
                amount_paid = $2,
                actual_payment_date = $3 -- <--- НОВОЕ: Обновляем actual_payment_date
            WHERE order_id = $4 AND status = 'confirmed';
        """, new_payment_status, new_amount_paid, current_datetime, order_id) # <--- НОВОЕ: Передаем current_datetime

        if result == 'UPDATE 1':
            logger.info(f"Частичная оплата по накладной #{order_id} обновлена на {new_amount_paid}. Статус: {new_payment_status}. Дата оплаты: {current_datetime}")
            return True
        else:
            logger.warning(f"Частичная оплата по накладной #{order_id} не была обновлена (статус не 'confirmed' или не найдена).")
            return False
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при обновлении частичной оплаты накладной #{order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при обновлении частичной оплаты накладной #{order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)

async def reverse_payment_in_db(pool, order_id: int) -> bool:
    """
    Отменяет оплату (полную или частичную), сбрасывая amount_paid, payment_status на 'unpaid' и actual_payment_date на NULL.
    """
    conn = None
    try:
        conn = await pool.acquire()
        result = await conn.execute("""
            UPDATE orders
            SET payment_status = 'unpaid',
                amount_paid = 0.00,
                actual_payment_date = NULL -- <--- НОВОЕ: Сбрасываем actual_payment_date
            WHERE order_id = $1 AND status = 'confirmed';
        """, order_id)

        if result == 'UPDATE 1':
            logger.info(f"Оплата по накладной #{order_id} отменена/сброшена.")
            return True
        else:
            logger.warning(f"Оплата по накладной #{order_id} не была отменена (статус не 'confirmed' или не найдена).")
            return False
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при отмене оплаты накладной #{order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при отмене оплаты накладной #{order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)

async def get_today_paid_invoices(pool) -> List[TodayPaidInvoice]:
    """
    Получает список накладных, которые были полностью оплачены сегодня.
    """
    conn = None
    try:
        conn = await pool.acquire()
        today = date.today() # Получаем сегодняшнюю дату

        query = """
        SELECT
            o.order_id,
            o.invoice_number,
            c.name AS client_name,
            o.total_amount,
            o.amount_paid,
            o.actual_payment_date AS actual_payment_date -- <--- ИЗМЕНЕНО: Выбираем actual_payment_date
        FROM
            orders o
        JOIN
            clients c ON o.client_id = c.client_id
        WHERE
            o.payment_status = 'paid'
            AND o.actual_payment_date::date = $1 -- <--- ИЗМЕНЕНО: Фильтруем по actual_payment_date
        ORDER BY
            o.actual_payment_date ASC, o.order_id ASC; -- <--- ИЗМЕНЕНО: Сортируем по actual_payment_date
        """
        records = await conn.fetch(query, today)
        return [TodayPaidInvoice(**r) for r in records]
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении списка сегодняшних оплат: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении списка сегодняшних оплат: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

