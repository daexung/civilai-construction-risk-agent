"""
equipment_cost/tools.py 코어/셸 분리 회귀 검증.
변경 전 기대값(EXPECTED)과 변경 후 실제 출력을 한 글자씩 비교한다.

실행:
  python _regression_check.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import patch, MagicMock

PASS = []
FAIL = []


def check(name, actual, expected):
    if actual == expected:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ {name}")
        for i, (a, e) in enumerate(zip(actual, expected)):
            if a != e:
                ctx = slice(max(0, i - 30), i + 30)
                print(f"     첫 불일치 위치 {i}: 실제={a!r} 기대={e!r}")
                print(f"     실제 주변: {actual[ctx]!r}")
                print(f"     기대 주변: {expected[ctx]!r}")
                break
        if len(actual) != len(expected):
            print(f"     길이 차이: 실제={len(actual)} 기대={len(expected)}")


# ════════════════════════════════════════════════════════════
# [1] calculate_standby_cost — DB 불필요, 직접 호출
# ════════════════════════════════════════════════════════════
print("\n[1] calculate_standby_cost")
from tools import calculate_standby_cost

# 케이스 A: 일반 (50% 대기요율, 3일)
# 원본: standby_day_rate = int(1530000 * 0.5) = 765000
#        total = int(765000 * 3) = 2295000
check(
    "standby_A",
    calculate_standby_cost.invoke({"daily_rental_rate": 1530000, "standby_rate": 0.5, "delay_days": 3.0}),
    (
        "  1일 임대단가: 1,530,000원\n"
        "  대기요율: 50%\n"
        "  1일 대기단가: 765,000원\n"
        "  지연일수: 3.0일\n"
        "  대기 추가 비용: 765,000원 × 3.0일 = 2,295,000원"
    ),
)

# 케이스 B: 단수 처리 확인 (대기요율 30%, 5일)
# standby_day_rate = int(990000 * 0.3) = 297000
# total = int(297000 * 5) = 1485000
check(
    "standby_B",
    calculate_standby_cost.invoke({"daily_rental_rate": 990000, "standby_rate": 0.3, "delay_days": 5.0}),
    (
        "  1일 임대단가: 990,000원\n"
        "  대기요율: 30%\n"
        "  1일 대기단가: 297,000원\n"
        "  지연일수: 5.0일\n"
        "  대기 추가 비용: 297,000원 × 5.0일 = 1,485,000원"
    ),
)

# 케이스 C: delay_days가 float 표기로 나오는지 확인 (소수점)
# standby_day_rate = int(500000 * 0.5) = 250000
# total = int(250000 * 2.5) = 625000
check(
    "standby_C_float_days",
    calculate_standby_cost.invoke({"daily_rental_rate": 500000, "standby_rate": 0.5, "delay_days": 2.5}),
    (
        "  1일 임대단가: 500,000원\n"
        "  대기요율: 50%\n"
        "  1일 대기단가: 250,000원\n"
        "  지연일수: 2.5일\n"
        "  대기 추가 비용: 250,000원 × 2.5일 = 625,000원"
    ),
)


# ════════════════════════════════════════════════════════════
# [2] get_equipment_by_work_type — DB mock
# ════════════════════════════════════════════════════════════
print("\n[2] get_equipment_by_work_type")
from tools import get_equipment_by_work_type

def _patch_conn(fetchall_result):
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = fetchall_result
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur
    return mock_conn

# 미발견
with patch("tools._get_pg_connection", return_value=_patch_conn([])):
    result = get_equipment_by_work_type.invoke({"work_type": "없는공종"})
check(
    "work_type_not_found",
    result,
    (
        "'없는공종' 공종을 DB에서 찾을 수 없습니다.\n"
        "지원 공종: 철골 세우기, 콘크리트 타설, 방수공사\n"
        "장비명을 직접 입력하려면 get_equipment_rental_rate를 사용하세요."
    ),
)

# 발견 — 2행: 주요(표준) + 조건부(비표준)
rows_wt = [
    ('주요',  '크레인(타이어)', '50ton',  1530000, 0.5, 1, '2026'),
    ('조건부', '고소작업차',    '17m',     330000, 0.5, 0, '2026'),
]
with patch("tools._get_pg_connection", return_value=_patch_conn(rows_wt)):
    result = get_equipment_by_work_type.invoke({"work_type": "철골 세우기"})
check(
    "work_type_found",
    result,
    (
        "[철골 세우기] 공종 투입 장비 목록 (2026 기준):\n"
        "  [주요] 크레인(타이어) / 50ton ★표준 — 1일: 1,530,000원, 대기요율: 50%\n"
        "  [조건부] 고소작업차 / 17m — 1일: 330,000원, 대기요율: 50%"
    ),
)


# ════════════════════════════════════════════════════════════
# [3] get_equipment_rental_rate — DB mock
# ════════════════════════════════════════════════════════════
print("\n[3] get_equipment_rental_rate")
from tools import get_equipment_rental_rate

# 미발견
with patch("tools._get_pg_connection", return_value=_patch_conn([])):
    result = get_equipment_rental_rate.invoke({"equipment_type": "없는장비"})
check("rental_not_found", result, "DB에 없는 장비입니다: 없는장비")

# 발견 — 2행: 표준 + 비표준
rows_er = [
    ('크레인(타이어)', '50ton', 1530000, 0.5, 1, '2026'),
    ('크레인(타이어)', '25ton',  990000, 0.5, 0, '2026'),
]
with patch("tools._get_pg_connection", return_value=_patch_conn(rows_er)):
    result = get_equipment_rental_rate.invoke({"equipment_type": "크레인(타이어)"})
check(
    "rental_found",
    result,
    (
        "[크레인(타이어) / 50ton ★표준] 1일 임대단가: 1,530,000원, 대기요율: 50% (2026 기준)\n"
        "[크레인(타이어) / 25ton] 1일 임대단가: 990,000원, 대기요율: 50% (2026 기준)"
    ),
)


# ════════════════════════════════════════════════════════════
# [4] get_equipment_cost_range — DB mock
# ════════════════════════════════════════════════════════════
print("\n[4] get_equipment_cost_range")
from tools import get_equipment_cost_range

# 미발견
with patch("tools._get_pg_connection", return_value=_patch_conn([])):
    result = get_equipment_cost_range.invoke({"equipment_type": "없는장비", "delay_days": 3.0})
check("range_not_found", result, "DB에 없는 장비입니다: 없는장비")

# 발견 — 3행: 표준 있는 경우
# standby_rate = rows[0][3] = 0.5 (최소단가 행 기준)
# calc = int(rate * 0.5 * 3.0)
rows_cr = [
    ('크레인(타이어)', '25ton',  990000, 0.5, 0),   # min (is_standard=0)
    ('크레인(타이어)', '50ton', 1530000, 0.5, 1),   # standard
    ('크레인(타이어)', '80ton', 2200000, 0.5, 0),   # max
]
# standby_rate = 0.5  (rows[0][3])
# std_row = rows[1] (is_standard=1)  → std_note = '(DB 표준 규격)'
# min_row = rows[0], max_row = rows[2]
sr = ('크레인(타이어)', '50ton', 1530000, 0.5, 1)
mr = ('크레인(타이어)', '25ton',  990000, 0.5, 0)
xr = ('크레인(타이어)', '80ton', 2200000, 0.5, 0)
calc = lambda rate: int(rate * 0.5 * 3.0)

with patch("tools._get_pg_connection", return_value=_patch_conn(rows_cr)):
    result = get_equipment_cost_range.invoke({"equipment_type": "크레인(타이어)", "delay_days": 3.0})
check(
    "range_found_with_standard",
    result,
    "\n".join([
        f"[크레인(타이어)] 규격별 대기 비용 (3.0일, 대기요율 50%)",
        f"",
        f"  ★ 표준 규격 (DB 표준 규격)",
        f"    50ton — 1,530,000원/일 × 0.5 × 3.0일 = {calc(1530000):,}원",
        f"",
        f"  ▼ 최소 규격",
        f"    25ton — 990,000원/일 × 0.5 × 3.0일 = {calc(990000):,}원",
        f"",
        f"  ▲ 최대 규격",
        f"    80ton — 2,200,000원/일 × 0.5 × 3.0일 = {calc(2200000):,}원",
        f"",
        f"  → 비용 범위: {calc(990000):,}원 ~ {calc(2200000):,}원",
        f"  → 대표값(표준 규격): {calc(1530000):,}원",
    ]),
)

# 발견 — 표준 없는 경우 (중간값 자동 선택)
rows_no_std = [
    ('크레인(타이어)', '25ton',  990000, 0.5, 0),
    ('크레인(타이어)', '50ton', 1530000, 0.5, 0),   # 중간값 → std
    ('크레인(타이어)', '80ton', 2200000, 0.5, 0),
]
# std_row = rows[3//2] = rows[1]
with patch("tools._get_pg_connection", return_value=_patch_conn(rows_no_std)):
    result = get_equipment_cost_range.invoke({"equipment_type": "크레인(타이어)", "delay_days": 3.0})
check(
    "range_found_no_standard",
    result,
    "\n".join([
        f"[크레인(타이어)] 규격별 대기 비용 (3.0일, 대기요율 50%)",
        f"",
        f"  ★ 표준 규격 (중간값 자동 선택)",
        f"    50ton — 1,530,000원/일 × 0.5 × 3.0일 = {calc(1530000):,}원",
        f"",
        f"  ▼ 최소 규격",
        f"    25ton — 990,000원/일 × 0.5 × 3.0일 = {calc(990000):,}원",
        f"",
        f"  ▲ 최대 규격",
        f"    80ton — 2,200,000원/일 × 0.5 × 3.0일 = {calc(2200000):,}원",
        f"",
        f"  → 비용 범위: {calc(990000):,}원 ~ {calc(2200000):,}원",
        f"  → 대표값(표준 규격): {calc(1530000):,}원",
    ]),
)


# ════════════════════════════════════════════════════════════
# 결과 요약
# ════════════════════════════════════════════════════════════
print(f"\n{'='*55}")
print(f"결과: {len(PASS)}/{len(PASS)+len(FAIL)} 통과")
if FAIL:
    print(f"실패 항목: {FAIL}")
    sys.exit(1)
else:
    print("전체 통과 — 문자열 출력 변경 없음 ✅")
    sys.exit(0)
