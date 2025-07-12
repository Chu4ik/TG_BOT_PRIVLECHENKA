# db_operations/supplier_operations.py

import asyncpg
import logging
from typing import List, Dict, Optional, NamedTuple
from datetime import date, datetime
from decimal import Decimal

logger = logging.getLogger(__name__)

# --- ОБНОВЛЕННЫЕ ОПРЕДЕЛЕНИЯ NAMEDTUPLE ---

class Supplier(NamedTuple):
    supplier_id: int
    name: str

# ВОЗВРАЩЕНО ЭТО ОПРЕДЕЛЕНИЕ! (Оно нужно для старой логики, которая ожидает старую структуру incoming_deliveries)
class IncomingDelivery(NamedTuple):
    incoming_delivery_id: int
    supplier_id: int
    delivery_date: date
    total_amount: Decimal
    amount_paid: Decimal
    payment_status: str
    invoice_number: Optional[str]
    description: Optional[str]


class SupplierInvoice(NamedTuple):
    supplier_invoice_id: int
    supplier_id: int
    invoice_number: str
    invoice_date: date
    due_date: Optional[date]
    total_amount: Decimal
    amount_paid: Decimal
    payment_status: str
    description: Optional[str]
    created_at: datetime

class IncomingDeliveryLine(NamedTuple): # Переименовал для ясности, по сути это ваша старая incoming_deliveries
    delivery_id: int # Это ID строки поступления, не ID шапки
    supplier_invoice_id: Optional[int] # Теперь привязка к шапке
    supplier_id: int # Дублируется, но полезно для запросов, если не хотим джойнить supplier_invoices
    product_id: int
    quantity: int
    unit_cost: Decimal
    total_cost: Decimal # Генерируемое поле в БД
    delivery_date: date # Добавлено для get_supplier_incoming_deliveries
    invoice_number: Optional[str]

class IncomingDeliveryReportItem(NamedTuple):
    delivery_id: int
    delivery_date: date
    supplier_name: str
    product_name: str
    quantity: int
    unit_cost: Decimal
    total_cost: Decimal
    invoice_number_from_supplier_invoice: Optional[str]

class SupplierPaymentReportItem(NamedTuple):
    payment_id: int
    supplier_name: str
    amount: Decimal
    payment_method: str
    payment_date: date
    incoming_delivery_id: Optional[int]
    supplier_invoice_number: Optional[str]

# --- КОНЕЦ ОБНОВЛЕННЫХ ОПРЕДЕЛЕНИЙ NAMEDTUPLE ---


async def find_suppliers_by_name(pool: asyncpg.Pool, name_query: str) -> List[Supplier]:
    """Ищет поставщиков по части имени."""
    conn = None
    try:
        conn = await pool.acquire()
        suppliers = await conn.fetch("SELECT supplier_id, name FROM suppliers WHERE name ILIKE $1 ORDER BY name ASC;", f"%{name_query}%")
        return [Supplier(**s) for s in suppliers]
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при поиске поставщиков по имени '{name_query}': {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_supplier_by_id(pool: asyncpg.Pool, supplier_id: int) -> Optional[Supplier]:
    """Получает информацию о поставщике по ID."""
    conn = None
    try:
        conn = await pool.acquire()
        supplier = await conn.fetchrow("SELECT supplier_id, name FROM suppliers WHERE supplier_id = $1;", supplier_id)
        return Supplier(**supplier) if supplier else None
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении поставщика по ID '{supplier_id}': {e}", exc_info=True)
        return None # Исправлено: Возвращаем None для Optional
    finally:
        if conn:
            await pool.release(conn)

# --- НОВЫЕ ФУНКЦИИ ДЛЯ supplier_invoices ---

async def create_supplier_invoice(
    pool: asyncpg.Pool,
    supplier_id: int,
    invoice_number: str,
    invoice_date: date,
    total_amount: Decimal,
    due_date: Optional[date] = None,
    description: Optional[str] = None
) -> Optional[int]:
    """
    Создает новую накладную поставщика (шапку).
    """
    conn = None
    try:
        conn = await pool.acquire()
        supplier_invoice_id = await conn.fetchval("""
            INSERT INTO supplier_invoices (supplier_id, invoice_number, invoice_date, total_amount, due_date, description)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING supplier_invoice_id;
        """, supplier_id, invoice_number, invoice_date, total_amount, due_date, description)
        
        logger.info(f"Создана накладная поставщика ID: {supplier_invoice_id}, номер: {invoice_number}")
        return supplier_invoice_id
    except asyncpg.exceptions.UniqueViolationError:
        logger.warning(f"Накладная поставщика с номером {invoice_number} уже существует.")
        return None
    except Exception as e:
        logger.error(f"Ошибка при создании накладной поставщика '{invoice_number}': {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)

async def get_supplier_invoice_by_number(pool: asyncpg.Pool, invoice_number: str) -> Optional[SupplierInvoice]:
    """Получает накладную поставщика по номеру."""
    conn = None
    try:
        conn = await pool.acquire()
        invoice_record = await conn.fetchrow("""
            SELECT supplier_invoice_id, supplier_id, invoice_number, invoice_date, due_date, total_amount, amount_paid, payment_status, description, created_at
            FROM supplier_invoices
            WHERE invoice_number ILIKE $1;
        """, f"%{invoice_number}%")
        return SupplierInvoice(**invoice_record) if invoice_record else None
    except Exception as e:
        logger.error(f"Ошибка при получении накладной поставщика по номеру '{invoice_number}': {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)

async def get_supplier_outstanding_invoices(pool: asyncpg.Pool, supplier_id: int) -> List[SupplierInvoice]:
    """
    Получает список накладных поставщика, по которым у нас есть задолженность.
    """
    conn = None
    try:
        conn = await pool.acquire()
        invoices = await conn.fetch("""
            SELECT supplier_invoice_id, supplier_id, invoice_number, invoice_date, due_date, total_amount, amount_paid, payment_status, description, created_at
            FROM supplier_invoices
            WHERE supplier_id = $1 AND payment_status IN ('unpaid', 'partially_paid', 'overdue')
            ORDER BY invoice_date DESC, supplier_invoice_id DESC;
        """, supplier_id)
        return [SupplierInvoice(**inv) for inv in invoices]
    except Exception as e:
        logger.error(f"Ошибка при получении неоплаченных накладных поставщика {supplier_id}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_all_suppliers(pool: asyncpg.Pool) -> List[Dict]:
    """
    Получает список всех поставщиков.
    """
    conn = None
    try:
        conn = await pool.acquire()
        suppliers = await conn.fetch("SELECT supplier_id, name FROM suppliers ORDER BY name LIMIT 10;") # Ограничиваем 10, как запрошено
        return [dict(s) for s in suppliers]
    except Exception as e:
        logger.error(f"Ошибка при получении списка поставщиков: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_supplier_outstanding_invoices(pool: asyncpg.Pool, supplier_id: int) -> List[Dict]:
    """
    Получает список накладных поставщика, по которым есть задолженность (не полностью оплачены).
    """
    conn = None
    try:
        conn = await pool.acquire()
        # Выбираем накладные, которые не полностью оплачены
        invoices = await conn.fetch("""
            SELECT
                supplier_invoice_id,
                invoice_number,
                total_amount,
                amount_paid,
                payment_status
            FROM
                supplier_invoices
            WHERE
                supplier_id = $1 AND payment_status != 'paid'
            ORDER BY
                invoice_date DESC;
        """, supplier_id)
        return [dict(inv) for inv in invoices]
    except Exception as e:
        logger.error(f"Ошибка при получении накладных поставщика {supplier_id}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_products_by_invoice_id(pool: asyncpg.Pool, supplier_invoice_id: int) -> List[Dict]:
    """
    Получает список продуктов, связанных с конкретной накладной поставщика.
    """
    conn = None
    try:
        conn = await pool.acquire()
        products = await conn.fetch("""
            SELECT
                id.product_id,
                p.name AS product_name,
                id.quantity,
                id.unit_cost
            FROM
                incoming_deliveries id
            JOIN
                products p ON id.product_id = p.product_id
            WHERE
                id.supplier_invoice_id = $1
            ORDER BY
                p.name;
        """, supplier_invoice_id)
        return [dict(prod) for prod in products]
    except Exception as e:
        logger.error(f"Ошибка при получении продуктов для накладной {supplier_invoice_id}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

# --- НОВАЯ ФУНКЦИЯ: record_supplier_payment_or_return ---
async def record_supplier_payment_or_return(
    pool: asyncpg.Pool,
    supplier_id: int,
    amount: Decimal,
    payment_method: str,
    description: Optional[str] = None,
    incoming_delivery_id: Optional[int] = None, # Этот аргумент функции
    supplier_invoice_id: Optional[int] = None
) -> tuple[bool, Optional[str]]:
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            # ИСПРАВЛЕНО: Используем 'delivery_id' в SQL-запросе, если это ваш столбец
            await conn.execute("""
                INSERT INTO supplier_payments (payment_date, supplier_id, delivery_id, supplier_invoice_id, amount, payment_method, description)
                VALUES ($1, $2, $3, $4, $5, $6, $7);
            """, date.today(), supplier_id, incoming_delivery_id, supplier_invoice_id, amount, payment_method, description)
            #                  ^ Используем $3 для incoming_delivery_id, которое будет передано как delivery_id в таблице.

            new_payment_status = None
            if supplier_invoice_id:
                # ... (логика обновления supplier_invoices - без изменений) ...
                invoice_info = await conn.fetchrow("SELECT total_amount, amount_paid FROM supplier_invoices WHERE supplier_invoice_id = $1 FOR UPDATE", supplier_invoice_id)
                if invoice_info:
                    current_total_amount = invoice_info['total_amount']
                    current_amount_paid = invoice_info['amount_paid']

                    new_amount_paid = current_amount_paid + amount
                    
                    new_payment_status_calc = 'unpaid'
                    if new_amount_paid >= current_total_amount:
                        new_payment_status_calc = 'paid'
                    elif new_amount_paid > 0 and new_amount_paid < current_total_amount:
                        new_payment_status_calc = 'partially_paid'
                    
                    await conn.execute("""
                        UPDATE supplier_invoices
                        SET amount_paid = $1, payment_status = $2
                        WHERE supplier_invoice_id = $3;
                    """, new_amount_paid, new_payment_status_calc, supplier_invoice_id)
                    
                    new_payment_status = new_payment_status_calc # Обновляем возвращаемое значение
                else:
                    logger.warning(f"Накладная поставщика ID {supplier_invoice_id} не найдена для обновления платежного статуса.")
            
            logger.info(f"Операция в supplier_payments записана: поставщик {supplier_id}, сумма {amount}, метод {payment_method}.")
            return True, new_payment_status
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при записи операции в supplier_payments: {e}", exc_info=True)
        return False, None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при записи операции в supplier_payments: {e}", exc_info=True)
        return False, None
    finally:
        if conn:
            await pool.release(conn)

async def record_incoming_delivery(
    pool: asyncpg.Pool,
    delivery_date: date,
    supplier_id: int,
    product_id: int,
    quantity: Decimal,
    unit_cost: Decimal,
    supplier_invoice_id: Optional[int] = None
) -> Optional[int]:
    conn = None
    try:
        conn = await pool.acquire()
        async with conn.transaction():
            # --- ИСПРАВЛЕНО ЗДЕСЬ: Вычисляем total_cost в Python ---
            calculated_total_cost = quantity * unit_cost
            # --- КОНЕЦ ИСПРАВЛЕНИЯ ---

            delivery_line_id = await conn.fetchval("""
                INSERT INTO incoming_deliveries (delivery_date, supplier_id, product_id, quantity, unit_cost, supplier_invoice_id, total_cost) -- ДОБАВЛЕН total_cost в список столбцов
                VALUES ($1, $2, $3, $4::NUMERIC, $5::NUMERIC, $6, $7::NUMERIC) -- ДОБАВЛЕН $7 для total_cost и явное приведение
                RETURNING delivery_id;
            """, delivery_date, supplier_id, product_id, quantity, unit_cost, supplier_invoice_id, calculated_total_cost) # ДОБАВЛЕН calculated_total_cost

            if not delivery_line_id:
                raise Exception("Не удалось создать запись о позиции поступления в incoming_deliveries.")

            import db_operations.product_operations

            success = await db_operations.product_operations.record_stock_movement(
                db_pool=pool,
                product_id=product_id,
                quantity=quantity,
                movement_type='incoming',
                source_document_type='incoming_delivery_line',
                source_document_id=delivery_line_id,
                unit_cost=unit_cost,
                description=f"Поступление продукта ID {product_id} по накладной поставщика ID {supplier_invoice_id or 'без номера'}"
            )
            if not success:
                raise Exception(f"Не удалось записать движение на складе для продукта {product_id}.")

            logger.info(f"Записана позиция поступления ID {delivery_line_id} для накладной поставщика {supplier_invoice_id or 'без номера'}.")
            return delivery_line_id
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при записи позиции поступления: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при записи позиции поступления: {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)

# --- НОВАЯ ФУНКЦИЯ: get_supplier_incoming_deliveries ---
async def get_supplier_incoming_deliveries(pool: asyncpg.Pool, supplier_id: int) -> List[IncomingDeliveryLine]:
    """
    Получает список всех строк поступлений (incoming_deliveries) для конкретного поставщика,
    включая номер накладной из supplier_invoices.
    """
    conn = None
    try:
        conn = await pool.acquire()
        query = """
            SELECT
                id.delivery_id,
                id.supplier_invoice_id,
                id.supplier_id,
                id.product_id,
                id.quantity,
                id.unit_cost,
                id.total_cost,
                id.delivery_date,
                si.invoice_number AS invoice_number -- <--- НОВОЕ: получаем номер накладной из supplier_invoices
            FROM
                incoming_deliveries id
            LEFT JOIN -- Используем LEFT JOIN, так как supplier_invoice_id может быть NULL
                supplier_invoices si ON id.supplier_invoice_id = si.supplier_invoice_id
            WHERE
                id.supplier_id = $1
            ORDER BY
                id.delivery_id DESC;
        """
        deliveries = await conn.fetch(query, supplier_id)
        return [IncomingDeliveryLine(**d) for d in deliveries]
    except Exception as e:
        logger.error(f"Ошибка БД при получении строк поступлений для поставщика {supplier_id}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_incoming_deliveries_for_date(pool: asyncpg.Pool, target_date: date) -> List[IncomingDeliveryReportItem]:
    """
    Получает отчет о поступлениях товара за указанную дату.
    Теперь джойним supplier_invoices для номера накладной.
    """
    query = """
    SELECT
        id.delivery_id,
        id.delivery_date,
        s.name AS supplier_name,
        p.name AS product_name,
        id.quantity,
        id.unit_cost,
        id.total_cost,
        si.invoice_number AS invoice_number_from_supplier_invoice
    FROM
        incoming_deliveries id
    JOIN
        suppliers s ON id.supplier_id = s.supplier_id
    JOIN
        products p ON id.product_id = p.product_id
    LEFT JOIN
        supplier_invoices si ON id.supplier_invoice_id = si.supplier_invoice_id
    WHERE
        id.delivery_date = $1
    ORDER BY
        id.delivery_date ASC, id.delivery_id ASC;
    """
    conn = None
    try:
        conn = await pool.acquire()
        records = await conn.fetch(query, target_date)
        return [IncomingDeliveryReportItem(**r) for r in records]
    except Exception as e:
        logger.error(f"Ошибка БД при получении отчета о поступлениях за {target_date}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_supplier_payments_for_date(pool: asyncpg.Pool, target_date: date) -> List[SupplierPaymentReportItem]:
    """
    Получает отчет об оплатах поставщикам за указанную дату.
    Теперь джойним supplier_invoices для номера накладной.
    """
    query = """
    SELECT
        sp.payment_id,
        s.name AS supplier_name,
        sp.amount,
        sp.payment_method,
        sp.payment_date,
        sp.incoming_delivery_id,
        si.invoice_number AS supplier_invoice_number
    FROM
        supplier_payments sp
    JOIN
        suppliers s ON sp.supplier_id = s.supplier_id
    LEFT JOIN
        supplier_invoices si ON sp.supplier_invoice_id = si.supplier_invoice_id
    WHERE
        sp.payment_date::date = $1
    ORDER BY
        sp.payment_date ASC, sp.payment_id ASC;
    """
    conn = None
    try:
        conn = await pool.acquire()
        records = await conn.fetch(query, target_date)
        return [SupplierPaymentReportItem(**r) for r in records]
    except Exception as e:
        logger.error(f"Ошибка БД при получении отчета об оплатах поставщикам за {target_date}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_incoming_delivery_lines_for_supplier_invoice(pool: asyncpg.Pool, supplier_invoice_id: int) -> List[IncomingDeliveryLine]:
    """
    Получает все строки поступления для конкретной накладной поставщика.
    """
    conn = None
    try:
        conn = await pool.acquire()
        lines = await conn.fetch("""
            SELECT delivery_id, supplier_invoice_id, supplier_id, product_id, quantity, unit_cost, total_cost, delivery_date
            FROM incoming_deliveries
            WHERE supplier_invoice_id = $1;
        """, supplier_invoice_id)
        return [IncomingDeliveryLine(**line) for line in lines]
    except Exception as e:
        logger.error(f"Ошибка при получении строк поступления для накладной поставщика {supplier_invoice_id}: {e}", exc_info=True)
        return []
    finally:
        if conn: await pool.release(conn)