"""Offline regression for shared isolated-Python author/repair/evaluation flow.

Mock callbacks provide candidate text; candidate code always runs in the real
digest-pinned sandbox. This test is not model-generation evidence.
"""
import hashlib
import json
import tempfile
from pathlib import Path

from pipeline.calculation_contract import build_source_bundle
from pipeline.calculation_modules import author_python_candidate, load_case_file
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.tools.calc.per_unit import per_unit

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1"

CALCULATOR = '''from fractions import Fraction
def calculate(spec, inputs, labor_only=False):
    for item in spec.get("blocked", []):
        rule = item.get("blocked_if", {})
        value = inputs.get(rule.get("input"))
        if ((rule.get("op") == "==" and value == rule.get("value")) or
            (rule.get("op") == "!=" and value != rule.get("value"))):
            return {"status": "blocked", "reason": item.get("reason")}
    model = spec["quantity_model"]
    params = model["params"]
    tables = {table["id"]: table for table in spec["tables"]}
    if model["name"] == "per_unit":
        ref = params["unit_rate_table"]
        table = tables[ref["table"]]
        quantity_name = params["quantity_input"]
        quantity = Fraction(str(inputs[quantity_name]))
        quantity_unit = next(field.get("unit") for field in spec["inputs"]
                             if field["name"] == quantity_name)
        column = inputs[ref["column_input"]]
        rates, totals = {}, {}
        for trade in ref["trades"]:
            row = next(name for name in table["values"] if trade in name)
            rate = Fraction(str(table["values"][row][column]))
            rates[trade] = str(rate)
            totals[trade] = str(rate * quantity)
        return {"status": "computed", "labor_unit_rates": rates,
                "labor_total_by_trade": totals, "quantity": str(quantity),
                "quantity_unit": quantity_unit}
    if model["name"] == "adjusted_daily_crew":
        output_ref = params["base_output"]
        table = tables[output_ref["table"]]
        output = Fraction(str(table["values"][output_ref["row"]][inputs[output_ref["column_input"]]]))
        quantity = Fraction(str(inputs[params["quantity_input"]]))
        days = quantity / output
        crew = params["crew"]
        person_days = {trade: str(days * Fraction(str(table["values"][trade][crew["column"]])))
                       for trade in crew["trades"]}
        equipment = params["equipment"]
        equipment_days = {equipment["name"]: str(days * Fraction(str(
            table["values"][equipment["name"]][equipment["column"]])))}
        return {"status": "computed", "daily_output": str(output),
                "work_days": str(days), "person_days": person_days,
                "equipment_days": equipment_days}
    return {"status": "unsupported"}
'''


def _project_paths(section_no: str, table_id: str):
    pdf = next((Path("data/raw/standard_estimation")).glob("*.pdf"))
    chunks = Path("data/processed/chunks.all.jsonl")
    page_map = Path("data/processed/page_map.json")
    source_division = next(json.loads(line)["division"] for line in chunks.read_text(encoding="utf-8").splitlines()
                          if json.loads(line).get("section_no") == section_no
                          and json.loads(line).get("source", {}).get("table_id") == table_id)
    return build_source_bundle(pdf, chunks, page_map, source_division, section_no)


def _contract(meta, spec, cases):
    notes = meta["calculation_notes"]
    # Deliberately poison program-owned fields. The production assembler must
    # replace these with pinned source/case metadata before validation.
    return {
        "contract_version": "model-controlled-wrong-version",
        "source": {
            "pdf_sha256": "0" * 64, "edition": "wrong", "division": "wrong",
            "section_no": "wrong", "pages": [], "citations": [],
            "note_rule_map": [{"note_id": n["note_id"], "rule_ids": ["source-derived-calculation"]}
                              for n in notes],
        },
        "site_inputs": [],
        "application": {"conditions": ["conditions are selected from the cited source table"],
                        "target": {"name": "source table calculation", "unit": "source units"},
                        "order": ["select source row and column", "scale by site quantity"],
                        "system_policies": []},
        "executor": {"kind": "json_interpreter"},
        "verification": {"cases": [{"id": "wrong-case", "citation": "wrong"}]},
    }

def _run_set(author_file: str, final_file: str, section_no: str, division: str):
    authoring = load_case_file(Path("evals/calculation_modules") / author_file)
    final = load_case_file(Path("evals/calculation_modules") / final_file)
    bundle, meta = _project_paths(section_no, authoring[0]["spec"]["tables"][0]["id"])
    division = meta["division"]
    note_ids = {note["note_id"] for note in meta["calculation_notes"]}
    prompts = []
    calls = 0
    author_expectations = [json.dumps(case["expected"], ensure_ascii=False, sort_keys=True)
                           for case in authoring]

    def mock_model(prompt):
        nonlocal calls
        calls += 1
        prompts.append(prompt)
        code = CALCULATOR
        if calls == 1:
            code = code.replace("str(rate * quantity)", "str(rate * quantity * 2)")
            code = code.replace("days = quantity / output", "days = 2 * quantity / output")
        response = {"code": code, "calculation_contract": _contract(meta, authoring[0]["spec"], authoring)}
        return json.dumps(response, ensure_ascii=False)

    with tempfile.TemporaryDirectory(prefix="civilai-offline-candidate-") as directory:
        result = author_python_candidate(
            bundle, authoring, model=mock_model, sandbox_image=IMAGE,
            max_repairs=1, output_dir=Path(directory), evaluation_cases=final,
            require_contract=True, source_pdf_hash=meta["pdf_sha256"],
            source_note_ids=note_ids, division=division, section_no=section_no,
            attempt_log=None,
        )
        result["saved_candidate_count"] = len(list(Path(directory).rglob("*.py")))
        if result.get("path"):
            contract_path = Path(result["path"]).with_suffix(".contract.json")
            assembled = json.loads(contract_path.read_text(encoding="utf-8"))
            result["program_assembled_metadata"] = (
                assembled["contract_version"] == "1.0"
                and assembled["source"]["pdf_sha256"] == meta["pdf_sha256"]
                and assembled["source"]["division"] == meta["division"]
                and assembled["source"]["section_no"] == section_no
                and assembled["executor"]["kind"] == "isolated_python"
                and [case["id"] for case in assembled["verification"]["cases"]]
                    == [case["id"] for case in authoring]
                and assembled["site_inputs"]
                    == [{key: field.get(key) for key in ("name", "type", "unit", "source")}
                        for field in authoring[0]["spec"]["inputs"]]
            )
    final_prompts = "\n".join(prompts)
    assert all(expected not in final_prompts for expected in author_expectations)
    for case in final:
        assert case["id"] not in final_prompts
        assert json.dumps(case["inputs"], ensure_ascii=False, sort_keys=True) not in final_prompts
        assert json.dumps(case["expected"], ensure_ascii=False, sort_keys=True) not in final_prompts
    return result, calls, prompts


def test_per_unit_and_adjusted_daily_crew_share_author_repair_and_holdout_path():
    scenarios = [
        ("steel-fabrication-per-unit-authoring-v3.json", "steel-fabrication-per-unit-final-v3.json",
         "1-2-2", "건축"),
        ("steel-post-equipment-authoring-v2.json", "steel-post-equipment-final-v2.json",
         "2-4-1", "공통"),
    ]
    spacing_case = load_case_file(Path("evals/calculation_modules/steel-post-equipment-authoring-v2.json"))[0]
    invalid_spacing = {**spacing_case["inputs"], "h_pile_spacing": "1.5"}
    assert adjusted_daily_crew(spacing_case["spec"], invalid_spacing, labor_only=True)["status"] == "blocked"
    fabrication_case = load_case_file(Path("evals/calculation_modules/steel-fabrication-per-unit-authoring-v3.json"))[0]
    for name, value in (("construction_method", "other"), ("steel_fabrication_complete", False),
                        ("underground_material_delivery_complete", False)):
        invalid = {**fabrication_case["inputs"], name: value}
        assert per_unit(fabrication_case["spec"], invalid, labor_only=True)["status"] == "blocked"
    for author_file, final_file, section_no, division in scenarios:
        result, calls, prompts = _run_set(author_file, final_file, section_no, division)
        assert calls == result["model_calls"] == 2
        assert result["status"] == "candidate"
        assert result["candidate_state"] == "candidate_unreviewed"
        assert result["runtime_registered"] is False
        assert result["program_assembled_metadata"] is True
        assert result["exit_reason"] == "candidate_unreviewed_after_final_pass"
        assert len(result["attempt_log"]) == 2
        assert "does not match the independent evaluation" in result["attempt_log"][1]["feedback_delivered"]
        assert result["final_evaluation"]["sent_to_model"] is False
        assert result["final_evaluation"]["passed"] == result["final_evaluation"]["total"] == 3
        assert result["attempt_log"][0]["errors"]
        assert not result["attempt_log"][1]["errors"]
        assert result["attempt_log"][0]["case_results"]
        assert all(case["status"] == "computed" for case in result["attempt_log"][0]["case_results"])
        assert all(case["status"] == "computed" for case in result["attempt_log"][1]["case_results"])
        assert all(case["status"] == "ok" and case["actual"]
                   for case in result["final_evaluation"]["cases"])
        assert result["path"]
        assert result["saved_candidate_count"] == 1
