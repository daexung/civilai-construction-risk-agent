"""
자재 단가 자동 갱신 Airflow DAG
- 스케줄: 매월 1일 오전 6시
- 흐름: 조달청 API 수집 → 전처리 → DB 갱신

로컬 실행 방법:
    pip install apache-airflow
    export AIRFLOW_HOME=./airflow_home
    airflow db init
    airflow scheduler &
    airflow webserver &
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

# 프로젝트 루트를 sys.path에 추가
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ── 태스크 함수 ────────────────────────────────────────────────────

def task_fetch_materials(**context):
    """조달청 API에서 최신 자재 단가 수집."""
    from scripts.fetch_materials import fetch_all
    success = fetch_all()
    if not success:
        raise RuntimeError("일부 사업부문 수집 실패. 로그 확인 필요.")


def task_preprocess(**context):
    """수집된 CSV 전처리 및 병합."""
    from scripts.preprocess_materials import main as preprocess_main
    preprocess_main()


def task_init_db(**context):
    """전처리 결과를 SQLite DB에 반영."""
    from db.material_cost.init_db import init_db
    init_db()


# ── DAG 정의 ──────────────────────────────────────────────────────

default_args = {
    "owner": "material-agent",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "email_on_failure": False,
}

with DAG(
    dag_id="material_price_update",
    description="조달청 자재 단가 월간 자동 갱신",
    default_args=default_args,
    start_date=datetime(2026, 6, 1),
    schedule_interval="0 6 1 * *",   # 매월 1일 오전 6시
    catchup=False,
    tags=["material", "price", "monthly"],
) as dag:

    fetch = PythonOperator(
        task_id="fetch_materials_from_api",
        python_callable=task_fetch_materials,
    )

    preprocess = PythonOperator(
        task_id="preprocess_materials",
        python_callable=task_preprocess,
    )

    init_db = PythonOperator(
        task_id="init_sqlite_db",
        python_callable=task_init_db,
    )

    # 실행 순서: 수집 → 전처리 → DB 갱신
    fetch >> preprocess >> init_db
