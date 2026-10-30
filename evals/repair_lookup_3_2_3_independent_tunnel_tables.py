"""Restore exact small-tunnel table axes and separate them from drill-speed lookup."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/토목/3-2-3.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
TABLE_TEXT = """3-2-3 천공기계의 천공속도
천공속도 표: 소형브레이커 암종별 천공속도(cm/min)
풍화암 27; 연암 20; 보통암 16; 경암 12
점보드릴 굴진장별 천공속도(cm/min)
1.2m 이하 75~85; 1.2~2.0m 이하 85~95; 2.0~3.0m 이하 95~105; 3.0m 초과 105~120
소형터널 굴착 기준: 1발파 진행거리(m)
열: 연암 0.8, 연암 1.0, 연암 1.1, 보통암 1.2, 보통암 1.3, 경암 1.4, 경암 1.5
굴착단면 1㎡당 천공수(도갱면적 5.3㎡): 2.1, 2.4, 3.3, 3.5, 3.8, 4.1, 4.5
굴착단면 1㎡당 천공수(도갱면적 9.7㎡): 2.0, 2.2, 3.2, 3.4, 3.7, 4.0, 4.3
1구멍당 천공길이(m): 1.0, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7
뚫기 1구멍 1m당 폭약량(kg/m): 0.25, 0.30, 0.30, 0.32, 0.35, 0.38, 0.40
심빼기 구멍수: 4, 5, 6, 6, 7, 8, 9"""


def main() -> None:
    for path, backup in ((SPEC, ROOT / "tmp/3-2-3-spec-before-independent-table-routes.json"),
                         (CHUNKS, ROOT / "tmp/chunks-before-3-2-3-independent-table-routes.jsonl")):
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    target = next(field for field in spec["inputs"] if field["name"] == "target_info")
    target["source_table_map"] = {"천공속도": "p396-t0", "소형터널 굴착기준": "p396-t1"}
    fields = {field["name"]: field for field in spec["inputs"]}
    fields["equipment_type"]["when"] = {"input": "target_info", "equals": "천공속도"}
    fields["rock_type_breaker"]["when"] = {"input": "equipment_type", "equals": "소형브레이커"}
    fields["advance_length_jumbo"]["when"] = {"input": "equipment_type", "equals": "점보드릴"}
    metrics = ["굴착단면 1㎡당천공수(도갱면적 5.3㎡)", "굴착단면 1㎡당천공수(도갱면적 9.7㎡)",
               "1구멍당천공길이(m)", "뚫기 1구멍 1m당 폭약량(㎏/m)", "심빼기구멍수"]
    metric = {"name": "small_tunnel_metric", "type": "enum", "allowed_values": metrics,
              "unit": None, "required": True, "ask": "소형터널에서 조회할 기준 항목은 무엇입니까?",
              "source": "PDF 340쪽 [주] ④ 소형터널 굴착 기준 표의 행 구분",
              "source_row_key": True,
              "when": {"input": "target_info", "equals": "소형터널 굴착기준"}}
    fields["small_tunnel_rock_advance"]["allowed_values"] = ["연암 0.8", "연암 1.0", "연암 1.1",
        "보통암 1.2", "보통암 1.3", "경암 1.4", "경암 1.5"]
    fields["small_tunnel_rock_advance"]["ask"] = "암질 및 1발파 진행거리(표의 열)는 무엇입니까? 풍화암은 원문 각주에 따라 연암 0.8m를 적용합니다."
    fields["small_tunnel_rock_advance"]["when"] = {"input": "target_info", "equals": "소형터널 굴착기준"}
    spec["inputs"] = [field for field in spec["inputs"] if field["name"] != "small_tunnel_area"]
    idx = next(i for i, field in enumerate(spec["inputs"]) if field["name"] == "small_tunnel_rock_advance")
    spec["inputs"].insert(idx, metric)
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = CHUNKS.read_text(encoding="utf-8").splitlines()
    found = 0
    for index, raw in enumerate(lines):
        if not raw.strip():
            continue
        chunk = json.loads(raw)
        if chunk.get("chunk_id") == "p396-t1":
            chunk["structure"] = "ok"
            chunk["issues"] = []
            chunk["uncertain_record_ids"] = []
            chunk["text"] = TABLE_TEXT
            lines[index] = json.dumps(chunk, ensure_ascii=False)
            found += 1
    assert found == 1, found
    CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("added table route, exact metric/column axes, and reconstructed p396-t1 grid text")


if __name__ == "__main__":
    main()
