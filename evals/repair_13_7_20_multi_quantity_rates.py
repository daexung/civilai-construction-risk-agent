"""Connect the printed 13-7-20 work rows to their distinct source quantities."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-7-20.json"


def main():
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    inputs = draft["inputs"]
    assert not any(item["name"] == "tech_management_days" for item in inputs)
    inputs.append({
        "name": "tech_management_days", "type": "positive_rational",
        "allowed_values": "0보다 큰 수", "unit": "일", "required": True,
        "ask": "기술관리(설치공사 기간중) 일수는 며칠입니까?",
        "source": "PDF 832쪽 13-7-20 표 기술관리 행 (인/일)",
    })
    params = draft["quantity_model"]["params"]
    params["quantity_input"] = "tech_management_days"
    params["unit_rate_table"] = {
        "table": "p888-t1", "row_input": "기술관리", "column_input": None,
        "row_by_trade": {"기계기사": "기술관리"}, "trades": ["기계기사"],
        "basis_by_row": {"기술관리": "인/일"},
    }
    params["additional_unit_rates"] = [
        {"table": "p888-t1", "row_by_trade": {"특별인부": "표면손질"}, "column": "특별인부",
         "trades": ["특별인부"], "quantity_input": "surface_area", "basis": "인/㎡"},
        {"table": "p888-t1", "row_by_trade": {"플랜트기계설치공": "가조립및해체"}, "column": "플랜트기계설치공",
         "trades": ["플랜트기계설치공"], "quantity_input": "quantity", "basis": "인/ton"},
        {"table": "p888-t1", "row_by_trade": {"특별인부": "조립설치_특별인부_가조립"}, "column": "특별인부",
         "trades": ["특별인부"], "quantity_input": "quantity", "basis": "인/ton"},
        {"table": "p888-t1", "row_by_trade": {"플랜트기계설치공": "조립설치_플랜트기계설치공"}, "column": "플랜트기계설치공",
         "trades": ["플랜트기계설치공"], "quantity_input": "quantity", "basis": "인/ton"},
        {"table": "p888-t1", "row_by_trade": {"비계공": "조립설치_비계공"}, "column": "비계공",
         "trades": ["비계공"], "quantity_input": "quantity", "basis": "인/ton"},
        {"table": "p888-t1", "row_by_trade": {"특별인부": "조립설치_특별인부"}, "column": "특별인부",
         "trades": ["특별인부"], "quantity_input": "quantity", "basis": "인/ton"},
    ]
    params["input_rate_adjustments"] = [{
        "operation": "add_source_percent", "name": "검사 및 교정",
        "percent": "10", "kinds": ["labor"], "exclude_trades": ["기계기사"],
        "cite": {"table_id": "p888-t1", "row": "검사및교정", "column": "수량",
                 "value": "기술관리를 제외한 본 품의 10%"},
    }]
    params["note_adjustments"] = []
    draft["quantity_model"]["steps"] = [
        "기술관리 일수에는 기술관리(인/일) 품을 적용한다.",
        "표면손질 면적에는 특별인부(인/㎡) 품을 적용한다.",
        "가조립·해체 및 조립·설치 중량에는 각 원문 행의 인/ton 품을 적용한다.",
        "검사 및 교정은 기술관리를 제외한 전공량의 10%를 더한다.",
        "포장해체, 소운반, Foundation chipping, marking, centering, 전기 배선공사 및 현장가공 품은 이 표에서 별도 계상 대상이다.",
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"restored six exact secondary work-row routes and source 10% adjustment: {SPEC.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
