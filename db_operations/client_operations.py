# db_operations/client_operations.py

import asyncpg
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

async def find_clients_by_name(pool: asyncpg.Pool, name_query: str) -> List[Dict]:
    """Ищет клиентов по части имени."""
    conn = None
    try:
        conn = await pool.acquire()
        clients = await conn.fetch("SELECT client_id, name FROM clients WHERE name ILIKE $1 ORDER BY name ASC;", f"%{name_query}%")
        return [dict(c) for c in clients]
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при поиске клиентов по имени '{name_query}': {e}", exc_info=True)
        return []
    finally:
        if conn:
            await pool.release(conn)

async def get_client_by_id(pool: asyncpg.Pool, client_id: int) -> Optional[Dict]:
    """Получает информацию о клиенте по ID."""
    conn = None
    try:
        conn = await pool.acquire()
        client = await conn.fetchrow("SELECT client_id, name FROM clients WHERE client_id = $1;", client_id)
        return dict(client) if client else None
    except asyncpg.exceptions.PostgresError as e:
        logger.error(f"Ошибка БД при получении клиента по ID '{client_id}': {e}", exc_info=True)
        return None
    finally:
        if conn:
            await pool.release(conn)