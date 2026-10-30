"""LLM-assisted authoring for constrained JSON or isolated-Python candidates.

Python source is never run in the host process. Candidate artifacts remain
unregistered until a separate human review and explicit registration.
"""
from __future__ import annotations

import json
import copy
import re
import math
import argparse
import hashlib
import datetime
import re
from pathlib import Path
from typing import Callable
from fractions import Fraction

CANDIDATE_DIR = Path(__file__).resolve().parents[1] / "data" / "calculation_modules" / "candidates"
ATTEMPT_LOG = CANDIDATE_DIR / "authoring-attempts.jsonl"
DEFAULT_CONFIG = Path(__file__).with_name("draft_specs_config.json")
PROCESSED_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"
ALLOWED_OPERATIONS = {"multiply_output", "add_output", "require_field", "apply_system_policy"}
_ID = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

# Gemini receives this semantic slice only. Identity, source hashes/pages, executor
# and verification metadata are assembled locally after semantic validation.
SEMANTIC_AUTHORING_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["conditions", "handled_condition_map", "target", "order", "inputs", "rules", "policy_references", "note_interpretations"],
    "properties": {
        "conditions": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "handled_condition_map": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["condition", "rule_ids"], "properties": {
                "condition": {"type": "string"}, "rule_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1}}}},
        "target": {"type": "object", "additionalProperties": False, "required": ["name", "unit"],
                    "properties": {"name": {"type": "string"}, "unit": {"type": "string"}}},
        "order": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "inputs": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["name", "type", "unit", "required", "ask"], "properties": {
                "name": {"type": "string"}, "type": {"type": "string", "enum": ["enum", "boolean", "nonnegative_integer", "positive_rational", "percentage", "source_reference", "positive_currency"]}, "unit": {"type": ["string", "null"]},
                "required": {"type": "boolean"}, "ask": {"type": "string"},
                "allowed_values": {"type": "array"}}}},
        "rules": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["id", "when", "operation", "source_note_ids", "reason"], "properties": {
                "id": {"type": "string"}, "when": {"type": "object"},
                "operation": {"type": "string", "enum": ["multiply_output", "add_output", "require_field"]},
                "value": {"type": ["string", "number"]}, "value_expr": {"type": "object"},
                "source_note_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "reason": {"type": "string"}}}},
        "policy_references": {"type": "array", "items": {"type": "object", "additionalProperties": False,
            "required": ["id", "when", "policy_id", "source_note_ids", "reason"], "properties": {
                "id": {"type": "string"}, "when": {"type": "object"}, "policy_id": {"type": "string"},
                "source_note_ids": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "reason": {"type": "string"}}}},
        "note_interpretations": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
            "required": ["note_id", "rule_ids", "excluded_reason"], "properties": {
                "note_id": {"type": "string"}, "rule_ids": {"type": "array", "items": {"type": "string"}},
                "excluded_reason": {"type": "string"}}}},
    },
}


def _schema_errors(value: object, schema: dict, path: str = "$",) -> list[str]:
    """Small local validator for the exact JSON Schema subset sent to Gemini."""
    errors = []
    expected_type = schema.get("type")
    types = expected_type if isinstance(expected_type, list) else [expected_type]
    checks = {"object": lambda x: isinstance(x, dict), "array": lambda x: isinstance(x, list),
              "string": lambda x: isinstance(x, str), "boolean": lambda x: isinstance(x, bool),
              "number": lambda x: type(x) in (int, float), "null": lambda x: x is None}
    if types != [None] and not any(checks[t](value) for t in types):
        return [f"{path}: expected {types}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is outside enum")
    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value: errors.append(f"{path}.{name}: required")
        if schema.get("additionalProperties") is False:
            errors.extend(f"{path}.{name}: additional property" for name in value if name not in schema.get("properties", {}))
        for name, child in schema.get("properties", {}).items():
            if name in value: errors.extend(_schema_errors(value[name], child, f"{path}.{name}"))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0): errors.append(f"{path}: too few items")
        for index, item in enumerate(value):
            errors.extend(_schema_errors(item, schema.get("items", {}), f"{path}[{index}]"))
    return errors


def _source_note_index(bundle: dict) -> tuple[dict[str, dict], dict[str, str], list[str]]:
    canonical, aliases, errors = {}, {}, []
    for item in bundle.get("calculation_notes", []):
        note_id = str(item.get("evidence_id") or item.get("note_id") or "")
        if not note_id:
            errors.append("source calculation evidence is missing a stable evidence ID")
            continue
        if note_id in canonical:
            errors.append(f"duplicate source evidence ID {note_id}")
        canonical[note_id] = item
        aliases[note_id] = note_id
        for alias in item.get("legacy_aliases", []):
            if alias in aliases and aliases[alias] != note_id:
                aliases.pop(alias, None)
                errors.append(f"ambiguous legacy source-note alias {alias}")
            elif alias not in aliases:
                aliases[alias] = note_id
    return canonical, aliases, errors


def validate_registered_policy_sources(source_bundle: str,
                                       allowed_system_policies: set[str] | None = None) -> list[str]:
    """Fail closed before generation unless every scoped policy has its actual source note."""
    try:
        bundle = json.loads(source_bundle)
    except (TypeError, ValueError):
        return ["source bundle is not valid JSON for registered-policy preflight"]
    if not isinstance(bundle, dict) or not bundle.get("pdf_sha256"):
        return ["registered-policy preflight requires a PDF-backed source bundle"] if allowed_system_policies else []
    from backend.agent.tools.calc.policies import resolve_policy_source_evidence
    errors = []
    for policy_id in sorted(allowed_system_policies or set()):
        _, policy_errors = resolve_policy_source_evidence(policy_id, bundle)
        errors.extend(policy_errors)
    return errors


def validate_semantic_authoring(value: object, source_bundle: str,
                                allowed_system_policies: set[str] | None = None,
                                known_blocked_conditions: dict[str, dict] | set[str] | None = None,
                                known_input_fields: dict[str, dict] | None = None) -> list[str]:
    errors = _schema_errors(value, SEMANTIC_AUTHORING_SCHEMA)
    if errors: return errors
    bundle = json.loads(source_bundle)
    note_by_id, note_aliases, index_errors = _source_note_index(bundle)
    errors.extend(index_errors)
    note_ids = set(note_by_id)
    blocked_map = (known_blocked_conditions if isinstance(known_blocked_conditions, dict)
                   else {label: {} for label in (known_blocked_conditions or set())})
    mapped = [note_aliases.get(item["note_id"], item["note_id"]) for item in value["note_interpretations"]]
    if len(mapped) != len(set(mapped)) or set(mapped) != note_ids:
        errors.append("note interpretations must map every supplied source note exactly once")
    normalized_rules = [{**rule, "kind": "json_rule"} for rule in value["rules"]]
    normalized_rules.extend({**rule, "kind": "system_policy_ref"} for rule in value["policy_references"])
    if not normalized_rules: errors.append("at least one executable rule or policy reference is required")
    rule_ids = {rule["id"] for rule in normalized_rules}
    if len(rule_ids) != len(normalized_rules): errors.append("semantic rule IDs must be unique across rules and policy references")
    for item in value["note_interpretations"]:
        if not item["rule_ids"] and not item["excluded_reason"].strip():
            errors.append(f"source note {item['note_id']} needs rule IDs or an evidence-backed exclusion")
        if set(item["rule_ids"]) - rule_ids: errors.append(f"source note {item['note_id']} references an unknown rule")
    input_names = set()
    for field in value["inputs"]:
        name = field["name"]
        if not _ID.fullmatch(name.replace("_", "-")):
            errors.append(f"input {name!r} must use a stable field identifier")
        if name in input_names: errors.append(f"duplicate semantic input {name}")
        input_names.add(name)
        if known_input_fields and name in known_input_fields:
            errors.append(f"input {name} already exists in the typed site-input contract; reference it without redefining it")
    known_names = set(known_input_fields or {}) | input_names
    for rule in normalized_rules:
        resolved_notes = {note_aliases.get(note_id, note_id) for note_id in rule["source_note_ids"]}
        if resolved_notes - note_ids: errors.append(f"rule {rule['id']} cites an unknown source note")
        if not rule["when"]: errors.append(f"rule {rule['id']} requires explicit application conditions")
        def find_input_names(node):
            found = set()
            if isinstance(node, dict):
                if set(node) == {"input"} and isinstance(node["input"], str): found.add(node["input"])
                for child in node.values(): found |= find_input_names(child)
            elif isinstance(node, list):
                for child in node: found |= find_input_names(child)
            return found
        refs = find_input_names(rule["when"]) | find_input_names(rule.get("value_expr", {}))
        refs.update(str(name) for name in rule["when"] if isinstance(name, str))
        unknown = refs - known_names
        if unknown: errors.append(f"rule {rule['id']} references undeclared site facts: {sorted(unknown)}")
        if rule["kind"] == "system_policy_ref":
            if rule.get("policy_id") not in (allowed_system_policies or set()):
                errors.append(f"rule {rule['id']} references a policy not authorized for this section")
        elif rule.get("operation") not in {"multiply_output", "add_output", "require_field"}:
            errors.append(f"rule {rule['id']} needs a supported executable operation")
    handled_labels = [item["condition"] for item in value["handled_condition_map"]]
    if len(handled_labels) != len(set(handled_labels)):
        errors.append("handled condition labels must be unique")
    for item in value["handled_condition_map"]:
        label = item["condition"]
        if label not in blocked_map:
            errors.append(f"handled condition {label!r} is not an existing exact spec condition")
            continue
        if set(item["rule_ids"]) - rule_ids:
            errors.append(f"handled condition {label!r} maps to unknown rule IDs")
            continue
        blocked_if = blocked_map[label].get("blocked_if", {}) if isinstance(blocked_map[label], dict) else {}
        if blocked_if:
            input_name, operator, expected = blocked_if.get("input"), blocked_if.get("op"), blocked_if.get("value")
            op_key = {">": "gt", ">=": "gte", "<": "lt", "<=": "lte", "==": "eq", "!=": "ne"}.get(operator)
            def covers(rule):
                actual = rule.get("when", {}).get(input_name, object())
                if isinstance(actual, dict): return actual.get(op_key, object()) == expected
                if operator == "==": return actual == expected
                if operator == "!=": return actual != expected
                return actual == expected
            if not any(covers(rule) for rule in normalized_rules if rule["id"] in item["rule_ids"]):
                errors.append(f"handled condition {label!r} has no mapped rule covering its structured blocked_if")
    from backend.agent.tools.calc.policies import POLICIES
    errors.extend(validate_registered_policy_sources(source_bundle, allowed_system_policies))
    for policy_id in allowed_system_policies or set():
        policy = POLICIES.get(policy_id)
        if not policy:
            continue
        expected_note_id = policy.get("source_note_id")
        if bundle.get("pdf_sha256"):
            from backend.agent.tools.calc.policies import resolve_policy_source_evidence
            evidence, _ = resolve_policy_source_evidence(policy_id, bundle)
            expected_note_id = evidence.get("evidence_id") if evidence else None
        note = next((item for item in value["note_interpretations"]
                     if note_aliases.get(item["note_id"], item["note_id"]) == expected_note_id), None)
        policy_rule_ids = {rule["id"] for rule in normalized_rules
                           if rule["kind"] == "system_policy_ref" and rule.get("policy_id") == policy_id
                           and expected_note_id in {note_aliases.get(note_id, note_id) for note_id in rule["source_note_ids"]}}
        if note is None or not policy_rule_ids.intersection(note["rule_ids"]):
            errors.append(f"registered policy {policy_id} must explicitly interpret its anchored source note")
    return errors


def assemble_semantic_candidate(semantic: dict, source_bundle: str, verification_cases: list[dict], *,
                                allowed_system_policies: set[str] | None = None,
                                known_blocked_conditions: dict[str, dict] | set[str] | None = None,
                                known_input_fields: dict[str, dict] | None = None) -> dict:
    """Join model-authored meaning to deterministic source/executor/test metadata."""
    errors = validate_semantic_authoring(semantic, source_bundle, allowed_system_policies,
                                         known_blocked_conditions, known_input_fields)
    if errors: raise ValueError("semantic authoring invalid: " + "; ".join(errors))
    bundle = json.loads(source_bundle)
    from backend.agent.tools.calc.policies import POLICIES
    note_by_id, note_aliases, _ = _source_note_index(bundle)
    pages = bundle["full_section_pdf_pages"]
    page_records = [{"pdf_page": item["pdf_page"], "printed_page": item.get("printed_page")} for item in pages]
    rules = []
    normalized_rules = [{**item, "kind": "json_rule"} for item in semantic["rules"]]
    normalized_rules.extend({**item, "kind": "system_policy_ref"} for item in semantic["policy_references"])
    for item in normalized_rules:
        citations = []
        for note_id in item["source_note_ids"]:
            canonical_id = note_aliases[note_id]
            note = note_by_id[canonical_id]
            chunk = note.get("chunk", {})
            cited_pages = [note.get("location", {}).get("pdf_page")]
            cited_pages.extend(int(p) for p in chunk.get("pages", []) if str(p).isdigit())
            citations.extend(cited_pages)
        pages_text = ", ".join(f"PDF p.{p} (printed p.{next((x.get('printed_page') for x in pages if x['pdf_page'] == p), None)})" for p in sorted(set(citations)))
        rule = {"id": item["id"], "when": item["when"], "source": f"{bundle['edition']} {bundle['division']} {bundle['section_no']}; {pages_text}",
                "reason": item["reason"]}
        if item["kind"] == "system_policy_ref":
            pid = item["policy_id"]
            rule.update({"operation": "apply_system_policy", "system_policy_ref": pid})
        else:
            rule["operation"] = item["operation"]
            for key in ("value", "value_expr"):
                if key in item: rule[key] = item[key]
        rules.append(rule)
    note_map = [{"note_id": note_aliases[item["note_id"]], "rule_ids": item["rule_ids"],
                 **({"excluded_reason": item["excluded_reason"]} if item["excluded_reason"].strip() else {})}
                for item in semantic["note_interpretations"]]
    policy_ids = sorted({item.get("policy_id") for item in normalized_rules if item["kind"] == "system_policy_ref"})
    app = {"conditions": semantic["conditions"], "target": semantic["target"], "order": semantic["order"],
           "system_policies": policy_ids,
           "policy_versions": {pid: POLICIES[pid]["version"] for pid in policy_ids},
           "policy_sources": {pid: POLICIES[pid]["source"] for pid in policy_ids}}
    from backend.agent.tools.calc.policies import resolve_policy_source_evidence
    policy_evidence = {}
    policy_note_ids = {}
    for pid in policy_ids:
        evidence, source_errors = resolve_policy_source_evidence(pid, bundle)
        if source_errors or not evidence:
            raise ValueError("registered policy source preflight failed: " + "; ".join(source_errors))
        locator = POLICIES[pid]["source_locator"]
        policy_evidence[pid] = {**locator, "evidence_id": evidence["evidence_id"]}
        policy_note_ids[pid] = evidence["evidence_id"]
    base_spec_names = {field.get("name") for case in verification_cases
                       for field in case.get("spec", {}).get("inputs", [])}
    referenced_names = set()
    def collect_input_names(node):
        if isinstance(node, dict):
            if set(node) == {"input"} and isinstance(node["input"], str): referenced_names.add(node["input"])
            for key, child in node.items():
                if key not in {"gt", "gte", "lt", "lte", "eq", "ne", "and", "or", "not", "add", "sub", "mul", "div", "floor", "ceil", "number", "quantity", "input"} and isinstance(key, str):
                    referenced_names.add(key)
                collect_input_names(child)
        elif isinstance(node, list):
            for child in node: collect_input_names(child)
    for rule in normalized_rules:
        collect_input_names(rule.get("when", {})); collect_input_names(rule.get("value_expr", {}))
    semantic_fields = {field["name"]: field for field in semantic["inputs"]}
    site_input_map = {}
    for name in referenced_names | set(semantic_fields):
        source_field = (known_input_fields or {}).get(name) or semantic_fields.get(name)
        if source_field:
            site_input_map[name] = {**source_field, "source": source_field.get("source", "user")}
    site_inputs = list(site_input_map.values())
    candidate_inputs = [site_input_map[name] for name in site_input_map
                        if name not in base_spec_names]
    identity = hashlib.sha256(f"{bundle['division']}|{bundle['section_no']}|{bundle['pdf_sha256']}".encode()).hexdigest()[:24]
    module_id = f"generated-{identity}"
    candidate = {"id": module_id, "version": "1.0.0", "source_hash": bundle["pdf_sha256"],
        "sections": [{"division": bundle["division"], "section_no": bundle["section_no"]}],
        "inputs": candidate_inputs,
        "handled_conditions": [item["condition"] for item in semantic["handled_condition_map"]], "rules": rules,
        "system_policy_ids": policy_ids, "policy_note_ids": policy_note_ids,
        "policy_evidence_ids": {pid: item["evidence_id"] for pid, item in policy_evidence.items()},
        "policy_versions": app["policy_versions"], "policy_sources": app["policy_sources"],
        "calculation_contract": {"contract_version": "1.0", "source": {"edition": bundle["edition"],
            "pdf_sha256": bundle["pdf_sha256"], "pages": page_records,
            "citations": [{"note_id": note_id, "evidence_id": note_id,
                           "kind": note_by_id[note_id].get("kind"),
                           "location": note_by_id[note_id].get("location"),
                           "content": note_by_id[note_id].get("content")}
                          for note_id in sorted(note_by_id)],
            "policy_evidence": policy_evidence, "note_rule_map": note_map},
            "site_inputs": site_inputs, "application": app,
            "executor": {"kind": "json_interpreter", "module_version": "1.0.0"},
            "verification": {"cases": [{"id": item["id"], "citation": item.get("citation", "trusted evaluation case")}
                                          for item in verification_cases]}}}
    full_errors = validate_candidate(candidate, allowed_system_policies=allowed_system_policies, require_contract=True)
    if full_errors: raise ValueError("assembled candidate invalid: " + "; ".join(full_errors))
    return candidate


class ResponseTruncatedError(RuntimeError):
    """Provider reported that its output-token allowance ended the response."""


def _safe_repair_feedback(errors: list[str], cases: list[dict]) -> str:
    """Keep private reference and observed values out of repair prompts."""
    safe = []
    for error in errors:
        match = re.match(r"case\[(\d+)\]:\s*(.*)", error)
        if match:
            index = int(match.group(1))
            case_id = cases[index].get("id", f"case-{index + 1}") if index < len(cases) else f"case-{index + 1}"
            field = match.group(2).split(":", 1)[0].strip()
            if field and field != match.group(2):
                safe.append(f"authoring case {case_id}: output field {field} failed")
            else:
                safe.append(f"authoring case {case_id}: trusted execution check failed")
        elif error.startswith("invalid JSON:"):
            safe.append("candidate response is not valid JSON")
        elif error.startswith("model call failed:"):
            safe.append("candidate generation did not complete successfully")
        else:
            safe.append(error.split(" expected ", 1)[0])
    return "\n".join(dict.fromkeys(safe))


def build_json_authoring_prompt(source_bundle: str, independent_cases: list[dict], *,
                               allowed_system_policies: set[str] | None = None) -> str:
    """Build the prompt once so countTokens can measure the exact model input."""
    try:
        parsed_bundle = json.loads(source_bundle)
        source_pdf_hash = parsed_bundle.get("pdf_sha256") if isinstance(parsed_bundle, dict) else None
    except ValueError:
        source_pdf_hash = None
    source_prefix = f"EXPECTED SOURCE PDF SHA256: {source_pdf_hash}\n" if source_pdf_hash else ""
    verification_ids = [case.get("id", f"case-{index + 1}") for index, case in enumerate(independent_cases)]
    from backend.agent.tools.calc.policies import POLICIES
    policy_details = [{"id": policy_id, **POLICIES[policy_id]}
                      for policy_id in sorted(allowed_system_policies or set()) if policy_id in POLICIES]
    return (source_prefix + "Return one concise JSON object with id (lowercase slug), version, source_hash, sections, calculation_contract, optional typed inputs, handled_conditions, and a non-empty top-level rules array. "
            "Contract shape: calculation_contract={contract_version:'1.0',source:{edition,pdf_sha256,pages,citations,note_rule_map},site_inputs,application:{conditions,target,order,system_policies},executor:{kind:'json_interpreter',module_version:<version>},verification:{cases}}. "
            "note_rule_map is a LIST of {note_id,rule_ids} entries, one per supplied calculation note; cite every rule. "
            "site_inputs entries each require name,type,unit (use null when dimensionless),source; optional ask/allowed_values/required are allowed. "
            "Put executable rules at top-level rules, never inside executor. Each rule needs id, when, operation, value_expr, source; use system_policy_ref when applicable. "
            "Source page objects distinguish 1-based actual pdf_page from printed_page; preserve both exactly as given. "
            "Citations should identify section, PDF page, printed page, table/note ID; do not copy whole source text. "
            "Give every rule a stable unique id and map each source calculation note to its rule IDs or evidence-backed exclusion. "
            f"calculation_contract.verification.cases must contain only {{id,citation}} entries with these exact IDs and order: {verification_ids}; do not add inputs, outputs, expected values, or test logic. "
            "New inputs use the existing typed field contract (name,type,allowed_values,unit,required,ask,source). "
            "Rules may use multiply_output, add_output, or require_field for missing site facts. "
            "Never ask users to choose calculation rates, formulas, accumulation, or source documents. "
            "Do not invent system policy; use only an explicitly provided policy, preserve its formula exactly, and do not reinterpret it as a different accumulation method. "
            "Optional value_expr/when_expr use JSON operators number/input/add/sub/mul/div/pow/floor/ceil "
            "and comparison/and/or/not. Output unit is daily production only. No Python or imports. "
            "Do not copy source tables or repeat prose into the candidate; encode each calculation-relevant rule once, "
            "retain all rule conditions and citations, and keep explanations brief.\n"
            f"AUTHORIZED SYSTEM POLICIES (their statements and scoped system formulas are authoritative system assumptions, not official-source quotations): {policy_details}\n"
            f"SOURCE BUNDLE:\n{source_bundle}")


def build_semantic_authoring_prompt(source_bundle: str, *,
                                   allowed_system_policies: set[str] | None = None,
                                   known_blocked_conditions: dict[str, dict] | set[str] | None = None,
                                   known_input_fields: dict[str, dict] | None = None) -> str:
    """Ask only for interpretation; deterministic contract metadata stays local."""
    from backend.agent.tools.calc.policies import POLICIES
    bundle = json.loads(source_bundle)
    from backend.agent.tools.calc.policies import resolve_policy_source_evidence
    policies = [{"id": pid, "version": POLICIES[pid]["version"],
                 "source_evidence_id": (resolve_policy_source_evidence(pid, bundle)[0] or {}).get("evidence_id"),
                 "source_locator": POLICIES[pid].get("source_locator"),
                 "scope": POLICIES[pid]["scope"], "official_source": POLICIES[pid]["source"],
                 "system_assumption": POLICIES[pid]["statement"]}
                for pid in sorted(allowed_system_policies or set()) if pid in POLICIES]
    note_ids = [str(item["note_id"]) for item in bundle.get("calculation_notes", [])]
    return ("Interpret calculation rules from the supplied source evidence and return only the JSON object matching the provided schema. "
        "Create executable rules for each calculation-relevant note and explicitly map every supplied note ID to rule IDs or an evidence-based exclusion. "
        "Put source formulas only in rules. Put authorized registered policies only in policy_references; that schema has no operation or formula field by design. "
        "The policy text is a system assumption, not an official quotation. For other rules, encode source conditions, operation, value/expression, units, and source_note_ids. "
        "Copy handled condition labels exactly and map each only to rule IDs whose executable conditions cover its structured blocked_if predicate. Preserve blocked conditions that no rule implements. "
        "Use existing typed input names directly in rule conditions and expressions; do not redeclare them in inputs. Put only genuinely new site facts in inputs. "
        "Do not invent rules, omit source notes, request calculation policies from users, or output module IDs, versions, hashes, page mappings, executor settings, verification cases, or expected results. "
        f"Source note IDs that must each be accounted for exactly once: {json.dumps(note_ids, ensure_ascii=False)}\n"
        f"Existing spec blocked conditions and executable predicates (mark handled only when mapped rules cover the predicate): {json.dumps(known_blocked_conditions or {}, ensure_ascii=False)}\n"
        f"Existing typed site-fact fields; reuse these exact identifiers/types/units where they match the evidence: {json.dumps(known_input_fields or {}, ensure_ascii=False)}\n"
        f"Authorized policy references: {json.dumps(policies, ensure_ascii=False)}\n"
        f"SOURCE EVIDENCE BUNDLE:\n{source_bundle}")


def collect_known_input_fields(cases: list[dict]) -> dict[str, dict]:
    """Collect already-reviewed typed fields from the spec and its registered module."""
    from backend.agent.tools.calc.generated import registered_module_for
    fields: dict[str, dict] = {}
    for case in cases:
        spec = case.get("spec", {})
        sources = [spec.get("inputs", [])]
        module = registered_module_for(spec) if isinstance(spec, dict) else None
        if module:
            sources.append(module.get("inputs", []))
        for group in sources:
            for field in group:
                name = field.get("name")
                if not name: continue
                current = fields.get(name)
                if current and any(current.get(key) != field.get(key) for key in ("type", "unit", "allowed_values")):
                    raise ValueError(f"conflicting existing site-input contract for {name}")
                fields.setdefault(name, copy.deepcopy(field))
    return fields


def author_semantic_candidate(source_bundle: str, independent_cases: list[dict], *,
                              model: Callable[[str], str], max_repairs: int = 0,
                              allowed_system_policies: set[str] | None = None,
                              output_dir: Path = CANDIDATE_DIR,
                              attempt_log: Path | None = ATTEMPT_LOG) -> dict:
    """Generate semantic JSON, assemble deterministic metadata, and run trusted cases."""
    if not independent_cases:
        return {"status": "failed", "attempts": 0, "errors": ["independent authoring cases are required"]}
    if not 0 <= max_repairs <= 2:
        raise ValueError("semantic candidate repairs are limited to two")
    preflight_errors = validate_registered_policy_sources(source_bundle, allowed_system_policies)
    if preflight_errors:
        return {"status": "failed", "attempts": 0,
                "errors": ["registered-policy source preflight failed: " + error for error in preflight_errors],
                "model_calls": 0, "exit_reason": "source_preflight_failed", "attempt_log": []}
    known_conditions = {str(item.get("condition")): item for case in independent_cases
                        for item in case.get("spec", {}).get("blocked", []) if item.get("condition")}
    known_fields = collect_known_input_fields(independent_cases)
    prompt = build_semantic_authoring_prompt(source_bundle, allowed_system_policies=allowed_system_policies,
        known_blocked_conditions=known_conditions, known_input_fields=known_fields)
    attempts, feedback, errors = [], "", []
    candidate = None
    for index in range(max_repairs + 1):
        try:
            raw = model(prompt + feedback)
        except Exception as exc:
            errors = [f"generation request failed: {type(exc).__name__}"]
            attempts.append({"attempt": index + 1, "errors": errors, "candidate_id": None})
            break
        try:
            semantic = json.loads(raw)
            errors = validate_semantic_authoring(semantic, source_bundle, allowed_system_policies,
                                                 known_conditions, known_fields)
            if not errors:
                candidate = assemble_semantic_candidate(semantic, source_bundle, independent_cases,
                    allowed_system_policies=allowed_system_policies, known_blocked_conditions=known_conditions,
                    known_input_fields=known_fields)
                for case_index, case in enumerate(independent_cases):
                    failures = run_candidate_case(candidate, {**case,
                        "allowed_system_policies": sorted(allowed_system_policies or set())})
                    errors.extend(f"case[{case_index}]: {message}" for message in failures)
        except (ValueError, TypeError, KeyError) as exc:
            errors = [f"semantic assembly/validation failed: {exc}"]
        attempts.append({"attempt": index + 1, "errors": list(errors),
                         "feedback_delivered": feedback.split("\n", 1)[-1] if feedback else "",
                         "candidate_id": candidate.get("id") if candidate and not errors else None})
        if not errors: break
        if index < max_repairs and (index == 0 or attempts[-2].get("errors") != errors):
            feedback = "\nRepair only the reported schema/semantic failure labels; do not remove source rules or change site questions into policy questions.\n" + _safe_repair_feedback(errors, independent_cases)
        elif index < max_repairs:
            attempts[-1]["repair_suppressed"] = "identical semantic failure repeated; no same-error retry"
            break
    if attempt_log:
        path = Path(attempt_log); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            for item in attempts:
                stream.write(json.dumps({"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "source_bundle_sha256": hashlib.sha256(source_bundle.encode()).hexdigest(),
                    "pipeline": "semantic-authoring-v1", **item}, ensure_ascii=False) + "\n")
    if errors or candidate is None:
        return {"status": "failed", "attempts": len(attempts), "model_calls": len(attempts),
                "errors": errors, "attempt_log": attempts,
                "exit_reason": (attempts[-1].get("repair_suppressed", "generation_or_validation_failed")
                                if attempts else "no_candidate")}
    output_dir = Path(output_dir).resolve()
    approved = (Path(__file__).resolve().parents[1] / "data" / "calculation_modules" / "approved").resolve()
    if output_dir == approved or approved in output_dir.parents:
        return {"status": "failed", "attempts": len(attempts), "errors": ["candidate output path overlaps approved registry"]}
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{candidate['id']}.json"
    if path.exists(): return {"status": "failed", "attempts": len(attempts), "errors": ["candidate already exists; refusing overwrite"]}
    path.write_text(json.dumps({**candidate, "review_status": "candidate_unreviewed"}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "candidate", "attempts": len(attempts), "model_calls": len(attempts),
            "path": str(path), "review_status": "candidate_unreviewed", "attempt_log": attempts,
            "exit_reason": "candidate_unreviewed"}


def _expr(expr: object, inputs: dict):
    """Evaluate a tiny JSON expression tree; this is data interpretation, never Python execution."""
    if not isinstance(expr, dict) or len(expr) != 1:
        raise ValueError("expression node must contain exactly one operator")
    op, arg = next(iter(expr.items()))
    if op == "input":
        if not isinstance(arg, str) or arg not in inputs:
            raise ValueError(f"unknown expression input: {arg}")
        value = inputs[arg]
        if type(value) not in (int, str):
            raise ValueError(f"non-numeric expression input: {arg}")
        return Fraction(str(value))
    if op == "number":
        return Fraction(str(arg))
    if op == "quantity":
        if not isinstance(arg, dict) or set(arg) != {"value", "unit"}:
            raise ValueError("quantity needs value and unit")
        return Fraction(str(arg["value"]))
    if op == "pow":
        if not isinstance(arg, list) or len(arg) != 2:
            raise ValueError("pow needs a base and exponent")
        base, exponent = (_expr(item, inputs) for item in arg)
        if exponent.denominator != 1 or exponent < 0 or exponent > 4096:
            raise ValueError("pow exponent must be an integer from 0 through 4096")
        return base ** exponent.numerator
    if op in ("floor", "ceil"):
        value = _expr(arg, inputs)
        return math.floor(value) if op == "floor" else math.ceil(value)
    if op in ("add", "sub", "mul", "div"):
        if not isinstance(arg, list) or len(arg) < 2:
            raise ValueError(f"{op} needs at least two operands")
        values = [_expr(node, inputs) for node in arg]
        result = values[0]
        for value in values[1:]:
            if op == "add": result += value
            elif op == "sub": result -= value
            elif op == "mul": result *= value
            else: result /= value
        return result
    raise ValueError(f"unsupported expression operator: {op}")


def _ast_size(node: object, depth: int = 0) -> tuple[int, int]:
    if depth > 24:
        raise ValueError("expression nesting exceeds 24 levels")
    if isinstance(node, dict):
        total = 1
        max_depth = depth
        for child in node.values():
            count, child_depth = _ast_size(child, depth + 1)
            total += count
            max_depth = max(max_depth, child_depth)
        return total, max_depth
    if isinstance(node, list):
        total = 1
        max_depth = depth
        for child in node:
            count, child_depth = _ast_size(child, depth + 1)
            total += count
            max_depth = max(max_depth, child_depth)
        return total, max_depth
    return 1, depth


def _condition(rule: dict, inputs: dict) -> bool:
    if "when_expr" not in rule:
        from backend.agent.tools.calc.generated import _condition_matches
        return _condition_matches(rule.get("when", {}), inputs)
    node = rule["when_expr"]
    if not isinstance(node, dict) or len(node) != 1:
        raise ValueError("when_expr must be a one-operator object")
    op, args = next(iter(node.items()))
    if op in ("and", "or"):
        if not isinstance(args, list) or not args:
            raise ValueError(f"{op} needs a non-empty list")
        result = [_condition({"when_expr": item}, inputs) for item in args]
        return all(result) if op == "and" else any(result)
    if op == "not":
        return not _condition({"when_expr": args}, inputs)
    if op in ("gt", "gte", "lt", "lte", "eq", "ne") and isinstance(args, list) and len(args) == 2:
        left = _expr(args[0], inputs)
        right = _expr(args[1], inputs)
        return {"gt": left > right, "gte": left >= right, "lt": left < right,
                "lte": left <= right, "eq": left == right, "ne": left != right}[op]
    raise ValueError(f"unsupported condition expression: {op}")


def _unit_dimension(unit: object) -> tuple[tuple[str, int], ...]:
    if unit in (None, "", "1"):
        return ()
    text = str(unit).strip().lower().replace("²", "2").replace("³", "3")
    aliases = {"m": "length", "meter": "length", "cm": "length", "mm": "length",
               "m2": "area", "㎡": "area", "m^2": "area", "m3": "volume", "㎥": "volume",
               "m^3": "volume", "day": "time", "days": "time", "hr": "time", "hour": "time",
               "ea": "count", "unit": "count"}
    return ((aliases.get(text, text), 1),)


def _expr_dimension(node: object, input_units: dict[str, object]) -> tuple[tuple[str, int], ...]:
    if not isinstance(node, dict) or len(node) != 1:
        raise ValueError("expression node must be an object")
    op, arg = next(iter(node.items()))
    if op == "number":
        return ()
    if op == "quantity":
        if not isinstance(arg, dict) or set(arg) != {"value", "unit"}:
            raise ValueError("quantity requires numeric value and explicit unit")
        Fraction(str(arg["value"]))
        return _unit_dimension(arg["unit"])
    if op == "input":
        if arg not in input_units:
            raise ValueError(f"unknown input {arg}")
        return _unit_dimension(input_units[arg])
    if op in ("floor", "ceil"):
        return _expr_dimension(arg, input_units)
    if op in ("add", "sub"):
        dimensions = [_expr_dimension(item, input_units) for item in arg]
        if len(set(dimensions)) != 1:
            raise ValueError(f"{op} operands have incompatible units")
        return dimensions[0]
    if op in ("mul", "div"):
        result = {}
        for index, item in enumerate(arg):
            dimension = dict(_expr_dimension(item, input_units))
            sign = 1 if op == "mul" or index == 0 else -1
            for name, exponent in dimension.items():
                result[name] = result.get(name, 0) + sign * exponent
        return tuple(sorted((name, exponent) for name, exponent in result.items() if exponent))
    if op == "pow":
        base, exponent = arg
        if _expr_dimension(exponent, input_units):
            raise ValueError("power exponent must be dimensionless")
        exponent_op, exponent_arg = next(iter(exponent.items()))
        if exponent_op in ("ceil", "floor"):
            multiplier = 1
        elif exponent_op == "number" and Fraction(str(exponent_arg)).denominator == 1:
            multiplier = Fraction(str(exponent_arg)).numerator
        else:
            raise ValueError("power exponent must be a literal integer or floor/ceil expression")
        return tuple((name, power * multiplier)
                     for name, power in _expr_dimension(base, input_units))
    raise ValueError(f"unit inference does not support {op}")


def validate_candidate_units(candidate: dict, spec: dict) -> list[str]:
    fields = {item.get("name"): item.get("unit") for item in spec.get("inputs", [])}
    fields.update({item.get("name"): item.get("unit") for item in candidate.get("inputs", [])})
    errors = []
    for index, rule in enumerate(candidate.get("rules", [])):
        if rule.get("operation") in ("multiply_output", "add_output") and "value_expr" in rule:
            try:
                dimension = _expr_dimension(rule["value_expr"], fields)
                if rule.get("operation") == "multiply_output" and dimension:
                    raise ValueError("output multiplier must be dimensionless")
                if rule.get("operation") == "add_output":
                    target = candidate.get("calculation_contract", {}).get("application", {}).get("target", {})
                    target_dimension = _unit_dimension(target.get("unit"))
                    if dimension != target_dimension:
                        raise ValueError(f"add_output must use target unit {target.get('unit')!r}")
            except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
                errors.append(f"rules[{index}] unit error: {exc}")
        def walk(node):
            if isinstance(node, dict):
                if len(node) == 1:
                    op, args = next(iter(node.items()))
                    if op in ("gt", "gte", "lt", "lte", "eq", "ne") and isinstance(args, list) and len(args) == 2:
                        if _expr_dimension(args[0], fields) != _expr_dimension(args[1], fields):
                            raise ValueError(f"condition {op} compares incompatible units")
                    for child in node.values(): walk(child)
            elif isinstance(node, list):
                for child in node: walk(child)
        if "when_expr" in rule:
            try: walk(rule["when_expr"])
            except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
                errors.append(f"rules[{index}] condition unit error: {exc}")
    return errors


def validate_candidate(candidate: object, *, allowed_system_policies: set[str] | None = None,
                       require_contract: bool = False) -> list[str]:
    errors = []
    if not isinstance(candidate, dict):
        return ["candidate must be a JSON object"]
    if not isinstance(candidate.get("id"), str) or not candidate["id"].strip():
        errors.append("id is required")
    elif not _ID.fullmatch(candidate["id"]):
        errors.append("id must be a lowercase slug (a-z, 0-9, hyphen), max 64 characters")
    if not isinstance(candidate.get("source_hash"), str) or not candidate["source_hash"].strip():
        errors.append("source_hash is required")
    if not isinstance(candidate.get("sections"), list) or not candidate["sections"]:
        errors.append("sections must identify every division and section_no covered")
    if require_contract or "calculation_contract" in candidate:
        from pipeline.calculation_contract import validate_contract
        errors.extend(validate_contract(candidate.get("calculation_contract")))
        if isinstance(candidate.get("calculation_contract"), dict):
            source_hash = candidate.get("source_hash")
            contract_hash = candidate["calculation_contract"].get("source", {}).get("pdf_sha256")
            if source_hash != contract_hash:
                errors.append("source_hash must match calculation_contract.source.pdf_sha256")
            if candidate["calculation_contract"].get("executor", {}).get("module_version") != candidate.get("version"):
                errors.append("executor.module_version must match the candidate version")
            policy_ids = set(candidate["calculation_contract"].get("application", {}).get("system_policies", []))
            referenced = {rule.get("system_policy_ref") for rule in candidate.get("rules", [])
                          if isinstance(rule, dict) and rule.get("system_policy_ref")}
            if referenced != policy_ids:
                errors.append("calculation_contract.application.system_policies must match the rule references exactly")
            from backend.agent.tools.calc.policies import POLICIES
            app = candidate["calculation_contract"].get("application", {})
            for policy_id in referenced:
                if policy_id in POLICIES:
                    policy = POLICIES[policy_id]
                    if app.get("policy_versions", {}).get(policy_id) != policy["version"]:
                        errors.append(f"system policy {policy_id} version does not match the registered implementation")
                    if app.get("policy_sources", {}).get(policy_id) != policy["source"]:
                        errors.append(f"system policy {policy_id} source citation does not match the registered source")
            if set(candidate.get("system_policy_ids", [])) != referenced:
                errors.append("candidate system_policy_ids must match calculation_contract references")
            source_contract = candidate["calculation_contract"].get("source", {})
            evidence_map = source_contract.get("policy_evidence", {})
            citations = source_contract.get("citations", [])
            source_pages = source_contract.get("pages", [])
            for pid in referenced:
                if pid not in POLICIES:
                    continue
                locator = POLICIES[pid].get("source_locator", {})
                anchored = evidence_map.get(pid)
                if not isinstance(anchored, dict):
                    errors.append(f"system policy {pid} requires a stable PDF/table evidence locator")
                    continue
                if any(anchored.get(key) != locator.get(key) for key in
                       ("edition", "pdf_sha256", "division", "section_no", "pdf_page", "printed_page", "kind",
                        "table_heading", "label", "parser_table_id", "table_bbox", "required_text")):
                    errors.append(f"system policy {pid} evidence locator differs from the registered source")
                if not any(page.get("pdf_page") == locator.get("pdf_page")
                           and page.get("printed_page") == locator.get("printed_page") for page in source_pages):
                    errors.append(f"system policy {pid} PDF/printed page pair is absent from source pages")
                citation = next((entry for entry in citations
                                 if entry.get("evidence_id") == anchored.get("evidence_id")), None)
                required = " ".join(str(locator.get("required_text", "")).split())
                cited = " ".join(str((citation or {}).get("content", "")).split())
                if (not citation or citation.get("kind") != "table_note"
                        or required not in cited
                        or citation.get("location", {}).get("pdf_page") != locator.get("pdf_page")
                        or citation.get("location", {}).get("printed_page") != locator.get("printed_page")
                        or citation.get("location", {}).get("table_heading") != locator.get("table_heading")
                        or citation.get("location", {}).get("label") != locator.get("label")
                        or citation.get("location", {}).get("parser_table_id") != locator.get("parser_table_id")
                        or citation.get("location", {}).get("table_bbox") != locator.get("table_bbox")):
                    errors.append(f"system policy {pid} citation does not match the registered PDF table note")
            expected_policy_note_ids = {pid: (evidence_map[pid].get("evidence_id") if pid in evidence_map
                                              else POLICIES[pid]["source_note_id"])
                                        for pid in referenced if pid in POLICIES}
            if candidate.get("policy_note_ids", {}) != expected_policy_note_ids:
                errors.append("candidate policy note anchors do not match registered source evidence")
            if evidence_map and candidate.get("policy_evidence_ids", {}) != {
                    pid: evidence_map[pid].get("evidence_id") for pid in referenced if pid in evidence_map}:
                errors.append("candidate policy evidence IDs do not match registered source locators")
            if candidate.get("policy_versions", {}) != app.get("policy_versions", {}):
                errors.append("candidate policy versions must match the calculation contract")
            if candidate.get("policy_sources", {}) != app.get("policy_sources", {}):
                errors.append("candidate policy sources must match the calculation contract")
            for policy_id in referenced:
                if policy_id in POLICIES:
                    note_id = (evidence_map.get(policy_id, {}).get("evidence_id")
                               or POLICIES[policy_id]["source_note_id"])
                    mapped_note = next((item for item in candidate["calculation_contract"]["source"]["note_rule_map"]
                                        if item.get("note_id") == note_id), None)
                    policy_rule_ids = {rule.get("id") for rule in candidate.get("rules", [])
                                       if rule.get("system_policy_ref") == policy_id}
                    if not mapped_note or not policy_rule_ids.intersection(mapped_note.get("rule_ids", [])):
                        errors.append(f"system policy {policy_id} is not mapped to its anchored source note")
    declared = candidate.get("inputs", [])
    if not isinstance(declared, list):
        errors.append("inputs must be a list of typed field definitions")
    else:
        names = set()
        supported_types = {"enum", "boolean", "nonnegative_integer", "positive_rational",
                           "percentage", "source_reference", "positive_currency"}
        for index, field in enumerate(declared):
            if not isinstance(field, dict) or not isinstance(field.get("name"), str) or not _ID.fullmatch(field["name"].replace("_", "-")):
                errors.append(f"inputs[{index}] needs a valid name")
                continue
            if field["name"] in names:
                errors.append(f"inputs[{index}] duplicates a field name")
            names.add(field["name"])
            forbidden_name = re.search(r"deduction|reduction|interval_(count|number)|accumulation|calculation_(source|formula|method|document)|policy_(choice|mode)", field["name"], re.I)
            ask_text = field.get("ask", "") if isinstance(field.get("ask", ""), str) else ""
            forbidden_ask = any(term in ask_text for term in (
                "감산", "감액률", "누적", "계산 근거", "근거 문서", "감산 구간", "산식 선택", "계산 방식"))
            if forbidden_name or forbidden_ask:
                errors.append(f"inputs[{index}] asks the user for a calculation policy or source decision")
            if field.get("type") not in supported_types:
                errors.append(f"inputs[{index}].type is unsupported")
            if not isinstance(field.get("ask"), str) or not field["ask"]:
                errors.append(f"inputs[{index}].ask is required")
            if field.get("type") == "enum" and not isinstance(field.get("allowed_values"), list):
                errors.append(f"inputs[{index}].allowed_values must be a list for enum fields")
            if field.get("type") == "boolean" and field.get("allowed_values") not in ([True, False], [False, True]):
                errors.append(f"inputs[{index}].allowed_values must be true/false")
    if not isinstance(candidate.get("rules"), list) or not candidate["rules"]:
        errors.append("rules must be a non-empty list")
        return errors
    if len(candidate["rules"]) > 128:
        errors.append("rules may contain at most 128 entries")
    rule_ids = set()
    for index, rule in enumerate(candidate["rules"]):
        if not isinstance(rule, dict):
            errors.append(f"rules[{index}] must be an object")
            continue
        if require_contract:
            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not _ID.fullmatch(rule_id.replace("_", "-")):
                errors.append(f"rules[{index}].id is required by calculation_contract v1")
            elif rule_id in rule_ids:
                errors.append(f"rules[{index}].id is duplicated")
            else:
                rule_ids.add(rule_id)
        if not ((isinstance(rule.get("when"), dict) and rule["when"])
                or isinstance(rule.get("when_expr"), dict)):
            errors.append(f"rules[{index}].when is required")
        operation = rule.get("operation")
        if operation not in ALLOWED_OPERATIONS:
            errors.append(f"rules[{index}].operation is unsupported")
        if operation == "apply_system_policy" and not rule.get("system_policy_ref"):
            errors.append(f"rules[{index}].apply_system_policy requires an authorized policy reference")
        if rule.get("system_policy_ref") and (operation != "apply_system_policy" or any(
                key in rule for key in ("value", "value_expr"))):
            errors.append(f"rules[{index}] must reference the registered policy without rewriting its formula")
        if operation in {"multiply_output", "add_output"}:
            if require_contract and operation == "add_output" and "value_expr" not in rule:
                errors.append(f"rules[{index}].add_output requires value_expr for dimensional checking")
            if "value_expr" in rule:
                if not isinstance(rule["value_expr"], dict):
                    errors.append(f"rules[{index}].value_expr must be an object")
            else:
                try:
                    value = Fraction(str(rule["value"]))
                    if operation == "multiply_output" and value <= 0:
                        errors.append(f"rules[{index}].value multiplier must be positive")
                except (KeyError, ValueError, ZeroDivisionError):
                    errors.append(f"rules[{index}].value must be an exact rational")
        if operation == "ask_policy":
            errors.append(f"rules[{index}].operation ask_policy is retired; ask only for site facts")
        if operation == "require_field" and (not isinstance(rule.get("policy_inputs"), list)
                or not rule["policy_inputs"] or not isinstance(rule.get("asks"), dict)
                or not isinstance(rule.get("source"), str) or not rule["source"]):
            errors.append(f"rules[{index}] require_field inputs, asks, and source are required")
        policy_ref = rule.get("system_policy_ref")
        if policy_ref and (allowed_system_policies is None or policy_ref not in allowed_system_policies):
            errors.append(f"rules[{index}].system_policy_ref is not authorized for this section")
        if not isinstance(rule.get("source"), str) or not rule["source"]:
            errors.append(f"rules[{index}].source is required")
        if "value_expr" in rule:
            try:
                if not isinstance(rule["value_expr"], dict):
                    raise ValueError("must be an object")
                count, _ = _ast_size(rule["value_expr"])
                if count > 512: raise ValueError("exceeds 512 nodes")
            except (ValueError, TypeError):
                errors.append(f"rules[{index}].value_expr must be a bounded expression object")
        if "when_expr" in rule:
            try:
                count, _ = _ast_size(rule["when_expr"])
                if count > 512: raise ValueError("exceeds 512 nodes")
            except (ValueError, TypeError):
                errors.append(f"rules[{index}].when_expr must be a bounded expression object")
    if require_contract and isinstance(candidate.get("calculation_contract"), dict):
        mapped = {rule_id for item in candidate["calculation_contract"].get("source", {}).get("note_rule_map", [])
                  if isinstance(item, dict) for rule_id in item.get("rule_ids", [])}
        if not mapped <= rule_ids:
            errors.append("note_rule_map references missing rule IDs; rules cannot be omitted to pass review")
        if not isinstance(candidate.get("handled_conditions"), list):
            errors.append("handled_conditions must list the source conditions implemented")
    return errors


def author_candidate(source_bundle: str, independent_cases: list[dict], *,
                     model: Callable[[str], str], max_repairs: int = 3,
                     case_runner: Callable[[dict, dict], list[str]] | None = None,
                     allowed_system_policies: set[str] | None = None,
                     output_dir: Path = CANDIDATE_DIR,
                     attempt_log: Path | None = ATTEMPT_LOG) -> dict:
    """Generate and bounded-repair a data-only candidate; never auto-approve it.

    Trusted expected outputs stay evaluator-only. Repair feedback reports the
    failed case and output field, without expected or observed values.
    """
    if not 0 <= max_repairs <= 3:
        raise ValueError("max_repairs must be between 0 and 3")
    if not independent_cases:
        return {"status": "failed", "attempts": 0, "errors": ["independent authoring cases are required"]}
    if independent_cases and case_runner is None:
        raise ValueError("independent cases require an offline case_runner")
    source_pdf_hash = None
    source_note_ids = None
    try:
        parsed_bundle = json.loads(source_bundle)
        source_pdf_hash = parsed_bundle.get("pdf_sha256") if isinstance(parsed_bundle, dict) else None
        if isinstance(parsed_bundle, dict) and isinstance(parsed_bundle.get("calculation_notes"), list):
            source_note_ids = {str(note.get("note_id")) for note in parsed_bundle["calculation_notes"]
                               if isinstance(note, dict) and note.get("note_id")}
    except ValueError:
        pass
    prompt = build_json_authoring_prompt(source_bundle, independent_cases,
                                         allowed_system_policies=allowed_system_policies)
    verification_ids = [case.get("id", f"case-{index + 1}")
                        for index, case in enumerate(independent_cases)]
    feedback = ""
    last_errors = []
    attempts = []
    for attempt in range(max_repairs + 1):
        try:
            raw = model(prompt + feedback)
        except Exception as exc:
            last_errors = [f"model call failed: {type(exc).__name__}: {exc}"]
            attempts.append({"attempt": attempt + 1, "errors": last_errors})
            break
        try:
            candidate = json.loads(raw)
            last_errors = validate_candidate(candidate, allowed_system_policies=allowed_system_policies,
                                              require_contract=True)
        except (ValueError, TypeError) as exc:
            candidate, last_errors = None, [f"invalid JSON: {exc}"]
        if not last_errors:
            for index, case in enumerate(independent_cases):
                try:
                    failures = case_runner(candidate, {**case, "allowed_system_policies": sorted(allowed_system_policies or set())}) or []
                except Exception as exc:
                    failures = [f"case runner error: {exc}"]
                last_errors.extend(f"case[{index}]: {message}" for message in failures)
        if not last_errors and source_pdf_hash and candidate.get("source_hash") != source_pdf_hash:
            last_errors.append("candidate source_hash does not match the supplied source PDF SHA-256")
        if not last_errors and source_note_ids is not None:
            mapped_ids = {entry.get("note_id") for entry in candidate["calculation_contract"]["source"]["note_rule_map"]}
            if mapped_ids != source_note_ids:
                last_errors.append("note_rule_map must account for every source calculation note exactly once")
        if not last_errors:
            contract_ids = [item.get("id") for item in candidate["calculation_contract"]["verification"]["cases"]]
            if contract_ids != verification_ids:
                last_errors.append(f"verification.cases IDs must exactly match independent case order {verification_ids}")
        if not last_errors:
            attempts.append({"attempt": attempt + 1, "errors": [],
                             "candidate_id": candidate.get("id") if isinstance(candidate, dict) else None})
            break
        attempts.append({"attempt": attempt + 1, "errors": list(last_errors),
                         "candidate_id": candidate.get("id") if isinstance(candidate, dict) else None})
        feedback = ("\nREPAIR FEEDBACK (do not change source facts or tests; no expected/observed values are included):\n"
                    + _safe_repair_feedback(last_errors, independent_cases))
    if attempt_log:
        log_path = Path(attempt_log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as stream:
            for item in attempts:
                stream.write(json.dumps({"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "source_hash": hashlib.sha256(source_bundle.encode("utf-8")).hexdigest(),
                    **item}, ensure_ascii=False) + "\n")
    if last_errors:
        return {"status": "failed", "attempts": len(attempts), "errors": last_errors}
    output_dir = Path(output_dir).resolve()
    approved = (Path(__file__).resolve().parents[1] / "data" / "calculation_modules" / "approved").resolve()
    if output_dir == approved or approved in output_dir.parents or output_dir in approved.parents:
        return {"status": "failed", "attempts": attempt + 1, "errors": ["candidate output path overlaps approved registry"]}
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{candidate['id']}.json"
    if path.exists():
        return {"status": "failed", "attempts": attempt + 1, "errors": ["candidate already exists; refusing overwrite"]}
    path.write_text(json.dumps({**candidate, "review_status": "candidate_unreviewed"},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "candidate", "attempts": attempt + 1, "path": str(path),
            "model_calls": model_calls, "attempt_log": attempts,
            "exit_reason": "candidate_unreviewed_after_final_pass",
            "candidate_state": "candidate_unreviewed", "review_status": "candidate_unreviewed"}


def run_candidate_case_detailed(candidate: dict, case: dict) -> dict:
    """Evaluate a candidate while separating execution failures from value mismatches.

    Reference values remain inside this trusted evaluator: the returned record
    includes only mismatch field names, never expected or observed values.
    """
    from backend.agent.tools.calc.generated import generated_daily_crew
    errors = validate_candidate(candidate, allowed_system_policies=set(case.get("allowed_system_policies", [])),
                                 require_contract=True)
    if isinstance(case, dict) and isinstance(case.get("spec"), dict):
        errors.extend(validate_candidate_units(candidate, case["spec"]))
    if errors:
        return {"status": "candidate_invalid", "validation_errors": errors}
    if not isinstance(case, dict) or not isinstance(case.get("spec"), dict) or not isinstance(case.get("inputs"), dict):
        return {"status": "case_invalid", "validation_errors": ["case requires spec and inputs objects"]}
    available = {field.get("name") for field in case["spec"].get("inputs", [])}
    available.update(field["name"] for field in candidate.get("inputs", []) if isinstance(field, dict) and field.get("name"))
    references = set()
    def collect(node):
        if isinstance(node, dict):
            if set(node) == {"input"} and isinstance(node["input"], str):
                references.add(node["input"])
            for child in node.values(): collect(child)
        elif isinstance(node, list):
            for child in node: collect(child)
    for rule in candidate["rules"]:
        collect(rule.get("when", {}))
        collect(rule.get("when_expr", {}))
        collect(rule.get("value_expr", {}))
        references.update(name for name in (rule.get("input"), rule.get("source_input")) if isinstance(name, str))
        references.update(name for name in (rule.get("height_input"),) if isinstance(name, str))
        references.update(name for name in rule.get("policy_inputs", []) if isinstance(name, str))
    unknown = sorted(references - available)
    if unknown:
        return {"status": "candidate_invalid", "validation_errors":
                [f"rules reference undeclared inputs: {', '.join(unknown)}"]}
    contract_site_inputs = {field.get("name") for field in candidate["calculation_contract"].get("site_inputs", [])
                            if isinstance(field, dict)}
    new_input_names = {field.get("name") for field in candidate.get("inputs", []) if isinstance(field, dict)}
    undeclared_facts = sorted(references - contract_site_inputs - new_input_names)
    if undeclared_facts:
        return {"status": "candidate_invalid", "validation_errors":
                [f"calculation_contract.site_inputs omits rule inputs: {', '.join(undeclared_facts)}"]}
    case_spec = copy.deepcopy(case["spec"])
    case_spec.setdefault("quantity_model", {}).setdefault("params", {})["module_id"] = candidate["id"]
    result = generated_daily_crew(case_spec, case["inputs"], labor_only=True, module_override=candidate)
    expected = case.get("expected")
    if not isinstance(expected, dict):
        return {"status": "case_invalid", "validation_errors": ["case requires an independent expected object"],
                "execution": {"status": result.get("status"), "reason": result.get("reason")}}
    execution = {"status": result.get("status"), "reason": result.get("reason")}
    if result.get("status") != "computed":
        return {"status": "execution_failed", "execution": execution, "mismatched_fields": []}

    def equal_value(actual, reference):
        if actual == reference:
            return True
        if (isinstance(actual, (str, int, float)) and not isinstance(actual, bool)
                and isinstance(reference, (str, int, float)) and not isinstance(reference, bool)):
            try:
                from fractions import Fraction
                return Fraction(str(actual)) == Fraction(str(reference))
            except (ValueError, ZeroDivisionError):
                return False
        return False

    mismatches = sorted(key for key, value in expected.items()
                        if not equal_value(result.get(key), value))
    return {"status": "passed" if not mismatches else "computed_mismatch",
            "execution": execution, "mismatched_fields": mismatches}


def run_candidate_case(candidate: dict, case: dict) -> list[str]:
    """Compatibility wrapper for callers that use the historical list result."""
    detail = run_candidate_case_detailed(candidate, case)
    if detail["status"] == "passed":
        return []
    if detail["status"] == "execution_failed":
        execution = detail["execution"]
        return [f"execution failed: status={execution.get('status')}; reason={execution.get('reason')}"]
    if detail["status"] == "computed_mismatch":
        return [f"computed result mismatch: {', '.join(detail['mismatched_fields'])}"]
    return list(detail.get("validation_errors", []))


def _assemble_python_contract(proposed: dict, source_bundle: str, cases: list[dict], *,
                             source_pdf_hash: str | None, division: str | None,
                             section_no: str | None) -> dict:
    """Assemble trusted identity, source locator, input, executor, and eval metadata in code."""
    from pipeline.calculation_contract import CONTRACT_VERSION
    try:
        evidence = json.loads(source_bundle)
    except (TypeError, ValueError):
        return proposed
    if not isinstance(evidence, dict) or not isinstance(cases[0].get("spec"), dict):
        return proposed
    source_proposal = proposed.get("source") if isinstance(proposed.get("source"), dict) else {}
    note_rule_map = source_proposal.get("note_rule_map", [])
    spec = cases[0]["spec"]
    source_hash = source_pdf_hash or evidence.get("pdf_sha256")
    pages = [{"pdf_page": item.get("pdf_page"), "printed_page": item.get("printed_page")}
             for item in evidence.get("full_section_pdf_pages", [])]
    citations = [{"note_id": item.get("note_id"), "kind": item.get("kind"),
                  "location": item.get("location")}
                 for item in evidence.get("calculation_notes", []) if item.get("note_id")]
    citations.extend({"table_id": (item.get("source") or {}).get("table_id"),
                      "pdf_page": (item.get("source") or {}).get("page"),
                      "kind": "table"}
                     for item in evidence.get("parsed_section_tables_notes", [])
                     if (item.get("source") or {}).get("table_id"))
    tables = spec.get("tables", [])
    verification = [{"id": case.get("id", f"case-{index + 1}"),
                     "citation": (tables[0].get("id") if tables else f"PDF {section_no}")}
                    for index, case in enumerate(cases)]
    schemas = [json.dumps(case["spec"].get("inputs", []), ensure_ascii=False, sort_keys=True)
               for case in cases if isinstance(case.get("spec"), dict)]
    if not schemas or any(schema != schemas[0] for schema in schemas[1:]):
        return proposed
    application = proposed.get("application")
    return {
        "contract_version": CONTRACT_VERSION,
        "source": {"pdf_sha256": source_hash, "edition": evidence.get("edition", ""),
                   "division": division or evidence.get("division"),
                   "section_no": section_no or evidence.get("section_no"),
                   "pages": pages, "citations": citations,
                   "note_rule_map": note_rule_map},
        "site_inputs": [{key: field.get(key) for key in ("name", "type", "unit", "source")}
                        for field in spec.get("inputs", [])],
        "application": application,
        "executor": {"kind": "isolated_python", "version": "v1"},
        "verification": {"cases": verification},
    }


def author_python_candidate(source_bundle: str, independent_cases: list[dict], *,
                            model: Callable[[str], str], sandbox_image: str,
                            max_repairs: int = 2, output_dir: Path = CANDIDATE_DIR,
                            evaluation_cases: list[dict] | None = None,
                            require_contract: bool = False, source_pdf_hash: str | None = None,
                            source_note_ids: set[str] | None = None,
                            division: str | None = None, section_no: str | None = None,
                            attempt_log: Path | None = ATTEMPT_LOG) -> dict:
    """Author and test Python only through the resource-limited sandbox; never register it."""
    from pipeline.python_sandbox import run_generated_python
    if not independent_cases:
        raise ValueError("Python candidates require independent execution cases")
    if not 0 <= max_repairs <= 2:
        raise ValueError("Python candidate repairs are limited to two")
    if require_contract:
        if not evaluation_cases:
            raise ValueError("contracted Python candidates require separate withheld evaluation cases")
        distinct_inputs = {json.dumps(case.get("inputs"), sort_keys=True, ensure_ascii=False)
                           for case in independent_cases if isinstance(case, dict)}
        expected_values = {}
        for case in independent_cases:
            if not isinstance(case.get("expected"), dict):
                raise ValueError("every contracted Python authoring case needs trusted expected outputs")
            for name, value in case["expected"].items():
                expected_values.setdefault(name, set()).add(json.dumps(value, sort_keys=True, ensure_ascii=False))
        if len(distinct_inputs) < 2 or not any(len(values) > 1 for values in expected_values.values()):
            raise ValueError("Python authoring suite must vary site inputs and at least one expected result field")
        if any(not isinstance(case.get("expected"), dict) for case in evaluation_cases):
            raise ValueError("every withheld Python evaluation case needs trusted expected outputs")
    verification_ids = [case.get("id", f"case-{index+1}") for index, case in enumerate(independent_cases)]
    authoring_facts = [{"id": case.get("id", f"case-{index+1}"),
                        "spec": case.get("spec"), "inputs": case.get("inputs", {})}
                       for index, case in enumerate(independent_cases)]
    prompt = ("Return ONLY a JSON object with keys code and calculation_contract. code is Python source defining "
              "calculate(spec, inputs, labor_only=False) -> result. calculation_contract contains your semantic application interpretation and source.note_rule_map only. Program code assembles "
              "source hash/pages/citations, site_inputs, executor metadata, and verification IDs from pinned inputs. "
              "Program-owned verification uses the authoring case IDs; do not add verification IDs to the proposed contract. "
              "Map every source calculation note to rule IDs or an evidence-backed exclusion. Reuse project-supported "
              "calculator semantics; return the existing computed result contract. Do not invent source rules or "
              "system policies. You receive source evidence and authoring cases' spec/site inputs only; never "
              "request or emit expected values and never change tests.\n"
              "AUTHORING CASE FACTS (expected outputs intentionally omitted):\n"
              f"{json.dumps(authoring_facts, ensure_ascii=False, sort_keys=True)}\n"
              f"SOURCE BUNDLE:\n{source_bundle}")
    feedback = ""
    attempts = []
    model_calls = 0
    for index in range(max_repairs + 1):
        case_results = []
        try:
            model_calls += 1
            raw = model(prompt + feedback)
            contract = None
            if isinstance(raw, str):
                try:
                    generated = json.loads(raw)
                except ValueError:
                    generated = None
                if isinstance(generated, dict) and isinstance(generated.get("code"), str):
                    source, proposed_contract = generated["code"], generated.get("calculation_contract")
                    contract = (_assemble_python_contract(proposed_contract, source_bundle, independent_cases,
                                source_pdf_hash=source_pdf_hash, division=division, section_no=section_no)
                                if isinstance(proposed_contract, dict) else proposed_contract)
                else:
                    source = raw
            else:
                source = ""
            errors = []
            from pipeline.calculation_contract import validate_contract
            from pipeline.python_sandbox import validate_python_candidate
            if require_contract and contract is None:
                errors.append("candidate must return Python code and the v1 calculation_contract JSON")
            if contract is not None:
                errors.extend(validate_contract(contract))
                if contract.get("executor", {}).get("kind") != "isolated_python":
                    errors.append("contract executor.kind must be isolated_python")
                if source_pdf_hash and contract.get("source", {}).get("pdf_sha256") != source_pdf_hash:
                    errors.append("contract source PDF hash does not match the supplied source")
                if division and contract.get("source", {}).get("division") != division:
                    errors.append("contract division does not match the supplied section")
                if section_no and contract.get("source", {}).get("section_no") != section_no:
                    errors.append("contract section number does not match the supplied section")
                if source_note_ids is not None:
                    mapped = {note.get("note_id") for note in contract.get("source", {}).get("note_rule_map", [])}
                    if mapped != source_note_ids:
                        errors.append("contract note_rule_map must cover every source calculation note exactly once")
                contract_case_ids = [item.get("id") for item in contract.get("verification", {}).get("cases", [])]
                if contract_case_ids != verification_ids:
                    errors.append(f"contract verification case IDs must exactly match {verification_ids}")
            errors.extend(validate_python_candidate(source))
            for case_index, case in enumerate(independent_cases):
                if errors:
                    break
                execution = run_generated_python(source, case["spec"], case["inputs"], image=sandbox_image)
                if execution.get("status") != "ok":
                    execution_errors = list(execution.get("errors", []))
                    case_results.append({"case": case.get("id"), "status": execution.get("status"),
                                         "errors": execution_errors})
                    errors.extend(f"case[{case_index}]: {error}" for error in execution_errors)
                    continue
                actual = execution["result"]
                case_results.append({"case": case.get("id"), "status": "computed", "actual": actual})
                for key, expected in case.get("expected", {}).items():
                    if actual.get(key) != expected:
                        # Never send reference values (or candidate outputs) back to the author.
                        errors.append(f"case[{case_index}] output field {key} does not match the independent evaluation")
            if not errors:
                attempts.append({"attempt": index + 1, "errors": [], "case_results": case_results,
                                 "feedback_delivered": feedback.split("\n", 1)[-1] if feedback else "",
                                 "candidate_id": "python"})
                break
        except Exception as exc:
            source = ""
            errors = [f"sandbox/model failure: {type(exc).__name__}: {exc}"]
        delivered_feedback = feedback.split("\n", 1)[-1] if feedback else ""
        attempts.append({"attempt": index + 1, "errors": errors, "case_results": case_results,
                         "feedback_delivered": delivered_feedback})
        if any("not already available locally" in error or "Docker" in error for error in errors):
            break
        feedback = "\nREPAIR FEEDBACK (preserve all source rules and test cases):\n" + "\n".join(errors)
    def log_attempts() -> None:
        if not attempt_log:
            return
        path = Path(attempt_log)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            for attempt_record in attempts:
                stream.write(json.dumps({"timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    "source_hash": hashlib.sha256(source_bundle.encode("utf-8")).hexdigest(),
                    "executor": "isolated_python", **attempt_record}, ensure_ascii=False) + "\n")
    if errors:
        log_attempts()
        return {"status": "failed", "attempts": len(attempts), "model_calls": model_calls,
                "attempt_log": attempts, "exit_reason": "authoring_failed", "errors": errors,
                "candidate_state": "failed_unsaved"}
    final_evaluation = None
    if evaluation_cases is not None:
        checks = []
        for case in evaluation_cases:
            execution = run_generated_python(source, case["spec"], case["inputs"], image=sandbox_image)
            actual = execution.get("result") if execution.get("status") == "ok" else None
            failures = execution.get("errors", []) if execution.get("status") != "ok" else []
            if not failures:
                failures = [key for key, expected in case.get("expected", {}).items()
                            if actual.get(key) != expected]
            checks.append({"case": case.get("id"), "passed": not failures,
                           "status": execution.get("status"), "actual": actual,
                           "errors": failures if failures else []})
        final_evaluation = {"passed": sum(item["passed"] for item in checks), "total": len(checks),
                            "cases": checks, "sent_to_model": False}
        if not checks or final_evaluation["passed"] != final_evaluation["total"]:
            attempts.append({"attempt": len(attempts), "stage": "withheld_final_evaluation",
                             "errors": [f"held-out case {item['case']} failed" for item in checks if not item["passed"]]})
            log_attempts()
            return {"status": "failed", "stage": "withheld_final_evaluation",
                    "attempts": len(attempts), "model_calls": model_calls,
                    "attempt_log": attempts, "exit_reason": "final_evaluation_failed",
                    "candidate_state": "failed_unsaved", "final_evaluation": final_evaluation,
                    "errors": [f"held-out case {item['case']} failed" for item in checks if not item["passed"]]}
    log_attempts()
    # Candidate material remains unregistered and is never imported by estimate workers.
    output_root = Path(output_dir).resolve()
    approved = (Path(__file__).resolve().parents[1] / "data" / "calculation_modules" / "approved").resolve()
    if output_root == approved or approved in output_root.parents or output_root in approved.parents:
        return {"status": "failed", "attempts": len(attempts),
                "errors": ["candidate output path overlaps approved registry"]}
    target_dir = output_root / "python"
    target_dir.mkdir(parents=True, exist_ok=True)
    candidate_id = "python-" + hashlib.sha256(source_bundle.encode("utf-8")).hexdigest()[:16]
    target = target_dir / f"{candidate_id}.py"
    if target.exists():
        return {"status": "failed", "attempts": index + 1, "errors": ["candidate already exists"]}
    target.write_text(source, encoding="utf-8")
    if contract is not None:
        target.with_suffix(".contract.json").write_text(
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (target.with_suffix(".candidate.json")).write_text(json.dumps({
        "status": "candidate_unreviewed", "attempts": index + 1,
        "code_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "source_bundle_sha256": hashlib.sha256(source_bundle.encode("utf-8")).hexdigest(),
        "authoring_cases_passed": len(independent_cases),
        "model_calls": model_calls, "attempt_log": attempts,
        "exit_reason": "candidate_unreviewed_after_final_pass",
        "final_evaluation": final_evaluation,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "candidate", "attempts": index + 1, "model_calls": model_calls,
            "attempt_log": attempts, "exit_reason": "candidate_unreviewed_after_final_pass",
            "candidate_state": "candidate_unreviewed", "path": str(target),
            "review_status": "candidate_unreviewed", "runtime_registered": False,
            **({"final_evaluation": final_evaluation} if final_evaluation is not None else {})}


def register_python_candidate(candidate_path: Path, registry_path: Path, *, module_id: str,
                              version: str, sections: list[dict], inputs: list[str],
                              source_hash: str, contract: dict, sandbox_image: str) -> dict:
    """Explicit operator action: register only an independently reviewed candidate."""
    from pipeline.calculation_contract import validate_contract
    from pipeline.python_sandbox import validate_python_candidate
    if not isinstance(module_id, str) or not _ID.fullmatch(module_id):
        raise ValueError("module ID must be a lowercase slug")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("module version is required")
    candidate_path, registry_path = Path(candidate_path).resolve(), Path(registry_path).resolve()
    errors = validate_python_candidate(candidate_path.read_text(encoding="utf-8"))
    errors.extend(validate_contract(contract))
    if errors:
        raise ValueError("candidate registration rejected: " + "; ".join(errors))
    metadata_path = candidate_path.with_suffix(".candidate.json")
    evaluation_path = candidate_path.with_suffix(".evaluation.json")
    contract_path = candidate_path.with_suffix(".contract.json")
    if not metadata_path.is_file() or not evaluation_path.is_file() or not contract_path.is_file():
        raise ValueError("registration requires candidate contract, authoring and withheld final-evaluation records")
    stored_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if stored_contract != contract:
        raise ValueError("registration contract differs from the candidate's generated contract")
    if contract.get("executor", {}).get("module_version") != version:
        raise ValueError("module version must match contract executor.module_version")
    if len(sections) != 1 or (contract.get("source", {}).get("division"), contract.get("source", {}).get("section_no")) != (
            sections[0].get("division"), sections[0].get("section_no")):
        raise ValueError("registration section must match candidate source contract")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    code_hash = hashlib.sha256(candidate_path.read_bytes()).hexdigest()
    if metadata.get("status") != "candidate_unreviewed" or metadata.get("code_sha256") != code_hash:
        raise ValueError("candidate authoring record is missing or does not match exact code")
    if (evaluation.get("status") != "passed" or evaluation.get("sent_to_model") is not False
            or not evaluation.get("total") or evaluation.get("passed") != evaluation.get("total")
            or evaluation.get("code_sha256") != code_hash):
        raise ValueError("withheld final evaluation has not passed for the exact candidate")
    if contract.get("executor", {}).get("kind") != "isolated_python":
        raise ValueError("candidate contract executor must be isolated_python")
    if contract.get("source", {}).get("pdf_sha256") != source_hash:
        raise ValueError("registration source hash does not match contract")
    if "@sha256:" not in sandbox_image:
        raise ValueError("sandbox image must be digest pinned")
    approved_root = registry_path.parent.resolve()
    python_root = approved_root / "python"
    python_root.mkdir(parents=True, exist_ok=True)
    target = python_root / f"{module_id}.py"
    if target.exists():
        raise FileExistsError(target)
    import shutil
    shutil.copyfile(candidate_path, target)
    entry = {"id": module_id, "version": version, "sections": sections,
             "inputs": inputs, "source_hash": source_hash,
             "code_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
             "file": f"{module_id}.py", "sandbox_image": sandbox_image,
             "review_status": "approved_for_runtime", "calculation_contract": contract}
    registry = json.loads(registry_path.read_text(encoding="utf-8")) if registry_path.exists() else {
        "registry_version": 1, "modules": []}
    if any(item.get("id") == module_id for item in registry.get("modules", [])):
        target.unlink()
        raise ValueError(f"module ID already registered: {module_id}")
    registry.setdefault("modules", []).append(entry)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return entry


def load_case_file(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases", []) if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise ValueError("case file must be a list or an object with a cases list")
    root = Path(__file__).resolve().parents[1]
    resolved = []
    for original in cases:
        if not isinstance(original, dict):
            raise ValueError("every case must be an object")
        case = dict(original)
        if not isinstance(case.get("spec"), dict) and case.get("spec_path"):
            spec_path = (root / case["spec_path"]).resolve()
            if root not in spec_path.parents or not spec_path.is_file():
                raise ValueError(f"case spec_path is outside the workspace or missing: {case['spec_path']}")
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            case["spec"] = spec.get("draft", spec)
        if isinstance(case.get("spec"), dict) and isinstance(case.get("inputs"), dict):
            fields = {field.get("name"): field for field in case["spec"].get("inputs", [])}
            for name, value in list(case["inputs"].items()):
                if isinstance(value, dict) and set(value) == {"allowed_index"}:
                    allowed = fields.get(name, {}).get("allowed_values")
                    index = value["allowed_index"]
                    if not isinstance(allowed, list) or type(index) is not int or not 0 <= index < len(allowed):
                        raise ValueError(f"invalid allowed_index for case input {name}")
                    case["inputs"][name] = allowed[index]
        resolved.append(case)
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prepare/review a constrained calculation-module candidate")
    parser.add_argument("--source", type=Path, required=True, help="source evidence text or PDF")
    parser.add_argument("--cases", type=Path, required=True, help="authoring cases with independent outputs")
    parser.add_argument("--executor", choices=("json_interpreter", "isolated_python"), default="json_interpreter")
    parser.add_argument("--sandbox-image", help="digest-pinned sandbox image for isolated_python")
    parser.add_argument("--register-candidate", type=Path, help="explicitly register a reviewed Python candidate")
    parser.add_argument("--registration-contract", type=Path, help="reviewed v1 contract JSON required for registration")
    parser.add_argument("--module-id", help="registered module ID")
    parser.add_argument("--module-version", help="registered module version")
    parser.add_argument("--registry", type=Path, default=Path("data/calculation_modules/approved/python-registry.json"))
    parser.add_argument("--chunks", type=Path, default=PROCESSED_DIR / "chunks.jsonl",
                        help="parsed tables/notes/reference JSONL")
    parser.add_argument("--page-map", type=Path, default=PROCESSED_DIR / "page_map.json",
                        help="PDF to printed-page map JSON")
    parser.add_argument("--evaluation-cases", type=Path, help="withheld final cases; never sent to the model")
    parser.add_argument("--output", type=Path, default=CANDIDATE_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--env", type=Path, default=Path(".env"),
                        help="same environment file used by the existing Vertex authoring pipeline")
    parser.add_argument("--model", help="override configured Gemini model for an explicitly budgeted run")
    parser.add_argument("--call-model", action="store_true", help="explicitly allow Vertex model calls")
    parser.add_argument("--max-calls", type=int, default=4)
    parser.add_argument("--token-budget", type=int, default=12000)
    parser.add_argument("--max-usd", type=float, default=0.25)
    parser.add_argument("--division", help="omit only when section_no uniquely identifies a division")
    parser.add_argument("--section-no", default="")
    args = parser.parse_args(argv)
    if args.call_model and args.executor == "isolated_python":
        if not args.evaluation_cases:
            parser.error("isolated_python generation requires separate --evaluation-cases")
        if not args.sandbox_image or "@sha256:" not in args.sandbox_image:
            parser.error("isolated_python generation requires digest-pinned --sandbox-image")
    if args.register_candidate:
        if not all((args.registration_contract, args.module_id, args.module_version, args.sandbox_image,
                    args.division, args.section_no)):
            parser.error("registration requires contract, module ID/version, sandbox image, division, and section number")
        contract = json.loads(args.registration_contract.read_text(encoding="utf-8"))
        from pipeline.calculation_modules import register_python_candidate
        source_hash = contract.get("source", {}).get("pdf_sha256", "")
        sections = [{"division": args.division, "section_no": args.section_no}]
        inputs = [field["name"] for field in contract.get("site_inputs", [])]
        entry = register_python_candidate(args.register_candidate, args.registry,
            module_id=args.module_id, version=args.module_version, sections=sections, inputs=inputs,
            source_hash=source_hash, contract=contract, sandbox_image=args.sandbox_image)
        print(json.dumps({"status": "registered", "id": entry["id"], "registry": str(args.registry)}, ensure_ascii=False))
        return 0
    try:
        authoring_cases = load_case_file(args.cases)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    source_bytes = args.source.read_bytes()
    model_pdf_bytes = b""
    source_pdf_hash = hashlib.sha256(source_bytes).hexdigest() if args.source.suffix.lower() == ".pdf" else None
    if args.source.suffix.lower() == ".pdf":
        if not args.section_no:
            parser.error("PDF generation requires --section-no; --division is required only when ambiguous")
        from pipeline.calculation_contract import build_source_bundle
        source_bundle, source_metadata = build_source_bundle(args.source, args.chunks, args.page_map,
                                                              args.division, args.section_no)
        args.division = args.division or source_metadata["division"]
        if source_metadata["pdf_sha256"] != source_pdf_hash:
            parser.error("source PDF hash mismatch while building section evidence")
        import fitz
        original_pdf = fitz.open(stream=source_bytes, filetype="pdf")
        excerpt = fitz.open()
        for record in source_metadata["full_section_pdf_pages"]:
            excerpt.insert_pdf(original_pdf, from_page=record["pdf_page"] - 1, to_page=record["pdf_page"] - 1)
        model_pdf_bytes = excerpt.tobytes()
    else:
        if args.executor == "isolated_python" and args.call_model:
            parser.error("isolated_python generation requires original PDF plus parsed section evidence")
        source_bundle = source_bytes.decode("utf-8")
    if args.source.suffix.lower() == ".pdf":
        from backend.agent.tools.calc.policies import allowed_policy_ids
        policy_errors = validate_registered_policy_sources(
            source_bundle, allowed_policy_ids(args.division, args.section_no))
        if policy_errors:
            parser.error("registered-policy source preflight failed; no model request made: " + "; ".join(policy_errors))
    if args.evaluation_cases:
        try:
            evaluation_cases = load_case_file(args.evaluation_cases)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        author_ids = {item.get("id") for item in authoring_cases if isinstance(item, dict)}
        final_ids = {item.get("id") for item in evaluation_cases if isinstance(item, dict)}
        overlap = author_ids & final_ids
        if overlap:
            parser.error(f"authoring and final evaluation case IDs overlap: {sorted(overlap)}")
        print(json.dumps({"withheld_evaluation_cases": len(evaluation_cases),
                          "sent_to_model": False}, ensure_ascii=False))
    if not args.call_model:
        print(json.dumps({"status": "prepared", "source_chars": len(source_bundle),
                          "cases": len(authoring_cases), "call_model": False}, ensure_ascii=False))
        return 0
    if args.max_calls < 1 or args.max_calls > 4 or args.token_budget < 1 or args.max_usd <= 0:
        parser.error("max-calls must be 1..4 and token-budget/max-usd positive")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    model_id = args.model or config["model"]
    from pipeline.draft_specs import env_value
    api_key = env_value("VERTEX_API_KEY_BULK", args.env)
    if not api_key:
        parser.error("VERTEX_API_KEY_BULK is required with --call-model")
    from pipeline.draft_specs import make_vertex_request_fn
    thinking_level = config.get("calculation_authoring_thinking_level", "LOW")
    max_output_tokens = int(config.get("calculation_authoring_max_output_tokens", 15000))
    semantic_schema = SEMANTIC_AUTHORING_SCHEMA if args.executor == "json_interpreter" and args.source.suffix.lower() == ".pdf" else None
    request = make_vertex_request_fn(api_key, thinking_level=thinking_level,
                                     response_json_schema=semantic_schema)
    calls, reserved_tokens, reserved_usd, observed_usd = 0, 0, 0.0, 0.0
    response_records = []
    input_rate, output_rate = float(config["input_usd_per_million"]), float(config["output_usd_per_million"])
    if input_rate <= 0 or output_rate <= 0:
        parser.error("configured input/output pricing must be positive before a model call")
    def model(prompt):
        nonlocal calls, reserved_tokens, reserved_usd, observed_usd
        if calls >= args.max_calls or reserved_tokens >= args.token_budget:
            raise RuntimeError("model call/token budget exhausted")
        remaining_output = min(max_output_tokens, args.token_budget - reserved_tokens)
        counter = getattr(request, "count_input_tokens", None)
        if not callable(counter):
            raise RuntimeError("provider countTokens preflight is required; no character estimate fallback")
        input_reservation = counter(model_id, model_pdf_bytes, prompt)
        if input_reservation + remaining_output > args.token_budget - reserved_tokens:
            raise RuntimeError("provider-counted input plus maximum output exceeds token budget")
        reservation = input_reservation * input_rate / 1_000_000 + remaining_output * output_rate / 1_000_000
        if reserved_usd + reservation > args.max_usd:
            raise RuntimeError("configured USD budget would be exceeded by next request reservation")
        # Reserve before network I/O. A lost response must not free the call or
        # estimated-cost allowance and accidentally permit an unbounded retry.
        calls += 1
        reserved_tokens += input_reservation + remaining_output
        reserved_usd += reservation
        call_id = calls
        try:
            text, input_tokens, output_tokens = request(model_id, model_pdf_bytes,
                                                         prompt, remaining_output)
        except Exception as exc:
            response_records.append({"call": call_id, "state": "request_failed_or_lost",
                                     "error_type": type(exc).__name__})
            raise
        metadata = dict(request.last_response_metadata or {})
        raw_dir = args.output / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"generation-{call_id}.json").write_text(text, encoding="utf-8")
        response_records.append({"call": call_id, "state": "response_received",
                                 "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                                 **metadata})
        observed_usd += input_tokens * input_rate / 1_000_000 + output_tokens * output_rate / 1_000_000
        if metadata.get("finish_reason") == "MAX_TOKENS":
            raise ResponseTruncatedError(
                f"finish_reason=MAX_TOKENS; answer_tokens={metadata.get('answer_tokens')}; "
                f"reasoning_tokens={metadata.get('reasoning_tokens')}; no semantic retry sent")
        return text
    if args.executor == "isolated_python":
        source_note_ids = {item.get("note_id") for item in source_metadata.get("calculation_notes", [])}
        result = author_python_candidate(source_bundle, authoring_cases, model=model,
            sandbox_image=args.sandbox_image, max_repairs=min(2, args.max_calls - 1), output_dir=args.output,
            evaluation_cases=evaluation_cases, require_contract=True, source_pdf_hash=source_pdf_hash,
            source_note_ids=source_note_ids, division=args.division, section_no=args.section_no)
    elif semantic_schema is not None:
        from backend.agent.tools.calc.policies import allowed_policy_ids
        result = author_semantic_candidate(source_bundle, authoring_cases, model=model,
            max_repairs=min(2, args.max_calls - 1),
            allowed_system_policies=allowed_policy_ids(args.division, args.section_no),
            output_dir=args.output)
    else:
        result = author_candidate(source_bundle, authoring_cases, model=model,
                                  max_repairs=min(3, args.max_calls - 1), case_runner=run_candidate_case,
                                  allowed_system_policies=__import__("backend.agent.tools.calc.policies", fromlist=["allowed_policy_ids"])
                                    .allowed_policy_ids(args.division, args.section_no),
                                  output_dir=args.output)
    if args.evaluation_cases and result.get("status") == "candidate" and args.executor == "json_interpreter":
        candidate = (json.loads(Path(result["path"]).read_text(encoding="utf-8"))
                     if args.executor == "json_interpreter" else None)
        evaluation = []
        from backend.agent.tools.calc.policies import allowed_policy_ids
        allowed = allowed_policy_ids(args.division, args.section_no)
        for index, case in enumerate(evaluation_cases):
            errors = run_candidate_case(candidate, {**case, "allowed_system_policies": sorted(allowed)})
            evaluation.append({"case": case.get("id", str(index)), "passed": not errors, "errors": errors})
        result["final_evaluation"] = {"passed": sum(item["passed"] for item in evaluation),
                                      "total": len(evaluation), "cases": evaluation,
                                      "sent_to_model": False}
        candidate_path = Path(result["path"])
        evaluation_record = {**result["final_evaluation"],
                             "status": "passed" if all(item["passed"] for item in evaluation) else "failed",
                             "code_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest()}
        if any(not item["passed"] for item in evaluation):
            result["status"] = "candidate_unreviewed_final_failed"
    if args.executor == "isolated_python" and result.get("status") == "candidate":
        candidate_path = Path(result["path"])
        final_evaluation = result["final_evaluation"]
        evaluation_record = {**final_evaluation,
            "status": "passed" if final_evaluation["passed"] == final_evaluation["total"] else "failed",
            "code_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest()}
        candidate_path.with_suffix(".evaluation.json").write_text(
            json.dumps(evaluation_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    settings = {"model": model_id, "thinking_level": thinking_level,
                "max_output_tokens_per_call": max_output_tokens,
                "response_mime_type": "application/json", "temperature": 0,
                "response_json_schema_sha256": (hashlib.sha256(json.dumps(semantic_schema, sort_keys=True).encode()).hexdigest()
                    if semantic_schema else None),
                "sdk_retries": 0, "pricing_input_usd_per_million": input_rate,
                "pricing_output_usd_per_million": output_rate}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "model-settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "model": model_id, "model_settings": settings,
                      "model_responses": response_records, "model_calls_reserved": calls,
                      "tokens_reserved": reserved_tokens, "cost_observed_usd": round(observed_usd, 6),
                      "cost_reserved_usd": round(reserved_usd, 6),
                      "max_cost_usd": args.max_usd}, ensure_ascii=False))
    return 0 if result["status"] == "candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
