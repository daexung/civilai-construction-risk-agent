"""계산 명세를 읽고 절 번호별로 찾는다."""

import json
from functools import cache
from pathlib import Path

from agent.tools.calc.per_unit import clean_label


SPECS_DIR = Path(__file__).resolve().parent / "specs"
ROOT = Path(__file__).resolve().parents[2]
REQUIRED = {"id", "division", "section_no", "title", "inputs", "tables", "quantity_model"}


@cache
def load_specs() -> dict[str, dict]:
    specs = {}
    for path in sorted(SPECS_DIR.rglob("*.json")):
        spec = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(spec, dict):
            raise ValueError(f"{path.name}: 명세는 JSON 객체여야 합니다")
        missing = REQUIRED - spec.keys()
        if missing:
            raise ValueError(f"{path.name}: 필수 키 누락: {', '.join(sorted(missing))}")
        if spec["id"] in specs:
            raise ValueError(f"{path.name}: 중복 명세 id: {spec['id']}")
        specs[spec["id"]] = spec
    config = json.loads((ROOT / "agent/rules/drafts_config.json").read_text(encoding="utf-8"))
    executable = set(json.loads((ROOT / "data/drafts/executable.json").read_text(encoding="utf-8"))["executable"])
    reviewed = {(spec["division"], spec["section_no"]) for spec in specs.values()}
    for path in sorted((ROOT / "data/drafts/specs").rglob("*.json")):
        package = json.loads(path.read_text(encoding="utf-8"))
        if package["calc_type"] not in ("daily_crew", "per_unit"):
            continue
        spec = package["draft"]
        section = (spec["division"], spec["section_no"])
        if spec["id"] not in executable or section in reviewed:
            continue
        if not any(f"{section[0]}/{section[1]}".startswith(prefix)
                   for prefix in config["enabled_prefixes"]):
            continue
        spec["review"] = "AI 초안 · 검토 전"
        spec["origin"] = "draft"
        for field in spec["inputs"]:
            if field["type"] == "enum":
                field["labels"] = {value: clean_label(value) for value in field["allowed_values"]}
        specs[spec["id"]] = spec
        reviewed.add(section)
    return specs


@cache
def specs_by_section() -> dict[tuple[str, str], list[dict]]:
    sections: dict[tuple[str, str], list[dict]] = {}
    for spec in load_specs().values():
        sections.setdefault((spec["division"], spec["section_no"]), []).append(spec)
    return sections
