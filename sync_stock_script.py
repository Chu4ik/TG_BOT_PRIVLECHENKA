# sync_stock_script.py

import asyncio
import asyncpg
import logging
from decimal import Decimal

# Импортируем функции для работы с пулом базы данных из db_operations
# Убедитесь, что ваш config.py находится в корне проекта или настройте путь
from config import DB_HOST, DB_NAME, DB_USER, DB_PASSWORD

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

async def init_db_pool():
    """Инициализирует пул соединений с базой данных."""
    try:
        if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
            missing_vars = []
            if not DB_HOST: missing_vars.append('DB_HOST')
            if not DB_NAME: missing_vars.append('DB_NAME')
            if not DB_USER: missing_vars.append('DB_USER')
            if not DB_PASSWORD: missing_vars.append('DB_PASSWORD')
            raise ValueError(f"Отсутствуют необходимые переменные конфигурации базы данных в config.py: {', '.join(missing_vars)}")

        pool = await asyncpg.create_pool(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            database=DB_NAME,
            min_size=1,
            max_size=10
        )
        logger.info("Пул соединений asyncpg успешно инициализирован для скрипта синхронизации.")
        return pool
    except Exception as e:
        logger.error(f"Ошибка при инициализации пула базы данных: {e}", exc_info=True)
        raise

async def close_db_pool(pool):
    """Закрывает пул соединений с базой данных."""
    if pool:
        await pool.close()
        logger.info("Пул соединений asyncpg успешно закрыт для скрипта синхронизации.")

async def synchronize_stock_table(db_pool: asyncpg.Pool):
    """
    Пересчитывает и синхронизирует таблицу 'stock' на основе 'inventory_movements'.
    """
    conn = None
    try:
        conn = await db_pool.acquire()
        async with conn.transaction():
            logger.info("Очистка таблицы 'stock' перед синхронизацией...")
            await conn.execute("TRUNCATE TABLE stock RESTART IDENTITY;")
            logger.info("Таблица 'stock' очищена.")

            logger.info("Пересчет остатков на основе 'inventory_movements'...")
            # ИСПРАВЛЕНО: Суммируем quantity_change условно, в зависимости от movement_type
            recalculate_query = """
            INSERT INTO stock (product_id, quantity)
            SELECT
                p.product_id,
                COALESCE(
                    SUM(CASE
                        WHEN im.movement_type = 'incoming' THEN im.quantity_change
                        WHEN im.movement_type = 'outgoing' THEN -im.quantity_change -- Вычитаем для исходящих
                        ELSE 0
                    END),
                0) AS calculated_quantity
            FROM
                products p
            LEFT JOIN
                inventory_movements im ON p.product_id = im.product_id
            GROUP BY
                p.product_id;
            """
            await conn.execute(recalculate_query)
            logger.info("Таблица 'stock' успешно синхронизирована с 'inventory_movements'.")

    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при синхронизации таблицы 'stock': {e}", exc_info=True)
        raise
    except Exception as e:
        logger.error(f"Неизвестная ошибка при синхронизации таблицы 'stock': {e}", exc_info=True)
        raise
    finally:
        if conn:
            await db_pool.release(conn)

async def main():
    db_pool = None
    try:
        db_pool = await init_db_pool()
        await synchronize_stock_table(db_pool)
        logger.info("Скрипт синхронизации завершен успешно.")
    except Exception as e:
        logger.error(f"Скрипт синхронизации завершился с ошибкой: {e}")
    finally:
        if db_pool:
            await close_db_pool(db_pool)

if __name__ == "__main__":
    asyncio.run(main())