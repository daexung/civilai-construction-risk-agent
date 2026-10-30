"""Rebuild common 8-3-4 lookup rows and chunk text from the printed PDF grid."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
PDF = ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
SPEC = ROOT / "data/drafts/specs/공통/8-3-4.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"


def main() -> int:
    table = pymupdf.open(PDF)[295].find_tables().tables[2].extract()
    assert len(table) == 3 and len(table[0]) == 11
    codes = [line.strip() for line in table[2][0].splitlines() if line.strip()]
    prefix = codes[0].split("-", 1)[0] + "-"
    codes = [codes[0], *(prefix + code for code in codes[1:])]
    specs = [line.strip() for line in table[2][1].splitlines() if line.strip()]
    specs = ["\n".join(specs[i:i + 2]) for i in range(0, len(specs), 2)]
    assert len(codes) == len(specs) == 5
    assert specs == ["40t\n(80㎾)", "60t\n(120㎾)", "80t\n(160㎾)",
                    "100t\n(200㎾)", "120t\n(240㎾)"]
    fields = ["내용\n시간", "연간표준\n가동시간", "상각\n비율", "정비\n비율",
              "연간\n관리\n비율", "시 간 당(10-7) 상각비\n계수",
              "시 간 당(10-7) 정비비\n계수", "시 간 당(10-7) 관리비\n계수",
              "시 간 당(10-7) 계"]
    columns = {}
    for index, name in enumerate(fields, start=2):
        cells = [line.strip() for line in table[2][index].splitlines() if line.strip()]
        assert len(cells) == 5, (name, cells)
        columns[name] = cells

    package = json.loads(SPEC.read_text(encoding="utf-8"))
    shutil.copy2(SPEC, ROOT / "tmp/8-3-4-pre-source-grid-recovery.json")
    draft = package["draft"]
    input_field = next(item for item in draft["inputs"] if item["name"] == "machine_spec")
    normalized_specs = [value.replace("\n", "") for value in specs]
    assert normalized_specs == input_field["allowed_values"]
    machine_codes = input_field.get("machine_codes", {})
    expected_codes = {spec: code for spec, code in zip(normalized_specs, codes)}
    assert machine_codes == expected_codes, (machine_codes, expected_codes)
    row_fields = {"분류 번호": codes}
    row_fields.update(columns)
    table_spec = draft["tables"][0]
    old_id, old_role, old_source = table_spec["id"], table_spec["role"], table_spec["source"]
    table_spec.update({"id": old_id, "role": old_role, "source": old_source, "unit": None,
                       "values": {spec: {field: row_fields[field][i] for field in row_fields}
                                  for i, spec in enumerate(normalized_specs)},
                       "cite": {"table_id": old_id}})
    package["citations"] = [
        {"table_id": old_id, "row": spec,
         "column": field, "value": row[field]}
        for spec, row in table_spec["values"].items() for field in row
    ]
    shutil.copy2(SPEC, ROOT / "tmp/8-3-4-pre-source-grid-citations.json")
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    replacement = ["8-3-4 [30]포장기계", "(3108) 아스팔트 믹싱플랜트"]
    for i, (code, spec) in enumerate(zip(codes, specs)):
        rendered = spec.replace("\n", " ")
        cells = [code, rendered, *(columns[field][i] for field in fields)]
        labels = ["분류 번호", "규격(ton/hr)", *fields]
        replacement.append(" | ".join(f"{label} {value}" for label, value in zip(labels, cells)))
    old_line = None
    updated = 0
    for i, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != old_id:
            continue
        old_line = line
        chunk["text"] = "\n".join(replacement)
        lines[i] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        updated += 1
    assert updated == 1 and old_line
    (ROOT / "tmp/chunk-p296-t2-pre-source-grid-recovery.json").write_text(old_line + "\n", encoding="utf-8")
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {"table_id": old_id, "pdf_page": 296, "printed_page": 240,
              "source_rows": len(codes), "source_cells": len(codes) * 11,
              "method": "PyMuPDF table-grid extraction; code suffixes grouped to their printed rows; row and column order preserved",
              "spec_backup": "tmp/8-3-4-pre-source-grid-recovery.json",
              "chunk_backup": "tmp/chunk-p296-t2-pre-source-grid-recovery.json",
              "chunks_sha256": hashlib.sha256(CHUNKS.read_bytes()).hexdigest()}
    (ROOT / "evals/runtime_validation/lookup-8-3-4-source-grid-recovery-2026-10-19.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
