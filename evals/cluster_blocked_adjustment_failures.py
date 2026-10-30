import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc.adjustments import classify_adjustment

index = json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))
failed_ids = {item["id"] for item in index["failed"]
              if item.get("reason") == "기본 조합 blocked: 이 할증 규칙은 아직 자동 계산하지 않음"}
for path in sorted((ROOT / "data/drafts/specs").rglob("*.json")):
    package = json.loads(path.read_text(encoding="utf-8"))
    draft = package["draft"]
    if draft["id"] not in failed_ids:
        continue
    params = draft.get("quantity_model", {}).get("params", {})
    items = params.get("surcharges", []) + params.get("note_adjustments", [])
    print(json.dumps({"id": draft["id"], "title": draft.get("title"),
                      "adjustments": [{"where": "surcharge" if item in params.get("surcharges", []) else "note",
                                       "classification": classify_adjustment(draft, item), **item}
                                      for item in items]}, ensure_ascii=False))
