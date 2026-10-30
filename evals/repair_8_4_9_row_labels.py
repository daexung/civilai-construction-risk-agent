"""Restore p342-t0's vertically merged row labels from the source page."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
BACKUP = ROOT / "tmp/chunk-p342-t0-pre-row-label-recovery.json"
REPORT = ROOT / "evals/runtime_validation/chunk-p342-t0-row-label-recovery-2026-10-19.json"
LABELS = iter(["주연료", "잡재료", "선원"])


def main() -> int:
    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    changed = 0
    for index, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != "p342-t0":
            continue
        BACKUP.write_text(line + "\n", encoding="utf-8")
        old_text = chunk["text"]
        names = iter(["주연료", "잡재료", "선원"])
        new_lines = []
        for source_line in old_text.splitlines():
            if source_line.startswith("명칭 | 단위 "):
                name = next(names)
                new_lines.append(source_line.replace("명칭 |", f"명칭 {name} |", 1))
            else:
                new_lines.append(source_line)
        assert sum(x.startswith("명칭 ") for x in new_lines) == 3
        assert all(label in "\n".join(new_lines) for label in ("주연료", "잡재료", "선원"))
        chunk["text"] = "\n".join(new_lines)
        lines[index] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        changed += 1
    assert changed == 1
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    digest = hashlib.sha256(CHUNKS.read_bytes()).hexdigest()
    REPORT.write_text(json.dumps({"table_id": "p342-t0", "pdf_page": 342, "printed_page": 286,
                                  "recovered_row_labels": ["주연료", "잡재료", "선원"],
                                  "method": "page image and PDF text confirmed the three original row labels; inserted into existing source-derived row groups",
                                  "backup": str(BACKUP.relative_to(ROOT)), "chunks_sha256": digest},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"table_id": "p342-t0", "recovered_row_labels": 3, "chunks_sha256": digest}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
