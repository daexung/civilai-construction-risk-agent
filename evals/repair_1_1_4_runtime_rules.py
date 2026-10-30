"""Complete the already source-backed 1-1-4 daily crew and conditional cost routes."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/1-1-4.json"


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    params = spec["quantity_model"]["params"]
    coefficient = params["coefficients"][0]
    coefficient["skip_values"] = ["일반"]
    coefficient["interpretation"] = "signed_percentage_change"
    params["output_adjustments"] = [{
        "when": {"lift_used": True}, "operation": "multiply_output", "value": "1.26",
        "cite": {"chunk_id": "p703-t0",
                 "quote": "자체 추진 고소작업대(시저형)시공의 경우 시공량의 26%를 가산한다."},
    }]
    params["crew"]["rate_codes"]["배관공"] = "1039"
    params["crew"]["column_selector_by_trade"] = {"배관공": "배관공", "보통인부": "보통인부"}
    spec["blocked"] = []
    spec["crew_rules"] = []
    note = {"chunk_id": "p703-x21"}
    spec["cost_rules"] = [
        {"name": "공구손료 및 경장비", "category": "경비", "base": "labor_subtotal", "rate": "0.02",
         "when": {"lift_used": False}, "cite": {**note,
         "quote": "공구손료 및 경장비(절단기, 자체 추진 고소작업대(시저형) 등)의 기계경비는 본 품의 2%로 계상하고,"}},
        {"name": "공구손료 및 경장비", "category": "경비", "base": "labor_subtotal", "rate": "0.10",
         "when": {"lift_used": True}, "cite": {**note,
         "quote": "고소작업대(시저형)시공의 경우 10%로 계상한다."}},
    ]
    package["calc_type_reason"] = "p703-t0에 관규격별 작업조와 일일 시공량이 있고, 비고의 위치요율·고소작업대 가산을 일당 출력에 적용한다. 경비율은 사용 여부에 따른 원문 조건으로 연결한다."
    package["open_questions"] = []
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("repaired 1-1-4 rules without changing shared runtime")


if __name__ == "__main__":
    main()
