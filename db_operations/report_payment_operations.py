# db_operations/report_payment_operations.py
import asyncpg
import logging
from typing import Optional, List, Dict
from datetime import datetime, date, timedelta
from collections import namedtuple
from decimal import Decimal

logger = logging.getLogger(__name__)

# ... (существующие namedtuple: UnconfirmedOrder, OrderDetail) ...

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
            o.confirmation_date ASC, o.order_id ASC; -- <--- ИЗМЕНЕНО: Добавлена сортировка по order_id
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
    Подтверждает полную оплату для накладной, обновляя amount_paid и payment_status.
    """
    conn = None
    try:
        conn = await pool.acquire()
        # Сначала получаем total_amount, чтобы установить amount_paid равным ему
        total_amount_record = await conn.fetchrow("SELECT total_amount FROM orders WHERE order_id = $1", order_id)
        if not total_amount_record:
            logger.warning(f"Накладная #{order_id} не найдена для подтверждения оплаты.")
            return False

        total_amount = total_amount_record['total_amount']

        result = await conn.execute("""
            UPDATE orders
            SET payment_status = 'paid',
                amount_paid = $1 -- Устанавливаем полную сумму оплаты
            WHERE order_id = $2 AND status = 'confirmed';
        """, total_amount, order_id)

        if result == 'UPDATE 1':
            logger.info(f"Оплата по накладной #{order_id} полностью подтверждена.")
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
    Обновляет частичную оплату для накладной, корректируя amount_paid и payment_status.
    """
    conn = None
    try:
        conn = await pool.acquire()
        # Получаем текущие данные, чтобы убедиться, что new_amount_paid не превышает total_amount
        current_data = await conn.fetchrow("SELECT total_amount, amount_paid FROM orders WHERE order_id = $1", order_id)
        if not current_data:
            logger.warning(f"Накладная #{order_id} не найдена для частичной оплаты.")
            return False

        total_amount = current_data['total_amount']
        current_amount_paid = current_data['amount_paid']

        if new_amount_paid < 0:
            logger.warning(f"Попытка установить отрицательную сумму оплаты для накладной #{order_id}.")
            return False

        # Обновляем amount_paid. Если new_amount_paid == total_amount, устанавливаем 'paid'.
        # Иначе, если new_amount_paid > 0 и < total_amount, устанавливаем 'partially_paid'.
        # Если new_amount_paid == 0, устанавливаем 'unpaid'.
        new_payment_status = 'unpaid'
        if new_amount_paid == total_amount:
            new_payment_status = 'paid'
        elif new_amount_paid > 0 and new_amount_paid < total_amount:
            new_payment_status = 'partially_paid'
        elif new_amount_paid > total_amount:
            logger.warning(f"Попытка оплатить больше, чем total_amount для накладной #{order_id}.")
            # Можно оставить статус 'paid' или 'partially_paid' в зависимости от логики
            # Или просто не позволять превышать total_amount
            # Пока оставим так, чтобы кассир мог "переплатить" при необходимости, но это редкость.
            # Лучше обрезать до total_amount или требовать точного ввода.
            new_amount_paid = total_amount # Можно принудительно установить полную оплату если ввели больше
            new_payment_status = 'paid'


        result = await conn.execute("""
            UPDATE orders
            SET payment_status = $1,
                amount_paid = $2
            WHERE order_id = $3 AND status = 'confirmed';
        """, new_payment_status, new_amount_paid, order_id)

        if result == 'UPDATE 1':
            logger.info(f"Частичная оплата по накладной #{order_id} обновлена на {new_amount_paid}. Статус: {new_payment_status}")
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
    Отменяет оплату (полную или частичную), сбрасывая amount_paid и payment_status на 'unpaid'.
    """
    conn = None
    try:
        conn = await pool.acquire()
        result = await conn.execute("""
            UPDATE orders
            SET payment_status = 'unpaid',
                amount_paid = 0.00
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

# ... (остальные существующие функции) ...