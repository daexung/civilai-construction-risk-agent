"""
material_price_tool.py / quantity_calculator.py 코어/셸 분리 회귀 검증.
변경 전 기대값(EXPECTED)과 변경 후 실제 출력을 한 글자씩 비교한다.

실행:
  python _regression_check.py
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from unittest.mock import MagicMock, patch

PASS = []
FAIL = []


def check(name, actual, expected):
    if actual == expected:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ {name}")
        # 첫 번째 다른 지점만 표시
        for i, (a, e) in enumerate(zip(actual, expected)):
            if a != e:
                print(f"     첫 불일치 위치 {i}: 실제={a!r}, 기대={e!r}")
                ctx = slice(max(0, i-20), i+20)
                print(f"     ...{actual[ctx]}...")
                break
        if len(actual) != len(expected):
            print(f"     길이 불일치: 실제={len(actual)}, 기대={len(expected)}")


# ══════════════════════════════════════════════════════════════════
# [1] calculate_quantity_change_cost  (DB 불필요 — 순수 계산)
# ══════════════════════════════════════════════════════════════════
print("\n[1] calculate_quantity_change_cost")
from quantity_calculator import calculate_quantity_change_cost

# 케이스 A: 계약단가 없음
args_A = dict(
    material_name="H파일", quantity=500.0, unit="ton",
    current_unit_price=850000.0,
)
expected_A = json.dumps({
    "status": "success",
    "자재명": "H파일",
    "추가물량": 500.0,
    "단위": "ton",
    "현재단가_원": 850000.0,
    "현재단가_기준": {
        "추가자재비_원": 425000000,
        "부가세_원": 42500000,
        "합계_원": 467500000,
        "합계_만원": 46750.0,
    },
    "material_cost_krw": 425000000,
    "price_diff_reference_krw": 0,
    "settlement_basis": "current_market_price",
    "basis": "현재단가 기준: 850,000원/ton × 500.0ton = 425,000,000원 | [중요] cost_items[].amount 및 total_cost에는 반드시 이 값(425,000,000)을 사용한다",
    "주의사항": [
        "ℹ️ 계약단가가 입력되지 않았습니다. Project Context DB에서 계약단가를 확인 후 재계산하세요.",
        "ℹ️ 부가세(10%)는 별도로 계산되었습니다.",
    ],
    "계약유형": "고정단가",
}, ensure_ascii=False, indent=2)
check("qty_A_no_contract", calculate_quantity_change_cost.invoke(args_A), expected_A)

# 케이스 B: 계약단가 있음, 고정단가
args_B = dict(
    material_name="철근", quantity=200.0, unit="ton",
    current_unit_price=900000.0, contract_unit_price=800000.0,
    contract_type="고정단가",
)
price_diff_B = 900000.0 - 800000.0          # 100000
cost_curr_B  = 200.0 * 900000.0             # 180000000
vat_curr_B   = cost_curr_B * 0.1            # 18000000
total_curr_B = cost_curr_B + vat_curr_B     # 198000000
cost_cont_B  = 200.0 * 800000.0             # 160000000
vat_cont_B   = cost_cont_B * 0.1            # 16000000
total_cont_B = cost_cont_B + vat_cont_B     # 176000000
cost_diff_B  = total_curr_B - total_cont_B  # 22000000
diff_ratio_B = (price_diff_B / 800000.0) * 100  # 12.5
expected_B = json.dumps({
    "status": "success",
    "자재명": "철근",
    "추가물량": 200.0,
    "단위": "ton",
    "현재단가_원": 900000.0,
    "현재단가_기준": {
        "추가자재비_원": round(cost_curr_B),
        "부가세_원": round(vat_curr_B),
        "합계_원": round(total_curr_B),
        "합계_만원": round(total_curr_B / 10000, 1),
    },
    "계약단가_원": 800000.0,
    "계약단가_기준": {
        "추가자재비_원": round(cost_cont_B),
        "부가세_원": round(vat_cont_B),
        "합계_원": round(total_cont_B),
        "합계_만원": round(total_cont_B / 10000, 1),
    },
    "단가차액분석": {
        "단가차이_원": round(price_diff_B),
        "비용차이_원": round(cost_diff_B),
        "비용차이_만원": round(cost_diff_B / 10000, 1),
        "단가변동률_pct": round(diff_ratio_B, 2),
        "현재단가가_더_높음": True,
    },
    "material_cost_krw": round(cost_cont_B),
    "price_diff_reference_krw": round(cost_curr_B - cost_cont_B),
    "settlement_basis": "fixed_contract_price",
    "basis": (
        f"고정단가 계약: 800,000원/ton × 200.0ton"
        f" = {round(cost_cont_B):,}원"
        f" | [중요] cost_items[].amount 및 total_cost에는 반드시 이 값"
        f"({round(cost_cont_B):,})을 사용하고"
        f" price_diff_reference_krw({round(cost_curr_B - cost_cont_B):,})는"
        f" assumptions에만 기록한다"
    ),
    "주의사항": ["ℹ️ 부가세(10%)는 별도로 계산되었습니다."],
    "계약유형": "고정단가",
}, ensure_ascii=False, indent=2)
check("qty_B_fixed_contract", calculate_quantity_change_cost.invoke(args_B), expected_B)

# 케이스 C: 시황성 자재, 시가연동, vat_included=True
args_C = dict(
    material_name="시멘트", quantity=100.0, unit="포",
    current_unit_price=10000.0, contract_unit_price=9000.0,
    is_market_sensitive=True, contract_type="시가연동", vat_included=True,
)
cost_curr_C  = 100.0 * 10000.0   # 1000000
vat_curr_C   = 0                  # vat_included=True
total_curr_C = cost_curr_C
cost_cont_C  = 100.0 * 9000.0    # 900000
vat_cont_C   = 0
total_cont_C = cost_cont_C
expected_C = json.dumps({
    "status": "success",
    "자재명": "시멘트",
    "추가물량": 100.0,
    "단위": "포",
    "현재단가_원": 10000.0,
    "현재단가_기준": {
        "추가자재비_원": round(cost_curr_C),
        "부가세_원": 0,
        "합계_원": round(total_curr_C),
        "합계_만원": round(total_curr_C / 10000, 1),
    },
    "계약단가_원": 9000.0,
    "계약단가_기준": {
        "추가자재비_원": round(cost_cont_C),
        "부가세_원": 0,
        "합계_원": round(total_cont_C),
        "합계_만원": round(total_cont_C / 10000, 1),
    },
    "단가차액분석": {
        "단가차이_원": round(10000.0 - 9000.0),
        "비용차이_원": round(total_curr_C - total_cont_C),
        "비용차이_만원": round((total_curr_C - total_cont_C) / 10000, 1),
        "단가변동률_pct": round((1000.0 / 9000.0) * 100, 2),
        "현재단가가_더_높음": True,
    },
    "material_cost_krw": round(cost_curr_C),
    "price_diff_reference_krw": round(cost_curr_C - cost_cont_C),
    "settlement_basis": "current_market_price",
    "basis": (
        "시가연동 계약: 10,000원/포 × 100.0포"
        f" = {round(cost_curr_C):,}원"
        " | [중요] cost_items[].amount 및 total_cost에는 반드시 이 값"
        f"({round(cost_curr_C):,})을 사용한다"
    ),
    "주의사항": [
        "⚠️ 이 자재는 시황성 자재입니다. 공시 이후 실제 구매 시점에 단가가 달라질 수 있습니다.",
        "📋 계약 유형이 '시가연동'입니다. 현재단가 기준으로 청구 가능한지 계약 조건을 확인하세요.",
    ],
    "계약유형": "시가연동",
}, ensure_ascii=False, indent=2)
check("qty_C_market_sensitive", calculate_quantity_change_cost.invoke(args_C), expected_C)


# ══════════════════════════════════════════════════════════════════
# [2] calculate_total_material_cost  (DB 불필요 — 순수 계산)
# ══════════════════════════════════════════════════════════════════
print("\n[2] calculate_total_material_cost")
from quantity_calculator import calculate_total_material_cost

# 빈 배열 → indent 없는 에러
check(
    "total_empty",
    calculate_total_material_cost.invoke({"items": []}),
    json.dumps({"status": "error", "message": "items가 비어있습니다."}, ensure_ascii=False),
)

# 정상 2개 항목
items_D = [
    {"자재명": "H파일", "추가비용_원": 50000000.0, "단가기준": "계약단가"},
    {"자재명": "철근",  "추가비용_원": 30000000.0, "단가기준": "현재단가"},
]
expected_D = json.dumps({
    "status": "success",
    "항목별_비용": [
        {"자재명": "H파일", "추가비용_원": 50000000, "추가비용_만원": 5000.0, "단가기준": "계약단가"},
        {"자재명": "철근",  "추가비용_원": 30000000, "추가비용_만원": 3000.0, "단가기준": "현재단가"},
    ],
    "총_추가자재비_원": 80000000,
    "총_추가자재비_만원": 8000.0,
    "총_추가자재비_억원": 0.8,
}, ensure_ascii=False, indent=2)
check("total_normal", calculate_total_material_cost.invoke({"items": items_D}), expected_D)


# ══════════════════════════════════════════════════════════════════
# [3] search_material_price  (DB mock)
# ══════════════════════════════════════════════════════════════════
print("\n[3] search_material_price")
from material_price_tool import search_material_price

# 미발견 케이스
def _patch_fuzzy(return_val):
    return patch("material_price_tool._fuzzy_search", return_value=return_val)

with _patch_fuzzy([]):
    result = search_material_price.invoke({"material_name": "없는자재XYZ"})
check(
    "mat_not_found",
    result,
    json.dumps({
        "status": "not_found",
        "query": "없는자재XYZ",
        "message": "'없는자재XYZ'에 해당하는 자재를 찾을 수 없습니다.",
    }, ensure_ascii=False, indent=2),
)

# 성공 케이스 (1개)
mock_row = {
    "자재명": "H파일",
    "단위": "ton",
    "현재단가": 850000,
    "자재분류": "강재",
    "품목분류": "파일",
    "공시일자": "2026-01-01",
    "시황성자재": True,
    "부가세여부": "부가가치세별도",
}
with _patch_fuzzy([mock_row]):
    result = search_material_price.invoke({"material_name": "H파일"})
check(
    "mat_found",
    result,
    json.dumps({
        "status": "success",
        "query": "H파일",
        "result_count": 1,
        "results": [{
            "자재명": "H파일",
            "단위": "ton",
            "현재단가_원": 850000,
            "자재분류": "강재",
            "품목분류": "파일",
            "공시일자": "2026-01-01",
            "시황성자재": True,
            "부가세여부": "부가가치세별도",
        }],
    }, ensure_ascii=False, indent=2),
)

# ConnectionError → indent 없는 에러
with patch("material_price_tool._fuzzy_search", side_effect=ConnectionError("DB 접속 실패")):
    result = search_material_price.invoke({"material_name": "H파일"})
check(
    "mat_conn_error",
    result,
    json.dumps({"status": "error", "message": "DB 접속 실패"}, ensure_ascii=False),
)

# 일반 Exception → indent 없는 에러
with patch("material_price_tool._fuzzy_search", side_effect=Exception("예상치 못한 오류")):
    result = search_material_price.invoke({"material_name": "H파일"})
check(
    "mat_generic_error",
    result,
    json.dumps({"status": "error", "message": "조회 중 오류: 예상치 못한 오류"}, ensure_ascii=False),
)


# ══════════════════════════════════════════════════════════════════
# [4] list_material_categories  (DB mock)
# ══════════════════════════════════════════════════════════════════
print("\n[4] list_material_categories")
from material_price_tool import list_material_categories

def _make_categories_conn():
    """cursor.fetchall / fetchone 순서를 맞춘 mock connection."""
    mock_cursor = MagicMock()

    # 1st fetchall: GROUP BY 결과
    cat_rows = [{"자재분류": "강재", "자재수": 10}, {"자재분류": "시멘트류", "자재수": 5}]
    # 2nd, 3rd fetchall: 각 분류별 샘플 (강재, 시멘트류)
    sample_강재    = [{"자재명": "H파일"}, {"자재명": "철근"}, {"자재명": "형강"}]
    sample_시멘트류 = [{"자재명": "시멘트"}, {"자재명": "혼화재"}]
    # fetchone: COUNT(*) 전체
    total_row = {"cnt": 15}

    mock_cursor.fetchall.side_effect = [cat_rows, sample_강재, sample_시멘트류]
    mock_cursor.fetchone.return_value = total_row

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn

with patch("material_price_tool._get_connection", return_value=_make_categories_conn()):
    result = list_material_categories.invoke({})

check(
    "categories_success",
    result,
    json.dumps({
        "status": "success",
        "total_materials": 15,
        "categories": {"강재": 10, "시멘트류": 5},
        "sample_materials": {
            "강재": ["H파일", "철근", "형강"],
            "시멘트류": ["시멘트", "혼화재"],
        },
    }, ensure_ascii=False, indent=2),
)

# ConnectionError
with patch("material_price_tool._get_connection", side_effect=ConnectionError("접속 실패")):
    result = list_material_categories.invoke({})
check(
    "categories_conn_error",
    result,
    json.dumps({"status": "error", "message": "접속 실패"}, ensure_ascii=False),
)


# ══════════════════════════════════════════════════════════════════
# 결과 요약
# ══════════════════════════════════════════════════════════════════
print(f"\n{'='*55}")
print(f"결과: {len(PASS)}/{len(PASS)+len(FAIL)} 통과")
if FAIL:
    print(f"실패 항목: {FAIL}")
    sys.exit(1)
else:
    print("전체 통과 — 문자열 출력 변경 없음 ✅")
    sys.exit(0)
