"""Reviewed calculation modules expressed as data, never dynamically executed Python.

Candidate modules use a deliberately small rule format. It is a constrained rule
interpreter, not a Python sandbox. Only reviewed modules in the registry run in
estimate requests.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from fractions import Fraction

from backend.agent.tools.calc.daily_crew import adjusted_daily_crew
from backend.agent.tools.calc.policies import policy_applies

MODULE_DIR = Path(__file__).resolve().parents[4] / "data" / "calculation_modules"
PYTHON_REGISTRY = MODULE_DIR / "approved" / "python-registry.json"


def registered_module_for(spec: dict) -> dict | None:
    """Resolve reviewed module registration from metadata, without trade-specific code branches."""
    directory = MODULE_DIR / "approved"
    if not directory.is_dir():
        return None
    section = {"division": spec.get("division"), "section_no": spec.get("section_no")}
    matches = []
    for path in sorted(directory.glob("*.json")):
        try:
            module = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (module.get("review_status") == "approved_for_runtime"
                and section in module.get("sections", [])):
            matches.append(module)
    return matches[0] if len(matches) == 1 else None


def registered_python_module_for(spec: dict) -> dict | None:
    """Only an explicit reviewed registry entry can select an isolated Python module."""
    try:
        registry = json.loads(PYTHON_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    sections = {"division": spec.get("division"), "section_no": spec.get("section_no")}
    found = [item for item in registry.get("modules", [])
             if item.get("review_status") == "approved_for_runtime" and sections in item.get("sections", [])]
    if len(found) != 1:
        return None
    item = found[0]
    spec_inputs = {field.get("name") for field in spec.get("inputs", [])}
    if not set(item.get("inputs", [])) <= spec_inputs:
        return None
    contract = item.get("calculation_contract")
    if not isinstance(contract, dict):
        return None
    try:
        from pipeline.calculation_contract import validate_contract
        if validate_contract(contract):
            return None
    except Exception:
        return None
    if (contract.get("source", {}).get("pdf_sha256") != item.get("source_hash")
            or contract.get("executor", {}).get("kind") != "isolated_python"
            or contract.get("executor", {}).get("module_version") != item.get("version")):
        return None
    root = (MODULE_DIR / "approved" / "python").resolve()
    path = (root / item.get("file", "")).resolve()
    if root not in path.parents or not path.is_file():
        return None
    import hashlib
    if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("code_sha256"):
        return None
    return {**item, "path": path}


def generated_python_daily_crew(spec: dict, inputs: dict, *, labor_only: bool = False) -> dict:
    module = registered_python_module_for(spec)
    if not module:
        return {"status": "rejected", "reason": "no explicitly registered Python calculation module"}
    try:
        from pipeline.python_sandbox import run_registered_python
        source = module["path"].read_text(encoding="utf-8")
        execution = run_registered_python(source, spec, inputs,
            image=module["sandbox_image"], timeout_seconds=int(module.get("timeout_seconds", 5)))
    except Exception as exc:
        return {"status": "rejected", "reason": f"isolated Python calculation unavailable: {exc}"}
    if execution.get("status") != "ok":
        return {"status": "rejected", "reason": "; ".join(execution.get("errors", []))}
    result = execution.get("result")
    if not isinstance(result, dict) or result.get("status") != "computed":
        return {"status": "rejected", "reason": "registered Python module returned an invalid result contract"}
    result.setdefault("provenance", {})["generated_module"] = {
        "module_id": module.get("id"), "version": module.get("version"),
        "source_hash": module.get("source_hash"), "review_status": module["review_status"],
        "code_sha256": module.get("code_sha256"),
        "executor": execution.get("executor", "digest-pinned Docker sandbox")}
    return result


def check_registered_blocked(spec: dict, inputs: dict) -> dict | None:
    """Keep every legacy block except conditions the matched reviewed module resolves."""
    from backend.agent.tools.calc.daily_crew import check_blocked
    module = registered_module_for(spec) or registered_python_module_for(spec)
    if not module:
        return check_blocked(spec, inputs)
    working = copy.deepcopy(spec)
    known_inputs = {field["name"] for field in working.get("inputs", [])}
    working.setdefault("inputs", []).extend(field for field in module.get("inputs", [])
                                             if field.get("name") not in known_inputs)
    handled = set(module.get("handled_conditions", []))
    working["blocked"] = [item for item in working.get("blocked", [])
                          if item.get("condition") not in handled]
    return check_blocked(working, inputs)


def _condition_matches(when: dict, values: dict) -> bool:
    from fractions import Fraction
    for key, expected in when.items():
        actual = values.get(key)
        if isinstance(expected, dict):
            operator, raw = next(iter(expected.items()))
            try:
                left, right = Fraction(str(actual)), Fraction(str(raw))
            except (ValueError, ZeroDivisionError):
                return False
            if operator == "gt" and not left > right:
                return False
            if operator == "gte" and not left >= right:
                return False
            if operator == "lte" and not left <= right:
                return False
            if operator == "lt" and not left < right:
                return False
            if operator not in ("gt", "gte", "lte", "lt"):
                return False
        elif actual != expected:
            return False
    return True


def _evaluate_expr(expr: object, values: dict):
    """Evaluate the supported JSON arithmetic AST; arbitrary Python is never evaluated."""
    import math
    if not isinstance(expr, dict) or len(expr) != 1:
        raise ValueError("expression node must contain exactly one operator")
    op, arg = next(iter(expr.items()))
    if op == "pi":
        # π to 50 decimal places as a bounded rational constant, avoiding float drift.
        return Fraction(314159265358979323846264338327950288419716939937510, 10**50)
    if op == "number": return Fraction(str(arg))
    if op == "quantity":
        if not isinstance(arg, dict) or set(arg) != {"value", "unit"}:
            raise ValueError("quantity needs value and unit")
        return Fraction(str(arg["value"]))
    if op == "input":
        if not isinstance(arg, str) or arg not in values: raise ValueError(f"unknown input: {arg}")
        return Fraction(str(values[arg]))
    if op in ("floor", "ceil"):
        value = _evaluate_expr(arg, values)
        return math.floor(value) if op == "floor" else math.ceil(value)
    if op in ("add", "sub", "mul", "div"):
        if not isinstance(arg, list) or len(arg) < 2: raise ValueError(f"{op} needs two operands")
        result = _evaluate_expr(arg[0], values)
        for node in arg[1:]:
            operand = _evaluate_expr(node, values)
            if op == "add": result += operand
            elif op == "sub": result -= operand
            elif op == "mul": result *= operand
            else: result /= operand
        return result
    if op == "pow":
        if not isinstance(arg, list) or len(arg) != 2:
            raise ValueError("pow needs a base and exponent")
        base, exponent = (_evaluate_expr(item, values) for item in arg)
        if exponent.denominator != 1 or exponent < 0 or exponent > 4096:
            raise ValueError("pow exponent must be an integer from 0 through 4096")
        return base ** exponent.numerator
    raise ValueError(f"unsupported expression operator: {op}")


def _rule_matches(rule: dict, values: dict) -> bool:
    if "when_expr" not in rule:
        return _condition_matches(rule.get("when", {}), values)
    node = rule["when_expr"]
    if not isinstance(node, dict) or len(node) != 1: raise ValueError("invalid condition AST")
    op, args = next(iter(node.items()))
    if op in ("and", "or"):
        items = [_rule_matches({"when_expr": item}, values) for item in args]
        return all(items) if op == "and" else any(items)
    if op == "not": return not _rule_matches({"when_expr": args}, values)
    if op in ("gt", "gte", "lt", "lte", "eq", "ne") and isinstance(args, list) and len(args) == 2:
        left, right = (_evaluate_expr(item, values) for item in args)
        return {"gt": left > right, "gte": left >= right, "lt": left < right,
                "lte": left <= right, "eq": left == right, "ne": left != right}[op]
    raise ValueError(f"unsupported condition operator: {op}")


def generated_daily_crew(spec: dict, inputs: dict, *, labor_only: bool = False,
                        module_override: dict | None = None) -> dict:
    """Apply reviewed daily-output operations, then reuse existing labor/price flow."""
    module = module_override or registered_module_for(spec)
    module_id = (spec.get("quantity_model", {}).get("params", {}).get("module_id")
                 or (module or {}).get("id"))
    if not module or (module_id and module["id"] != module_id):
        return {"status": "rejected", "reason": f"승인된 계산 모듈이 없습니다: {module_id}"}
    working = copy.deepcopy(spec)
    known_inputs = {field["name"] for field in working.get("inputs", [])}
    working.setdefault("inputs", []).extend(field for field in module.get("inputs", [])
                                             if field.get("name") not in known_inputs)
    handled = set(module.get("handled_conditions", []))
    working["blocked"] = [item for item in working.get("blocked", [])
                          if item.get("condition") not in handled]
    model = working["quantity_model"]
    params = model["params"]
    table_id = params["base_output"]["table"]
    row = params["base_output"].get("row", params["base_output"].get("row_input"))
    column_input = params["base_output"].get("column_input")
    column = inputs.get(column_input)
    if not row or column is None:
        return {"status": "unresolvable", "reason": "기준 시공량 행 또는 열이 지정되지 않았습니다"}
    table = next((item for item in working["tables"] if item["id"] == table_id), None)
    if not table or row not in table["values"] or column not in table["values"][row]:
        return {"status": "unresolvable", "reason": "계산 모듈의 기준 시공량 표 연결이 잘못되었습니다"}

    applied = []
    output_adjustments = []
    rules = list(module.get("rules", []))
    application_order = (module.get("calculation_contract", {}).get("application", {}).get("order", []))
    if application_order:
        rank = {rule_id: index for index, rule_id in enumerate(application_order)
                if isinstance(rule_id, str)}
        rules = [rule for _, rule in sorted(enumerate(rules), key=lambda pair: (
            rank.get(pair[1].get("id"), len(rank)), pair[0]))]
    for rule in rules:
        try:
            matches = _rule_matches(rule, inputs)
        except (ValueError, TypeError, ZeroDivisionError) as exc:
            return {"status": "rejected", "reason": f"계산 모듈 조건식 오류: {exc}"}
        if not matches:
            continue
        operation = rule.get("operation")
        policy_ref = rule.get("system_policy_ref")
        if policy_ref and not policy_applies(policy_ref, module, spec):
            return {"status": "rejected", "reason": f"system policy {policy_ref} is not authorized for this module scope"}
        if operation == "apply_system_policy":
            try:
                from backend.agent.tools.calc.policies import evaluate_policy
                evaluated = evaluate_policy(policy_ref, inputs)
            except (KeyError, ValueError, TypeError, ZeroDivisionError) as exc:
                return {"status": "rejected", "reason": f"system policy evaluation failed: {exc}"}
            output_adjustments.append({"operation": "multiply_output", "value": str(evaluated["multiplier"]),
                "source": rule.get("source"), "reason": rule.get("reason"),
                "system_policy_ref": policy_ref, "system_assumption": evaluated["system_assumption"],
                "policy_version": evaluated["policy_version"], "official_source": evaluated["source"],
                "intervals": evaluated["intervals"]})
            applied.append({"operation": operation, "source": rule.get("source"),
                "system_policy_ref": policy_ref, "policy_version": evaluated["policy_version"],
                "official_source": evaluated["source"], "system_assumption": evaluated["system_assumption"],
                "intervals": evaluated["intervals"], "value": str(evaluated["multiplier"])})
            continue
        if operation in ("ask_policy", "require_field"):
            pending = [name for name in rule.get("policy_inputs", []) if name not in inputs or inputs[name] is None or inputs[name] == ""]
            if pending:
                fields = {field["name"]: field for field in working["inputs"]}
                return {"status": "ask", "missing": pending, "questions": [{
                    "name": name, "ask": rule.get("asks", {}).get(name, fields.get(name, {}).get("ask", "")),
                    "allowed_values": fields.get(name, {}).get("allowed_values", "담당자 결정 필요"),
                    "source": rule.get("source"),
                } for name in pending], "policy": {"source": rule.get("source"), "reason": rule.get("reason")}}
            continue
        if operation not in ("multiply_output", "add_output"):
            return {"status": "rejected", "reason": f"허용되지 않은 규칙 연산: {operation}"}
        try:
            operand = (_evaluate_expr(rule["value_expr"], inputs) if "value_expr" in rule
                       else Fraction(str(rule["value"])))
        except (ValueError, ZeroDivisionError, KeyError):
            return {"status": "rejected", "reason": "계산 모듈의 정확한 수치 형식이 잘못되었습니다"}
        output_adjustments.append({"operation": operation, "value": str(operand),
                                   "source": rule.get("source"), "reason": rule.get("reason"),
                                   **({"system_policy_ref": policy_ref} if policy_ref else {})})
        applied.append({"operation": operation, "value": str(operand), "source": rule.get("source"),
                        "reason": rule.get("reason"),
                        **({"system_policy_ref": rule["system_policy_ref"]}
                           if rule.get("system_policy_ref") else {})})

    # Existing calculator owns typed validation, missing questions, exact units, trace, and crew math.
    result = adjusted_daily_crew(working, inputs, labor_only=labor_only,
                                 daily_output_adjustments=output_adjustments)
    if result.get("status") == "computed":
        result["not_calculated"] = list(result.get("not_calculated", [])) + [
            {"item": unresolved["name"], "source": unresolved.get("source"),
             "reason": unresolved["reason"]}
            for unresolved in module.get("conditional_unpriced", [])
            if all(inputs.get(name) == value for name, value in unresolved.get("when", {}).items())]
        result.setdefault("provenance", {})["generated_module"] = {
            "module_id": module["id"], "version": module["version"],
            "source_hash": module["source_hash"], "rules": applied,
            "review_status": module.get("review_status", "candidate_unreviewed"),
        }
    return result
