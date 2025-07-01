import psycopg2
from psycopg2 import sql
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT


# def test_connection():
#     try:
#         conn = psycopg2.connect(
#             dbname=DB_NAME,
#             user=DB_USER,
#             password=DB_PASSWORD,
#             host=DB_HOST,
#             port=DB_PORT
#         )
#         print("✅ Успешное подключение к базе данных PostgreSQL")
#         conn.close()
#     except Exception as e:
#         print("❌ Ошибка подключения:", e)

def get_table_list():
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT
        )
        with conn.cursor() as cur:
            cur.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            tables = cur.fetchall()
            print("📦 Список таблиц в базе:")
            for row in tables:
                print(f"• {row[0]}")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # test_connection()
    get_table_list()