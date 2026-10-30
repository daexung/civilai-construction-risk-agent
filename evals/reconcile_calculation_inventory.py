"""Reconcile draft calculation work records to the pinned 2026 standard ToC.

This script does not decide whether a ToC section contains a calculation task.
It creates a reviewable queue and leaves that classification open until the
source rules are reviewed. Run from the repository root.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
COVERAGE = ROOT / "evals/runtime_validation/calculation-coverage-2026-10-18.json"
PAGE_MAP = ROOT / "data/processed/page_map.json"
CHUNKS = ROOT / "data/processed/chunks.all.jsonl"
DIVISION_LABELS = {
    "\uacf5\ud1b5\ubd80\ubb38": "\uacf5\ud1b5",
    "\ud1a0\ubaa9\ubd80\ubb38": "\ud1a0\ubaa9",
    "\uac74\ucd95\ubd80\ubb38": "\uac74\ucd95",
    "\uae30\uacc4\uc124\ube44\ubd80\ubb38": "\uae30\uacc4\uc124\ube44",
    "\uc720\uc9c0\uad00\ub9ac\ubd80\ubb38": "\uc720\uc9c0\uad00\ub9ac",
}
SECTION = re.compile(r"^\s*(\d+(?:-\d+){1,2})\s+(.+?)\s*$")
PRINTED_PAGE = re.compile(r"(\d{1,3})\s*$")


def classify_legacy_failure(reason: str) -> str:
    """Group stored reason strings for triage; this is not root-cause confirmation."""
    text = reason or ""
    if "형식 또는 인용 불일치" in text:
        return "format_or_citation_record"
    if "blocked:" in text:
        return "applicability_or_policy_block"
    if "기준 단위 파싱 실패" in text:
        return "unit_parsing"
    if any(token in text for token in ("행 후보", "열 후보", "열 지정 없음", "행 지정 없음", "행 이름 없음", "행 '")):
        return "table_row_column_resolution"
    if "표 이름 줄 밀림" in text:
        return "source_table_alignment"
    if "KeyError" in text or "ValueError" in text or "숫자 형식 아님" in text:
        return "spec_data_shape_or_numeric_parse"
    if "rejected:" in text:
        return "calculator_input_rejection"
    return "unclassified_legacy_failure"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_chunks() -> tuple[list[dict], dict[tuple[str | None, str], list[dict]]]:
    chunks = [json.loads(line) for line in CHUNKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    identities: dict[tuple[str | None, str], list[dict]] = collections.defaultdict(list)
    for chunk in chunks:
        if chunk.get("section_no"):
            identities[(chunk.get("division"), chunk["section_no"])].append(chunk)
    return chunks, identities


def read_toc(pdf_path: Path) -> list[dict]:
    document = pymupdf.open(pdf_path)
    division = None
    rows = []
    for pdf_page, page in enumerate(document, 1):
        text = page.get_text()
        if "\ubaa9\ucc28" not in text:
            continue
        for line in text.splitlines():
            for label, value in DIVISION_LABELS.items():
                if label in line:
                    division = value
            match = SECTION.match(line)
            if not match:
                continue
            section_no, rest = match.groups()
            if chr(183) not in rest:
                continue
            title = rest.split(chr(183), 1)[0].strip()
            page_match = PRINTED_PAGE.search(rest)
            if not title or not page_match:
                continue
            rows.append({
                "division": division,
                "section_no": section_no,
                "title": title,
                "printed_page": int(page_match.group(1)),
                "toc_pdf_page": pdf_page,
                "level": 3 if section_no.count("-") == 2 else 2,
                "work_item_classification": "not_yet_assessed",
                "calculation_rule_denominator": "not_enumerated",
            })
    return rows


def main() -> None:
    coverage = json.loads(COVERAGE.read_text(encoding="utf-8"))
    page_map = json.loads(PAGE_MAP.read_text(encoding="utf-8"))
    pdf_path = ROOT / page_map["pdf"]
    toc_rows = read_toc(pdf_path)
    toc_third = [row for row in toc_rows if row["level"] == 3]
    toc_parent = [row for row in toc_rows if row["level"] == 2]
    if (len(toc_third), len(toc_parent)) != (1095, 222):
        raise SystemExit(f"Pinned ToC extraction changed: third-level={len(toc_third)}, parent={len(toc_parent)}")

    _, parsed = read_chunks()
    parsed_ids = set(parsed)
    work_items = coverage["calculation_work_items"]
    work_ids = {(row["division"], row["section_no"]) for row in work_items}
    toc_ids = {(row["division"], row["section_no"]) for row in toc_third}
    section_numbers_by_division: dict[str, set[str | None]] = collections.defaultdict(set)
    for division, section_no in parsed_ids:
        section_numbers_by_division[section_no].add(division)

    for row in toc_rows:
        key = (row["division"], row["section_no"])
        matches = parsed.get(key, [])
        row["draft_work_entry_present"] = key in work_ids
        row["parsed_identity_present"] = key in parsed_ids
        row["parsed_chunk_ids"] = sorted({chunk["chunk_id"] for chunk in matches})
        row["parsed_pdf_pages"] = sorted({page for chunk in matches for page in chunk.get("pages", [])})
        row["source_match_state"] = "exact" if matches else "no_exact_division_section_match"

    row_by_id = {(row["division"], row["section_no"]): row for row in toc_third}
    for row in work_items:
        key = (row["division"], row["section_no"])
        toc_match = row_by_id.get(key)
        legacy_state = row.get("legacy_execution_observation")
        if row.get("citation_issue"):
            next_actions = ["verify_source_and_rule_citations"]
        elif row.get("parsed_chunk_mismatch"):
            next_actions = ["repair_source_chunk_link"]
        elif row.get("format_issue"):
            next_actions = ["repair_spec_format"]
        elif legacy_state == "legacy_basic_execution_failed":
            next_actions = ["diagnose_legacy_basic_execution_failure"]
        elif legacy_state == "legacy_basic_executable":
            next_actions = ["enumerate_rules_and_test_conditions_beyond_legacy_basic_pass"]
        else:
            next_actions = ["establish_source_rules_and_first_execution_evidence"]
        row["processing_status"] = {
            "inventory_unit": "draft_work_entry_proxy",
            "official_toc_section_match": bool(toc_match),
            "parsed_source_identity_match": row.get("source_parse_section_present", False),
            "source_table_note_reference_rules": "not_enumerated",
            "rule_interpretation": "not_verified",
            "existing_spec": "draft_present" if row.get("execution_spec_present") else "missing",
            "calculator_reuse": "candidate_family_declared_not_condition_verified",
            "runtime_representability": "not_established",
            "legacy_execution_state": legacy_state,
            "all_conditions_calculation_verified": False,
            "real_automatic_generation": "not_verified",
            "consultation": "not_verified",
            "multi_item_aggregation": "not_verified",
            "excel": "not_verified",
            "next_actions": next_actions,
        }

    parsed_only = []
    for (division, section_no), chunks in sorted(parsed.items(), key=lambda item: ((item[0][0] or ""), item[0][1])):
        if (division, section_no) in work_ids:
            continue
        parsed_only.append({
            "division": division,
            "section_no": section_no,
            "titles": sorted({chunk.get("section") or "" for chunk in chunks}),
            "pdf_pages": sorted({page for chunk in chunks for page in chunk.get("pages", [])}),
            "chunk_ids": sorted({chunk["chunk_id"] for chunk in chunks}),
            "division_identity_missing": division in (None, ""),
            "same_section_number_other_divisions": len(section_numbers_by_division[section_no]) > 1,
            "official_toc_exact_match": (division, section_no) in toc_ids,
            "work_item_classification": "unresolved_not_assumed_calculation_work",
        })
    draft_only = [
        {"division": row["division"], "section_no": row["section_no"], "spec_path": row["spec_path"],
         "official_toc_exact_match": (row["division"], row["section_no"]) in toc_ids,
         "classification": "unresolved_not_assumed_source_omission"}
        for row in work_items if (row["division"], row["section_no"]) not in parsed_ids
    ]

    legacy_counts = collections.Counter(row.get("legacy_execution_observation") for row in work_items)
    failure_clusters: dict[str, dict] = {}
    for row in work_items:
        item_key = f"{row['division']}:{row['section_no']}"
        classified = []
        for record in row.get("legacy_execution_attempt_records", []):
            if record.get("state") != "basic_execution_failed":
                continue
            cluster_id = classify_legacy_failure(record.get("reason", ""))
            classified.append(cluster_id)
            cluster = failure_clusters.setdefault(cluster_id, {"record_count": 0, "affected_work_items": []})
            cluster["record_count"] += 1
            affected = {"work_item": item_key, "execution_record_id": record.get("id"),
                        "reason": record.get("reason", "")}
            if affected not in cluster["affected_work_items"]:
                cluster["affected_work_items"].append(affected)
        row["processing_status"]["legacy_failure_clusters"] = classified
    coverage["inventory_reconciliation"] = {
        "version": "2026-10-18.official-toc-v1",
        "source_pdf": str(pdf_path.relative_to(ROOT)).replace("\\", "/"),
        "source_pdf_sha256": sha256(pdf_path),
        "toc_pdf_pages": sorted({row["toc_pdf_page"] for row in toc_rows}),
        "official_parent_section_count": len(toc_parent),
        "official_third_level_section_count": len(toc_third),
        "official_third_level_by_division": dict(collections.Counter(row["division"] for row in toc_third)),
        "draft_work_entries": len(work_items),
        "official_third_level_exact_draft_matches": len(toc_ids & work_ids),
        "official_third_level_without_draft": len(toc_ids - work_ids),
        "draft_without_exact_official_third_level": len(work_ids - toc_ids),
        "parsed_section_identities": len(parsed_ids),
        "official_third_level_exact_parse_matches": len(toc_ids & parsed_ids),
        "parsed_identity_without_draft_entry": len(parsed_ids - work_ids),
        "draft_without_exact_parsed_identity": len(work_ids - parsed_ids),
        "parsed_null_or_empty_division_identities": sum(division in (None, "") for division, _ in parsed_ids),
        "parsed_section_numbers_reused_across_divisions": sum(len(divisions) > 1 for divisions in section_numbers_by_division.values()),
        "work_item_denominator_resolved": False,
        "rule_denominator_resolved": False,
        "limitation": "Official ToC establishes section identities, not which sections are calculation work items. Parents, continuation pages, common policies, lookups, and resource codes still require classification against source pages; no unmatched row is silently excluded.",
        "legacy_execution_counts": dict(legacy_counts),
        "legacy_failure_grouping_method": "Provisional string classification of stored failure reasons; counts aid triage and do not confirm causal root cause.",
        "legacy_failure_clusters": failure_clusters,
        "parsed_only_candidates": parsed_only,
        "draft_only_candidates": draft_only,
        "official_toc_inventory": toc_rows,
    }
    coverage["report_version"] = "2026-10-18.v2"
    coverage["denominator_definitions"]["section"] = (
        "official contents: 222 parent plus 1,095 third-level identities; parsed chunk identities are a separate extraction denominator, not an official work-item count"
    )
    coverage["inventory_summary"].update({
        "official_parent_sections": len(toc_parent),
        "official_third_level_sections": len(toc_third),
        "official_third_level_exact_draft_matches": len(toc_ids & work_ids),
        "official_third_level_without_draft": len(toc_ids - work_ids),
        "draft_without_exact_official_third_level": len(work_ids - toc_ids),
        "official_third_level_without_parse": len(toc_ids - parsed_ids),
        "parsed_identity_outside_official_third_level": len(parsed_ids - toc_ids),
        "official_calculation_work_item_denominator_resolved": False,
        "official_rule_denominator_resolved": False,
    })
    coverage["work_queue"] = {
        "version": "2026-10-18.work-queue-v2",
        "denominator": f"{len(work_items)} current draft work-entry proxies; the official calculation work-item denominator is unresolved",
        "legacy_execution_counts": dict(legacy_counts),
        "all_conditions_calculation_verified": 0,
        "real_automatic_generation_verified": 0,
        "consultation_aggregate_excel_verified": 0,
        "queue_rule": "A row stays open until source rule mapping, applicability, execution, consultation, aggregation, and Excel have evidence. Draft presence, basic legacy execution, or mock generation alone cannot close it.",
    }
    coverage["inputs_and_hashes"]["inventory_identity_audit"] = {
        "official_toc_pdf_sha256": sha256(pdf_path),
        "chunks": str(CHUNKS.relative_to(ROOT)).replace("\\", "/"),
        "chunks_sha256": sha256(CHUNKS),
        "page_map": str(PAGE_MAP.relative_to(ROOT)).replace("\\", "/"),
        "page_map_sha256": sha256(PAGE_MAP),
    }
    defects = coverage["common_defects"]
    defects[:] = [item for item in defects if item.get("id") not in {"C6", "C7"}]
    defects.extend([
        {
            "id": "C6",
            "cause": "Parsed section identity does not preserve parent/division metadata consistently, so parse identity counts cannot stand in for official work-item coverage.",
            "evidence": "Pinned official ToC has 1,095 third-level sections and 222 parent sections. Current 1,058 draft rows match 1,044 official third-level identities; 51 ToC identities lack a draft row and 14 draft rows lack an exact ToC identity. Parsed data has 1,120 identities, including 15 with null/empty division and 204 section numbers reused across divisions.",
            "affected_inventory": "All ToC, parse, and draft identities until parent/continuation ranges and calculation-vs-reference sections are reconciled.",
            "completion": "Classify every official ToC section as calculation work, source policy/reference, lookup, heading, or other with page evidence; link parsed chunks and drafts without dropping or double-counting entries; then establish work-item and rule denominators.",
        },
        {
            "id": "C7",
            "cause": "The estimate tools and dialogue use the first/only item, while session and aggregate primitives have partial multi-item shapes; there is no active-item consultation orchestration.",
            "evidence": "Focused single-item API/XLSX integration passed. Static inspection shows tools._item selects item_order[0] and DialogueState describes one item. No multi-item consultation/edit/restore test exists.",
            "affected_inventory": "Multi-work estimates; single-item consultation is not affected by this specific gap.",
            "completion": "Add common item-scoped orchestration and verify two distinct items through calculation, pricing, edit isolation, aggregate refresh, persisted restore, and XLSX with no duplicate/missing shared costs.",
        },
    ])
    c3 = next((item for item in defects if item.get("id") == "C3"), None)
    if c3:
        c3["evidence"] = (
            "339 stored basic failures are retained. Provisional reason-string groups (not confirmed root causes): "
            + ", ".join(f"{name}={group['record_count']}" for name, group in sorted(failure_clusters.items()))
            + ". Affected work item and execution record IDs are in inventory_reconciliation.legacy_failure_clusters."
        )
    COVERAGE.write_text(json.dumps(coverage, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "official_toc_parents": len(toc_parent),
        "official_toc_third_level": len(toc_third),
        "official_draft_matches": len(toc_ids & work_ids),
        "official_without_draft": len(toc_ids - work_ids),
        "draft_without_toc": len(work_ids - toc_ids),
        "parsed_identities": len(parsed_ids),
        "parsed_null_division": coverage["inventory_reconciliation"]["parsed_null_or_empty_division_identities"],
        "legacy_execution": dict(legacy_counts),
        "official_toc_pages": coverage["inventory_reconciliation"]["toc_pdf_pages"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
