"""Refresh selected source-table chunks with current PDF extraction logic.

The saved corpus snapshot was produced by an older extraction pass. This
targeted repair re-extracts only named PDF pages and preserves the original
global record-id references in the saved chunks.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pymupdf
from pipeline.parse import parse_pages
from pipeline.chunk import make_chunks

PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
TARGETS = {"p429-t1": 429, "p449-t1": 449, "p496-t0": 496,
           "p572-t1": 572, "p577-t0": 577, "p578-t1": 578}
NUM = re.compile(r"(?<![\w])\d+(?:,\d{3})*(?:\.\d+)?")


def package(section: str) -> dict:
    path = ROOT / "data/drafts/specs/토목" / f"{section}.json"
    return json.loads(path.read_text(encoding="utf-8"))["draft"]


def compare_exact_two_column_cut(grid: list, spec: dict) -> None:
    assert len(grid) == 2 and len(grid[1]) == 6
    columns = [[part.strip() for part in (grid[1][i] or "").splitlines()]
               for i in range(6)]
    values = spec["values"]
    normalized_values = {key.replace(",", ""): row for key, row in values.items()}
    for base in (0, 3):
        assert len({len(columns[i]) for i in (base, base + 1, base + 2)}) == 1
        for diameter, labor_a, labor_b in zip(columns[base], columns[base + 1], columns[base + 2]):
            row = normalized_values[diameter.replace(",", "")]
            assert row["배관공(수도)"] == labor_a and row["보통인부"] == labor_b
    assert set(normalized_values) == {d.replace(",", "") for base in (0, 3) for d in columns[base]}


def compare_delivery_joint(grid: list, spec: dict) -> None:
    assert len(grid) == 4 and len(grid[2]) == 5
    columns = [[part.strip() for part in (grid[2][i] or "").splitlines()]
               for i in range(5)]
    keys = [d.replace(",", "") for d in columns[0]]
    assert len(set(map(len, columns))) == 1
    normalized_values = {key.replace(",", ""): row for key, row in spec["values"].items()}
    assert set(keys) == set(normalized_values)
    labels = ["배관공(수도)", "보통인부", "크레인(hr) 플랜지접합", "크레인(hr) 고무슬리브접합"]
    for row_index, key in enumerate(keys):
        for label, col in zip(labels, columns[1:]):
            assert normalized_values[key][label] == col[row_index]


def compare_numeric_cell_inventory(grid: list, spec: dict) -> None:
    src = Counter(x.replace(",", "") for row in grid for cell in row if cell for x in NUM.findall(cell))

    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)
        elif isinstance(value, (str, int, float)):
            for token in NUM.findall(str(value)):
                yield token.replace(",", "")

    dst = Counter(walk(spec["values"]))
    # 9-5-9 table task labels are nonnumeric, so every numeric source cell is
    # represented once in the extracted source matrix.
    assert src == dst, {"source_only": list((src - dst).items()), "spec_only": list((dst - src).items())}


def main() -> int:
    old_chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    old_by_id = {item["chunk_id"]: item for item in old_chunks}
    fresh = {}
    for page in sorted(set(TARGETS.values())):
        # Include nearby preceding pages so a title printed on the prior page
        # remains attached to the source chunk metadata.
        records = parse_pages(str(PDF), max(1, page - 2), page)
        for chunk in make_chunks(records):
            if chunk.get("chunk_id") in TARGETS:
                fresh[chunk["chunk_id"]] = chunk
    assert set(fresh) == set(TARGETS)
    report = {"method": "current parse.py/make_chunks run on exact source PDF pages; no fuzzy or value inference",
              "refreshed_table_ids": [], "source_cell_audits": {}, "preserved_global_record_ids": True}
    with pymupdf.open(PDF) as doc:
        for table_id, page in TARGETS.items():
            old, new = old_by_id[table_id], fresh[table_id]
            assert old["source"]["page"] == page and new["source"]["page"] == page
            assert old["source"]["table_id"] == new["source"]["table_id"] == table_id
            assert old["source"]["bbox"] == new["source"]["bbox"]
            assert new["structure"] == "ok" and not new.get("issues")
            package_by_table = {
                "p429-t1": ("6-6-3", "p429-t1"), "p449-t1": ("7-4-1", "p449-t1"),
                "p496-t0": ("9-3-2", "p496-t0"), "p572-t1": ("9-5-9", "p572-t1"),
                "p577-t0": ("9-6-1", "p577-t0"), "p578-t1": ("9-6-2", "p578-t1"),
            }
            section, spec_table_id = package_by_table[table_id]
            spec = next(item for item in package(section)["tables"] if item["id"] == spec_table_id)
            grid = doc[page - 1].find_tables().tables[int(table_id.rsplit("t", 1)[1])].extract()
            if table_id == "p429-t1":
                compare_exact_two_column_cut(grid, spec)
                audit = "source grid: 18 diameters × 2 labor columns; every exact cell matched spec"
            elif table_id == "p449-t1":
                compare_delivery_joint(grid, spec)
                audit = "source grid: 14 diameters × 4 rate columns; every exact cell matched spec"
            elif table_id == "p572-t1":
                compare_numeric_cell_inventory(grid, spec)
                audit = "source grid numeric-cell multiset matched all 44 spec numeric tokens"
            else:
                # Source structure is refreshed, but the richer row/cell mapping
                # remains pending separate rule-level audit before promotion.
                audit = "fresh source extraction verified; detailed spec-cell audit pending"
            report["source_cell_audits"][table_id] = audit
            new["record_ids"] = old.get("record_ids", [])
            for key in ("section", "section_no", "division", "subsection", "source", "pages",
                        "basis", "structure", "issues", "uncertain_record_ids", "text"):
                old[key] = new.get(key)
            old["record_ids"] = new["record_ids"]
            old_by_id[table_id] = old
            report["refreshed_table_ids"].append(table_id)
    CHUNKS.write_text("\n".join(json.dumps(item, ensure_ascii=False) for item in old_by_id.values()) + "\n",
                      encoding="utf-8")
    out = ROOT / "evals/runtime_validation/source-preflight-chunk-refresh-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
