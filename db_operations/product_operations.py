# db_operations/product_operations.py
import asyncpg
import logging
from typing import List, Optional, Dict, Any
from decimal import Decimal
from datetime import datetime

logger = logging.getLogger(__name__)

class ProductItem:
    def __init__(self, product_id: int, name: str, description: Optional[str], cost_per_unit: Decimal):
        self.product_id = product_id
        self.name = name
        self.description = description
        self.cost_per_unit = cost_per_unit # Это базовая стоимость из таблицы products

class ProductStockItem(ProductItem):
    def __init__(self, product_id: int, name: str, description: Optional[str], cost_per_unit: Decimal, current_stock: Decimal, average_movement_cost: Optional[Decimal] = None):
        super().__init__(product_id, name, description, cost_per_unit)
        self.current_stock = current_stock
        self.average_movement_cost = average_movement_cost # Средняя стоимость из движений

async def get_all_products_for_selection(db_pool: asyncpg.Pool) -> List[ProductItem]:
    """
    Получает список всех продуктов для выбора.
    """
    query = """
    SELECT product_id, name, cost_per_unit -- УДАЛЕНО: description
    FROM products
    ORDER BY name;
    """
    async with db_pool.acquire() as conn:
        records = await conn.fetch(query)
        # Передаем None для description, так как он больше не выбирается из БД
        return [ProductItem(r['product_id'], r['name'], None, r['cost_per_unit']) for r in records]

async def get_product_by_id(db_pool: asyncpg.Pool, product_id: int) -> Optional[ProductItem]:
    """
    Получает продукт по его ID.
    """
    query = """
    SELECT product_id, name, cost_per_unit -- УДАЛЕНО: description
    FROM products
    WHERE product_id = $1;
    """
    async with db_pool.acquire() as conn:
        record = await conn.fetchrow(query, product_id)
        if record:
            # Передаем None для description, так как он больше не выбирается из БД
            return ProductItem(record['product_id'], record['name'], None, record['cost_per_unit'])
        return None

async def get_all_product_stock(db_pool: asyncpg.Pool) -> List[ProductStockItem]:
    """
    Получает список всех продуктов с их текущим остатком на складе
    и средней стоимостью поступления из inventory_movements.
    """
    query = """
    SELECT
        p.product_id,
        p.name,
        p.cost_per_unit, -- Базовая стоимость из таблицы products
        COALESCE(s.quantity, 0) AS current_stock, -- ИСПРАВЛЕНО: Берем напрямую из stock.quantity
        -- Расчет средней стоимости поступления из inventory_movements
        -- Используем im.quantity_change для фильтрации, если это необходимо для AVG
        COALESCE(AVG(im.unit_cost) FILTER (WHERE im.movement_type = 'incoming'), p.cost_per_unit) AS average_movement_cost
    FROM
        products p
    LEFT JOIN
        stock s ON p.product_id = s.product_id
    LEFT JOIN
        inventory_movements im ON p.product_id = im.product_id
    GROUP BY
        p.product_id, p.name, p.cost_per_unit, s.quantity -- ИСПРАВЛЕНО: Добавлен s.quantity в GROUP BY
    ORDER BY
        p.name;
    """
    async with db_pool.acquire() as conn:
        try:
            records = await conn.fetch(query)
            
            # --- DEBUGGING START ---
            logger.info("DEBUG: Данные, полученные из БД для отчета об остатках:")
            for r in records:
                logger.info(f"  Product ID: {r['product_id']}, Name: {r['name']}, Current Stock: {r['current_stock']}")
            # --- DEBUGGING END ---

            return [ProductStockItem(
                r['product_id'],
                r['name'],
                None, # Передаем None для description, так как он больше не выбирается из БД
                r['cost_per_unit'], # Базовая стоимость
                r['current_stock'],
                r['average_movement_cost'] # Средняя стоимость из движений
            ) for r in records]
        except Exception as e:
            logger.error(f"Ошибка БД при получении остатков товаров: {e}", exc_info=True)
            return []

async def add_product(db_pool: asyncpg.Pool, name: str, description: Optional[str], cost_per_unit: Decimal) -> Optional[int]:
    """
    Добавляет новый продукт в базу данных.
    Возвращает ID нового продукта или None в случае ошибки.
    """
    query = """
    INSERT INTO products (name, description, cost_per_unit)
    VALUES ($1, $2, $3)
    RETURNING product_id;
    """
    async with db_pool.acquire() as conn:
        try:
            product_id = await conn.fetchval(query, name, description, cost_per_unit)
            logger.info(f"Добавлен новый продукт: ID={product_id}, Название='{name}'")
            return product_id
        except Exception as e:
            logger.error(f"Ошибка при добавлении продукта '{name}': {e}", exc_info=True)
            return None

async def update_product(db_pool: asyncpg.Pool, product_id: int, name: str, description: Optional[str], cost_per_unit: Decimal) -> bool:
    """
    Обновляет информацию о существующем продукте.
    """
    query = """
    UPDATE products
    SET name = $2, description = $3, cost_per_unit = $4
    WHERE product_id = $1;
    """
    async with db_pool.acquire() as conn:
        try:
            result = await conn.execute(query, product_id, name, description, cost_per_unit)
            return result == 'UPDATE 1'
        except Exception as e:
            logger.error(f"Ошибка при обновлении продукта ID {product_id}: {e}", exc_info=True)
            return False

async def delete_product(db_pool: asyncpg.Pool, product_id: int) -> bool:
    """
    Удаляет продукт из базы данных.
    """
    query = """
    DELETE FROM products
    WHERE product_id = $1;
    """
    async with db_pool.acquire() as conn:
        try:
            result = await conn.execute(query, product_id)
            return result == 'DELETE 1'
        except Exception as e:
            logger.error(f"Ошибка при удалении продукта ID {product_id}: {e}", exc_info=True)
            return False

async def update_stock_on_order_confirmation(db_pool: asyncpg.Pool, order_id: int) -> bool:
    """
    Обновляет остаток товара на складе и записывает исходящее движение в inventory_movements
    при подтверждении заказа.
    Теперь принимает только order_id и получает детали из order_lines.
    """
    conn = None
    try:
        conn = await db_pool.acquire()
        async with conn.transaction():
            order_lines = await conn.fetch("""
                SELECT product_id, quantity, unit_price FROM order_lines WHERE order_id = $1;
            """, order_id)

            if not order_lines:
                logger.warning(f"Для заказа #{order_id} не найдено позиций для списания со склада.")
                return False

            for item in order_lines:
                product_id = item['product_id']
                quantity_ordered = item['quantity']
                # Для исходящих движений unit_cost берем из products.cost_per_unit
                product_info = await conn.fetchrow("SELECT cost_per_unit FROM products WHERE product_id = $1", product_id)
                if not product_info:
                    logger.error(f"Продукт ID {product_id} не найден при попытке записать исходящее движение инвентаря для заказа #{order_id}.")
                    raise ValueError(f"Product {product_id} not found.")
                
                unit_cost = product_info['cost_per_unit']

                # Используем универсальную функцию record_stock_movement
                success = await record_stock_movement(
                    db_pool=db_pool,
                    product_id=product_id,
                    quantity=quantity_ordered, # Количество для списания
                    movement_type='outgoing',
                    source_document_type='order', # Тип документа-источника
                    source_document_id=order_id, # ID документа-источника
                    unit_cost=unit_cost, # Себестоимость для исходящего движения
                    description=f"Продажа по заказу #{order_id}"
                )
                if not success:
                    logger.error(f"Не удалось записать исходящее движение для продукта {product_id} по заказу #{order_id}.")
                    raise Exception(f"Failed to record outgoing stock movement for product {product_id} on order {order_id}.")
            
            logger.info(f"Все исходящие движения для заказа #{order_id} успешно записаны.")
            return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при обновлении остатков для заказа {order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при обновлении остатков для заказа {order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await db_pool.release(conn)


async def get_product_current_stock(db_pool: asyncpg.Pool, product_id: int) -> Decimal:
    """
    Получает текущий остаток товара на складе.
    """
    query = """
    SELECT COALESCE(quantity, 0) FROM stock WHERE product_id = $1;
    """
    async with db_pool.acquire() as conn:
        try:
            stock = await conn.fetchval(query, product_id)
            return stock if stock is not None else Decimal('0.00')
        except Exception as e:
            logger.error(f"Ошибка БД при получении текущего остатка для продукта ID {product_id}: {e}", exc_info=True)
            return Decimal('0.00') # Возвращаем 0 в случае ошибки

async def record_stock_movement(db_pool: asyncpg.Pool, product_id: int, quantity: Decimal, movement_type: str, source_document_type: Optional[str] = None, source_document_id: Optional[int] = None, unit_cost: Optional[Decimal] = None, description: Optional[str] = None) -> bool:
    """
    Записывает движение товара на складе (incoming/outgoing) и обновляет таблицу stock.

    Args:
        db_pool: Пул соединений с базой данных.
        product_id: ID продукта.
        quantity: Количество товара, участвующего в движении.
        movement_type: Тип движения ('incoming' или 'outgoing').
        source_document_type: Тип документа-источника (например, 'order', 'delivery').
        source_document_id: ID документа-источника (например, order_id, delivery_id).
        unit_cost: Стоимость за единицу для данного движения (обязательно для 'incoming').
        description: Описание движения.
    Returns:
        True, если движение успешно записано и остаток обновлен, False в противном случае.
    """
    conn = None
    try:
        conn = await db_pool.acquire()
        async with conn.transaction():
            # Обновление таблицы 'stock'
            existing_stock = await conn.fetchrow("SELECT quantity FROM stock WHERE product_id = $1 FOR UPDATE", product_id)
            
            current_stock_quantity = existing_stock['quantity'] if existing_stock else Decimal('0.00')

            if movement_type == 'incoming':
                new_quantity = current_stock_quantity + quantity
            elif movement_type == 'outgoing':
                new_quantity = current_stock_quantity - quantity
            else:
                logger.error(f"Неизвестный тип движения: {movement_type}")
                return False

            if existing_stock:
                await conn.execute("UPDATE stock SET quantity = $1 WHERE product_id = $2", new_quantity, product_id)
            else:
                await conn.execute("INSERT INTO stock (product_id, quantity) VALUES ($1, $2)", product_id, new_quantity)

            # Запись движения в 'inventory_movements'
            # Для входящих движений unit_cost должен быть предоставлен
            if movement_type == 'incoming' and unit_cost is None:
                logger.error("Для входящего движения (incoming) unit_cost должен быть предоставлен.")
                raise ValueError("unit_cost is required for 'incoming' movement type.")
            
            # Используем quantity_change, source_document_type, source_document_id и description
            await conn.execute("""
                INSERT INTO inventory_movements (product_id, quantity_change, movement_type, movement_date, unit_cost, source_document_type, source_document_id, description)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8);
            """, product_id, quantity, movement_type, datetime.now(), unit_cost, source_document_type, source_document_id, description)
            
            logger.info(f"Записано {movement_type} движение для продукта ID {product_id}: {quantity}. Новый остаток: {new_quantity}.")
            return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при записи движения инвентаря для продукта {product_id}, тип {movement_type}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при записи движения инвентаря для продукта {product_id}, тип {movement_type}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await db_pool.release(conn)
