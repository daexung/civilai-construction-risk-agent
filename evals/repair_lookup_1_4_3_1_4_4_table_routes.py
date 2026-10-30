"""Route independent 1-4-3 and 1-4-4 lookup tables by explicit source choice."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(section: str) -> tuple[Path, dict]:
    path = ROOT / "data/drafts/specs/공통" / f"{section}.json"
    package = json.loads(path.read_text(encoding="utf-8"))
    return path, package


def field(spec: dict, name: str) -> dict:
    return next(item for item in spec["inputs"] if item["name"] == name)


def add_selector(spec: dict, choices: dict[str, str], source: str) -> None:
    selector = {
        "name": "lookup_type", "type": "enum", "allowed_values": list(choices),
        "unit": None, "required": True, "ask": "조회할 기준표를 선택해주세요.",
        "source": source, "source_table_map": choices,
    }
    spec["inputs"].insert(0, selector)


def condition(spec: dict, name: str, selected: str) -> None:
    field(spec, name)["when"] = {"input": "lookup_type", "equals": selected}


def main() -> None:
    for section in ("1-4-3", "1-4-4"):
        path, _ = load(section)
        backup = ROOT / "tmp" / f"{section}-spec-before-explicit-table-route.json"
        if not backup.exists():
            backup.write_bytes(path.read_bytes())

    path, package = load("1-4-3")
    spec = package["draft"]
    add_selector(spec, {
        "현장조건": "p80-t0", "열차의 운행빈도": "p80-t1", "건물 층수": "p81-t0",
    }, "PDF 24~25쪽의 1. 현장조건 / 2. 열차의 운행빈도 / 3. 건물 층수 표")
    for name in ("site_condition",):
        condition(spec, name, "현장조건")
    for name in ("train_work_type", "train_frequency"):
        condition(spec, name, "열차의 운행빈도")
    for name in ("building_floor_type", "above_ground_floor", "underground_floor"):
        condition(spec, name, "건물 층수")
    field(spec, "above_ground_floor")["when"] = {
        "input": "building_floor_type", "equals": "지상층",
    }
    field(spec, "underground_floor")["when"] = {
        "input": "building_floor_type", "equals": "지하층",
    }
    train = next(table for table in spec["tables"] if table["id"] == "p80-t1")
    train["values"] = {
        row: {column.removeprefix("적용조건 - 열차운행횟수(8시간) "): value
              for column, value in values.items()}
        for row, values in train["values"].items()
    }
    floors = next(table for table in spec["tables"] if table["id"] == "p81-t0")
    floors["values"] = {
        row: {column.removeprefix("적용조건 "): value for column, value in values.items()}
        for row, values in floors["values"].items()
    }
    open_ended = next(item for item in spec["blocked"]
                      if item.get("condition") == "지상 30층 초과 또는 지하 2층 초과")
    underground = {**open_ended, "blocked_if": {
        "input": "underground_floor", "op": "==", "value": "지하 2층 초과",
    }}
    if not any(item.get("blocked_if", {}).get("input") == "underground_floor"
               for item in spec["blocked"]):
        spec["blocked"].append(underground)
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    path, package = load("1-4-4")
    spec = package["draft"]
    add_selector(spec, {"지세": "p81-t1", "도심지": "p83-t0"},
                 "PDF 25~27쪽의 1. 지세 / 2. 도심지 표")
    condition(spec, "terrain_type", "지세")
    condition(spec, "urban_type", "도심지")
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("added exact table routes and branch conditions to 1-4-3 and 1-4-4")


if __name__ == "__main__":
    main()
