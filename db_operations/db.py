import psycopg2
import psycopg2.extras
from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT

def get_connection():
    """Устанавливает и возвращает соединение с базой данных PostgreSQL."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        print(f"Ошибка подключения к базе данных: {e}")
        raise # Важно повторно вызвать исключение для обработки в вызывающем коде

def get_dict_cursor(conn):
    """Возвращает курсор, который извлекает строки как словари."""
    return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)