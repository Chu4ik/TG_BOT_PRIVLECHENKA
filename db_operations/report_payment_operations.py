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
    Создает запись в client_payments.
    """
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction(): # Все операции в транзакции
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
                # --- НОВОЕ: ЗАПИСЬ В client_payments ---
                await conn.execute("""
                    INSERT INTO client_payments (payment_date, client_id, order_id, amount, payment_method, description)
                    VALUES ($1, $2, $3, $4, $5, $6);
                """, date.today(), client_id, order_id, total_amount, 'full_payment', f"Полная оплата по накладной #{order_id}")
                # --- КОНЕЦ НОВОГО ---
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
        async with conn.transaction(): # Все операции в транзакции
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

            new_total_paid = current_amount_paid + new_amount_increase # Добавляем к текущей сумме
            
            new_payment_status = 'unpaid'
            current_datetime = datetime.now()

            if new_total_paid >= total_amount:
                new_payment_status = 'paid'
                new_total_paid = total_amount # Не позволяем "переплату" через этот метод, оплачиваем ровно
            elif new_total_paid > 0 and new_total_paid < total_amount:
                new_payment_status = 'partially_paid'
            elif new_total_paid <= 0: # Если вдруг стало 0 или меньше после вычитания (не должно быть в этом методе)
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
                # --- НОВОЕ: ЗАПИСЬ В client_payments ---
                await conn.execute("""
                    INSERT INTO client_payments (payment_date, client_id, order_id, amount, payment_method, description)
                    VALUES ($1, $2, $3, $4, $5, $6);
                """, date.today(), client_id, order_id, new_amount_increase, 'partial_payment', f"Частичная оплата по накладной #{order_id}")
                # --- КОНЕЦ НОВОГО ---
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
        async with conn.transaction(): # Все операции в транзакции
            current_data = await conn.fetchrow("SELECT total_amount, amount_paid, client_id FROM orders WHERE order_id = $1 FOR UPDATE", order_id)
            if not current_data:
                logger.warning(f"Накладная #{order_id} не найдена для отмены оплаты.")
                return False
            
            client_id = current_data['client_id']
            amount_to_reverse = current_data['amount_paid'] # Сумма, которая была оплачена и будет сторнирована

            result = await conn.execute("""
                UPDATE orders
                SET payment_status = 'unpaid',
                    amount_paid = 0.00,
                    actual_payment_date = NULL
                WHERE order_id = $1 AND status = 'confirmed';
            """, order_id)

            if result == 'UPDATE 1':
                # --- НОВОЕ: ЗАПИСЬ СТОРНИРОВАНИЯ В client_payments ---
                if amount_to_reverse > 0: # Только если что-то было оплачено
                    await conn.execute("""
                        INSERT INTO client_payments (payment_date, client_id, order_id, amount, payment_method, description)
                        VALUES ($1, $2, $3, $4, $5, $6);
                    """, date.today(), client_id, order_id, -amount_to_reverse, 'reverse_payment', f"Отмена оплаты по накладной #{order_id}")
                # --- КОНЕЦ НОВОГО ---
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


async def get_client_outstanding_invoices(pool, client_id: int) -> List[UnpaidInvoice]:
    """
    Получает список подтвержденных накладных для клиента, по которым есть задолженность.
    """
    conn = None
    try:
        conn = await pool.acquire()
        query = """
        SELECT
            o.order_id,
            o.invoice_number,
            o.confirmation_date,
            (SELECT c.name FROM clients c WHERE c.client_id = o.client_id) AS client_name, -- Для полноты namedtuple
            o.total_amount,
            o.amount_paid,
            (o.total_amount - o.amount_paid) AS outstanding_balance,
            o.payment_status,
            o.due_date
        FROM
            orders o
        WHERE
            o.client_id = $1
            AND o.status = 'confirmed' -- Только подтвержденные заказы могут иметь накладные и долги
            AND o.payment_status IN ('unpaid', 'partially_paid', 'overdue')
        ORDER BY
            o.confirmation_date DESC, o.order_id DESC;
        """
        records = await conn.fetch(query, client_id)
        return [UnpaidInvoice(**r) for r in records]
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
        """, f"%{invoice_number}%") # Используем ILIKE для поиска по части номера
        return dict(order_record) if order_record else None
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при поиске заказа по номеру накладной '{invoice_number}': {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)

