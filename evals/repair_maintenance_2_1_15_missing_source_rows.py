"""Restore table text omitted by the saved extraction using direct PDF page evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PDF = next((ROOT / "data/raw/standard_estimation").glob("*.pdf"))
from pypdf import PdfReader  # noqa: E402

pages = PdfReader(PDF).pages
page882 = "".join((pages[937].extract_text() or "").split())
page883 = "".join((pages[938].extract_text() or "").split())
assert all(token in page882 for token in ("2.수용성형페인트수동식", "특별인부인2", "보통인부인2", "600", "300", "228", "108", "트럭4.5ton대1"))
assert "트럭2.5ton대1" in page883 and "3.수용성형페인트기계식" in page883

restored = {
    "p938-t2": """2-1-15 차선도색('08, '14, '16, '17, '20, '25, '26년 보완)
2. 수용성형 페인트 수동식
기준 (일당)
특별인부 | 단위 인 | 수량 2
보통인부 | 단위 인 | 수량 2 | 시공량(㎡) 실선 600 | 시공량(㎡) 파선 300 | 시공량(㎡) 횡단보도,\n주차장 228 | 시공량(㎡) 문자,\n기호 108
트럭 | 규격 4.5ton | 단위 대 | 수량 1
비고 | - 노면에 표지병 등이 설치되어 작업능률이 저하되는 경우에는 시공량을 10%까지 감하여 적용한다.""",
    "p939-t0": """2-1-15 차선도색('08, '14, '16, '17, '20, '25, '26년 보완)
3. 수용성형 페인트 기계식
기준 (일당)
특별인부 보통인부 | 단위 인 | 수량 1 | 시공량(㎡) 실선 4,000 | 시공량(㎡) 파선 2,000
라인마커트럭 | 규격 10㎞/hr | 단위 대 | 수량 1
트럭 | 규격 2.5ton | 단위 대 | 수량 1""",
}
changed = []
for rel in ("data/processed/chunks.all.jsonl", "data/processed/chunks.jsonl"):
    path = ROOT / rel
    if not path.exists():
        continue
    lines = path.read_text(encoding="utf-8").splitlines()
    found = set()
    output = []
    for line in lines:
        item = json.loads(line)
        chunk_id = item.get("chunk_id")
        if chunk_id in restored:
            found.add(chunk_id)
            item["text"] = restored[chunk_id]
            item["structure"] = "source_table_rows_repaired_from_original_pdf"
        output.append(json.dumps(item, ensure_ascii=False))
    if "p938-t2" in found and "p939-t0" in found:
        path.write_text("\n".join(output) + "\n", encoding="utf-8")
        changed.append(rel)
    elif found:
        raise SystemExit(f"partial chunk file update declined: {rel} {sorted(found)}")
if "data/processed/chunks.all.jsonl" not in changed:
    raise SystemExit("required source chunks not found")

package_path = ROOT / "data/drafts/specs/유지관리/2-1-15.json"
package = json.loads(package_path.read_text(encoding="utf-8"))
citations = package.setdefault("citations", [])
repairs = [
    ("p938-t2", "특별인부", "수량", "2"),
    ("p938-t2", "보통인부", "수량", "2"),
    ("p938-t2", "보통인부", "시공량(㎡) 실선", "600"),
    ("p938-t2", "보통인부", "시공량(㎡) 파선", "300"),
    ("p938-t2", "보통인부", "시공량(㎡) 횡단보도,\n주차장", "228"),
    ("p938-t2", "보통인부", "시공량(㎡) 문자,\n기호", "108"),
    ("p938-t2", "트럭", "수량", "1"),
    ("p939-t0", "트럭", "수량", "1"),
]
keys = {(x.get("table_id"), x.get("row"), x.get("column"), x.get("value")) for x in citations}
for table_id, row, column, value in repairs:
    key = (table_id, row, column, value)
    if key not in keys:
        citations.append({"table_id": table_id, "row": row, "column": column, "value": value})
        keys.add(key)
package["meta"]["chunks_sha256"] = hashlib.sha256((ROOT / "data/processed/chunks.all.jsonl").read_bytes()).hexdigest()
package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"updated_chunks": changed, "source_chunks_sha256": package["meta"]["chunks_sha256"],
                  "added_cell_citations": len(repairs)}, ensure_ascii=False))
