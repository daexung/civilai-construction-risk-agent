"""Independently verify the two 1-4-6 table rows, conditional domains and citations."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/공통/1-4-6.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
WORK = dict(zip(["2시간 이하", "3시간 〃", "4시간 〃", "5시간 〃", "6시간 〃"],
                ["50%", "35%", "25%", "20%", "15%"]))
HEAT = dict(zip(["2시간 이상일 경우 작업시", "4시간 〃", "6시간 〃", "8시간 〃"],
                ["5%", "10%", "15%", "20%"]))


def lines(value: str | None) -> list[str]:
    return [cell.strip() for cell in (value or "").splitlines() if cell.strip()]


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    tables = {table["id"]: table for table in spec["tables"]}
    assert tables["p85-t1"]["values"] == {"작업가능시간": WORK}
    assert tables["p85-t2"]["values"] == {"체감온도 33도 이상": HEAT}
    with pymupdf.open(PDF) as document:
        raw_work = document[84].find_tables().tables[1].extract()[1]
        raw_heat = document[84].find_tables().tables[2].extract()[1]
    assert raw_work[0].replace(" ", "") == "작업가능시간"
    assert dict(zip(lines(raw_work[1]), lines(raw_work[2]))) == WORK
    assert raw_heat[0].replace(" ", "") == "체감온도33도이상"
    assert dict(zip(lines(raw_heat[1]), lines(raw_heat[2]))) == HEAT
    routes = {"작업시간 제한": ("p85-t1", "work_time_limit", WORK),
              "폭염시 휴게시간": ("p85-t2", "heat_wave_work_time", HEAT)}
    checked = 0
    for route, (table_id, field, cases) in routes.items():
        first = lookup(spec, {"lookup_type": route})
        assert first["status"] == "ask" and [q["name"] for q in first["questions"]] == [field]
        assert first["questions"][0]["allowed_values"] == list(cases)
        for condition, rate in cases.items():
            result = lookup(spec, {"lookup_type": route, field: condition})
            assert result["status"] == "computed" and result["value"] == rate
            citation = result["provenance"]["citations"][0]
            expected_row = "작업가능시간" if table_id == "p85-t1" else "체감온도 33도 이상"
            assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (
                table_id, expected_row, condition, rate)
            checked += 1
    wrong_branch = lookup(spec, {"lookup_type": "폭염시 휴게시간", "work_time_limit": "2시간 이하"})
    assert wrong_branch["status"] == "rejected", wrong_branch
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 29, "source_tables": 2,
              "independently_compared_source_cells": checked,
              "exact_runtime_cell_citations": checked, "wrong_branch_rejected": True,
              "citation_preflight": "pass"}
    out = ROOT / "evals/runtime_validation/lookup-1-4-6-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
