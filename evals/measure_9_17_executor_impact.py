import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.agent.tools.calc import adjustments

index = json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))
executable = set(index["executable"])
specs = {}
for path in (ROOT / "data/drafts/specs").rglob("*.json"):
    try:
        draft = json.loads(path.read_text(encoding="utf-8"))["draft"]
        specs[draft["id"]] = draft
    except (KeyError, json.JSONDecodeError):
        pass

old_words = adjustments.ACTION_WORDS
new_sentences = adjustments._sentences
new_percent_values = adjustments._percent_values

def old_sentences(chunk):
    import re
    sentences = []
    for raw in chunk["text"].splitlines()[1:]:
        line = raw.split(" | ", 1)[-1].strip()
        line = re.sub(r"(?:^|\s)-\s+(?=[가-힣])", ". ", line)
        sentences.extend(part.strip(" .") + "." for part in re.split(r"(?<=다\.)\s*", line)
                         if part.strip(" ."))
    return sentences

adjustments._sentences = old_sentences
adjustments._percent_values = lambda sentence: [
    __import__("fractions").Fraction(value) / 100
    for value in __import__("re").findall(r"(\d+(?:\.\d+)?)\s*%", sentence)]
adjustments.ACTION_WORDS = ("가산", "감", "요율", "적용", "산정")
old = {}
for ident in executable:
    draft = specs.get(ident)
    if draft:
        params = draft.get("quantity_model", {}).get("params", {})
        items = params.get("surcharges", []) + params.get("note_adjustments", [])
        old[ident] = [adjustments.classify_adjustment(draft, item) for item in items]
adjustments.ACTION_WORDS = old_words
adjustments._sentences = new_sentences
adjustments._percent_values = new_percent_values
changed = []
for ident in executable:
    draft = specs.get(ident)
    if not draft:
        continue
    params = draft.get("quantity_model", {}).get("params", {})
    items = params.get("surcharges", []) + params.get("note_adjustments", [])
    new = [adjustments.classify_adjustment(draft, item) for item in items]
    if old.get(ident, []) != new:
        changed.append({"id": ident, "before": old.get(ident, []), "after": new})

unit_users = []
for ident in executable:
    draft = specs.get(ident)
    if not draft or draft.get("quantity_model", {}).get("name") != "per_unit":
        continue
    rate = draft.get("quantity_model", {}).get("params", {}).get("unit_rate_table", {})
    table = next((item for item in draft.get("tables", []) if item.get("id") == rate.get("table")), {})
    if "장" in str(table.get("unit", "")) or "장" in str(rate.get("basis_by_row", {})):
        unit_users.append({"id": ident, "table_unit": table.get("unit"),
                           "basis_by_row": rate.get("basis_by_row")})

print(json.dumps({"current_executable_count": len(executable),
                  "existing_executable_adjustment_classifications_changed_by_계상": changed,
                  "existing_executable_per_unit_specs_using_장": unit_users},
                 ensure_ascii=False, indent=2))
