"""Repair only stale text-citation locators with one exact same-section match."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPECS = ROOT / "data/drafts/specs"
BACKUP = ROOT / "tmp/citation-locator-pre-repair-2026-10-18.jsonl"
REPORT = ROOT / "evals/runtime_validation/citation-locator-repair-2026-10-18.json"


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or "")).replace(",", "")


def walk_citations(value, path="root"):
    if isinstance(value, dict):
        if isinstance(value.get("chunk_id"), str) and isinstance(value.get("quote"), str):
            yield value, path
        for key, child in value.items():
            yield from walk_citations(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_citations(child, f"{path}[{index}]")


def main() -> int:
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_section = defaultdict(list)
    by_id = {}
    for chunk in chunks:
        by_section[(chunk.get("division"), chunk.get("section_no"))].append(chunk)
        by_id[chunk.get("chunk_id")] = chunk

    backups = []
    changes = []
    for path in sorted(SPECS.rglob("*.json")):
        raw = path.read_bytes()
        package = json.loads(raw.decode("utf-8"))
        draft = package.get("draft", {})
        section_key = (draft.get("division"), draft.get("section_no"))
        changed = False
        for citation, citation_path in walk_citations(package):
            quote = citation.get("quote", "")
            old_id = citation.get("chunk_id")
            old_chunk = by_id.get(old_id)
            if not quote or (old_chunk and normalize(quote) in normalize(old_chunk.get("text", ""))):
                continue
            matches = [chunk for chunk in by_section[section_key]
                       if normalize(quote) in normalize(chunk.get("text", ""))]
            if len(matches) != 1:
                continue
            citation["chunk_id"] = matches[0]["chunk_id"]
            changed = True
            changes.append({"spec": path.relative_to(ROOT).as_posix(), "citation_path": citation_path,
                            "old_chunk_id": old_id, "new_chunk_id": matches[0]["chunk_id"],
                            "section": section_key[1], "quote": quote})
        if changed:
            backups.append({"path": path.relative_to(ROOT).as_posix(),
                            "sha256": hashlib.sha256(raw).hexdigest(),
                            "content_base64": base64.b64encode(raw).decode("ascii")})
            path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in backups), encoding="utf-8")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps({"record_version": "2026-10-18.unique-citation-repair-v1",
                                  "policy": "exact quote, unique current chunk, same division and section; no fuzzy or cross-section relocation",
                                  "files_changed": len(backups), "citations_repaired": len(changes),
                                  "changes": changes, "backup": BACKUP.relative_to(ROOT).as_posix()},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"files_changed": len(backups), "citations_repaired": len(changes),
                      "backup": BACKUP.relative_to(ROOT).as_posix(),
                      "report": REPORT.relative_to(ROOT).as_posix()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
