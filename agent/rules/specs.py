"""계산 명세를 읽고 절 번호별로 찾는다."""

import json
from functools import cache
from pathlib import Path


SPECS_DIR = Path(__file__).resolve().parent / "specs"
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
    return specs


@cache
def specs_by_section() -> dict[tuple[str, str], list[dict]]:
    sections: dict[tuple[str, str], list[dict]] = {}
    for spec in load_specs().values():
        sections.setdefault((spec["division"], spec["section_no"]), []).append(spec)
    return sections
