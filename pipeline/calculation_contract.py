"""Shared evidence and execution contract for calculation-module candidates."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

CONTRACT_VERSION = "1.0"
EXECUTORS = {"json_interpreter", "isolated_python"}


def _normalized_evidence_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split())


def _evidence_id(pdf_hash: str, edition: str, division: str, section_no: str,
                 kind: str, pdf_page: int | None, printed_page: int | None,
                 locator: str, content: str) -> str:
    # Identity is source/location/content based. It never depends on parser array order.
    stable = "|".join((pdf_hash, edition, division, section_no, kind,
                       str(pdf_page or ""), str(printed_page or ""),
                       _normalized_evidence_text(locator), _normalized_evidence_text(content)))
    return "evidence-" + hashlib.sha256(stable.encode("utf-8")).hexdigest()[:24]


def _table_note_text(chunk: dict) -> tuple[str, str] | None:
    """Extract only an explicitly labeled table '비고' cell; ordinary table rows are excluded."""
    if chunk.get("kind") != "table":
        return None
    lines = (chunk.get("text") or "").splitlines()
    heading = next((line.strip() for line in lines
                    if re.match(r"^\s*\d+(?:-\d+)*\.\s+", line)), "")
    cells = []
    for line in lines:
        cells_in_line = [part.strip() for part in line.split("|")]
        for index, cell in enumerate(cells_in_line[:-1]):
            if cell == "비고":
                note = cells_in_line[index + 1]
                if note:
                    cells.append(note)
    if not cells:
        return None
    return heading, "\n".join(cells)


def _source_evidence(item: dict, *, index: int, pdf_hash: str, edition: str,
                     division: str, section_no: str, page_map: dict,
                     legacy_note: bool) -> dict | None:
    kind = item.get("kind")
    source = item.get("source") or {}
    pages = [int(page) for page in item.get("pages", []) if str(page).isdigit()]
    pdf_page = int(source.get("page") or (pages[0] if pages else 0)) or None
    printed_page = (page_map.get(str(pdf_page), {}).get("printed_page") if pdf_page else None)
    if kind == "table":
        parsed = _table_note_text(item)
        if not parsed:
            return None
        heading, content = parsed
        table_id = source.get("table_id")
        bbox = source.get("bbox")
        locator = f"{heading}|{table_id or ''}|{json.dumps(bbox, separators=(',', ':')) if bbox else ''}"
        evidence_kind = "table_note"
        location = {"kind": evidence_kind, "pdf_page": pdf_page,
                    "printed_page": printed_page, "table_heading": heading,
                    "label": "비고", "parser_table_id": table_id, "table_bbox": bbox}
    elif kind in ("note", "paragraph", "text"):
        content = item.get("text") or ""
        if not content.strip():
            return None
        evidence_kind, locator = f"prose_{kind}", "section prose"
        location = {"kind": evidence_kind, "pdf_page": pdf_page,
                    "printed_page": printed_page}
    else:
        return None
    evidence_id = _evidence_id(pdf_hash, edition, division, section_no,
                               evidence_kind, pdf_page, printed_page, locator, content)
    aliases = []
    if legacy_note:
        explicit_id = item.get("id") or item.get("internal_id") or item.get("chunk_id") or source.get("chunk_id")
        if explicit_id:
            alias = str(explicit_id)
            if item.get("chunk_id") and not item.get("id") and not item.get("internal_id"):
                alias = f"{division}/{section_no}/{alias}"
            aliases.append(alias)
    return {"note_id": evidence_id, "evidence_id": evidence_id,
            "legacy_aliases": aliases, "kind": evidence_kind,
            "location": location, "content": content, "chunk": item}


def validate_contract(contract: object) -> list[str]:
    if not isinstance(contract, dict):
        return ["calculation_contract must be an object"]
    errors = []
    if contract.get("contract_version") != CONTRACT_VERSION:
        errors.append("calculation_contract.contract_version must be 1.0")
    source = contract.get("source")
    if not isinstance(source, dict):
        errors.append("calculation_contract.source is required")
    else:
        if not isinstance(source.get("pdf_sha256"), str) or len(source["pdf_sha256"]) != 64:
            errors.append("source.pdf_sha256 must be a SHA-256 digest")
        if not isinstance(source.get("edition"), str) or not source["edition"]:
            errors.append("source.edition is required")
        if not isinstance(source.get("pages"), list) or not source["pages"]:
            errors.append("source.pages must identify the full source section")
        if not isinstance(source.get("citations"), list) or not source["citations"]:
            errors.append("source.citations must preserve note/table/reference links")
        if not isinstance(source.get("note_rule_map"), list):
            errors.append("source.note_rule_map must list every calculation note")
        else:
            seen = set()
            for index, item in enumerate(source["note_rule_map"]):
                if not isinstance(item, dict) or not isinstance(item.get("note_id"), str):
                    errors.append(f"source.note_rule_map[{index}] needs note_id")
                    continue
                if item["note_id"] in seen:
                    errors.append(f"source.note_rule_map duplicates {item['note_id']}")
                seen.add(item["note_id"])
                if not item.get("rule_ids") and not item.get("excluded_reason"):
                    errors.append(f"source.note_rule_map[{index}] needs rule_ids or an evidence-backed excluded_reason")
    site_inputs = contract.get("site_inputs")
    if not isinstance(site_inputs, list):
        errors.append("site_inputs must be a list")
    else:
        seen_inputs = set()
        for index, field in enumerate(site_inputs):
            if (not isinstance(field, dict) or not isinstance(field.get("name"), str)
                    or not isinstance(field.get("type"), str) or "unit" not in field
                    or not isinstance(field.get("source"), str)):
                errors.append(f"site_inputs[{index}] needs name, type, unit, and source")
                continue
            if field["name"] in seen_inputs:
                errors.append(f"site_inputs duplicates {field['name']}")
            seen_inputs.add(field["name"])
    application = contract.get("application")
    if not isinstance(application, dict):
        errors.append("application scope and calculation order are required")
    else:
        for key in ("conditions", "target", "order", "system_policies"):
            if key not in application:
                errors.append(f"application.{key} is required")
    executor = contract.get("executor")
    if not isinstance(executor, dict) or executor.get("kind") not in EXECUTORS:
        errors.append("executor.kind must be json_interpreter or isolated_python")
    verification = contract.get("verification")
    if not isinstance(verification, dict) or not isinstance(verification.get("cases"), list) or not verification["cases"]:
        errors.append("verification.cases must include independently expected test IDs and source citations")
    elif any(not isinstance(case, dict) or not isinstance(case.get("id"), str)
             or not isinstance(case.get("citation"), str) for case in verification["cases"]):
        errors.append("every verification case needs an ID and source citation")
    return errors


def build_source_bundle(pdf_path: Path, chunks_path: Path, page_map_path: Path,
                        division: str | None, section_no: str) -> tuple[str, dict]:
    """Build a scoped evidence package containing PDF pages, parser output and citations."""
    import fitz
    pdf_path, chunks_path, page_map_path = map(Path, (pdf_path, chunks_path, page_map_path))
    pdf_bytes = pdf_path.read_bytes()
    chunks = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    page_map = json.loads(page_map_path.read_text(encoding="utf-8"))["pages"]
    matches = [item for item in chunks if item.get("section_no") == section_no
               and (not division or item.get("division") == division)]
    divisions = {item.get("division") for item in matches}
    if not division and len(divisions) > 1:
        raise ValueError(f"section {section_no} is ambiguous; specify --division")
    if not division and divisions:
        division = next(iter(divisions))
    section_chunks = matches
    if not section_chunks:
        raise ValueError(f"parsed chunks missing for {division}/{section_no}")
    pages = sorted({int(item.get("source", {}).get("page") or page)
                    for item in section_chunks for page in item.get("pages", [])})
    if not pages:
        pages = sorted({int(item["source"]["page"]) for item in section_chunks if item.get("source", {}).get("page")})
    if not pages:
        raise ValueError("section PDF page mapping is missing")
    # Preserve outgoing section references as source material and explicit citations.
    references = []
    def scan_references(node):
        if isinstance(node, dict):
            if node.get("section_no") or node.get("section"):
                references.append(node)
            for value in node.values():
                scan_references(value)
        elif isinstance(node, list):
            for value in node:
                scan_references(value)
    for item in section_chunks:
        scan_references(item)
    related = []
    for ref in references:
        ref_section = ref.get("section_no") or ref.get("section")
        ref_division = ref.get("division", division)
        related.extend(item for item in chunks if ref_section and (ref_division, ref_section) != (division, section_no)
                       and item.get("section_no") == ref_section
                       and item.get("division") == ref_division)
    pages = sorted(set(pages) | {int(item["source"]["page"]) for item in related
                                  if item.get("source", {}).get("page")})
    if pages:
        pages = sorted(set(pages) | set(range(min(pages), max(pages) + 1)))
    pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
    page_records = []
    for page in pages:
        if page < 1 or page > len(pdf):
            raise ValueError(f"PDF page {page} is outside source document")
        record = page_map.get(str(page), {})
        page_records.append({"pdf_page": page, "printed_page": record.get("printed_page"),
                             "text": pdf[page - 1].get_text()})
    edition = "2026"
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    calculation_notes = []
    for index, item in enumerate(section_chunks):
        evidence = _source_evidence(item, index=index, pdf_hash=pdf_hash,
            edition=edition, division=division, section_no=section_no,
            page_map=page_map, legacy_note=True)
        if evidence:
            calculation_notes.append(evidence)
    referenced_evidence = []
    for index, item in enumerate(related):
        evidence = _source_evidence(item, index=index, pdf_hash=pdf_hash,
            edition=edition, division=item.get("division", division),
            section_no=str(item.get("section_no") or item.get("section") or ""),
            page_map=page_map, legacy_note=False)
        if evidence:
            referenced_evidence.append(evidence)
    evidence_ids = [item["evidence_id"] for item in calculation_notes]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("source contains duplicate stable calculation-evidence identities")
    payload = {"edition": edition, "division": division, "section_no": section_no,
        "pdf_file": pdf_path.name, "pdf_sha256": pdf_hash,
        "page_map_sha256": hashlib.sha256(page_map_path.read_bytes()).hexdigest(),
        "chunks_sha256": hashlib.sha256(chunks_path.read_bytes()).hexdigest(),
        "full_section_pdf_pages": page_records, "parsed_section_tables_notes": section_chunks,
        "referenced_chunks": related, "referenced_evidence": referenced_evidence,
        "references": references,
        # Keep the historical field name for contract compatibility. Its IDs are
        # now stable evidence IDs; legacy parser IDs are explicit aliases only.
        "calculation_notes": calculation_notes,
        "source_evidence": calculation_notes + referenced_evidence}
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")), payload
