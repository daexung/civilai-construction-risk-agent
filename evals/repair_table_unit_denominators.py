"""per_unit 명세의 단위당 품 표에서 '인', '인, hr'처럼 분모가 빠진 표 단위에 원문 표머리의 분모를 보충한다.

분모는 (1) 청크의 `basis`(예: '(㎥당)') 또는 (2) 그 절 PDF 쪽에서 절 제목 뒤 처음 나오는 '( … 당)' 표기에서만 가져온다.
찾지 못하면 고치지 않는다. 분자 표기('인', 'hr' 등)는 그대로 둔다. 기본은 점검만(dry-run), --apply 시 백업·보고서를 남긴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.agent.tools.calc.per_unit import parse_basis  # noqa: E402

CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
SPECS = ROOT / "data/drafts/specs"
BACKUP = ROOT / "tmp/table-unit-denominator-pre-2026-10-19.jsonl"
REPORT = ROOT / "evals/runtime_validation/table-unit-denominator-2026-10-19.json"
BASIS = re.compile(r"\((?:[^()]*\s)?(\d*\s*[^\s()\d][^()]*?)당\)")


def denominator_from_basis(text: str | None) -> str | None:
    match = BASIS.fullmatch((text or "").strip())
    return match.group(1).replace(" ", "") if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-pdf", action="store_true",
                        help="청크 basis에 없을 때 PDF 절 제목 뒤 표기를 쓴다(기본은 끔: 쪽 안 다른 표의 표기와 섞일 수 있어 사람이 확인)")
    args = parser.parse_args()
    chunks = {}
    for line in CHUNKS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunk = json.loads(line)
            chunks[chunk["chunk_id"]] = chunk
    from pypdf import PdfReader
    reader = PdfReader(next((ROOT / "data/raw/standard_estimation").glob("*.pdf")))
    changed, skipped, backups = [], [], []
    for path in sorted(SPECS.rglob("*.json")):
        original = path.read_text(encoding="utf-8")
        package = json.loads(original)
        spec = package["draft"]
        if package["calc_type"] != "per_unit":
            continue
        rate = spec["quantity_model"]["params"].get("unit_rate_table") or {}
        table = next((t for t in spec["tables"] if t["id"] == rate.get("table")), None)
        if not table or parse_basis(table.get("unit")) is not None:
            continue
        unit = (table.get("unit") or "").strip()
        if "/" in unit or not unit:
            continue
        chunk = chunks.get(table["id"], {})
        denominator = denominator_from_basis(chunk.get("basis")) if chunk.get("basis") else None
        origin = "chunk.basis"
        if denominator is None and args.allow_pdf:
            page = int(re.match(r"p(\d+)", table["id"]).group(1))
            text = reader.pages[page - 1].extract_text() or ""
            start = text.find(spec["section_no"] + " ")
            hit = BASIS.search(text[start:start + 400]) if start >= 0 else None
            denominator = hit.group(1).replace(" ", "") if hit else None
            origin = f"pdf p{page} section heading"
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        if denominator is None or denominator == "일":
            skipped.append({"path": rel, "unit": unit, "reason": "분모를 원문에서 찾지 못했거나 일당(작업조) 표"})
            continue
        parts = [part.strip() for part in unit.split(",") if part.strip()]
        new_unit = ", ".join(f"{part}/{denominator}" for part in parts)
        if parse_basis(new_unit) is None:
            skipped.append({"path": rel, "unit": unit, "reason": f"보충 후에도 분모 해석 불가: {new_unit}"})
            continue
        changed.append({"path": rel, "table": table["id"], "before": unit, "after": new_unit, "origin": origin})
        table["unit"] = new_unit
        backups.append({"path": rel, "content": original})
        if args.apply:
            path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"분모 보충 {len(changed)}건, 건너뜀 {len(skipped)}건 ({'적용' if args.apply else 'dry-run'})")
    for item in changed:
        print("  ", item["path"], item["before"], "->", item["after"], f"[{item['origin']}]")
    if args.apply:
        BACKUP.write_text("\n".join(json.dumps(b, ensure_ascii=False) for b in backups) + "\n", encoding="utf-8")
        REPORT.write_text(json.dumps({"changed": changed, "skipped": skipped}, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
