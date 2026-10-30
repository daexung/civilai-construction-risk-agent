"""Restore the two distinct 1m-or-longer rows in the 8-3-6 source extraction."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPEC = ROOT / "data/drafts/specs/기계설비/8-3-6.json"

def main() -> None:
    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    found = 0
    for i, raw in enumerate(lines):
        chunk = json.loads(raw)
        if chunk.get("chunk_id") != "p754-t0":
            continue
        text = chunk["text"]
        expected = """8-3-6 방열기('07년 보완)
주 철 재 바 닥 설 치 20절 이하 | 단위 인/조 | 배관공 1.10 | 보통인부 0.10
21절 이상 | 단위 인/조 | 배관공 1.50 | 보통인부 0.10
벽 걸 이 3절 | 단위 인/조 | 배관공 1.60 | 보통인부 0.20
천 장 달 기 3절 | 단위 인/조 | 배관공 2.50 | 보통인부 0.50
1m길트 | 단위 인/본 | 배관공 0.70 | 보통인부 0.10
콘백터 길이 1m 미만 | 단위 인/조 | 배관공 0.80 | 보통인부 0.10
콘백터 길이 1m 이상 | 단위 인/조 | 배관공 1.10 | 보통인부 0.10
베이스보드 1단형길이 2m 미만 | 단위 인/단 | 배관공 1.90 | 보통인부 0.20
2m이상 | 단위 인/단 | 배관공 2.40 | 보통인부 0.20
강판제 및 알루미늄제 방열기 1m 미만 | 단위 인/조 | 배관공 0.44 | 보통인부 0.06
강판제 및 알루미늄제 방열기 1m 이상 | 단위 인/조 | 배관공 0.60 | 보통인부 0.06"""
        assert chunk.get("structure") == "ok" and not chunk.get("issues"), chunk
        # Require the stored extraction's full, exact row values before repairing labels.
        for exact in (
            "콘백터 길이 1m 미만 | 단위 인/조 | 배관공 0.80 | 보통인부 0.10",
            "1m 이상 | 단위 인/조 | 배관공 1.10 | 보통인부 0.10",
            "강판제 및 알루미늄제 방열기 1m 미만 | 단위 인/조 | 배관공 0.44 | 보통인부 0.06",
            "1m 이상 | 단위 인/조 | 배관공 0.60 | 보통인부 0.06",
        ):
            assert exact in text, exact
        chunk["text"] = expected
        lines[i] = json.dumps(chunk, ensure_ascii=False)
        found += 1
    assert found == 1, found
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")

    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    table = next(t for t in draft["tables"] if t["id"] == "p754-t0")
    old = table["values"]
    old.pop("1m 이상")
    old["콘백터 길이 1m 이상"] = {
        "단위": "인/조", "배관공": "1.10", "보통인부": "0.10"}
    old["강판제 및 알루미늄제 방열기 1m 이상"] = {
        "단위": "인/조", "배관공": "0.60", "보통인부": "0.06"}
    package["draft"]["inputs"][0]["allowed_values"] = [
        "주 철 재 바 닥 설 치 20절 이하", "21절 이상", "벽 걸 이 3절", "천 장 달 기 3절",
        "1m길트", "콘백터 길이 1m 미만", "콘백터 길이 1m 이상",
        "베이스보드 1단형길이 2m 미만", "2m이상",
        "강판제 및 알루미늄제 방열기 1m 미만", "강판제 및 알루미늄제 방열기 1m 이상",
        "패널 라디에이터",
    ]
    for field in draft["inputs"]:
        if field["name"] == "quantity":
            field["unit"] = "조/본/단"
            field["unit_by"] = {"input": "radiator_type", "values": {
                value: ("본" if value == "1m길트" else
                        "단" if value in ("베이스보드 1단형길이 2m 미만", "2m이상") else "조")
                for value in package["draft"]["inputs"][0]["allowed_values"]}}
    draft["quantity_model"] = {
        "name": "per_unit",
        "params": {
            "unit_rate_table": {
                "table": "p754-t0", "row_input": "radiator_type",
                "column_input": None,
                "trades": ["배관공", "보통인부"],
                "quantity_unit_selector": {"input": "radiator_type", "values": {
                    value: ("본" if value == "1m길트" else
                            "단" if value in ("베이스보드 1단형길이 2m 미만", "2m이상") else "조")
                    for value in package["draft"]["inputs"][0]["allowed_values"]}},
            },
            "quantity_input": "quantity", "surcharges": [], "note_adjustments": [],
            "input_rate_adjustments": [
                {"operation": "add_percent_per_count", "count_input": "extra_sections",
                 "percent_per_count": "15", "when": {"radiator_type": "벽 걸 이 3절"},
                 "cite": {"chunk_id": "p754-x11", "quote": "벽걸이 3절 초과하는 경우 매 1절 증가마다 15%씩 가산한다."}},
                {"operation": "add_percent_per_count", "count_input": "extra_tiers",
                 "percent_per_count": "20", "when": {"radiator_type": "콘백터 길이 1m 미만"},
                 "cite": {"chunk_id": "p754-x11", "quote": "콘백터 및 베이스 보드는 1단 증가마다 20%씩 가산한다."}},
                {"operation": "add_percent_per_count", "count_input": "extra_tiers",
                 "percent_per_count": "20", "when": {"radiator_type": "콘백터 길이 1m 이상"},
                 "cite": {"chunk_id": "p754-x11", "quote": "콘백터 및 베이스 보드는 1단 증가마다 20%씩 가산한다."}},
                {"operation": "add_percent_per_count", "count_input": "extra_tiers",
                 "percent_per_count": "20", "when": {"radiator_type": "베이스보드 1단형길이 2m 미만"},
                 "cite": {"chunk_id": "p754-x11", "quote": "콘백터 및 베이스 보드는 1단 증가마다 20%씩 가산한다."}},
                {"operation": "add_percent_per_count", "count_input": "extra_tiers",
                 "percent_per_count": "20", "when": {"radiator_type": "2m이상"},
                 "cite": {"chunk_id": "p754-x11", "quote": "콘백터 및 베이스 보드는 1단 증가마다 20%씩 가산한다."}},
            ],
        },
        "steps": [
            "방열기 종류 및 규격에 따라 p754-t0에서 배관공·보통인부의 단위당 품을 조회한다.",
            "벽걸이 3절형은 초과 절마다 15%, 콘벡터 및 베이스보드는 추가 단마다 20%를 기본 품에 가산한다.",
            "단위당 품에 물량을 곱한다. 패널 라디에이터는 길이별 콘벡터 품의 적용 기준이 원문에 명시되지 않아 계산을 보류한다.",
        ],
        "source": "PDF 698쪽 8-3-6 표 및 [주]",
        "rounding": "총 투입량은 정확한 유리수로 보존; 단위당 품은 공통 1-2-8·1-2-1 기본 자릿수 적용",
    }
    draft["blocked"] = [{
        "condition": "패널 라디에이터는 콘벡터 품을 적용하지만 길이별(1m 미만/이상) 선택 기준이 원문에서 지정되지 않음",
        "blocked_if": {"input": "radiator_type", "op": "==", "value": "패널 라디에이터"},
        "reason": "두 콘벡터 길이 규격 중 하나를 임의 선택하지 않음",
        "source": "PDF 698쪽 [주] ④ 및 p754-t0",
        "cite": {"chunk_id": "p754-x11", "quote": "패널 라디에이터(panel radiator)는 콘백터 품을 적용한다."},
    }]
    package["calc_type"] = "per_unit"
    package["calc_type_raw"] = "per_unit"
    package["calc_type_reason"] = "원표 행명과 단위가 복원되어 기존 per_unit 실행기로 표현됨; 패널 라디에이터 길이별 적용은 원문 미확정으로 차단"
    package["open_questions"] = [
        "패널 라디에이터가 콘벡터의 1m 미만 또는 1m 이상 중 어느 품을 적용하는지 원문이 지정하지 않는다.",
    ]
    package["questions"] = []
    package["citations"] = [
        {"table_id": "p754-t0", "row": row, "column": resource, "value": values[resource]}
        for row, values in old.items() for resource in ("배관공", "보통인부")
    ] + [
        {"chunk_id": "p754-x11", "quote": quote}
        for quote in (
            "벽걸이 3절 초과하는 경우 매 1절 증가마다 15%씩 가산한다.",
            "콘백터 및 베이스 보드는 1단 증가마다 20%씩 가산한다.",
            "패널 라디에이터(panel radiator)는 콘백터 품을 적용한다.",
        )
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("restored duplicate rows and routed supported radiator types; panel length remains explicitly blocked")

if __name__ == "__main__":
    main()
