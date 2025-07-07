# db_operations/supplier_operations.py

import asyncpg
import logging
from typing import List, Optional
from datetime import date, datetime
from collections import namedtuple
from decimal import Decimal

logger = logging.getLogger(__name__)

# Namedtuple для отчета о поступлениях товара
IncomingDeliveryReportItem = namedtuple(
    "IncomingDeliveryReportItem",
    [
        "delivery_id",
        "delivery_date",
        "supplier_name",
        "product_name",
        "quantity",
        "unit_cost",
        "total_cost"
    ]
)

# Namedtuple для отчета об оплатах поставщикам
SupplierPaymentReportItem = namedtuple(
    "SupplierPaymentReportItem",
    [
        "payment_id",
        "payment_date",
        "supplier_name",
        "delivery_id", # Может быть NULL, если оплата не привязана к конкретной поставке
        "amount",
        "payment_method"
    ]
)

async def get_incoming_deliveries_for_date(pool, report_date: date) -> List[IncomingDeliveryReportItem]:
    """
    Получает список поступлений товара за указанную дату.
    """
    conn = None
    try:
        conn = await pool.acquire()
        query = """
        SELECT
            id.delivery_id,
            id.delivery_date,
            s.name AS supplier_name,
            p.name AS product_name,
            id.quantity,
            id.unit_cost,
            id.total_cost
        FROM
            incoming_deliveries id
        JOIN
            suppliers s ON id.supplier_id = s.supplier_id
        JOIN
            products p ON id.product_id = p.product_id
        WHERE
            id.delivery_date = $1
        ORDER BY
            id.delivery_date ASC, s.name ASC, p.name ASC;
        """
        records = await conn.fetch(query, report_date)
        return [IncomingDeliveryReportItem(**r) for r in records]
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении поступлений за {report_date}: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении поступлений за {report_date}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)


async def get_supplier_payments_for_date(pool, report_date: date) -> List[SupplierPaymentReportItem]:
    """
    Получает список оплат поставщикам за указанную дату.
    """
    conn = None
    try:
        conn = await pool.acquire()
        query = """
        SELECT
            sp.payment_id,
            sp.payment_date,
            s.name AS supplier_name,
            sp.delivery_id,
            sp.amount,
            sp.payment_method
        FROM
            supplier_payments sp
        JOIN
            suppliers s ON sp.supplier_id = s.supplier_id
        WHERE
            sp.payment_date = $1
        ORDER BY
            sp.payment_date ASC, s.name ASC, sp.payment_id ASC;
        """
        records = await conn.fetch(query, report_date)
        return [SupplierPaymentReportItem(**r) for r in records]
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении оплат поставщикам за {report_date}: {e}", exc_info=True)
        return []
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении оплат поставщикам за {report_date}: {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)