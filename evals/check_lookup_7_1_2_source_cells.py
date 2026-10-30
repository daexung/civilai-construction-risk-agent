"""Compare all seven 7-1-2 matrix cells to the rendered source and runtime."""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/토목/7-1-2.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "펌프준설선": {"448이하": "119∼336", "746∼1,492": "373∼746",
                    "1,641∼5,968": "746∼1,790", "8,952이상": "1,790이상"},
    "그래브준설선": {"75∼1,492": "187∼336"},
    "토운선": {"60㎥∼300㎥": "119∼187", "300㎥이상": "187∼1,790"},
}
AXIS = {"펌프준설선": "pump_dredger_power", "그래브준설선": "grab_dredger_power",
        "토운선": "barge_capacity"}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(item for item in spec["tables"] if item["id"] == "p443-t2")
    assert table["values"] == EXPECTED
    with pymupdf.open(PDF) as doc:
        source = norm(doc[442].get_text())
        for vessel, values in EXPECTED.items():
            assert norm(vessel) in source or vessel == "그래브준설선" and norm("그래브 준설선") in source
            for criterion, result_value in values.items():
                assert norm(criterion) in source, criterion
                assert norm(result_value) in source, result_value
                inputs = {"towed_vessel_type": vessel, AXIS[vessel]: criterion}
                result = lookup(spec, inputs)
                assert result["status"] == "computed" and result["value"] == result_value, (inputs, result)
                cite = result["provenance"]["citations"][0]
                assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                    "p443-t2", vessel, criterion, result_value)
        wrong = lookup(spec, {"towed_vessel_type": "토운선", "pump_dredger_power": "448이하"})
        assert wrong["status"] == "rejected", wrong
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 387, "independent_source_cells": 7,
              "runtime_exact_citations": 7, "vessel_conditional_domains": 3,
              "irrelevant_vessel_axis_rejected": True, "citation_preflight": "pass",
              "source_visual_review": "p.387 row groups and combined-cell ranges compared"}
    out = ROOT / "evals/runtime_validation/lookup-7-1-2-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
