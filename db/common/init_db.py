"""
공통 앱 데이터베이스 초기화 (PostgreSQL)
- projects: 프로젝트/현장 정보
- conversations: 대화 세션
- messages: 메시지 히스토리

DB 설정: .env에서 읽음
  DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""

import os
import psycopg2
from psycopg2 import sql
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# DB 설정 (기본값 포함)
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "construction_risk_agent")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")


def get_db():
    """PostgreSQL 연결"""
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    return conn


def init_db():
    """테이블 생성"""
    conn = get_db()
    cursor = conn.cursor()

    try:
        # 1. projects 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id          VARCHAR(36) PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            created_at  TIMESTAMP NOT NULL
        )
        """)

        # 2. conversations 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id          VARCHAR(36) PRIMARY KEY,
            project_id  VARCHAR(36) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title       TEXT NOT NULL DEFAULT '새로운 대화',
            created_at  TIMESTAMP NOT NULL
        )
        """)

        # 3. messages 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id              VARCHAR(36) PRIMARY KEY,
            conversation_id VARCHAR(36) NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role            VARCHAR(10) NOT NULL CHECK(role IN ('user', 'assistant')),
            content         TEXT NOT NULL,
            created_at      TIMESTAMP NOT NULL
        )
        """)

        conn.commit()
        print(f"[OK] DB initialized: postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def create_default_project():
    """기본 프로젝트(__quick__) 생성"""
    conn = get_db()
    cursor = conn.cursor()

    default_id = "00000000-0000-0000-0000-000000000001"
    now = datetime.utcnow()

    try:
        # 기존 기본 프로젝트 확인
        cursor.execute("SELECT id FROM projects WHERE id = %s", (default_id,))
        if cursor.fetchone():
            print(f"[OK] Default project already exists: {default_id}")
            return

        # 생성
        cursor.execute(
            """
            INSERT INTO projects (id, name, description, created_at)
            VALUES (%s, %s, %s, %s)
            """,
            (default_id, "__quick__", "빠른 질문용 (프로젝트 미지정)", now)
        )
        conn.commit()
        print(f"[OK] Default project created: {default_id}")

    except Exception as e:
        conn.rollback()
        print(f"[ERROR] {e}")
        raise
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    init_db()
    create_default_project()
