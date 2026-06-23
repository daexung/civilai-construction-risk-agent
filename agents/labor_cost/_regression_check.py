"""
tools.py 코어/셸 분리 회귀 검증.
변경 전 기대값(EXPECTED)과 변경 후 실제 출력을 한 글자씩 비교한다.

실행:
  python _regression_check.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import math
from unittest.mock import MagicMock, patch

# ── 변경 전 기대값 (원본 포맷 문자열을 그대로 손으로 평가한 값) ────────────

EXPECTED = {
    # calculate_workers: f'총 투입 인부수: {quantity} × {unit_labor}인/단위 = {raw:.2f} → 올림 처리 → {total_workers}인 (man-day)'
    "workers_A": "총 투입 인부수: 200.0 × 0.33인/단위 = 66.00 → 올림 처리 → 66인 (man-day)",
    "workers_B": "총 투입 인부수: 150.0 × 0.06인/단위 = 9.00 → 올림 처리 → 9인 (man-day)",
    "workers_C": "총 투입 인부수: 130.0 × 0.33인/단위 = 42.90 → 올림 처리 → 43인 (man-day)",

    # calculate_labor_cost: f'총 인건비: {labor_price:,}원 × {workers}명 = {total:,}원'
    # workers: float 타입 힌트 → @tool이 정수 입력을 float으로 변환 (450→450.0, 1→1.0)
    "cost_A": "총 인건비: 273,540원 × 450.0명 = 123,093,000원",
    "cost_B": "총 인건비: 200,000원 × 10.5명 = 2,100,000원",
    "cost_C": "총 인건비: 150,000원 × 1.0명 = 150,000원",

    # get_labor_price (found): f'노임단가 DB 조회 결과: {res[0]}: {res[1]:,}원 ({res[2]} 기준)'
    "labor_price_found": "노임단가 DB 조회 결과: 콘크리트공: 273,540원 (2026 기준)",

    # get_labor_price (not found): f'DB에 없는 직종입니다: "{job_type}". 직종명을 다시 확인하세요.'
    "labor_price_not_found": 'DB에 없는 직종입니다: "없는직종XYZ". 직종명을 다시 확인하세요.',

    # search_standard_spec (not found)
    "spec_not_found": "표준품셈에서 관련 내용을 찾지 못했습니다.",

    # search_standard_spec (low similarity)
    "spec_low_sim": "[주의: 검색 유사도가 낮습니다(거리=0.55). 아래 내용이 질문과 다를 수 있습니다.]\n\n저유사도 청크",

    # search_standard_spec (normal, 2 chunks)
    "spec_normal": "청크A\n\n청크B",
}

PASS = []
FAIL = []


def check(name, actual, expected):
    if actual == expected:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ {name}")
        print(f"     기대: {expected!r}")
        print(f"     실제: {actual!r}")


# ── 1. calculate_workers (DB 불필요 — 직접 호출) ─────────────────────────────

from tools import calculate_workers

print("\n[1] calculate_workers")
check("workers_A", calculate_workers.invoke({"quantity": 200.0, "unit_labor": 0.33}), EXPECTED["workers_A"])
check("workers_B", calculate_workers.invoke({"quantity": 150.0, "unit_labor": 0.06}), EXPECTED["workers_B"])
check("workers_C", calculate_workers.invoke({"quantity": 130.0, "unit_labor": 0.33}), EXPECTED["workers_C"])


# ── 2. calculate_labor_cost (DB 불필요 — 직접 호출) ──────────────────────────

from tools import calculate_labor_cost

print("\n[2] calculate_labor_cost")
check("cost_A", calculate_labor_cost.invoke({"labor_price": 273540, "workers": 450}),   EXPECTED["cost_A"])
check("cost_B", calculate_labor_cost.invoke({"labor_price": 200000, "workers": 10.5}),  EXPECTED["cost_B"])
check("cost_C", calculate_labor_cost.invoke({"labor_price": 150000, "workers": 1}),     EXPECTED["cost_C"])


# ── 3. get_labor_price (DB mock) ─────────────────────────────────────────────

from tools import get_labor_price

def _make_mock_conn(fetchone_result):
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = fetchone_result
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn

print("\n[3] get_labor_price")

# 발견 케이스: res = ("콘크리트공", 273540, "2026")
with patch("tools._get_pg_connection", return_value=_make_mock_conn(("콘크리트공", 273540, "2026"))):
    result = get_labor_price.invoke({"job_type": "콘크리트공"})
check("labor_price_found", result, EXPECTED["labor_price_found"])

# 미발견 케이스: fetchone → None (두 번 모두)
mock_cur_nf = MagicMock()
mock_cur_nf.fetchone.return_value = None
mock_conn_nf = MagicMock()
mock_conn_nf.cursor.return_value = mock_cur_nf
with patch("tools._get_pg_connection", return_value=mock_conn_nf):
    result = get_labor_price.invoke({"job_type": "없는직종XYZ"})
check("labor_price_not_found", result, EXPECTED["labor_price_not_found"])


# ── 4. search_standard_spec (embedder + DB mock) ──────────────────────────────

from tools import search_standard_spec

def _make_spec_conn(rows):
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = rows
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn

print("\n[4] search_standard_spec")

with patch("tools.embedder") as mock_emb:
    mock_emb.embed_query.return_value = [0.0] * 1536

    # 결과 없음
    with patch("tools._get_pg_connection", return_value=_make_spec_conn([])):
        result = search_standard_spec.invoke({"query": "없는공종"})
    check("spec_not_found", result, EXPECTED["spec_not_found"])

    # 저유사도 (임계값 초과): distance=0.55 > 0.45
    with patch("tools._get_pg_connection", return_value=_make_spec_conn([("저유사도 청크", 0.55)])):
        result = search_standard_spec.invoke({"query": "모호한공종"})
    check("spec_low_sim", result, EXPECTED["spec_low_sim"])

    # 정상 (2개 채택)
    with patch("tools._get_pg_connection", return_value=_make_spec_conn([("청크A", 0.30), ("청크B", 0.40)])):
        result = search_standard_spec.invoke({"query": "레디믹스트콘크리트 타설"})
    check("spec_normal", result, EXPECTED["spec_normal"])


# ── 결과 요약 ────────────────────────────────────────────────────────────────

print(f"\n{'='*50}")
print(f"결과: {len(PASS)}/{len(PASS)+len(FAIL)} 통과")
if FAIL:
    print(f"실패: {FAIL}")
    sys.exit(1)
else:
    print("전체 통과 — 문자열 출력 변경 없음 ✅")
    sys.exit(0)
