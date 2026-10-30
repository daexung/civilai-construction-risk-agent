"""Restore the omitted 1-1-2 source table and connect its daily-crew calculation."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/1-1-2.json"

RATES = {
    "ø15": ("3", "1", "83"), "20": ("3", "1", "75"), "25": ("3", "1", "60"),
    "32": ("3", "1", "50"), "40": ("3", "1", "45"), "50": ("3", "1", "37"),
    "65": ("3", "1", "30"), "80": ("3", "1", "25"), "100": ("3", "1", "18"),
    "125": ("3", "1", "14"), "150": ("3", "1", "12"), "200": ("4", "1", "10"),
    "250": ("4", "1", "8.0"), "300": ("4", "1", "6.0"), "350": ("4", "1", "5.0"),
    "400": ("4", "1", "4.0"),
}


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    spec["source_pages"] = [645, 646]
    spec["work"] = "용접배관"
    spec["inputs"].extend([
        {"name": "pipe_size", "type": "enum", "allowed_values": list(RATES), "unit": "㎜",
         "required": True, "ask": "배관의 관규격(구경)은 몇 ㎜입니까?", "source": "PDF 645쪽 p701-t1 관규격(㎜)"},
        {"name": "quantity", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "m",
         "required": True, "ask": "배관 설치 물량은 몇 m입니까?", "source": "PDF 645쪽 p701-t1 시공량(m)"},
    ])
    spec["inputs"][0]["allowed_values"] = ["일반", "화장실배관", "기계실배관", "옥외배관(암거내)"]
    spec["inputs"][1]["ask"] = "자체 추진 고소작업대(시저형)를 사용합니까?"
    labor_table = {
        "id": "p701-t1", "role": "관규격별 작업조 인원 및 일일 시공량",
        "source": "PDF 645쪽 표 1-1-2 용접배관 (일당)", "unit": "인/작업조, m/일",
        "values": {size: {"배관공": crew, "보통인부": helper, "시공량(m)": output}
                   for size, (crew, helper, output) in RATES.items()},
        "cite": {"table_id": "p701-t1"},
    }
    location_table = {
        "id": "p702-t0", "role": "시공위치별 시공량 가감 요율",
        "source": "PDF 646쪽 표 1-1-2 비고", "unit": "%",
        "values": {"요율": {"화장실배관": "- 17%", "기계실배관": "- 23%", "옥외배관(암거내)": "+ 11%"}},
        "cite": {"table_id": "p702-t0"},
    }
    spec["tables"] = [labor_table, location_table]
    spec["quantity_model"] = {
        "name": "adjusted_daily_crew",
        "params": {
            "quantity_input": "quantity",
            "base_output": {"table": "p701-t1", "row_input": "pipe_size", "column": "시공량(m)"},
            "coefficients": [{"table": "p702-t0", "row": "요율", "input": "location",
                              "skip_values": ["일반"], "interpretation": "signed_percentage_change"}],
            "output_adjustments": [{"when": {"use_lift": True}, "operation": "multiply_output",
                                    "value": "1.26", "cite": {"chunk_id": "p702-x0",
                                    "quote": "자체 추진 고소작업대(시저형)시공의 경우 시공량의 26%를 가산한다."}}],
            "crew": {"table": "p701-t1", "row_input": "pipe_size", "column": "배관공",
                     "trades": ["배관공", "보통인부"],
                     "column_selector_by_trade": {"보통인부": "보통인부"},
                     "rate_codes": {"배관공": "1039", "보통인부": "1002"}},
        },
        "steps": [
            "p701-t1에서 관규격별 작업조 인원과 일일 시공량을 찾는다.",
            "고소작업대 사용 시 일일 시공량에 1.26을 곱하고, 시공 위치별 요율을 적용한다.",
            "작업일수 = 배관 물량 ÷ 조정된 일일 시공량으로 구한다.",
            "작업일수 × 직종별 작업조 인원으로 직종별 인·일을 계산한다.",
        ],
        "source": "PDF 645~646쪽 1-1-2 표, 비고 및 [주]",
        "rounding": "총 투입량은 정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용",
    }
    spec["cost_rules"] = [
        {"name": "공구손료 및 경장비", "category": "경비", "base": "labor_subtotal", "rate": "0.02",
         "when": {"use_lift": False}, "cite": {"chunk_id": "p702-x3",
         "quote": "공구손료 및 경장비(절단기, 자체 추진 고소작업대(시저형) 등)의 기계경비는 본 품의 2%로 계상하고,"}},
        {"name": "공구손료 및 경장비", "category": "경비", "base": "labor_subtotal", "rate": "0.10",
         "when": {"use_lift": True}, "cite": {"chunk_id": "p702-x3",
         "quote": "고소작업대(시저형)시공의 경우 10%로 계상한다."}},
    ]
    spec["blocked"] = []
    package["calc_type"] = "adjusted_daily_crew"
    package["calc_type_reason"] = "원문 p.645의 관규격별 작업조·일일 시공량과 p.646의 위치별 가감률 및 고소작업대 보정으로 일당 작업조 계산을 표현한다."
    package["open_questions"] = []
    package["questions"] = ["관규격(구경)은 몇 ㎜입니까?", "배관 설치 물량은 몇 m입니까?",
                            "시공 위치와 고소작업대 사용 여부를 알려주세요."]
    package["citations"] = []
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("updated", SPEC.relative_to(ROOT))


if __name__ == "__main__":
    main()
