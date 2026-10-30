"""Explicit system policies, scoped to the exact reviewed rule they resolve."""
from __future__ import annotations

import math
import unicodedata
from fractions import Fraction

POLICIES = {
    "formwork-6-3-1-height-started-interval-compound-v1": {
        "version": "1",
        "source_note_id": "evidence-b29a23168b16a5da70306d2a",
        "source_locator": {"edition": "2026", "pdf_sha256": "cc226366b633a4e7d479ee55298318d9959dc988a910875c2ee775d958ee944b",
            "division": "\uacf5\ud1b5", "section_no": "6-3-1",
            "pdf_page": 193, "printed_page": 137, "kind": "table_note",
            "table_heading": "3. \uc124\uce58 \ubc0f \ud574\uccb4", "label": "\ube44\uace0",
            "parser_table_id": "p193-t0", "table_bbox": [68.0, 100.3, 543.4, 260.6],
            "required_text": "\ubcf8 \ud488\uc740 \uc218\uc9c1\uace0 7m\uae4c\uc9c0 \uc801\uc6a9\ud558\uba70, \uc591\uc911\uc7a5\ube44\ub97c \ud65c\uc6a9\ud558\uc9c0 \uc54a\uace0 \uc218\uc9c1\uace0\uac00 7m\ub97c \ucd08\uacfc\ud558\ub294 \uacbd\uc6b0 \ub9e4 3m\ub9c8\ub2e4 \uc2dc\uacf5\ub7c9\uc744 9%\uae4c\uc9c0 \uac10\ud55c\ub2e4."},
        "source": {"edition": "2026", "section_no": "6-3-1", "pdf_page": 193,
                   "printed_page": 137,
                   "text": "\ubcf8 \ud488\uc740 \uc218\uc9c1\uace0 7m\uae4c\uc9c0 \uc801\uc6a9\ud558\uba70, \uc591\uc911\uc7a5\ube44\ub97c \ud65c\uc6a9\ud558\uc9c0 \uc54a\uace0 \uc218\uc9c1\uace0\uac00 7m\ub97c \ucd08\uacfc\ud558\ub294 \uacbd\uc6b0 \ub9e4 3m\ub9c8\ub2e4 \uc2dc\uacf5\ub7c9\uc744 9%\uae4c\uc9c0 \uac10\ud55c\ub2e4."},
        "scope": {"division": "공통", "section_no": "6-3-1"},
        "statement": (
            "System-only convention for common 6-3-1: count every started 3 m interval above 7 m, "
            "use the stated maximum 9% per interval, and apply intervals successively. "
            "The source does not specify partial intervals, exact rate, or accumulation."
        ),
        "authoring_formula": (
            "For this section only, when height > 7 m and neither continuous crane nor ordinary lifting "
            "equipment is used: k = ceil((height - 7 m) / 3 m), and multiply daily output by "
            "(1 - 9/100)^k. Continuous crane and ordinary lifting equipment each bypass this height "
            "output deduction under their separate source conditions. This formula is a system policy, "
            "not a quoted official rule."
        ),
        "input_names": {"height"},
    }
}


def allowed_policy_ids(division: str, section_no: str) -> set[str]:
    return {policy_id for policy_id, item in POLICIES.items()
            if item["scope"] == {"division": division, "section_no": section_no}}


def policy_applies(policy_id: str, module: dict, spec: dict) -> bool:
    if policy_id not in POLICIES:
        return False
    policy = POLICIES[policy_id]
    scope = policy["scope"]
    contract = module.get("calculation_contract") or {}
    application = contract.get("application", {}) if isinstance(contract, dict) else {}
    source_contract = contract.get("source", {}) if isinstance(contract, dict) else {}
    note_map = source_contract.get("note_rule_map", []) if isinstance(source_contract, dict) else []
    referenced_rule_ids = {rule.get("id") for rule in module.get("rules", [])
                           if rule.get("system_policy_ref") == policy_id}
    robust_anchor = source_contract.get("policy_evidence", {}).get(policy_id)
    if robust_anchor:
        locator = policy.get("source_locator", {})
        source_pages = source_contract.get("pages", [])
        page_map_ok = any(item.get("pdf_page") == locator.get("pdf_page")
                          and item.get("printed_page") == locator.get("printed_page") for item in source_pages)
        citation = next((item for item in source_contract.get("citations", [])
                         if item.get("evidence_id") == robust_anchor.get("evidence_id")), None)
        content = " ".join(unicodedata.normalize("NFKC", str((citation or {}).get("content", ""))).split())
        required = " ".join(unicodedata.normalize("NFKC", str(locator.get("required_text", ""))).split())
        robust_ok = (all(robust_anchor.get(key) == locator.get(key) for key in
            ("edition", "pdf_sha256", "division", "section_no", "pdf_page", "printed_page", "kind", "table_heading", "label",
             "parser_table_id", "table_bbox", "required_text"))
            and robust_anchor.get("evidence_id") == module.get("policy_evidence_ids", {}).get(policy_id)
            and page_map_ok and citation is not None and citation.get("kind") == "table_note"
            and citation.get("location", {}).get("pdf_page") == locator.get("pdf_page")
            and citation.get("location", {}).get("printed_page") == locator.get("printed_page")
            and citation.get("location", {}).get("table_heading") == locator.get("table_heading")
            and citation.get("location", {}).get("label") == locator.get("label")
            and citation.get("location", {}).get("parser_table_id") == locator.get("parser_table_id")
            and citation.get("location", {}).get("table_bbox") == locator.get("table_bbox")
            and required in content)
        anchored = next((item for item in note_map
                         if item.get("note_id") == robust_anchor.get("evidence_id")), None)
    else:
        # A legacy chunk number cannot prove edition/page/table/note provenance.
        robust_ok = False
        anchored = None
    return (scope in module.get("sections", [])
            and spec.get("division") == scope["division"]
            and spec.get("section_no") == scope["section_no"]
            and policy_id in module.get("system_policy_ids", [])
            and (module.get("policy_note_ids", {}).get(policy_id) == policy["source_note_id"]
                 if not robust_anchor else robust_ok)
            and module.get("policy_versions", {}).get(policy_id) == policy["version"]
            and module.get("policy_sources", {}).get(policy_id) == policy["source"]
            and (not contract or (
                policy_id in application.get("system_policies", [])
                and application.get("policy_versions", {}).get(policy_id) == policy["version"]
                and application.get("policy_sources", {}).get(policy_id) == policy["source"]
                and bool(anchored) and bool(referenced_rule_ids.intersection(anchored.get("rule_ids", []))))))


def resolve_policy_source_evidence(policy_id: str, source_bundle: dict) -> tuple[dict | None, list[str]]:
    """Match a registered policy to its actual PDF page and labeled table note."""
    if policy_id not in POLICIES:
        return None, [f"unknown registered policy {policy_id}"]
    policy = POLICIES[policy_id]
    locator = policy.get("source_locator")
    if not isinstance(locator, dict):
        return None, [f"registered policy {policy_id} has no stable source locator"]
    errors = []
    for key in ("edition", "pdf_sha256", "division", "section_no"):
        if source_bundle.get(key) != locator.get(key):
            errors.append(f"policy {policy_id} source {key} does not match the supplied section")
    page = next((item for item in source_bundle.get("full_section_pdf_pages", [])
                 if item.get("pdf_page") == locator.get("pdf_page")), None)
    if not page or page.get("printed_page") != locator.get("printed_page"):
        errors.append(f"policy {policy_id} PDF/printed page mapping is absent or incorrect")
    def norm(value):
        return " ".join(unicodedata.normalize("NFKC", str(value or "")).split())
    required = norm(locator.get("required_text"))
    if not page or required not in norm(page.get("text")):
        errors.append(f"policy {policy_id} required wording is absent from its cited PDF page")
    matched = []
    for evidence in source_bundle.get("calculation_notes", []):
        location = evidence.get("location", {})
        if (location.get("kind") == locator.get("kind")
                and location.get("pdf_page") == locator.get("pdf_page")
                and location.get("printed_page") == locator.get("printed_page")
                and location.get("table_heading") == locator.get("table_heading")
                and location.get("label") == locator.get("label")
                and location.get("parser_table_id") == locator.get("parser_table_id")
                and location.get("table_bbox") == locator.get("table_bbox")
                and required in norm(evidence.get("content"))):
            matched.append(evidence)
    if len(matched) != 1:
        errors.append(f"policy {policy_id} must match exactly one explicitly labeled source table note")
    elif matched[0].get("evidence_id") != policy.get("source_note_id"):
        errors.append(f"policy {policy_id} registered evidence ID does not match its declared source locator")
    parsed_table_match = False
    for chunk in source_bundle.get("parsed_section_tables_notes", []):
        source = chunk.get("source") or {}
        if chunk.get("kind") != "table" or source.get("page") != locator.get("pdf_page"):
            continue
        text = chunk.get("text") or ""
        cells = [cell.strip() for line in text.splitlines() for cell in line.split("|")[:-1]]
        if (locator.get("table_heading") in text and source.get("table_id") == locator.get("parser_table_id")
                and source.get("bbox") == locator.get("table_bbox") and locator.get("label") in cells
                and required in norm(text)):
            parsed_table_match = True
    if not parsed_table_match:
        errors.append(f"policy {policy_id} table heading/label/wording does not match parsed source at the cited page")
    return (matched[0], []) if not errors else (None, errors)


def evaluate_policy(policy_id: str, inputs: dict) -> dict:
    """Execute a reviewed system policy and keep its assumptions separate from the source quote."""
    if policy_id not in POLICIES:
        raise ValueError("unknown system policy")
    policy = POLICIES[policy_id]
    if policy_id != "formwork-6-3-1-height-started-interval-compound-v1":
        raise ValueError("system policy has no registered evaluator")
    height = Fraction(str(inputs["height"]))
    if height <= 7:
        multiplier, intervals = Fraction(1), 0
    else:
        intervals = math.ceil((height - 7) / 3)
        multiplier = Fraction(91, 100) ** intervals
    return {"multiplier": multiplier, "intervals": intervals,
            "source": policy["source"], "policy_id": policy_id,
            "policy_version": policy["version"], "system_assumption": policy["statement"]}
