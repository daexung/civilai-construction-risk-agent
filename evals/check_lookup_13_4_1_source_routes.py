"""Compare both 13-4-1 lookup tables with PDF p.764 and verify exact routed citations."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pymupdf  # noqa: E402
from backend.agent.tools.calc.lookup import lookup  # noqa: E402
from pipeline.validate_drafts import load_chunks, validate_one  # noqa: E402

SPEC = ROOT / "data/drafts/specs/기계설비/13-4-1.json"
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
EXPECTED_WEIGHT = {
    "철골조건물": {"연면적에 대하여": "0.10∼0.15", "목재중도리": "0.04∼0.06"},
    "철골조지붕틀": {"철골중도리": "0.06∼0.08", "철근을 구조계산에 가산할 경우": "0.08∼0.10"},
    "철골철근콘크리트조": {"철근을 구조계산에 가산하지 않을 경우": "0.10∼0.15"},
}
EXPECTED_ACCESSORY = {
    "작은보": "15∼20", "지붕틀": "10", "큰보": "10∼15",
    "격자기둥": "10∼15", "강관기둥": "10", "벽보": "10",
}


def lines(cell: str | None) -> list[str]:
    return [value.strip() for value in (cell or "").splitlines() if value.strip()]


def compact(value: str) -> str:
    return "".join(value.split())


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    tables = {table["id"]: table for table in spec["tables"]}
    assert tables["p820-t1"]["values"] == EXPECTED_WEIGHT
    assert tables["p820-t2"]["values"] == {"부속재(%)": EXPECTED_ACCESSORY}
    with pymupdf.open(PDF) as document:
        page = document[819]
        weight_rows = page.find_tables().tables[1].extract()[2:]
        source_weight = {}
        for building, structure, values in weight_rows:
            structures, figures = lines(structure), lines(values)
            if len(structures) > len(figures):
                structures = structures[:len(figures) - 1] + [" ".join(structures[len(figures) - 1:])]
            assert len(structures) == len(figures)
            source_weight[compact(building)] = {compact(label): figure for label, figure in zip(structures, figures)}
        accessory_row = page.find_tables().tables[2].extract()[1]
        materials, rates = lines(accessory_row[0]), lines(accessory_row[1])
        source_accessory = {compact(material): rate for material, rate in zip(materials, rates)}
    normalized_weight = {compact(row): {compact(column): value for column, value in columns.items()}
                         for row, columns in EXPECTED_WEIGHT.items()}
    assert source_weight == normalized_weight
    assert source_accessory == EXPECTED_ACCESSORY

    route_field = next(field for field in spec["inputs"] if field["name"] == "lookup_type")
    assert route_field["source_table_map"] == {
        "철골재의 무게산출 표준": "p820-t1", "부속재의 비율": "p820-t2"
    }
    checked = 0
    for building, structures in EXPECTED_WEIGHT.items():
        for structure, value in structures.items():
            result = lookup(spec, {"lookup_type": "철골재의 무게산출 표준",
                                   "building_type": building, "structure_type": structure})
            assert result["status"] == "computed" and result["value"] == value
            citation = result["provenance"]["citations"][0]
            assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (
                "p820-t1", building, structure, value)
            checked += 1
    for material, value in EXPECTED_ACCESSORY.items():
        result = lookup(spec, {"lookup_type": "부속재의 비율", "main_material": material})
        assert result["status"] == "computed" and result["value"] == value
        citation = result["provenance"]["citations"][0]
        assert (citation["internal_id"], citation["row"], citation["column"], citation["value"]) == (
            "p820-t2", "부속재(%)", material, value)
        checked += 1
    bad = lookup(spec, {"lookup_type": "부속재의 비율", "building_type": "철골조건물"})
    assert bad["status"] == "rejected", bad
    validation = validate_one(SPEC, ROOT / "data/drafts/specs",
                              load_chunks(ROOT / "data/processed/chunks.all.jsonl"), None)
    assert validation["ok"], validation
    report = {"status": "pass", "pdf_page": 764, "source_tables": 2,
              "independent_source_cells": 11, "exact_routed_cell_citations": checked,
              "wrong_branch_rejected": True, "citation_preflight": "pass"}
    out = ROOT / "evals/runtime_validation/lookup-13-4-1-independent-source-audit-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
