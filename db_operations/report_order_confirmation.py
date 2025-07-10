# db_operations/report_order_confirmation.py

import asyncpg
from datetime import date, timedelta, datetime
from collections import namedtuple
import logging
from typing import Optional, List, Dict
from decimal import Decimal
from db_operations.product_operations import update_stock_on_order_confirmation, get_product_current_stock

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

OrderDetail = namedtuple(
    "OrderDetail",
    [
        "product_name",
        "quantity",
        "unit_price",
        "total_item_amount"
    ]
)

# НОВЫЙ namedtuple для отображения неоплаченных накладных (если вы его переместили сюда)
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


async def get_unconfirmed_orders(pool):
    # ... (ваш существующий код) ...
    conn = None
    try:
        conn = await pool.acquire()

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
        
        rows = await conn.fetch(query)
        
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
            await pool.release(conn)


async def get_unconfirmed_order_full_details(pool, order_id: int) -> Optional[Dict]:
    # ... (ваш существующий код) ...
    conn = None
    try:
        conn = await pool.acquire()
        order_row = await conn.fetchrow("""
            SELECT
                o.order_id,
                o.order_date,
                o.delivery_date,
                c.name,
                a.address_text,
                o.total_amount,
                o.status
            FROM
                orders o
            JOIN
                clients c ON o.client_id = c.client_id
            JOIN
                addresses a ON o.address_id = a.address_id
            WHERE
                o.order_id = $1 AND o.status = 'draft';
        """, order_id)

        if not order_row:
            return None

        order_details = {
            "order_id": order_row['order_id'],
            "order_date": order_row['order_date'],
            "delivery_date": order_row['delivery_date'],
            "client_name": order_row['name'],
            "address_text": order_row['address_text'],
            "total_amount": order_row['total_amount'],
            "status": order_row['status'],
            "items": []
        }

        item_rows = await conn.fetch("""
            SELECT
                ol.quantity,
                ol.unit_price,
                p.name
            FROM
                order_lines ol
            JOIN
                products p ON ol.product_id = p.product_id
            WHERE
                ol.order_id = $1;
        """, order_id)

        for item_row in item_rows:
            order_details["items"].append(OrderDetail(
                product_name=item_row['name'],
                quantity=item_row['quantity'],
                unit_price=item_row['unit_price'],
                total_item_amount=item_row['quantity'] * item_row['unit_price']
            ))
        
        return order_details
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при получении полной информации о неподтвержденном заказе {order_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении полной информации о неподтвержденном заказе {order_id}: {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)

async def confirm_order_in_db(pool, order_id: int) -> bool:
    """
    Подтверждает один заказ в БД, устанавливая статус 'confirmed',
    генерируя номер накладной (дата из delivery_date), устанавливая confirmation_date = delivery_date и due_date.
    КЛЮЧЕВОЕ: Сначала проверяет и корректирует количества в order_lines по реальным остаткам,
    затем списывает скорректированные количества.
    """
    conn = None
    try:
        conn = await pool.acquire()

        async with conn.transaction(): # Все операции внутри одной транзакции
            # Шаг 1: Получаем основную информацию о заказе и его текущие строки
            order_info = await conn.fetchrow("SELECT delivery_date, client_id, address_id, employee_id FROM orders WHERE order_id = $1 AND status = 'draft';", order_id)
            if not order_info:
                logger.warning(f"Заказ #{order_id} не найден или уже не в статусе 'draft' для подтверждения.")
                return False

            current_order_lines = await conn.fetch("""
                SELECT product_id, quantity, unit_price FROM order_lines WHERE order_id = $1;
            """, order_id)

            if not current_order_lines:
                logger.warning(f"Заказ #{order_id} не содержит товаров. Невозможно подтвердить.")
                return False

            # Переменные для отслеживания изменений
            adjusted_items_info = [] # Для логирования корректировок
            new_order_lines_for_db = [] # Новые строки, которые будут записаны
            new_total_amount = Decimal('0.00')

            # Шаг 2: Проверяем наличие и корректируем количество для каждой позиции
            for item in current_order_lines:
                product_id = item['product_id']
                requested_quantity = item['quantity']
                unit_price = item['unit_price']
                
                # Получаем текущий остаток товара
                current_stock = await get_product_current_stock(pool, product_id) # Используем pool, а не conn

                if current_stock is None: # Если товар не найден в stock (ошибка)
                    logger.error(f"Продукт ID {product_id} не найден в таблице stock при проверке остатков для заказа #{order_id}. Откат.")
                    # Лучше не подтверждать заказ, если данные о продукте некорректны
                    raise Exception(f"Продукт ID {product_id} не найден в остатках.")

                actual_quantity_to_ship = requested_quantity # Изначально, отгружаем столько, сколько заказано

                if requested_quantity > current_stock:
                    # Если заказано больше, чем есть на складе
                    actual_quantity_to_ship = current_stock
                    adjusted_items_info.append(
                        f"Товар ID {product_id}: заказано {requested_quantity}, отгружено {actual_quantity_to_ship} (доступно: {current_stock})."
                    )
                    logger.warning(f"Заказ #{order_id} - Недостаточно товара (ID: {product_id}). Заказано: {requested_quantity}, Доступно: {current_stock}. Количество скорректировано до {actual_quantity_to_ship}.")
                
                if actual_quantity_to_ship > 0:
                    # Добавляем позицию в список для новой записи, если количество больше 0
                    new_order_lines_for_db.append({
                        "product_id": product_id,
                        "quantity": actual_quantity_to_ship,
                        "unit_price": unit_price
                    })
                    new_total_amount += actual_quantity_to_ship * unit_price
                else:
                    # Если после корректировки количество стало 0 или было 0
                    adjusted_items_info.append(
                        f"Товар ID {product_id} (заказано {requested_quantity}) отсутствует на складе (0 ед.) и удален из накладной."
                    )
                    logger.warning(f"Заказ #{order_id} - Товар (ID: {product_id}) будет удален из накладной, т.к. остаток 0.")


            # Если после всех корректировок в заказе не осталось товаров
            if not new_order_lines_for_db:
                logger.warning(f"Заказ #{order_id} стал пустым после корректировки остатков. Отменяем заказ.")
                # Опционально: можно сменить статус на 'cancelled' и вернуть False
                await conn.execute("UPDATE orders SET status = 'cancelled' WHERE order_id = $1;", order_id)
                return False # Возвращаем False, так как заказ не подтвержден, а отменен

            # Шаг 3: Обновляем order_lines в БД с новыми количествами
            await conn.execute("DELETE FROM order_lines WHERE order_id = $1;", order_id) # Удаляем старые строки
            for item_data in new_order_lines_for_db:
                await conn.execute("""
                    INSERT INTO order_lines (order_id, product_id, quantity, unit_price)
                    VALUES ($1, $2, $3, $4)
                """, order_id, item_data['product_id'], item_data['quantity'], item_data['unit_price'])

            # Шаг 4: Обновляем статус заказа и total_amount в таблице orders
            delivery_date_for_invoice = order_info['delivery_date']
            invoice_number = f"INV-{delivery_date_for_invoice.strftime('%Y%m%d')}-{order_id}"
            confirmation_date_val = datetime.now() # Фактическая дата подтверждения (текущая)
            due_date_calculated = confirmation_date_val + timedelta(days=7) # Срок оплаты 7 дней

            result = await conn.execute("""
                UPDATE orders
                SET status = 'confirmed',
                    invoice_number = $1,
                    confirmation_date = $2,
                    due_date = $3,
                    total_amount = $4 -- Обновляем total_amount после корректировок
                WHERE order_id = $5 AND status = 'draft';
            """, invoice_number, confirmation_date_val, due_date_calculated, new_total_amount, order_id)
            
            if result != 'UPDATE 1':
                logger.warning(f"Заказ #{order_id} не был подтвержден (статус не 'draft' или не найден) после корректировки остатков.")
                return False

            # Шаг 5: Списываем остатки и записываем движения в inventory_movements
            # update_stock_on_order_confirmation будет использовать уже скорректированные order_lines
            stock_updated = await update_stock_on_order_confirmation(pool, order_id) # Используем pool, а не conn
            if not stock_updated:
                logger.error(f"Не удалось записать движения расхода для заказа #{order_id}. Откат транзакции.")
                raise Exception(f"Ошибка записи движений по складу для заказа #{order_id}.")
            
            logger.info(f"Заказ #{order_id} успешно подтвержден. Новая общая сумма: {new_total_amount:.2f}. Корректировки остатков: {adjusted_items_info if adjusted_items_info else 'нет'}.")
            return True

    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при подтверждении заказа #{order_id} с корректировкой остатков: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при подтверждении заказа #{order_id} с корректировкой остатков: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)

async def cancel_order_in_db(pool, order_id: int):
    # ... (ваш существующий код) ...
    conn = None
    try:
        conn = await pool.acquire()
        
        result = await conn.execute("""
            UPDATE orders
            SET status = 'cancelled'
            WHERE order_id = $1;
        """, order_id)
        
        if result == 'UPDATE 1':
            logger.info(f"Заказ #{order_id} успешно отменен (статус изменен на 'cancelled').")
            return True
        else:
            logger.warning(f"Заказ #{order_id} не был отменен (не найден).")
            return False
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при отмене заказа #{order_id}: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при отмене заказа #{order_id}: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)


async def confirm_all_orders_in_db(pool, order_ids: list[int]) -> bool:
    """
    Массовое подтверждение заказов.
    Важно: эта функция будет вызывать confirm_order_in_db для каждого заказа,
    поэтому логика корректировки остатков будет применяться индивидуально.
    """
    success_count = 0
    total_count = len(order_ids)
    for order_id in order_ids:
        # Здесь мы используем ту же логику, что и для одиночного подтверждения
        # Если confirm_order_in_db возвращает False, это означает,
        # что заказ либо не найден, либо стал пустым после корректировки, либо произошла ошибка.
        if await confirm_order_in_db(pool, order_id):
            success_count += 1
    
    if success_count == total_count:
        logger.info(f"Все {total_count} выбранные заказы успешно подтверждены.")
        return True
    elif success_count > 0:
        logger.warning(f"{success_count} из {total_count} заказов подтверждены. Были ошибки или корректировки/отмены для других.")
        return True # Частичный успех
    else:
        logger.error(f"Не удалось подтвердить ни один из {total_count} заказов.")
        return False

async def cancel_all_orders_in_db(pool, order_ids: list[int]):
    # ... (ваш существующий код) ...
    conn = None
    try:
        conn = await pool.acquire()
        # Используем транзакцию для массовых операций
        async with conn.transaction():
            for order_id in order_ids:
                await conn.execute("""
                    UPDATE orders
                    SET status = 'cancelled'
                    WHERE order_id = $1;
                """, order_id)
        
        logger.info(f"Все выбранные заказы ({len(order_ids)}) отменены.")
        return True
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при массовой отмене и удалении заказов: {e}", exc_info=True)
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при массовой отмене и удалении заказов: {e}", exc_info=True)
        return False
    finally:
        if conn:
            await pool.release(conn)