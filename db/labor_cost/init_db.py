"""
labor_cost PostgreSQL DB 초기화 스크립트
- data/raw/labor_cost/labor_cost_unit_price.csv 를 읽어서 labor_cost 스키마에 테이블 생성 및 적재
- CSV 헤더에서 연도 컬럼을 자동으로 읽어서 적재 (내용 교체만 하면 됨, 파일명은 고정)
- 실행: python db/labor_cost/init_db.py
- 필요 환경변수(.env): DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""
import csv
import os

import psycopg2
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILENAME = 'labor_cost_unit_price_2026.csv'
CSV_PATH = os.path.join(BASE_DIR, '..', '..', 'data', 'raw', 'labor_cost', CSV_FILENAME)

load_dotenv()

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'dbname': os.getenv('DB_NAME', 'construction_risk'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', ''),
}


def to_int(val):
    v = val.strip()
    return int(v) if v and v != '-' else None


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def init_db():
    if not os.path.exists(CSV_PATH):
        print(f'ERROR: CSV file not found at {CSV_PATH}')
        return

    print(f'CSV: {CSV_PATH}')

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute('CREATE SCHEMA IF NOT EXISTS labor_cost')
    cursor.execute('DROP TABLE IF EXISTS labor_cost.labor_cost')
    cursor.execute('''
        CREATE TABLE labor_cost.labor_cost (
            job_code  TEXT,
            job_type  TEXT NOT NULL,
            year      TEXT,
            price     INTEGER,
            PRIMARY KEY (job_code, year)
        )
    ''')

    rows = []
    with open(CSV_PATH, encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f)
        # 헤더에서 연도 컬럼 자동 추출 (첫 번째 컬럼 제외)
        price_cols = reader.fieldnames[1:]  # ['2025.2/2', '2026.1/2', ...]

        for row in reader:
            vals = list(row.values())
            raw = vals[0].strip()
            code, name = raw.split('-', 1) if '-' in raw else ('', raw)

            # 연도 컬럼마다 한 행씩 추가
            for i, year in enumerate(price_cols):
                price = to_int(vals[i + 1])
                rows.append((code, name, year, price))

    cursor.executemany(
        'INSERT INTO labor_cost.labor_cost (job_code, job_type, year, price) VALUES (%s, %s, %s, %s)',
        rows
    )
    conn.commit()
    cursor.close()
    conn.close()
    print(f'Done: {len(rows)} rows inserted -> {DB_CONFIG["dbname"]}.labor_cost.labor_cost')


if __name__ == '__main__':
    init_db()