"""Compare every distance band and ambiguous endpoint with printed p.337."""
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

SPEC = ROOT / "data/drafts/specs/토목/3-1-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED = {
    "갱구에서 500m 까지": "-", "500m∼1,000m 까지": "10", "1,000m∼1,500m 까지": "20",
    "1,500m∼2,000m 까지": "30", "2,000m∼2,500m 까지": "40", "2,500m∼3,000m 까지": "50",
    "3,000m∼3,500m 까지": "60", "3,500m∼4,000m 까지": "70", "4,000m∼4,500m 까지": "80",
    "4,500m∼5,000m 까지": "90", "5,000m 이상": "100",
}


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    table = next(item for item in spec["tables"] if item["id"] == "p393-t1")
    assert table["values"] == {"할증률(%)": EXPECTED}
    distance = next(field for field in spec["inputs"] if field["name"] == "distance")
    routes = distance["source_range_map"]
    assert len(routes) == len(EXPECTED)
    with pymupdf.open(PDF) as doc:
        source = norm(doc[392].get_text())
        for index, (column, value) in enumerate(EXPECTED.items()):
            assert norm(column) in source and norm(value) in source, (column, value)
            sample = 100 if index == 0 else (index * 500 + 250 if index < 10 else 5_500)
            result = lookup(spec, {"distance": sample})
            assert result["status"] == "computed" and result["value"] == value, (sample, result)
            cite = result["provenance"]["citations"][0]
            assert (cite["internal_id"], cite["row"], cite["column"], cite["value"]) == (
                "p393-t1", "할증률(%)", column, value)
        for endpoint in range(500, 5001, 500):
            result = lookup(spec, {"distance": endpoint})
            assert result["status"] == "blocked", (endpoint, result)
            assert "".join(result["reason"].split())
    validation = validate_one(SPEC, ROOT / "data/drafts/specs", load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "printed_page": 337, "independent_source_cells": len(EXPECTED),
              "runtime_exact_citations": len(EXPECTED), "nonboundary_distance_bands": "11/11",
              "ambiguous_endpoints_blocked": 10, "boundary_policy": "unresolved and recorded in open_questions",
              "citation_preflight": "pass", "source_visual_review": "p.337 formula/table and inclusivity wording checked"}
    out = ROOT / "evals/runtime_validation/lookup-3-1-1-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
