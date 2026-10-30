"""Restore the exact boiler table rows and source-backed per-work routing."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data/drafts/specs/기계설비/13-5-1.json"

def main():
    package = json.loads(PATH.read_text(encoding="utf-8"))
    draft = package["draft"]
    tables = {t["id"]: t for t in draft["tables"]}
    p826 = tables["p826-t0"]["values"]
    chain = next(k for k in p826 if k.startswith("Chain block 설치 및 철거"))
    p826[chain] = {"용접공": "0.021", "비계공": "0.028", "일반기계운전사": "0.028", "(윈치운전)": "0.028"}

    p827 = tables["p827-t0"]["values"]
    # Rejoin continuation fragments according to the printed row grid on p.771.
    for fragment in ("Buckstay 조립조정", "조양된 buckstay를 alignment하고", "tiebar 취급함.",
                     "Casing 설치", "성형된 casing을 운반, 조양 alignment", "후 설치"):
        p827.pop(fragment, None)
    p827["Buckstay 조립조정 조양된 buckstay를 alignment하고 tiebar 취급함."] = {
        "플랜트기계설치공": "1.5", "특별인부": "1.5", "플랜트용접공": "1.5"}
    p827["Casing 설치 성형된 casing을 운반, 조양 alignment 후 설치"] = {
        "윈치운전조": "1.01", "비계공": "2.87", "특별인부": "1.33"}

    p827_ref = tables["p827-t1"]["values"]
    for fragment in ("Tube Panel 조립조정", "조양된 Panel을 alignment하고 hangering", "혹은 supporting 후 가고정 해체함"):
        p827_ref.pop(fragment, None)
    p827_ref["Tube Panel 조립조정 조양된 Panel을 alignment하고 hangering 혹은 supporting 후 가고정 해체함"] = {
        "플랜트기계설치공": "1.38", "특별인부": "1.45", "플랜트용접공": "1.16"}

    # The printed note is a rule cell, not a direct labor quantity row.
    note_row = "검사 및 교정 외관검사, 수압시험후 casing leak test 교정 작업(비파괴 시험은 제외)"
    note_col = "기술관리, 포장해체를 제외한 모든 품의 10%"
    p827[note_row] = {note_col: ""}

    tasks = draft["inputs"][0]["allowed_values"]
    task_rows = {
        "기술관리": ("p826-t0", "기술관리 Boiler 본체 설비공사 기간중", "인/일"),
        "포장해체": ("p826-t0", "포장해체 수송을 위해 포장된 목재를 해체하고 목재를 소정 위치에 정리함", "인/㎥"),
        "표면손질": ("p826-t0", "표면손질", "인/㎡"),
        "용접면손질": ("p826-t0", next(k for k in p826 if k.startswith("용접면손질")), "인/㎡"),
        "소운반": ("p826-t0", next(k for k in p826 if k.startswith("소운반")), "인/ton"),
        "Scaffolder 조립설치 및 철거": ("p826-t0", next(k for k in p826 if k.startswith("Scaffolder")), "인/㎡"),
        "Chain block 설치 및 철거": ("p826-t0", chain, "인/개"),
        "윈치설치 및 철거": ("p826-t0", next(k for k in p826 if k.startswith("윈치설치 및 철거")), "인/대"),
        "조양": ("p826-t0", next(k for k in p826 if k.startswith("조양")), "인/ton"),
        "Tube Panel 조립조정": ("p827-t0", next(k for k in p827 if k.startswith("Tube Panel")), "인/개"),
        "Header류 조립조정": ("p827-t0", next(k for k in p827 if k.startswith("Header류")), "인/개"),
        "Buckstay 조립조정": ("p827-t0", next(k for k in p827 if k.startswith("Buckstay")), "인/개"),
        "Tube piece 조립조정": ("p827-t0", next(k for k in p827 if k.startswith("Tube piece")), "인/개"),
        "Casing 조립": ("p827-t0", next(k for k in p827 if k.startswith("Casing 조립")), "인/ton"),
        "Casing 설치": ("p827-t0", next(k for k in p827 if k.startswith("Casing 설치")), "인/ton"),
    }
    assert set(task_rows) == set(tasks), (set(tasks) - set(task_rows), set(task_rows) - set(tasks))
    quantity = next(x for x in draft["inputs"] if x["name"] == "quantity")
    quantity["unit"] = None
    quantity["unit_by"] = {"input": "work_type", "values": {task: unit.split("/", 1)[1] for task, (_, _, unit) in task_rows.items()}}

    params = draft["quantity_model"]["params"]
    rate = params["unit_rate_table"]
    rate.update({
        "table": "p826-t0", "row_input": "work_type", "column_input": None,
        "trades": [], "row_value_map": {task: row for task, (_, row, _) in task_rows.items()},
        "table_selector": {"routes": [
            {"when": {"work_type": task, "boiler_capacity_500mw_over": high},
             "table": ("p827-t1" if high and task in ("Tube Panel 조립조정", "Header류 조립조정") else table)}
            for task, (table, _, _) in task_rows.items()
            for high in (False, True)
        ]},
        "quantity_unit_selector": {"input": "work_type", "values": {
            task: unit.split("/", 1)[1] for task, (_, _, unit) in task_rows.items()}},
        "basis_by_row": {row: unit for _, row, unit in task_rows.values()},
        "trades_by_row": {row: list(tables[table]["values"][row])
                           for table, row, _ in task_rows.values()},
        "resource_units_by_row": {
            task_rows["소운반"][1]: {"건설기계운전조": "인"},
            task_rows["윈치설치 및 철거"][1]: {"건설기계운전조": "조"},
            task_rows["조양"][1]: {"건설기계운전조": "조"},
            task_rows["Casing 조립"][1]: {"건설기계운전조": "조"},
            task_rows["Casing 설치"][1]: {"윈치운전조": "조"},
        },
        "preserve_labor_source_unit": ["건설기계운전조", "윈치운전조"],
    })
    special_rows = {
        "Tube Panel 조립조정": "Tube Panel 조립조정 조양된 Panel을 alignment하고 hangering 혹은 supporting 후 가고정 해체함",
        "Header류 조립조정": next(k for k in p827_ref if k.startswith("Header류")),
    }
    rate["row_value_map_by_table"] = {"p827-t1": special_rows}
    rate["trades_by_row"].update({special_rows[task]: list(p827_ref[special_rows[task]])
                                  for task in special_rows})
    rate["basis_by_row"].update({special_rows[task]: task_rows[task][2]
                                 for task in special_rows})
    params["quantity_input"] = "quantity"
    params["input_rate_adjustments"] = [
        {"operation": "add_source_percent", "name": "검사 및 교정", "percent": "10",
         "kinds": ["labor"], "when": {"work_type": task},
         "cite": {"table_id": "p827-t0", "row": note_row, "column": note_col}}
        for task in tasks if task not in ("기술관리", "포장해체")
    ]
    for block in draft.get("blocked", []):
        if block.get("condition", "").startswith("50만㎾ 이상 보일러의 Buckstay"):
            block.pop("blocked_if", None)
            block["blocked_if_all"] = [
                {"input": "boiler_capacity_500mw_over", "op": "==", "value": True},
                {"input": "work_type", "op": "==", "value": "Buckstay 조립조정"},
            ]
            block["condition"] = "50만㎾ 이상 보일러의 Buckstay 조립조정"
    draft["quantity_model"]["steps"] = [
        "작업구분에 따라 원문의 해당 행·표와 인/일·인/㎥·인/㎡·인/ton·인/개·인/대 중 표시된 분모를 선택한다.",
        "50만㎾ 이상인 경우 Tube Panel 및 Header류 조립조정은 p827-t1 참고 품을 적용한다.",
        "검사 및 교정 품은 기술관리와 포장해체를 제외한 각 작업의 품에 원문 10%를 가산한다.",
        "원문 행의 인 및 조 단위를 보존하고 선택 물량을 곱해 산출한다.",
        "본용접은 각 tube size별 별도 산출이며 비파괴시험은 검사·교정 범위에서 제외한다.",
    ]
    draft["not_calculated"] = [x for x in draft["not_calculated"] if x["item"] != "검사 및 교정"]
    PATH.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"routes": len(task_rows), "tables": sorted({x[0] for x in task_rows.values()}),
                      "references": ["p827-t1:50만㎾ 이상 Tube Panel/Header", "p828-t0:high-capacity Buckstay blocked"]}, ensure_ascii=False))

if __name__ == "__main__":
    main()
