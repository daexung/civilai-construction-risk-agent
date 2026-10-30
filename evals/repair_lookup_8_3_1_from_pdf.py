"""Restore the two source-truncated 8-3-1 matrices from printed PDF tables."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC = ROOT / "data/drafts/specs/공통/8-3-1.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"

FIELDS = [
    "규격\n(㎥)", "내용\n시간", "연간표준\n가동시간", "상각\n비율",
    "정비\n비율", "연간\n관리\n비율", "시 간 당(10-7) 상각비\n계수",
    "시 간 당(10-7) 정비비\n계수", "시 간 당(10-7) 관리비\n계수", "시 간 당(10-7) 계",
]
REPAIRS = {
    "p286-t3": {
        "codes": ["0221-0040", "0221-0070"],
        "columns": [
            ["0.4", "0.7"], ["10,000", "10,000"], ["1,250", "1,250"],
            ["0.9", "0.9"], ["0.7", "0.7"], ["0.1", "0.1"],
            ["900", "900"], ["700", "700"], ["485", "485"], ["2,085", "2,085"],
        ],
        "method": "PDF table grid; both vertically stacked rows retained",
    },
    "p287-t0": {
        "codes": ["0230-0002", "0230-0004", "0230-0006", "0230-0007", "0230-0008", "0230-0010"],
        "columns": [
            ["0.2", "0.4", "0.6", "0.7", "0.8", "1.0"],
            ["3,000"] * 6, ["890"] * 6, ["0.9"] * 6, ["0.85"] * 6,
            ["0.1"] * 6, ["3,000"] * 6, ["2,833"] * 6, ["768"] * 6,
            ["6,601"] * 6,
        ],
        "method": "rendered PDF p.231 table image; six merged code rows and all ten value columns transcribed",
    },
}


def main() -> int:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    tables = {table["id"]: table for table in package["draft"]["tables"]}
    chunk_lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    chunk_by_id = {json.loads(line).get("chunk_id"): (i, json.loads(line))
                   for i, line in enumerate(chunk_lines)}
    backup_spec = ROOT / "tmp/8-3-1-before-pdf-matrix-repair.json"
    backup_chunks = ROOT / "tmp/chunks-before-8-3-1-pdf-matrix-repair.jsonl"
    shutil.copy2(SPEC, backup_spec)
    shutil.copy2(CHUNKS, backup_chunks)
    repaired = {}
    for table_id, data in REPAIRS.items():
        table = tables[table_id]
        assert len(data["columns"]) == len(FIELDS)
        assert all(len(column) == len(data["codes"]) for column in data["columns"])
        table["values"] = {
            code: {field: data["columns"][col][row] for col, field in enumerate(FIELDS)}
            for row, code in enumerate(data["codes"])
        }
        assert table_id in chunk_by_id
        index, chunk = chunk_by_id[table_id]
        rendered = ["8-3-1 [00]토공기계('19년 보완)", table["role"]]
        labels = ["분류 번호", *FIELDS]
        for row, code in enumerate(data["codes"]):
            cells = [code, *(column[row] for column in data["columns"])]
            rendered.append(" | ".join(f"{label} {value}" for label, value in zip(labels, cells)))
        chunk["text"] = "\n".join(rendered)
        chunk["structure"] = "ok"
        chunk["uncertain_record_ids"] = []
        chunk["issues"] = []
        chunk_lines[index] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        repaired[table_id] = {"source_rows": len(data["codes"]), "source_value_cells": len(data["codes"]) * len(FIELDS),
                              "method": data["method"]}

    # p289-t3 had an issue marker from the original row-flattening pass even
    # though the complete grid is extractable. Rebuild it from the source grid.
    with pymupdf.open(PDF) as document:
        grid = document[288].find_tables().tables[3].extract()[2]
    codes = [value.strip() for value in (grid[0] or "").splitlines() if value.strip()]
    prefix = codes[0].split("-", 1)[0] + "-"
    codes = [codes[0], *(value if "-" in value else prefix + value for value in codes[1:])]
    source_columns = [[value.strip() for value in (cell or "").splitlines() if value.strip()]
                      for cell in grid[1:]]
    table = tables["p289-t3"]
    assert codes == [key if "-" in key else prefix + key for key in table["values"]]
    assert all(source_columns[i] == [row[field] for row in table["values"].values()]
               for i, field in enumerate(next(iter(table["values"].values()))))
    index, chunk = chunk_by_id["p289-t3"]
    rendered = ["8-3-1 [00]토공기계('19년 보완)", table["role"]]
    labels = ["분류 번호", *next(iter(table["values"].values())).keys()]
    for row_index, code in enumerate(codes):
        cells = [code, *(column[row_index] for column in source_columns)]
        rendered.append(" | ".join(f"{label} {value}" for label, value in zip(labels, cells)))
    chunk["text"] = "\n".join(rendered)
    chunk["structure"] = "ok"
    chunk["uncertain_record_ids"] = []
    chunk["issues"] = []
    chunk_lines[index] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
    repaired["p289-t3"] = {"source_rows": len(codes), "source_value_cells": sum(map(len, source_columns)),
                           "method": "PDF table grid; rebuilt merged code suffixes and exact columns"}

    package["citations"] = [
        citation for citation in package.get("citations", [])
        if citation.get("table_id") not in REPAIRS
    ] + [
        {"table_id": table_id, "row": code, "column": field, "value": value}
        for table_id in REPAIRS
        for code, row in tables[table_id]["values"].items()
        for field, value in row.items()
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CHUNKS.write_text("\n".join(chunk_lines) + "\n", encoding="utf-8")
    report = {
        "cause": "merged vertical code rows were omitted from extracted source cells; p287-t0 also lost every code label and the total column",
        "repairs": repaired,
        "backups": [str(backup_spec.relative_to(ROOT)), str(backup_chunks.relative_to(ROOT))],
        "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
        "chunks_sha256": hashlib.sha256(CHUNKS.read_bytes()).hexdigest(),
    }
    out = ROOT / "evals/runtime_validation/repair-8-3-1-source-matrices-2026-10-19.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
