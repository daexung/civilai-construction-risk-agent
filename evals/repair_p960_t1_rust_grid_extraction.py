"""Repair the p960-t1 header/row shift from the visually verified source grid."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
EXPECTED = {
    "chunk_id": "p960-t1",
    "kind": "table",
    "source": {"page": 960, "table_id": "p960-t1"},
}
TEXT = (
    "2-4-3 관세관(스크레이퍼+워터젯트 병행 방법)('10, '11년 보완)\n"
    "구분 | 녹 부 착 상 태 | 적용(%)\n"
    "불량 | 표면전체에 금속성 사태로 두껍게 밀착 생성된 상태 | +5\n"
    "보통 | 표면전체에 녹이 금속성 상태로 얇게 부착되고 전반적으로 돌기상태로 부착된 상태 | 0\n"
    "양호 | 표면전체에 녹이 형성되고 부분적으로 돌기형성이 되었거나 비교적 녹생성이 적고 라이닝만을 하기위한 세척작업이 필요한 경우 | -5"
)

lines = CHUNKS.read_text(encoding="utf-8").splitlines()
matches = []
for index, line in enumerate(lines):
    value = json.loads(line)
    if value.get("chunk_id") == EXPECTED["chunk_id"]:
        matches.append((index, value))
assert len(matches) == 1, len(matches)
index, chunk = matches[0]
assert chunk.get("kind") == "table" and chunk.get("source", {}).get("page") == 960
assert "보통 |" in chunk.get("text", "") and "불량 |" not in chunk.get("text", "")
chunk["text"] = TEXT
lines[index] = json.dumps(chunk, ensure_ascii=False)
CHUNKS.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(json.dumps({"chunk_id": "p960-t1", "physical_page": 960,
                  "repair": "restored exact row labels and applied-percent cells",
                  "visual_source": "tmp/p960-2-4-3-source.png"}, ensure_ascii=False))
