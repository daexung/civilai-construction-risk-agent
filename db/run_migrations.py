#!/usr/bin/env python3
"""Run SQL migrations in db/migrations in filename order."""

import os
import sys
from pathlib import Path

import psycopg2
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "construction_risk_agent")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def run_migrations():
    """Execute all migration SQL files in lexical order."""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
        )
        cursor = conn.cursor()

        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not migration_files:
            print("[ERROR] No migration files found.")
            sys.exit(1)

        for migration_file in migration_files:
            print(f"Running {migration_file.name}...")
            sql = migration_file.read_text(encoding="utf-8")
            try:
                cursor.execute(sql)
                conn.commit()
                print(f"[OK] {migration_file.name}")
            except Exception as e:
                conn.rollback()
                print(f"[FAIL] {migration_file.name}: {e}")
                raise

        cursor.close()
        conn.close()
        print("\n[OK] All migrations completed.")

    except Exception as e:
        print(f"[ERROR] DB migration error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_migrations()
