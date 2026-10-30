"""Repair two source-confirmed synthetic row-axis citations."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"


def update_spec(path: Path, table_id: str, old_row: str, new_row: str | None) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for citation in data["citations"]:
        if citation.get("table_id") == table_id and citation.get("row") == old_row:
            if new_row is None:
                citation.pop("row")
            else:
                citation["row"] = new_row
            changed += 1
    assert changed > 0, (path, table_id, old_row)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    update_spec(ROOT / "data/drafts/specs/건축/7-1-7.json", "p669-t3",
                "후레싱 잡재료및소모재료 (못,실리콘등) 주재료비의",
                "후레싱 잡재료및소모재료 (못,실리콘등)")
    update_spec(ROOT / "data/drafts/specs/기계설비/11-1-2.json", "p770-t0", "요율", None)

    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(lines):
        chunk = json.loads(line)
        if chunk.get("chunk_id") != "p770-t0":
            continue
        old = "11-1-2 용접식 부설('15년 보완)\n1% | 기계시공 3%"
        assert chunk["text"] == old, repr(chunk["text"])
        chunk["text"] = "11-1-2 용접식 부설('15년 보완)\n인력시공 | 1% | 기계시공 | 3%"
        lines[i] = json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
        found = True
        break
    assert found
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"fixed": ["건축/7-1-7 p669-t3 row axis",
                                  "기계설비/11-1-2 p770-t0 missing column heading"],
                      "source_checked_printed_pages": [613, 714]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
