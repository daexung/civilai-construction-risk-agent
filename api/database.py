"""PostgreSQL 연결 및 쿼리 헬퍼"""

import os
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from pathlib import Path
from contextlib import contextmanager

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "construction_risk_agent")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_POOL_MIN = int(os.getenv("DB_POOL_MIN", "1"))
DB_POOL_MAX = int(os.getenv("DB_POOL_MAX", "5"))

_connection_pool = pool.ThreadedConnectionPool(
    DB_POOL_MIN,
    DB_POOL_MAX,
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD,
)


@contextmanager
def get_db_cursor():
    """DB 연결 및 커서 제공 (context manager)"""
    conn = _connection_pool.getconn()
    conn.set_session(autocommit=False)
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield cursor, conn
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        _connection_pool.putconn(conn)


def dict_from_row(row):
    """RealDictCursor Row → dict 변환"""
    if row is None:
        return None
    return dict(row)
