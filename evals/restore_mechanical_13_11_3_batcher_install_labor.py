"""Restore the source's direct per-ton Batcher Plant installation labor row."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-11-3.json"
pkg = json.loads(SPEC.read_text(encoding="utf-8"))
draft = pkg["draft"]
rates = {
    "기계산업기사": "0.50", "비계공": "1.255", "특별인부": "5.270", "제관공": "1.470",
    "용접공": "0.882", "기계설비공": "0.882", "측량사": "0.167", "검사시험": "0.975",
}
table = {
    "id": "p907-t0", "role": "직종별 Batcher Plant 설치 직접 품", "source": "PDF 물리 907쪽 / 인쇄 851쪽, 1. 직종별 설치품",
    "unit": "인/ton", "values": {trade: {"수량": value} for trade, value in rates.items()},
    "cite": {"table_id": "p907-t0"},
}
draft["inputs"] = [{"name": "quantity", "type": "positive_rational", "allowed_values": "0보다 큰 수",
                    "unit": "ton", "required": True, "ask": "설치할 Batcher Plant 중량은 몇 ton입니까?",
                    "source": "p907-t0 표 기준 (ton당)"}]
draft["tables"] = [table]
trades = list(rates)
draft["quantity_model"] = {
    "name": "per_unit",
    "params": {"unit_rate_table": {"table": "p907-t0", "trades": trades, "row_input": "수량",
                                    "column_input": "수량", "row_by_trade": {t: t for t in trades},
                                    "resource_units": {t: "인" for t in trades}},
                "quantity_input": "quantity", "surcharges": [], "note_adjustments": []},
    "steps": ["p907-t0의 직종별 설치품(ton당)을 적용한다.",
              "동일 설치품의 공정별 분해표(p907-t1)는 합산용이 아니라 직종별 합계의 독립 대조 자료로만 사용한다.",
              "파손·마모부 제작수리(p907-t2, p908-t0)와 참고 사용장비(p908-t1)는 기본 설치품에 더하지 않는다.",
              "전기 배관·배선·도장, 소재 소운반 등 원문에서 별도 또는 제외한 항목은 이 노동품 총계에 포함하지 않는다."],
    "source": "PDF 물리 907쪽 / 인쇄 851쪽 1. 직종별 설치품; 원문과 공정별 설치품 대조",
    "rounding": "원문 직종별 단위품을 그대로 적용; 전체 금액의 반올림 규칙은 별도 적용",
}
draft["blocked"] = []
draft["not_calculated"] = [
    {"item": "파손·마모부 제관 수리품", "source": "PDF 물리 908쪽 / 인쇄 852쪽 주 ①",
     "cite": {"chunk_id": "p908-x9", "quote": "본 품은 Batcher Plant 설치시 파손 및 마모부분의 제작 설치에만 적용한다."}},
    {"item": "소재 소운반", "source": "PDF 물리 908쪽 / 인쇄 852쪽 주 ②",
     "cite": {"chunk_id": "p908-x9", "quote": "본 품에는 소재의 소운반이 포함되어 있지 않으므로 소재의 운반품은 Batcher Plant 설치품에서 발췌 적용한다."}},
    {"item": "전기 배관·배선 및 도장품", "source": "PDF 물리 908쪽 / 인쇄 852쪽 주 ③",
     "cite": {"chunk_id": "p908-x9", "quote": "본 품에는 전기 배관, 배선 및 도장품은 포함되어 있지 않다."}},
    {"item": "수리품 참고 사용장비·소모재", "source": "PDF 물리 908쪽 / 인쇄 852쪽 [참고] 사용장비",
     "cite": {"table_id": "p908-t1"}},
]
draft["open_questions"] = []
pkg["calc_type"] = "per_unit"
pkg["calc_type_raw"] = "per_unit"
pkg["calc_type_reason"] = "원문 1. 직종별 설치품에 8개 직종의 ton당 직접 품이 명시됨."
pkg["citations"] = [{"table_id": "p907-t0", "row": trade, "column": "수량", "value": value}
                    for trade, value in rates.items()]
pkg["open_questions"] = []
SPEC.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines()]
updates = {
    "p907-t0": ("13-11-3 Batcher Plant 설치 / 1. 직종별 설치품 (ton당)\n직종 | 수량\n"
                "기계산업기사 | 0.50\n비계공 | 1.255\n특별인부 | 5.270\n제관공 | 1.470\n"
                "용접공 | 0.882\n기계설비공 | 0.882\n측량사 | 0.167\n검사시험 | 0.975",
                "profession_rate_rows_exact"),
    "p907-t1": ("13-11-3 Batcher Plant 설치 / 2. 공정별 설치품 (ton당)\n"
                "기술관리 | 기계산업기사 | 0.500\n소운반조작 | 비계공 | 0.667\n소운반조작 | 특별인부 | 0.333\n"
                "표면손질 | 특별인부 | 3.3\n현장가공 | 제관공 | 0.588\n현장가공 | 용접공 | 0.588\n현장가공 | 특별인부 | 0.588\n"
                "조립설치 | 기계설비공 | 0.882\n조립설치 | 제관공 | 0.882\n조립설치 | 비계공 | 0.588\n조립설치 | 용접공 | 0.294\n"
                "조립설치 | 특별인부 | 0.882\n조립설치 | 측량사 | 0.167\n뒷정리 | 특별인부 | 0.167\n검사시험 | 특별인부 | 0.975\n"
                "비고 | 기술관리 및 뒷정리를 제외한 전 품의 10%", "process_profession_rate_rows_exact"),
    "p907-t2": ("13-11-3 Batcher Plant 설치 / 3. 직종별 제관수리품 (ton당; 파손·마모부 제작수리에만 적용)\n"
                "제도공 | 0.785\n기계설비공 | 1.830\n특별인부 | 2.041\n용접공 | 4.972\n검사및시험 | 0.962\n계 | 10.590",
                "repair_profession_rate_rows_exact"),
}
for chunk in chunks:
    if chunk.get("chunk_id") in updates:
        chunk["text"], chunk["structure"] = updates[chunk["chunk_id"]]
        chunk["issues"] = []
if not all(any(c.get("chunk_id") == key for c in chunks) for key in updates):
    raise AssertionError("a source table chunk is missing")
CHUNKS.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks) + "\n", encoding="utf-8")
print(json.dumps({"source_direct_labor_cells": len(rates), "process_breakdown_rows": 15,
                  "repair_rate_cells": 6, "equipment_table_calculated": False}, ensure_ascii=False))
