"""Verify the 2.87 cell and preflight repair without inventing its quantity basis."""
from __future__ import annotations

import json
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.per_unit import per_unit  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/기계설비/13-5-4.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"


def norm(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).casefold()


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    cell = spec["tables"][0]["values"]["DUCT 설치 성형된 duct를 운반조양 alignment후 bolting 및 hangering"]["비계공"]
    assert cell == "2.87"
    with pymupdf.open(PDF) as doc:
        source = norm(doc[830].get_text())
        for token in ("13-5-4덕트설치", "비계공", "인/ton", "2.87"):
            assert norm(token) in source, token
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    result = per_unit(spec, {"quantity": "1"})
    assert result.get("status") == "rejected" and "quantity" in result.get("reason", ""), result
    report = {"status": "source_cell_and_preflight_pass", "printed_page": 775,
              "source_cell": {"work": "DUCT 설치", "trade": "비계공", "unit": "인/ton", "value": cell},
              "format_citation_preflight": "pass", "calculator_probe": result,
              "calculation": "not performed; quantity input and unit_rate_table params are absent, and table bases are heterogeneous"}
    out = ROOT / "evals/runtime_validation/per-unit-13-5-4-source-cell-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
