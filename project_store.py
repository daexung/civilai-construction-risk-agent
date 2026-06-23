"""
프로젝트 데이터 로더 - PostgreSQL 연동

PostgreSQL projects 테이블에서 프로젝트 정보를 조회.
fallback: sample_projects.json (DB 미사용 또는 레코드 없을 때)
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from weather_risk.models import WeatherRiskRequest, WorkType

KST = ZoneInfo("Asia/Seoul")

_DATA_PATH = Path(__file__).resolve().parent / "sample_projects.json"


def _load_from_db(project_id: str) -> dict | None:
    """PostgreSQL에서 프로젝트 조회. 없으면 None 반환."""
    try:
        import psycopg2
        from dotenv import load_dotenv

        PROJECT_ROOT = Path(__file__).resolve().parent
        load_dotenv(PROJECT_ROOT / ".env")

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "construction_risk_agent"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
            connect_timeout=5
        )
        cursor = conn.cursor()

        cursor.execute(
            "SELECT id, COALESCE(site_name, name), latitude, longitude, work_type "
            "FROM public.projects WHERE id = %s",
            (project_id,)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if not row or row[2] is None or row[3] is None or row[4] is None:
            print(f'[프로젝트 스토어] DB row 없음 또는 필수값 null (project_id={project_id!r})')
            return None

        print(f'[프로젝트 스토어] DB 조회 성공: project_id={project_id!r}  site_name={row[1]!r}  lat={row[2]}  lon={row[3]}')
        return {
            "project_id":           str(row[0]),
            "site_name":            str(row[1]),
            "latitude":             float(row[2]),
            "longitude":            float(row[3]),
            "work_type":            str(row[4]),
            "scheduled_start_time": "08:00",
            "scheduled_end_time":   "16:00",
        }
    except Exception as exc:
        print(f'[프로젝트 스토어] DB 연결/조회 예외: type={type(exc).__name__}  msg={exc}')
        return None


def _load_from_sample() -> dict:
    """sample_projects.json에서 프로젝트 조회 (fallback)."""
    return json.loads(_DATA_PATH.read_text(encoding="utf-8"))


def get_project(project_id: str, query_date: datetime | None = None) -> WeatherRiskRequest:
    """
    project_id로 프로젝트 정보를 조회해 WeatherRiskRequest로 반환.

    우선순위:
    1. PostgreSQL projects 테이블
    2. sample_projects.json (fallback)

    query_date: 분석 기준 날짜 (None이면 오늘). KST-aware datetime.
    """
    p = _load_from_db(project_id)

    if not p:
        print(f'[프로젝트 스토어] sample_projects.json fallback 사용 (project_id={project_id!r})')
        projects = _load_from_sample()
        if project_id not in projects:
            available = list(projects.keys())
            raise KeyError(f"project_id '{project_id}' not found. available: {available}")
        p = projects[project_id]

    base_date = (query_date or datetime.now(KST)).date()

    start_h, start_m = map(int, p["scheduled_start_time"].split(":"))
    end_h, end_m = map(int, p["scheduled_end_time"].split(":"))

    scheduled_start = datetime(base_date.year, base_date.month, base_date.day,
                               start_h, start_m, tzinfo=KST)
    scheduled_end = datetime(base_date.year, base_date.month, base_date.day,
                             end_h, end_m, tzinfo=KST)

    return WeatherRiskRequest(
        project_id=p["project_id"],
        site_name=p["site_name"],
        latitude=p["latitude"],
        longitude=p["longitude"],
        work_type=WorkType(p["work_type"]),
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        query_type="SHORT_TERM",
    )