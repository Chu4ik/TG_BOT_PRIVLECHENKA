# db_operations/supplier_operations.py
import asyncpg
import logging
from typing import List, Optional, Dict, Any
from datetime import date, datetime
from decimal import Decimal
from collections import namedtuple

# Импортируем модуль product_operations целиком, чтобы избежать проблем с циклической зависимостью
# и отложить доступ к record_stock_movement до момента его использования.
import db_operations.product_operations

logger = logging.getLogger(__name__)

# Data models
SupplierItem = namedtuple("SupplierItem", ["supplier_id", "name"])

# Соответствует структуре таблицы incoming_deliveries пользователя
IncomingDeliveryReportItem = namedtuple("IncomingDeliveryReportItem", ["delivery_id", "delivery_date", "supplier_name", "product_name", "quantity", "unit_cost", "total_cost"])
SupplierPaymentReportItem = namedtuple("SupplierPaymentReportItem", ["payment_id", "supplier_name", "amount", "payment_method", "payment_date", "delivery_id"])


async def get_all_suppliers(db_pool: asyncpg.Pool) -> List[SupplierItem]:
    """
    Получает список всех поставщиков.
    """
    query = "SELECT supplier_id, name FROM suppliers ORDER BY name;"
    async with db_pool.acquire() as conn:
        records = await conn.fetch(query)
        return [SupplierItem(**r) for r in records]

async def get_all_products_for_selection(db_pool: asyncpg.Pool) -> List[db_operations.product_operations.ProductItem]:
    """
    Получает список всех продуктов для выбора.
    Эта функция оставлена здесь, так как add_delivery_handler.py явно импортирует ее отсюда.
    Использует ProductItem, определенный в db_operations.product_operations.
    """
    query = """
    SELECT product_id, name, description, cost_per_unit
    FROM products
    ORDER BY name;
    """
    async with db_pool.acquire() as conn:
        records = await conn.fetch(query)
        # Используем ProductItem из импортированного модуля product_operations
        return [db_operations.product_operations.ProductItem(r['product_id'], r['name'], r['description'], r['cost_per_unit']) for r in records]


async def record_incoming_delivery(
    db_pool: asyncpg.Pool,
    delivery_date: date,
    supplier_id: int,
    product_id: int,
    quantity: Decimal,
    unit_cost: Decimal
) -> Optional[int]:
    """
    Записывает поступление товара от поставщика в таблицу incoming_deliveries
    и обновляет остаток на складе.
    """
    conn = None
    try:
        conn = await db_pool.acquire()
        async with conn.transaction():
            # Вставляем данные напрямую в incoming_deliveries
            delivery_id = await conn.fetchval("""
                INSERT INTO incoming_deliveries (delivery_date, supplier_id, product_id, quantity, unit_cost)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING delivery_id;
            """, delivery_date, supplier_id, product_id, quantity, unit_cost)

            if not delivery_id:
                raise Exception("Не удалось создать запись о поступлении в incoming_deliveries.")

            # Обновить остаток на складе и записать движение инвентаря
            # Используем универсальную функцию record_stock_movement из db_operations.product_operations
            success = await db_operations.product_operations.record_stock_movement(
                db_pool=db_pool, # Передаем пул соединений
                product_id=product_id,
                quantity=quantity,
                movement_type='incoming',
                source_document_type='delivery', # Используем source_document_type
                source_document_id=delivery_id, # Используем source_document_id
                unit_cost=unit_cost,
                description=f"Поступление от поставщика ID {supplier_id}, поставка ID {delivery_id}" # Добавлено описание
            )
            if not success:
                raise Exception(f"Не удалось записать движение на складе для продукта {product_id}.")

            logger.info(f"Записано поступление ID {delivery_id} от поставщика {supplier_id} для продукта {product_id}.")
            return delivery_id
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при записи поступления: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при записи поступления: {e}", exc_info=True)
        return None
    finally:
        if conn:
            await db_pool.release(conn)

async def get_incoming_deliveries_for_date(db_pool: asyncpg.Pool, target_date: date) -> List[IncomingDeliveryReportItem]:
    """
    Получает отчет о поступлениях товара за указанную дату из таблицы incoming_deliveries.
    """
    query = """
    SELECT
        id.delivery_id,
        id.delivery_date,
        s.name AS supplier_name,
        p.name AS product_name,
        id.quantity,
        id.unit_cost,
        id.total_cost -- Используем GENERATED ALWAYS AS (quantity * unit_cost) STORED
    FROM
        incoming_deliveries id
    JOIN
        suppliers s ON id.supplier_id = s.supplier_id
    JOIN
        products p ON id.product_id = p.product_id
    WHERE
        id.delivery_date = $1
    ORDER BY
        id.delivery_date ASC, id.delivery_id ASC;
    """
    async with db_pool.acquire() as conn:
        try:
            records = await conn.fetch(query, target_date)
            return [IncomingDeliveryReportItem(**r) for r in records]
        except Exception as e:
            logger.error(f"Ошибка БД при получении отчета о поступлениях за {target_date}: {e}", exc_info=True)
            return []

async def get_supplier_payments_for_date(db_pool: asyncpg.Pool, target_date: date) -> List[SupplierPaymentReportItem]:
    """
    Получает отчет об оплатах поставщикам за указанную дату.
    """
    query = """
    SELECT
        sp.payment_id,
        s.name AS supplier_name,
        sp.amount,
        sp.payment_method,
        sp.payment_date,
        sp.delivery_id -- Может быть NULL
    FROM
        supplier_payments sp
    JOIN
        suppliers s ON sp.supplier_id = s.supplier_id
    WHERE
        sp.payment_date::date = $1
    ORDER BY
        sp.payment_date ASC, sp.payment_id ASC;
    """
    async with db_pool.acquire() as conn:
        try:
            records = await conn.fetch(query, target_date)
            return [SupplierPaymentReportItem(**r) for r in records]
        except Exception as e:
            logger.error(f"Ошибка БД при получении отчета об оплатах поставщикам за {target_date}: {e}", exc_info=True)
            return []
