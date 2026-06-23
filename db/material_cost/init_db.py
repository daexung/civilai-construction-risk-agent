"""
자재 단가 PostgreSQL DB 초기화 스크립트
- data/processed/materials_db.csv 를 읽어 PostgreSQL DB에 저장
- 실행 전 preprocess_materials.py 를 먼저 실행해야 합니다
- 로컬: .env의 DB_* 환경변수 사용
- AWS RDS: 동일한 환경변수를 RDS 엔드포인트로 교체
"""

import os
import psycopg2
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

BASE_DIR = Path(__file__).resolve().parent.parent.parent
CSV_PATH = BASE_DIR / "data" / "processed" / "materials_db.csv"

load_dotenv(BASE_DIR / ".env")

# ── DB 접속 정보 (.env에서 로드) ──────────────────────────────────
DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = os.getenv("DB_PORT", "5432")
DB_NAME     = os.getenv("DB_NAME", "construction_risk")
DB_USER     = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

DATABASE_URL = f"postgresql+psycopg2://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS material_prices (
    id          SERIAL PRIMARY KEY,
    자재명        TEXT    NOT NULL,
    단위          TEXT,
    현재단가       INTEGER NOT NULL,
    자재분류       TEXT,
    품목분류       TEXT,
    공시일자       TEXT,
    시황성자재      BOOLEAN DEFAULT FALSE,
    부가세여부      TEXT
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_material_name ON material_prices (자재명);
"""


def get_connection() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def init_db():
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"전처리 CSV가 없습니다. 먼저 scripts/preprocess_materials.py 를 실행하세요.\n경로: {CSV_PATH}"
        )

    print(f"CSV 로드 중: {CSV_PATH}")
    df = pd.read_csv(CSV_PATH, encoding="utf-8-sig")

    # 시황성자재 bool 변환
    if "시황성자재" in df.columns:
        df["시황성자재"] = df["시황성자재"].astype(bool)

    # 공시일자 문자열 변환
    if "공시일자" in df.columns:
        df["공시일자"] = df["공시일자"].astype(str)

    print(f"DB 접속 중: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    conn = get_connection()
    cursor = conn.cursor()

    # 테이블 생성
    cursor.execute(CREATE_TABLE_SQL)
    cursor.execute(CREATE_INDEX_SQL)

    # 기존 데이터 삭제 후 재삽입 (재실행 안전)
    cursor.execute("DELETE FROM material_prices")
    conn.commit()
    cursor.close()
    conn.close()

    # pandas → PostgreSQL 벌크 삽입 (SQLAlchemy 경유)
    engine = create_engine(DATABASE_URL)
    columns = ["자재명", "단위", "현재단가", "자재분류", "품목분류", "공시일자", "시황성자재", "부가세여부"]
    existing_cols = [c for c in columns if c in df.columns]
    df[existing_cols].to_sql("material_prices", engine, if_exists="append", index=False)

    # 저장 건수 확인
    with engine.connect() as con:
        count = con.execute(text("SELECT COUNT(*) FROM material_prices")).scalar()

    print(f"✅ DB 저장 완료: {count:,}개 자재")


if __name__ == "__main__":
    init_db()
