# db_operations/report_payment_operations.py

import asyncpg
import logging
from typing import Optional, List, Dict
from datetime import datetime, date, timedelta
from collections import namedtuple
from decimal import Decimal

logger = logging.getLogger(__name__)

# ОБНОВЛЕННЫЙ NAMEDTUPLE для отображения неоплаченных накладных
# Теперь включает детали по платежам и возвратам для более точного отчета
UnpaidInvoice = namedtuple(
    "UnpaidInvoice",
    [
        "order_id",
        "invoice_number",
        "confirmation_date",
        "client_name",
        "total_amount",
        "amount_paid", # Это orders.amount_paid - фактическая сумма в таблице orders
        "total_payments_received",  # НОВОЕ: Сумма только ПОЛОЖИТЕЛЬНЫХ платежей из client_payments
        "total_credits_issued", # НОВОЕ: Сумма только ОТРИЦАТЕЛЬНЫХ возвратов из client_payments (как положительное число)
        "actual_outstanding_balance", # НОВОЕ: Фактически вычисленная задолженность (total_amount - total_payments_received + total_credits_issued)
        "payment_status",
        "due_date"
    ]
)

TodayPaidInvoice = namedtuple(
    "TodayPaidInvoice",
    [
        "order_id",
        "invoice_number",
        "client_name",
        "total_amount",
        "amount_paid",
        "actual_payment_date"
    ]
)

# --- ФУНКЦИИ БД ДЛЯ УПРАВЛЕНИЯ ОПЛАТАМИ ---

async def get_unpaid_invoices(pool) -> List[UnpaidInvoice]:
    """
    Получает список накладных со статусом оплаты 'unpaid' или 'partially_paid',
    динамически вычисляя задолженность с учетом всех транзакций в client_payments.
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
            COALESCE(SUM(CASE WHEN cp.payment_type IN ('payment', 'partial_payment') THEN cp.amount ELSE 0 END) FILTER (WHERE cp.order_id = o.order_id), 0) AS total_payments_received,
            COALESCE(SUM(CASE WHEN cp.payment_type = 'return_credit' THEN ABS(cp.amount) ELSE 0 END) FILTER (WHERE cp.order_id = o.order_id), 0) AS total_credits_issued,
            o.payment_status,
            o.due_date
        FROM
            orders o
        JOIN
            clients c ON o.client_id = c.client_id
        LEFT JOIN
            client_payments cp ON o.order_id = cp.order_id
        WHERE
            o.status = 'confirmed'
            AND o.payment_status IN ('unpaid', 'partially_paid', 'overdue')
        GROUP BY
            o.order_id, o.invoice_number, o.confirmation_date, c.name, o.total_amount, o.amount_paid, o.payment_status, o.due_date
        ORDER BY
            o.confirmation_date ASC, o.order_id ASC;
        """
        records = await conn.fetch(query)
        
        invoices_with_calculated_debt = []
        for r in records:
            calculated_outstanding_balance = r['total_amount'] - r['total_payments_received'] + r['total_credits_issued']
            
            invoices_with_calculated_debt.append(
                UnpaidInvoice(
                    order_id=r['order_id'],
                    invoice_number=r['invoice_number'],
                    confirmation_date=r['confirmation_date'],
                    client_name=r['client_name'],
                    total_amount=r['total_amount'],
                    amount_paid=r['amount_paid'],
                    total_payments_received=r['total_payments_received'],
                    total_credits_issued=r['total_credits_issued'],
                    actual_outstanding_balance=calculated_outstanding_balance,
                    payment_status=r['payment_status'],
                    due_date=r['due_date']
                )
            )
        return invoices_with_calculated_debt
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении списка неоплаченных накладных: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении списка неоплаченных накладных: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

# НОВАЯ ФУНКЦИЯ: get_single_unpaid_invoice_details
async def get_single_unpaid_invoice_details(pool, order_id: int) -> Optional[UnpaidInvoice]:
    """
    Получает полную информацию об одной неоплаченной накладной по order_id,
    вычисляя задолженность с учетом всех транзакций client_payments.
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
            COALESCE(SUM(CASE WHEN cp.payment_type IN ('payment', 'partial_payment') THEN cp.amount ELSE 0 END) FILTER (WHERE cp.order_id = o.order_id), 0) AS total_payments_received,
            COALESCE(SUM(CASE WHEN cp.payment_type = 'return_credit' THEN ABS(cp.amount) ELSE 0 END) FILTER (WHERE cp.order_id = o.order_id), 0) AS total_credits_issued,
            o.payment_status,
            o.due_date
        FROM
            orders o
        JOIN
            clients c ON o.client_id = c.client_id
        LEFT JOIN
            client_payments cp ON o.order_id = cp.order_id
        WHERE
            o.order_id = $1
        GROUP BY
            o.order_id, o.invoice_number, o.confirmation_date, c.name, o.total_amount, o.amount_paid, o.payment_status, o.due_date;
        """
        record = await conn.fetchrow(query, order_id)
        
        if record:
            calculated_outstanding_balance = record['total_amount'] - record['total_payments_received'] + record['total_credits_issued']
            return UnpaidInvoice(
                order_id=record['order_id'],
                invoice_number=record['invoice_number'],
                confirmation_date=record['confirmation_date'],
                client_name=record['client_name'],
                total_amount=record['total_amount'],
                amount_paid=record['amount_paid'],
                total_payments_received=record['total_payments_received'],
                total_credits_issued=record['total_credits_issued'],
                actual_outstanding_balance=calculated_outstanding_balance,
                payment_status=record['payment_status'],
                due_date=record['due_date']
            )
        return None
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении деталей накладной #{order_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении деталей накладной #{order_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)

async def confirm_payment_in_db(pool, order_id: int) -> bool:
    """
    Подтверждает полную оплату для накладной, обновляя amount_paid, payment_status и actual_payment_date.
    Создает запись в client_payments.
    """
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            total_amount_record = await conn.fetchrow("SELECT total_amount, client_id FROM orders WHERE order_id = $1 FOR UPDATE", order_id)
            if not total_amount_record:
                logger.warning(f"Накладная #{order_id} не найдена для подтверждения оплаты.")
                return False

            total_amount = total_amount_record['total_amount']
            client_id = total_amount_record['client_id']
            
            current_datetime = datetime.now()

            result = await conn.execute("""
                UPDATE orders
                SET payment_status = 'paid',
                    amount_paid = $1,
                    actual_payment_date = $2
                WHERE order_id = $3 AND status = 'confirmed';
            """, total_amount, current_datetime, order_id)

            if result == 'UPDATE 1':
                await conn.execute("""
                    INSERT INTO client_payments (payment_date, client_id, order_id, amount, payment_method, description, payment_type)
                    VALUES ($1, $2, $3, $4, $5, $6, $7);
                """, date.today(), client_id, order_id, total_amount, 'full_payment', f"Полная оплата по накладной #{order_id}", 'payment')
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

async def update_partial_payment_in_db(pool, order_id: int, new_amount_increase: Decimal) -> bool:
    """
    Обновляет частичную оплату для накладной, ДОБАВЛЯЯ new_amount_increase к amount_paid.
    """
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            current_data = await conn.fetchrow("SELECT total_amount, amount_paid, client_id FROM orders WHERE order_id = $1 FOR UPDATE", order_id)
            if not current_data:
                logger.warning(f"Накладная #{order_id} не найдена для частичной оплаты.")
                return False

            total_amount = current_data['total_amount']
            current_amount_paid = current_data['amount_paid']
            client_id = current_data['client_id']

            if new_amount_increase < 0:
                logger.warning(f"Попытка внести отрицательную сумму частичной оплаты для накладной #{order_id}.")
                return False

            new_total_paid = current_amount_paid + new_amount_increase
            
            new_payment_status = 'unpaid'
            current_datetime = None
            if new_total_paid >= total_amount:
                new_payment_status = 'paid'
                new_total_paid = total_amount
                current_datetime = datetime.now()
            elif new_total_paid > 0 and new_total_paid < total_amount:
                new_payment_status = 'partially_paid'
                current_datetime = datetime.now()
            elif new_total_paid <= 0:
                new_payment_status = 'unpaid'
                new_total_paid = Decimal('0.00')

            result = await conn.execute("""
                UPDATE orders
                SET payment_status = $1,
                    amount_paid = $2,
                    actual_payment_date = $3
                WHERE order_id = $4 AND status = 'confirmed';
            """, new_payment_status, new_total_paid, current_datetime, order_id)

            if result == 'UPDATE 1':
                await conn.execute("""
                    INSERT INTO client_payments (payment_date, client_id, order_id, amount, payment_method, description, payment_type)
                    VALUES ($1, $2, $3, $4, $5, $6, $7);
                """, date.today(), client_id, order_id, new_amount_increase, 'partial_payment', f"Частичная оплата по накладной #{order_id}", 'payment')
                logger.info(f"Частичная оплата по накладной #{order_id} обновлена на {new_total_paid}. Статус: {new_payment_status}. Дата оплаты: {current_datetime}")
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
    Создает сторнирующую запись в client_payments.
    """
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            current_data = await conn.fetchrow("SELECT total_amount, amount_paid, client_id FROM orders WHERE order_id = $1 FOR UPDATE", order_id)
            if not current_data:
                logger.warning(f"Накладная #{order_id} не найдена для отмены оплаты.")
                return False
            
            client_id = current_data['client_id']
            amount_to_reverse = current_data['amount_paid']

            result = await conn.execute("""
                UPDATE orders
                SET payment_status = 'unpaid',
                    amount_paid = 0.00,
                    actual_payment_date = NULL
                WHERE order_id = $1 AND status = 'confirmed';
            """, order_id)

            if result == 'UPDATE 1':
                if amount_to_reverse > 0:
                    await conn.execute("""
                        INSERT INTO client_payments (payment_date, client_id, order_id, amount, payment_method, description, payment_type)
                        VALUES ($1, $2, $3, $4, $5, $6, $7);
                    """, date.today(), client_id, order_id, -amount_to_reverse, 'reverse_payment', f"Отмена оплаты по накладной #{order_id}", 'reverse_payment')
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
        today = date.today()

        query = """
        SELECT
            o.order_id,
            o.invoice_number,
            c.name AS client_name,
            o.total_amount,
            o.amount_paid,
            o.actual_payment_date AS actual_payment_date
        FROM
            orders o
        JOIN
            clients c ON o.client_id = c.client_id
        WHERE
            o.payment_status = 'paid'
            AND o.actual_payment_date::date = $1
        ORDER BY
            o.actual_payment_date ASC, o.order_id ASC;
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

async def get_client_outstanding_invoices(pool, client_id: int) -> List[UnpaidInvoice]:
    """
    Получает список подтвержденных накладных для клиента, по которым есть задолженность,
    динамически вычисляя задолженность с учетом всех транзакций в client_payments.
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
            o.amount_paid, -- orders.amount_paid (который должен быть total_amount - Sum(payments) + Sum(returns))
            -- Сумма только платежей (без возвратов)
            COALESCE(SUM(CASE WHEN cp.payment_type IN ('payment', 'partial_payment') THEN cp.amount ELSE 0 END) FILTER (WHERE cp.order_id = o.order_id), 0) AS total_payments_received,
            -- Сумма только возвратов (берем абсолютное значение, т.к. в БД они отрицательные)
            COALESCE(SUM(CASE WHEN cp.payment_type = 'return_credit' THEN ABS(cp.amount) ELSE 0 END) FILTER (WHERE cp.order_id = o.order_id), 0) AS total_credits_issued,
            o.payment_status,
            o.due_date
        FROM
            orders o
        JOIN
            clients c ON o.client_id = c.client_id
        LEFT JOIN
            client_payments cp ON o.order_id = cp.order_id
        WHERE
            o.client_id = $1 AND o.status = 'confirmed' AND o.payment_status IN ('unpaid', 'partially_paid', 'overdue')
        GROUP BY
            o.order_id, o.invoice_number, o.confirmation_date, c.name, o.total_amount, o.amount_paid, o.payment_status, o.due_date
        ORDER BY
            o.confirmation_date ASC, o.order_id ASC;
        """
        records = await conn.fetch(query, client_id)
        
        invoices_with_calculated_debt = []
        for r in records:
            calculated_outstanding_balance = r['total_amount'] - r['total_payments_received'] + r['total_credits_issued']
            
            invoices_with_calculated_debt.append(
                UnpaidInvoice(
                    order_id=r['order_id'],
                    invoice_number=r['invoice_number'],
                    confirmation_date=r['confirmation_date'],
                    client_name=r['client_name'],
                    total_amount=r['total_amount'],
                    amount_paid=r['amount_paid'],
                    total_payments_received=r['total_payments_received'],
                    total_credits_issued=r['total_credits_issued'],
                    actual_outstanding_balance=calculated_outstanding_balance,
                    payment_status=r['payment_status'],
                    due_date=r['due_date']
                )
            )
        return invoices_with_calculated_debt
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении списка неоплаченных накладных для клиента {client_id}: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении списка неоплаченных накладных для клиента {client_id}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_order_by_invoice_number(pool: asyncpg.Pool, invoice_number: str) -> Optional[Dict]:
    """Получает информацию о заказе по номеру накладной."""
    conn = None
    try:
        conn = await pool.acquire()
        order_record = await conn.fetchrow("""
            SELECT
                order_id, invoice_number, total_amount, amount_paid, payment_status, due_date
            FROM
                orders
            WHERE
                invoice_number ILIKE $1;
        """, f"%{invoice_number}%")
        return dict(order_record) if order_record else None
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при поиске заказа по номеру накладной '{invoice_number}': {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при поиске заказа по номеру накладной '{invoice_number}': {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)

