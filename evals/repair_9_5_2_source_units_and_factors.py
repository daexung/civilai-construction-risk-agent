"""Implement 9-5-2 source units and exact distance/elevation choices."""
from __future__ import annotations

import json
import sys
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.per_unit import per_unit
from backend.agent.tools.calc.price import price_unit, select_rate_version
from pipeline.validate_drafts import file_sha256, load_chunks, validate_one

SPEC = ROOT / "data/drafts/specs/토목/9-5-2.json"
BASE = {"고급기술자": Fraction(4), "중급기술자": Fraction(30),
        "초급기능사(측량)": Fraction(20)}
DISTANCE = {"1km이내": Fraction(1), "2∼3km": Fraction("1.30"),
            "3∼4km": Fraction("1.60"), "4km이상": Fraction(2)}
ELEVATION = {"500m 미만": Fraction(0), "500m∼l,000m": Fraction("0.20"),
             "1,000m이상": Fraction("0.40")}
DISTANCE_CITE = "1km이상일 경우에는 다음의 계수를 곱하여 계상할"
ELEVATION_CITE = "작업지역의 평균표고가 500m∼l,000m일 때는 20%, 1,000m이상일 때는 40%를 가산할 수 있다."
TIDELAND_CITE = "간석지 작업시는 간조시간을 고려하여 본 품에 3배까지 가산할 수 있다."


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    draft = package["draft"]
    rate = draft["quantity_model"]["params"]["unit_rate_table"]
    primary = next(table for table in draft["tables"] if table["id"] == "p528-t1")
    coefficients = next(table for table in draft["tables"] if table["id"] == "p528-t2")
    source_columns = {
        "고급기술자": "인원수 합계 고급\n기술\n자",
        "중급기술자": "인원수 중급\n기술\n자",
        "초급기능사(측량)": "인원수 초급\n기능사\n(측량)",
    }
    assert {trade: Fraction(primary["values"]["계"][source_columns[trade]])
            for trade in BASE} == BASE
    assert coefficients["values"]["계수"] == {
        "1km이내": "1.00", "2∼3km": "1.30", "3∼4km": "1.60", "4km이상": "2.00"}
    rate["basis_by_row"] = {"계": "인/40점"}
    rate["basis_cites_by_row"] = {"계": {"chunk_id": "p528-x14",
                                          "quote": "본 품은 40점을 1작업단위로 하고, 대공표지설치에 적용한다."}}

    clauses = []
    for number, distance in enumerate(list(DISTANCE)[1:], 1):
        clauses.append({"when": {"distance": distance}, "rate": str(DISTANCE[distance]),
                        "operation": "multiply", "applies_to": list(BASE),
                        "rate_table": {"id": "p528-t2", "row": "계수", "column": distance},
                        "application_cite": {"chunk_id": "p528-x14", "quote": DISTANCE_CITE},
                        "source": "PDF 472쪽 [주] ④ 거리계수 표"})
    for elevation in list(ELEVATION)[1:]:
        clauses.append({"when": {"elevation": elevation}, "rate": str(ELEVATION[elevation]),
                        "applies_to": list(BASE),
                        "application_cite": {"chunk_id": "p528-x20", "quote": ELEVATION_CITE},
                        "source": "PDF 472쪽 [주] ⑥ 표고 가산"})
    draft["quantity_model"]["params"]["surcharges"] = clauses
    draft["quantity_model"]["params"]["note_adjustments"] = []
    inputs = draft["inputs"]
    tidal = next(field for field in inputs
                 if field["name"] in ("tideland_multiplier", "tideland_work"))
    tidal.update({"name": "tideland_work", "type": "boolean", "allowed_values": [True, False],
                  "unit": None, "ask": "간석지 작업입니까?",
                  "source": "PDF 472쪽 [주] ⑦ 간석지 작업 규정"})
    draft["blocked"] = [{"blocked_if": {"input": "tideland_work", "op": "==", "value": True},
                         "reason": "간석지 작업의 원문은 간조시간을 고려해 최대 3배까지 가산할 수 있다고만 정하고 구체 승수 산식을 제시하지 않아 계산을 보류합니다.",
                         "source": "PDF 472쪽 [주] ⑦", "cite": {"chunk_id": "p528-x20", "quote": TIDELAND_CITE}}]
    draft["quantity_model"]["steps"] = [
        "표 p528-t1의 합계 인원은 40점 기준이므로 40점으로 나누어 점당 품으로 환산한다.",
        "점당거리 1km 초과 시 p528-t2에서 정확한 거리계수를 선택한다.",
        "평균표고에 따른 20% 또는 40% 가산은 원문이 선택 적용으로 규정하므로 적용 여부를 확인한다.",
        "간석지 작업은 구체 가산 승수가 명시되지 않아 계산을 보류한다."]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    cases = []
    for distance, distance_factor in DISTANCE.items():
        for elevation, elevation_rate in ELEVATION.items():
            inputs = {"quantity": "40", "distance": distance, "elevation": elevation,
                      "tideland_work": False}
            # The distance and elevation source clauses are permission statements;
            # answer yes only when the corresponding rule is selected.
            inputs.update({f"apply_adj_{i}": "예" for i in range(1, 6)})
            result = per_unit(draft, inputs)
            assert result.get("status") == "computed", (inputs, result)
            factor = distance_factor * (1 + elevation_rate)
            expected = {name: value * factor / 40 for name, value in BASE.items()}
            actual = {line["name"]: Fraction(line["exact"]) for line in result["unit_lines"]}
            assert actual == expected, (inputs, expected, actual)
            assert all(any(cite.get("value") in ("4", "30", "20") for cite in line["citations"])
                       for line in result["unit_lines"])
            priced = price_unit(draft, result["unit_lines"], select_rate_version("2026-10-01"),
                                inputs, "2026-10-01")
            assert priced.get("status") in ("COMPLETE", "PARTIAL"), priced
            assert priced["reference_amounts"]["volume"] == "40"
            cases.append({"distance": distance, "distance_factor": str(distance_factor),
                          "elevation": elevation, "elevation_rate": str(elevation_rate),
                          "expected_per_point": {name: str(value) for name, value in expected.items()},
                          "actual_per_point": {line["name"]: line["exact"] for line in result["unit_lines"]},
                          "price_status": priced["status"],
                          "reference_amounts": priced["reference_amounts"]})

    blocked_inputs = {"quantity": "40", "distance": "1km이내", "elevation": "500m 미만",
                      "tideland_work": True}
    blocked = per_unit(draft, blocked_inputs)
    assert blocked.get("status") == "blocked" and TIDELAND_CITE in str(blocked.get("citations")), blocked

    chunks_path = ROOT / "data/processed/chunks.all.jsonl"
    validation = validate_one(SPEC, ROOT / "data/drafts", load_chunks(chunks_path),
                              file_sha256(chunks_path))
    assert validation["ok"], validation
    report_path = ROOT / "data/drafts/report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    old = next(item for item in report["results"]
               if item["path"].replace("\\", "/") == "specs/토목/9-5-2.json")
    report["ok"] += int(validation["ok"]) - int(old["ok"])
    for key in ("with_format_issues", "with_citation_issues"):
        field = key.replace("with_", "")
        report[key] += int(bool(validation[field])) - int(bool(old[field]))
    report["results"][report["results"].index(old)] = validation
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    index_path = ROOT / "data/drafts/executable.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    ident = draft["id"]
    index["failed"] = [item for item in index["failed"] if item["id"] != ident]
    index["executable"] = sorted(set(index["executable"]) | {ident})
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    audit = {"id": ident, "source": {"physical_page": 528, "printed_page": 472,
             "visual_checked": "tmp/9-5-2-source-p528.png", "base_table": "p528-t1",
             "distance_table": "p528-t2", "base_totals": {name: str(value) for name, value in BASE.items()},
             "work_basis": "40점/작업단위", "distance_coefficients": {k: str(v) for k, v in DISTANCE.items()},
             "elevation_clause": ELEVATION_CITE, "tideland_policy": TIDELAND_CITE},
             "cases": cases, "tideland_case": {"inputs": blocked_inputs, "status": blocked["status"],
                                                    "reason": blocked["reason"]},
             "focused_validation_ok": validation["ok"],
             "scope": "three base cells, four exact distance factors, three elevation choices, combined per-point results, offline pricing and the unresolved tidal block verified; whole section non-table rules and all-rule inventory completion not claimed"}
    out = ROOT / "evals/runtime_validation/per-unit-9-5-2-source-unit-factor-audit-2026-10-19.json"
    out.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": ident, "focused_validation_ok": validation["ok"],
                      "numeric_source_cells": 6, "distance_elevation_routes": len(cases),
                      "tideland_policy": blocked["status"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
