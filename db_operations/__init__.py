import logging
import asyncpg
from datetime import date, timedelta
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

logger = logging.getLogger(__name__)

# Объявляем переменную для пула соединений, инициализируем её None
# Эту строку db_pool = None можно удалить, так как пул теперь передается
# или, если вы оставили её для справки, просто знайте, что она не используется
# для текущей архитектуры передачи пула.

async def init_db_pool():
    """Инициализирует пул соединений asyncpg. Вызывается при старте бота."""
    try:
        # Используем локальную переменную 'pool'
        pool = await asyncpg.create_pool(
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            host=DB_HOST,
            port=DB_PORT,
            min_size=5,
            max_size=10,
            timeout=60
        )
        logger.info("Пул соединений asyncpg успешно инициализирован.")
        return pool # Возвращаем локальный 'pool'
    except Exception as e:
        logger.critical(f"Ошибка при инициализации пула соединений asyncpg: {e}", exc_info=True)
        raise # Перевызываем исключение, чтобы остановить запуск бота, если нет подключения к БД

async def close_db_pool(pool): # Теперь 'pool' - это аргумент
    """Закрывает пул соединений asyncpg. Вызывается при остановке бота."""
    if pool:
        await pool.close()
        logger.info("Пул соединений asyncpg успешно закрыт.")


async def get_employee_id(pool, telegram_id: int): # Добавили 'pool' как аргумент
    """
    Получает employee_id из таблицы employees по telegram_id пользователя (используя asyncpg).
    """
    conn = None
    try:
        # Получаем соединение из ПЕРЕДАННОГО пула
        conn = await pool.acquire() # Используем 'pool'
        
        # asyncpg использует $1, $2 для параметров вместо %s
        result = await conn.fetchrow("SELECT employee_id FROM employees WHERE id_telegram = $1", telegram_id)
        
        return result['employee_id'] if result else None
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка asyncpg при получении employee_id для telegram_id {telegram_id}: {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении employee_id для telegram_id {telegram_id}: {e}", exc_info=True)
        return None
    finally:
        # Важно: всегда возвращайте соединение в пул!
        if conn:
            await pool.release(conn) # Используем 'pool'


