"""Route each selected tank-cleaning task to its own exact source row/input."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "data/drafts/specs/기계설비/13-4-7.json"

TASKS = {
    "task_scoop": ("떠내기", "area"),
    "task_remove_dirt": ("오물제거", "area"),
    "task_remove_rust": ("녹제거", "area"),
    "task_pour_back": ("되붓기", "area"),
    "task_drum_transport": ("드럼운반", "area"),
    "task_wipe": ("닦아내기", "area"),
}
DOOR_CITE = {
    "table_id": "p825-t1", "row": "비고",
    "value": "Clean Out Door가 없는 탱크는 떠내기 및 오물제거에 각각 20%씩 가산한다.",
}
RUST_CITE = {
    "table_id": "p825-t1", "row": "비고",
    "value": "추가작업 부분(Shell, Roof 등)에 대해서는 탱크 청소 품의 80%를 별도 계상한다.",
}


def main() -> None:
    package = json.loads(SPEC.read_text(encoding="utf-8"))
    spec = package["draft"]
    params = spec["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    rate.update({"table": "p825-t1", "row_input": None, "column_input": None, "trades": []})
    params["quantity_input"] = "area"
    params["surcharges"] = []
    activities = []
    for input_name, (row, quantity_input) in TASKS.items():
        activity = {
            "table": "p825-t1", "basis": "㎡", "quantity_input": quantity_input,
            "trades": ["보통인부"], "row_by_trade": {"보통인부": row},
            "column_selector": "fluid_type",
            "when": {input_name: True},
            "source": f"PDF 769쪽 13-4-7 표: {row} 행, 보통인부 열",
        }
        if input_name in ("task_scoop", "task_remove_dirt"):
            activity["multipliers"] = [{
                "when": {"has_clean_out_door": False}, "factor": "1.2", "cite": DOOR_CITE,
            }]
        activities.append(activity)

    extra = {
        "table": "p825-t1", "basis": "㎡", "quantity_input": "extra_rust_removal_area",
        "trades": ["보통인부"], "row_by_trade": {"보통인부": "녹제거"},
        "column_selector": "fluid_type", "quantity_multiplier": "0.8",
        "when": {"task_remove_rust": True}, "cite": RUST_CITE,
        "source": "PDF 769쪽 13-4-7 비고: 추가 Shell/Roof 녹제거 면적은 원 품의 80% 별도 계상",
    }
    activities.append(extra)
    params["additional_unit_rates"] = activities
    for note in params.get("note_adjustments", []):
        note["implemented_by"] = "additional_unit_rates task-specific source row/multiplier"
    extra_field = next(field for field in spec["inputs"] if field["name"] == "extra_rust_removal_area")
    extra_field["when"] = {"input": "task_remove_rust", "equals": True}
    spec["quantity_model"]["steps"] = [
        "선택한 유체(fluid_type)와 수행 작업(task_*)에 맞는 p825-t1의 보통인부 행을 조회한다.",
        "선택 작업별 단위당 노무량에 탱크 바닥면적(area)을 곱해 합산한다.",
        "Clean Out Door가 없는 경우 떠내기와 오물제거에 각각 원문 20%를 가산한다.",
        "녹제거 추가 부분(extra_rust_removal_area)은 원문 80% 계수를 적용해 별도 산출한다.",
        "유해가스 발생 시 본 절에 요율이 없어 계산을 차단한다.",
    ]
    package["open_questions"] = [
        "유해가스 할증률은 원문에서 다른 기준을 참조하므로 승인된 요율을 찾기 전까지 해당 조합을 차단합니다.",
        "표의 대시(물에 대한 되붓기·드럼운반)는 원문상 계수 부재로 해당 조합을 계산하지 않습니다.",
        "소모자재는 원문 지시대로 별도 산정하며, 이 계산에서 재료비는 산출하지 않습니다.",
    ]
    SPEC.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"id": spec["id"], "task_routes": len(TASKS),
                      "separate_rust_area_route": True, "source_multipliers": 2}, ensure_ascii=False))


if __name__ == "__main__":
    main()
