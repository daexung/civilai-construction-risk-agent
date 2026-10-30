import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
failed = json.loads((root / "data/drafts/executable.json").read_text(encoding="utf-8"))["failed"]
specs = {}
for path in (root / "data/drafts/specs").rglob("*.json"):
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))["draft"]
        specs[spec["id"]] = spec
    except (KeyError, json.JSONDecodeError):
        continue
chunks = {}
for line in (root / "data/processed/chunks.all.jsonl").read_text(encoding="utf-8").splitlines():
    if line.strip():
        chunk = json.loads(line)
        chunks[chunk.get("chunk_id")] = chunk
for item in failed:
    reason = item.get("reason", "")
    if "기준 단위 파싱 실패" not in reason:
        continue
    spec = specs[item["id"]]
    params = spec.get("quantity_model", {}).get("params", {})
    rate = params.get("unit_rate_table", {})
    refs = {v for v in (rate.get("table"),) if v}
    tables = [t for t in spec.get("tables", []) if t.get("id") in refs]
    source = chunks.get(rate.get("table"), {})
    print(json.dumps({"id": item["id"], "reason": reason, "inputs": spec.get("inputs"),
                      "rate": rate, "tables": tables, "source_text": source.get("text", "")}, ensure_ascii=False))
