"""Restore the Cooling Tower task/trade table and route its mixed source units."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-11-2.json"
pkg = json.loads(SPEC.read_text(encoding="utf-8"))
draft = pkg["draft"]
TABLE = "p906-t1"

rows = {
    "기술관리 : 공사기간중": ("기계산업기사", "인/일", "1.0"),
    "기초 Check : 기초 check": ("기계설비공", "인/㎡", "0.41"),
    "Chipping 및 Grouting": ("특별인부", "인/㎡", "0.595"),
    "표면손질 : Eliminator 및 구동부": ("특별인부", "인/㎡", "0.2"),
    "본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 철골공": ("철골공", "인/ton", "4.18"),
    "본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 비계공": ("비계공", "인/ton", "3.0"),
    "본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 특별인부": ("특별인부", "인/ton", "0.3"),
    "Drift-Eliminator 설치 / 건축목공": ("건축목공", "인/㎡", "3.1"),
    "Drift-Eliminator 설치 / 보통인부": ("보통인부", "인/㎡", "0.698"),
    "스레이트 잇기 / 스레이트공": ("스레이트공", "인/㎡", "0.05"),
    "스레이트 잇기 / 보통인부": ("보통인부", "인/㎡", "0.04"),
    "충전물충전 : 충전물을 규격별 순서로 충전 작업함": ("보통인부", "인/㎥", "0.6"),
}
values = {row: {"직종": trade, "단위": basis, "수량": rate}
          for row, (trade, basis, rate) in rows.items()}
draft["inputs"] = [
    {"name": "duration", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "일",
     "required": True, "ask": "Cooling Tower 기술관리 기간은 며칠입니까?", "source": f"{TABLE} 기술관리 행 (공사기간중), 인/일"},
    {"name": "base_area", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "㎡",
     "required": True, "ask": "기초 Check 및 Chipping·Grouting 면적은 몇 ㎡입니까?", "source": f"{TABLE} 기초 Check·Chipping 행, 인/㎡"},
    {"name": "surface_area", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "㎡",
     "required": True, "ask": "Eliminator 및 구동부 표면손질 면적은 몇 ㎡입니까?", "source": f"{TABLE} 표면손질 행, 인/㎡"},
    {"name": "weight", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "ton",
     "required": True, "ask": "본체 설치 중량은 몇 ton입니까?", "source": f"{TABLE} 본체설치 행, 인/ton"},
    {"name": "eliminator_area", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "㎡",
     "required": True, "ask": "Drift-Eliminator 설치 면적은 몇 ㎡입니까?", "source": f"{TABLE} Drift-Eliminator 설치 행, 인/㎡"},
    {"name": "slate_area", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "㎡",
     "required": True, "ask": "Louver 측 스레이트 잇기 면적은 몇 ㎡입니까?", "source": f"{TABLE} 스레이트 잇기 행, 인/㎡"},
    {"name": "filler_volume", "type": "positive_rational", "allowed_values": "0보다 큰 수", "unit": "㎥",
     "required": True, "ask": "충전물 충전 부피는 몇 ㎥입니까?", "source": f"{TABLE} 충전물충전 행, 인/㎥"},
]
draft["tables"] = [{"id": TABLE, "role": "Cooling Tower 공정·직종별 다중 단위 설치품",
                    "source": "PDF 물리 906쪽 / 인쇄 850쪽, 13-11-2 (기당)",
                    "unit": "인/일, 인/㎡, 인/ton, 인/㎥", "values": values,
                    "cite": {"table_id": TABLE}}]

def activity(row: str, trade: str, quantity_input: str, basis: str) -> dict:
    return {"table": TABLE, "trades": [trade], "quantity_input": quantity_input,
            "basis_by_trade": {trade: basis}, "row_by_trade": {trade: row}, "column": "수량"}

activity_routes = [
    activity("기술관리 : 공사기간중", "기계산업기사", "duration", "인/일"),
    activity("Chipping 및 Grouting", "특별인부", "base_area", "인/㎡"),
    activity("표면손질 : Eliminator 및 구동부", "특별인부", "surface_area", "인/㎡"),
    activity(next(r for r in rows if r.endswith("/ 철골공")), "철골공", "weight", "인/ton"),
    activity(next(r for r in rows if r.endswith("/ 비계공")), "비계공", "weight", "인/ton"),
    activity(next(r for r in rows if r.endswith("/ 특별인부")), "특별인부", "weight", "인/ton"),
    activity("Drift-Eliminator 설치 / 건축목공", "건축목공", "eliminator_area", "인/㎡"),
    activity("Drift-Eliminator 설치 / 보통인부", "보통인부", "eliminator_area", "인/㎡"),
    activity("스레이트 잇기 / 스레이트공", "스레이트공", "slate_area", "인/㎡"),
    activity("스레이트 잇기 / 보통인부", "보통인부", "slate_area", "인/㎡"),
    activity("충전물충전 : 충전물을 규격별 순서로 충전 작업함", "보통인부", "filler_volume", "인/㎥"),
]
primary_row = "기초 Check : 기초 check"
draft["quantity_model"] = {
    "name": "per_unit",
    "params": {
        "unit_rate_table": {"table": TABLE, "trades": ["기계설비공"], "row_input": primary_row,
                            "column_input": "수량", "row_by_trade": {"기계설비공": primary_row},
                            "basis_by_row": {row: f"{basis}" for row, (_, basis, _) in rows.items()},
                            "resource_units": {trade: "인" for trade, _, _ in rows.values()}},
        "quantity_input": "base_area", "additional_unit_rates": activity_routes,
        "proportional_resource_additions": [{
            "when": {}, "base": "each_labor_line_rate", "factor": "0.1",
            "exclude_trades": ["기계산업기사"], "resource_name": "검사 및 교정", "resource_unit": "인",
            "source": "p906-t1 검사 및 교정 행: 기술관리를 제외한 전 품의 10%",
            "cite": {"chunk_id": "p906-t1", "quote": "검사 및 교정 | 기술관리를 제외한 전 품의 10%"},
        }],
        "surcharges": [], "note_adjustments": [],
    },
    "steps": ["각 공정별 측정 물량에 원문 행의 직종별 품과 해당 분모(일·㎡·ton·㎥)를 각각 적용한다.",
              "Chipping 및 Grouting의 단위 〃는 직전 기초 Check 행의 인/㎡를 그대로 뜻한다.",
              "기술관리를 제외한 각 공정 품에 10%를 적용하여 검사 및 교정 인력을 별도 행으로 더한다.",
              "목재 Drift-Eliminator 가공품은 원문 주에 따라 별도 자재로 유지한다."],
    "source": "PDF 물리 906쪽 / 인쇄 850쪽 13-11-2 Cooling Tower 설치 표 및 주 ②",
    "rounding": "원문 단위품을 정확한 유리수로 적용; 단위별 물량은 가격·집계 단계에서 각각 반영",
}
draft["not_calculated"] = [{"item": "가공 목재 Drift-Eliminator 자재",
                            "source": "PDF 물리 906쪽 / 인쇄 850쪽 주 ②",
                            "cite": {"chunk_id": "p906-x24",
                                     "quote": "Drift-Eliminator 설치는 가공된 목재 Eliminator를 설치하는 품으로 가공품은 제외되었다."}}]
draft["blocked"] = []
draft["open_questions"] = []
pkg["calc_type"] = "per_unit"
pkg["calc_type_raw"] = "per_unit"
pkg["calc_type_reason"] = "원문 행별 분모가 명시되어 다중 물량 단위별 보조 요율과 source-scoped 10% 검사 인력을 연결함."
pkg["citations"] = [{"table_id": TABLE, "row": row, "column": "수량", "value": rate}
                    for row, (_, _, rate) in rows.items()]
pkg["citations"].append({"chunk_id": TABLE, "quote": "검사 및 교정 | 기술관리를 제외한 전 품의 10%"})
pkg["open_questions"] = []
SPEC.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines()]
chunk_lines = ["13-11-2 Cooling Tower 설치 (기당)",
               "기술관리 : 공사기간중 | 직종 기계산업기사 | 단위 인/일 | 수량 1.0",
               "기초 Check : 기초 check | 직종 기계설비공 | 단위 인/㎡ | 수량 0.41",
               "Chipping 및 Grouting | 직종 특별인부 | 단위 〃(인/㎡; 직전 단위 상속) | 수량 0.595",
               "표면손질 : Eliminator 및 구동부 | 직종 특별인부 | 단위 인/㎡ | 수량 0.2",
               "본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 철골공 | 직종 철골공 | 단위 인/ton | 수량 4.18",
               "본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 비계공 | 직종 비계공 | 단위 〃(인/ton; 직전 단위 상속) | 수량 3.0",
               "본체설치 / Distribution box, Distributor, Louver Post 등의 조립설치 / 특별인부 | 직종 특별인부 | 단위 〃(인/ton; 직전 단위 상속) | 수량 0.3",
               "Drift-Eliminator 설치 / 건축목공 | 직종 건축목공 | 단위 인/㎡ | 수량 3.1",
               "Drift-Eliminator 설치 / 보통인부 | 직종 보통인부 | 단위 〃(인/㎡; 직전 단위 상속) | 수량 0.698",
               "스레이트 잇기 / 스레이트공 | 직종 스레이트공 | 단위 인/㎡ | 수량 0.05",
               "스레이트 잇기 / 보통인부 | 직종 보통인부 | 단위 〃(인/㎡; 직전 단위 상속) | 수량 0.04",
               "충전물충전 : 충전물을 규격별 순서로 충전 작업함 | 직종 보통인부 | 단위 인/㎥ | 수량 0.6",
               "검사 및 교정 | 기술관리를 제외한 전 품의 10%"]
for chunk in chunks:
    if chunk.get("chunk_id") == TABLE:
        chunk["text"] = "\n".join(chunk_lines)
        chunk["structure"] = "task_trade_multi_denominator_rows"
        chunk["issues"] = []
        break
else:
    raise AssertionError(f"missing source table chunk {TABLE}")
CHUNKS.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")
print(json.dumps({"source_rate_rows": len(rows), "additional_quantity_routes": len(activity_routes),
                  "inspection_rule": "10% of each source labor rate except technical management",
                  "inherited_unit_rows": 4}, ensure_ascii=False))
