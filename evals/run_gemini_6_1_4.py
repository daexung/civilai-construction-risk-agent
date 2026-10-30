"""Cost-reserved real Gemini generation/evaluation for source section 6-1-4.

This is an evaluation candidate flow only. It never registers or deploys a spec.
Expected values stay in the trusted evaluator and are never sent to the model.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.draft_specs import (  # noqa: E402
    build_instructions, build_parsed_payload, build_pdf_excerpt, env_value,
    fill_divisions, group_sections, load_chunks, load_page_map,
    make_vertex_request_fn, parse_response,
)
from pipeline.validate_drafts import check_citations, chunks_by_id_from_list  # noqa: E402
from backend.agent.tools.calc.daily_crew import adjusted_daily_crew  # noqa: E402
from pipeline.calculation_contract import build_source_bundle  # noqa: E402
from pipeline.calculation_modules import (  # noqa: E402
    ResponseTruncatedError, SEMANTIC_AUTHORING_SCHEMA, author_semantic_candidate,
    build_semantic_authoring_prompt, validate_semantic_authoring, assemble_semantic_candidate,
    collect_known_input_fields,
    load_case_file, run_candidate_case,
)
from backend.agent.tools.calc.policies import allowed_policy_ids  # noqa: E402

RUN_DIR = ROOT / "evals" / "runtime_validation" / "gemini_6_1_4_2026-10-17"
MODEL_CONFIG = ROOT / "pipeline" / "draft_specs_config.json"
CHUNKS_PATH = ROOT / "data" / "processed" / "chunks.all.jsonl"
PAGE_MAP_PATH = ROOT / "data" / "processed" / "page_map.json"
SPEC_FORMAT_PATH = ROOT / "docs" / "SPEC_FORMAT.md"
AUTHOR_PATH = ROOT / "evals" / "calculation_modules" / "gemini_6_1_4_authoring_2026-10-17.json"
FINAL_PATH = ROOT / "evals" / "calculation_modules" / "gemini_6_1_4_final_2026-10-17.json"
PDF_PATH = next((ROOT / "data" / "raw" / "standard_estimation").glob("*.pdf"))
MAX_USD = 1.0
MAX_CALLS = 9
MAX_OUTPUT_TOKENS = 7000
REPAIR_SUFFIX = """

[Trusted authoring-test failure feedback]
The prior candidate failed these authoring checks. Correct the calculation specification while preserving every rule and condition stated in the supplied source. Do not remove a source rule, add a blocked condition to avoid a calculable case, or ask the user to provide a calculation policy. The reported failure labels identify only which behavior needs correction; no expected values or held-out cases are provided.
{issues}
Return the complete corrected JSON object in the required format only.
"""


def setup() -> tuple[str, bytes, str, list[dict], dict]:
    config = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
    chunks = fill_divisions(load_chunks(CHUNKS_PATH), load_page_map(PAGE_MAP_PATH))
    grouped = group_sections(chunks)
    section_key = next(key for key in grouped if key[1] == "6-1-4" and key[0] != "건축")
    section_chunks = grouped[section_key]
    source_pdf = build_pdf_excerpt(PDF_PATH, [186, 187])
    prompt = build_instructions(section_key[0], section_key[1], build_parsed_payload(section_chunks),
                                SPEC_FORMAT_PATH.read_text(encoding="utf-8"), None)
    return config["model"], source_pdf, prompt, section_chunks, config


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def exact_cost(input_tokens: int, output_tokens: int, input_rate: float, output_rate: float) -> float:
    return input_tokens * input_rate / 1_000_000 + output_tokens * output_rate / 1_000_000


def load_ledger() -> dict:
    path = RUN_DIR / "budget-ledger.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"max_usd": MAX_USD, "max_generation_calls": MAX_CALLS, "reserved_usd": 0.0,
            "actual_usd": 0.0, "calls": []}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def reconcile_ledger(ledger: dict, config: dict) -> dict:
    """Settle only received calls with usable token counts and a known applicable rate."""
    historical_reservations = sum(float(item.get("reserved_usd", 0)) for item in ledger.get("calls", []))
    settled = 0.0
    unsettled = 0.0
    for item in ledger.get("calls", []):
        reserve = float(item.get("reserved_usd", 0))
        if item.get("state") != "response-received":
            unsettled += reserve
            continue
        in_tokens = item.get("actual_input_tokens", item.get("input_tokens"))
        out_tokens = item.get("output_tokens_billed", item.get("output_tokens_including_thoughts"))
        if in_tokens is None or out_tokens is None:
            unsettled += reserve
            continue
        in_rate = item.get("input_usd_per_million", config.get("input_usd_per_million"))
        out_rate = item.get("output_usd_per_million", config.get("output_usd_per_million"))
        if in_rate is None or out_rate is None:
            unsettled += reserve
            continue
        settled += exact_cost(int(in_tokens), int(out_tokens), float(in_rate), float(out_rate))
    return {"historical_max_reservations_usd": round(historical_reservations, 9),
            "settled_usage_estimate_usd": round(settled, 9),
            "unsettled_reservations_usd": round(unsettled, 9),
            "remaining_budget_usd": round(MAX_USD - settled - unsettled, 9),
            "billing_invoice_verified": False,
            "basis": "reported input/output+reasoning tokens x applicable non-Priority global token rates",
            "pricing_source": "https://cloud.google.com/vertex-ai/generative-ai/pricing"}


def preflight() -> None:
    model, source_bundle, pdf_bytes, bundle_hash, author_cases, _, config = _module_source()
    output_limit = int(config.get("calculation_authoring_max_output_tokens", MAX_OUTPUT_TOKENS))
    thinking_level = config.get("calculation_authoring_thinking_level", "LOW")
    if not 1 <= output_limit <= 65536 or thinking_level not in {"LOW", "MEDIUM", "HIGH"}:
        raise SystemExit("BLOCKED: unsupported Gemini output or thinking configuration")
    key = env_value("VERTEX_API_KEY_BULK", ROOT / ".env")
    if not key:
        raise SystemExit("BLOCKED: VERTEX_API_KEY_BULK is not configured")
    request = make_vertex_request_fn(key, thinking_level=thinking_level,
                                    response_json_schema=SEMANTIC_AUTHORING_SCHEMA)
    known_conditions = {str(block["condition"]): block for case in author_cases
        for block in case.get("spec", {}).get("blocked", []) if block.get("condition")}
    known_fields = collect_known_input_fields(author_cases)
    prompt = build_semantic_authoring_prompt(source_bundle,
        allowed_system_policies=allowed_policy_ids("\uacf5\ud1b5", "6-3-1"),
        known_blocked_conditions=known_conditions, known_input_fields=known_fields)
    counted_content = request.count_input_tokens(model, pdf_bytes, prompt)
    counted_schema = request.count_input_tokens(model, b"", json.dumps(SEMANTIC_AUTHORING_SCHEMA, separators=(",", ":")))
    input_tokens = counted_content + counted_schema
    input_rate, output_rate = float(config["input_usd_per_million"]), float(config["output_usd_per_million"])
    reserve = exact_cost(input_tokens, output_limit, input_rate, output_rate)
    ledger = load_ledger()
    settlement = reconcile_ledger(ledger, config)
    if len(ledger.get("calls", [])) >= MAX_CALLS or settlement["settled_usage_estimate_usd"] + settlement["unsettled_reservations_usd"] + reserve > MAX_USD:
        raise SystemExit("BLOCKED: preflight maximum reservation exceeds the unchanged cumulative call/USD authorization")
    record = {"pipeline": "semantic-authoring-v1", "model": model,
        "provider": "Vertex AI Express Mode", "thinking_level": thinking_level,
        "max_output_tokens": output_limit, "response_json_schema_sha256": sha(json.dumps(SEMANTIC_AUTHORING_SCHEMA, sort_keys=True).encode()),
        "source_pdf_sha256": sha(PDF_PATH.read_bytes()), "source_bundle_sha256": bundle_hash,
        "prompt_sha256": sha(prompt.encode("utf-8")), "content_tokens_counted": counted_content,
        "schema_tokens_counted_conservatively": counted_schema, "input_tokens_reserved": input_tokens,
        "input_usd_per_million": input_rate, "output_usd_per_million": output_rate,
        "next_call_max_reservation_usd": round(reserve, 9), "settlement": settlement,
        "count_tokens": "success", "count_tokens_pricing": "no charge per official provider documentation",
        "checked_at": datetime.now(timezone.utc).isoformat()}
    write_json(RUN_DIR / "module-json-semantic-preflight.json", record)
    ledger["settlement_summary"] = settlement
    write_json(RUN_DIR / "budget-ledger.json", ledger)
    print(json.dumps(record, ensure_ascii=False))

def _module_source() -> tuple[str, dict, bytes, str, list[dict], list[dict], dict]:
    config = json.loads(MODEL_CONFIG.read_text(encoding="utf-8"))
    source_bundle, source_meta = build_source_bundle(
        PDF_PATH, ROOT / "data" / "processed" / "chunks.all.jsonl", PAGE_MAP_PATH,
        "공통", "6-3-1")
    page_records = source_meta["full_section_pdf_pages"]
    if not any(item.get("pdf_page") == 193 and item.get("printed_page") == 137
               for item in page_records):
        raise RuntimeError("source page map did not preserve PDF p.193 / printed p.137")
    pdf_bytes = build_pdf_excerpt(PDF_PATH, [item["pdf_page"] for item in page_records])
    author_cases = load_case_file(ROOT / "evals" / "calculation_modules" / "formwork_authoring_cases.json")
    final_path = ROOT / "evals" / "calculation_modules" / "formwork_final_evaluation_cases.json"
    final_cases = load_case_file(final_path)
    return config["model"], source_bundle, pdf_bytes, sha(source_bundle.encode("utf-8")), author_cases, final_cases, config


def _verify_api_contract(candidate: dict) -> dict:
    """Exercise /api/chat, item edit, totals and XLSX with a temporary module override."""
    import os
    from contextlib import nullcontext
    from io import BytesIO
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from openpyxl import load_workbook
    from backend.api.main import app
    from backend.agent.rules.specs import load_specs
    from backend.agent.tools.calc import generated

    original_lookup = generated.registered_module_for
    def candidate_lookup(spec):
        if spec.get("division") == "공통" and spec.get("section_no") == "6-3-1":
            return candidate
        return original_lookup(spec)

    spec = next(item for item in load_specs().values()
                if item.get("division") == "공통" and item.get("section_no") == "6-3-1")
    spec["quantity_model"]["params"]["module_id"] = candidate["id"]
    env = {"AGENT_MODE": "tools", "AGENT_LLM": "off", "AGENT_OFFLINE": "1"}
    with patch.dict(os.environ, env), \
         patch("backend.api.usage_limits.processing", return_value=nullcontext((None, "eval", False))), \
         patch("backend.api.usage_limits.consume", return_value={}), \
         patch("backend.api.usage_limits.status", return_value={}), \
         patch("backend.shared.answer_trace.persist_start"), \
         patch("backend.shared.answer_trace.finalize"), \
         patch.object(generated, "registered_module_for", side_effect=candidate_lookup), \
         patch("backend.agent.nodes.compute.registered_module_for", side_effect=candidate_lookup):
        client = TestClient(app, headers={"X-Guest-Session": "gemini-eval-" + "x" * 32})
        first_response = client.post("/api/chat", json={
            "message": "합판거푸집 100㎡ 비용 견적, 높이 40m, 양중장비 미사용"})
        if first_response.status_code != 200:
            raise AssertionError(f"/api/chat initial request: {first_response.status_code}")
        first = first_response.json()
        answer_values = {"complexity": "복잡", "height": "40", "volume": "100",
                         "is_roof_slab": False, "crane_used": False,
                         "lifting_equipment_used": False}
        current = first
        for _ in range(8):
            questions = current.get("questions", [])
            if not questions:
                break
            work_choice = next((item.get("default") or item["choices"][0] for item in questions
                                if item.get("name") == "work" and (item.get("choices") or item.get("default"))), None)
            answers = {item["name"]: answer_values[item["name"]]
                       for item in questions if item["name"] in answer_values}
            if work_choice:
                answers["work"] = work_choice
            if not answers:
                raise AssertionError(f"unhandled site-fact questions: {questions}")
            refs = {item["name"]: item["ref"] for item in questions
                    if item["name"] in answers and item.get("ref")}
            response = client.post("/api/chat", json={"thread_id": first["thread_id"],
                                     "answers": answers, "refs": refs})
            if response.status_code != 200:
                raise AssertionError(f"/api/chat answers: {response.status_code}")
            current = response.json()
        if current.get("status") not in ("PARTIAL", "OK", "COMPUTED"):
            raise AssertionError(f"/api/chat did not compute with site facts: {current.get('status')}")
        before_total = current["statement"]["totals"]["contract_amount"]
        edit = client.post("/api/chat", json={"thread_id": first["thread_id"],
                            "message": "물량을 120㎡로 변경해서 다시 계산해 주세요"})
        if edit.status_code != 200:
            raise AssertionError(f"/api/chat edit: {edit.status_code}")
        updated = edit.json()
        after_total = updated["statement"]["totals"]["contract_amount"]
        if after_total == before_total or updated["statement"]["status"] != "PARTIAL":
            raise AssertionError("edited aggregate did not refresh or missing costs were shown as complete")
        export = client.get(f"/api/export/{first['thread_id']}.xlsx")
        if export.status_code != 200:
            raise AssertionError(f"/api/export: {export.status_code}")
        workbook = load_workbook(BytesIO(export.content), data_only=False)
        basis = [" ".join(str(cell) for cell in row if cell is not None)
                 for row in workbook["산출근거"].iter_rows(values_only=True)]
        return {"chat_status": current["status"], "edit_status": updated["status"],
                "before_contract_amount": before_total, "after_contract_amount": after_total,
                "estimate_status": updated["statement"]["status"],
                "xlsx_status": "exported", "basis_contains_candidate_id":
                    any(candidate["id"] in row for row in basis)}


def _verify_api_contract_v2(candidate: dict) -> dict:
    """Run the generated candidate through chat, edit, aggregate and XLSX contracts."""
    import os
    from contextlib import nullcontext
    from io import BytesIO
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from openpyxl import load_workbook
    from backend.api.main import app
    from backend.agent.tools.calc import generated

    original_lookup = generated.registered_module_for
    def candidate_lookup(spec):
        if spec.get("division") == "\uacf5\ud1b5" and spec.get("section_no") == "6-3-1":
            return candidate
        return original_lookup(spec)

    with patch.dict(os.environ, {"AGENT_MODE": "graph", "AGENT_LLM": "off", "AGENT_OFFLINE": "1"}), \
         patch("backend.api.usage_limits.processing", return_value=nullcontext((None, "eval", False))), \
         patch("backend.api.usage_limits.consume", return_value={}), \
         patch("backend.api.usage_limits.status", return_value={}), \
         patch("backend.shared.answer_trace.persist_start"), \
         patch("backend.shared.answer_trace.finalize"), \
         patch.object(generated, "registered_module_for", side_effect=candidate_lookup), \
         patch("backend.agent.nodes.compute.registered_module_for", side_effect=candidate_lookup):
        client = TestClient(app, headers={"X-Guest-Session": "gemini-eval-" + "x" * 32})
        first_response = client.post("/api/chat", json={"message":
            "\uacf5\ud1b5 6-3-1 \ud569\ud310\uac70\ud478\uc9d1 \uc124\uce58 \ubc0f \ud574\uccb4, \ubcf5\uc7a1 100m2 \uc0b0\ucd9c \uacac\uc801, \ub192\uc774 40m, \uc591\uc911\uc7a5\ube44 \ubbf8\uc0ac\uc6a9"})
        if first_response.status_code != 200:
            raise AssertionError(f"/api/chat initial request: {first_response.status_code} {first_response.text}")
        first = first_response.json()
        answer_values = {"complexity": "\ubcf5\uc7a1", "height": "40", "volume": "100",
                         "is_roof_slab": False, "crane_used": False, "lifting_equipment_used": False}
        current = first
        for _ in range(8):
            questions = current.get("questions", [])
            if not questions:
                break
            answers = {item["name"]: answer_values[item["name"]]
                       for item in questions if item["name"] in answer_values}
            if not answers:
                raise AssertionError(f"unhandled site-fact questions: {questions}")
            refs = {item["name"]: item["ref"] for item in questions
                    if item["name"] in answers and item.get("ref")}
            response = client.post("/api/chat", json={"thread_id": first["thread_id"],
                                     "answers": answers, "refs": refs})
            if response.status_code != 200:
                raise AssertionError(f"/api/chat answers: {response.status_code} {response.text}")
            current = response.json()
        if current.get("status") not in ("PARTIAL", "OK", "COMPUTED"):
            raise AssertionError(f"/api/chat did not compute with site facts: {current.get('status')}")
        daily = current.get("result", {}).get("daily_volume", {})
        if daily.get("value") != "10.631060024624333494473":
            raise AssertionError(f"chat calculation did not use candidate output: {daily}")
        if not any("PDF p.193 (printed p.137)" in str(row.get("source", ""))
                   and "System assumption" in str(row.get("reason", ""))
                   for row in daily.get("adjustments", [])):
            raise AssertionError("chat response omitted page provenance or system assumption")
        if current.get("result", {}).get("calculation_module", {}).get("module_id") != candidate["id"]:
            raise AssertionError("chat result omitted temporary candidate module id")
        before_total = current["statement"]["totals"]["contract_amount"]
        edit = client.post("/api/chat", json={"thread_id": first["thread_id"],
                            "conditions": {"volume": "120"}})
        if edit.status_code != 200:
            raise AssertionError(f"/api/chat edit: {edit.status_code} {edit.text}")
        updated = edit.json()
        if not any(row.get("name") == "volume" and row.get("value") == "120"
                   for row in updated.get("inputs", [])):
            raise AssertionError("chat edit did not update volume")
        after_total = updated["statement"]["totals"]["contract_amount"]
        if after_total == before_total or updated["statement"]["status"] != "PARTIAL":
            raise AssertionError("edited aggregate failed to refresh or incomplete estimate was marked complete")
        export = client.get(f"/api/export/{first['thread_id']}.xlsx")
        if export.status_code != 200:
            raise AssertionError(f"/api/export: {export.status_code}")
        workbook = load_workbook(BytesIO(export.content), data_only=False)
        basis = [" ".join(str(cell) for cell in row if cell is not None)
                 for row in workbook["\uc0b0\ucd9c\uadfc\uac70"].iter_rows(values_only=True)]
        if not any(candidate["id"] in row for row in basis):
            raise AssertionError("XLSX omitted candidate module provenance")
        if not any("PDF p.193 (printed p.137)" in row and "System assumption" in row for row in basis):
            raise AssertionError("XLSX omitted source pages or system assumption")
        if not any("10.631060024624333494473" in row for row in basis):
            raise AssertionError("XLSX calculation did not match candidate")
        statement_rows = [" ".join(str(cell) for cell in row if cell is not None)
                          for row in workbook["\uacac\uc801\uc11c"].iter_rows(values_only=True)]
        if not any(str(after_total) in row for row in statement_rows):
            raise AssertionError("XLSX aggregate did not match the API result")
        return {"chat_status": current["status"], "edit_status": updated["status"],
                "before_contract_amount": before_total, "after_contract_amount": after_total,
                "estimate_status": updated["statement"]["status"],
                "candidate_daily_output": daily["value"], "basis_contains_candidate_id": True,
                "basis_contains_source_and_policy": True, "xlsx_total_matches": True,
                "xlsx_quantity_matches_edit": any("120" in row for row in basis)}


def execute_module_json() -> None:
    """Real Gemini authoring through calculation_modules with the cumulative ledger."""
    from google import genai as _genai  # noqa: F401 — verifies installed provider SDK import before budget reservation
    model, source_bundle, pdf_bytes, bundle_hash, author_cases, _, config = _module_source()
    output_limit = int(config.get("calculation_authoring_max_output_tokens", MAX_OUTPUT_TOKENS))
    thinking_level = config.get("calculation_authoring_thinking_level", "LOW")
    if not 1 <= output_limit <= 65536:
        raise SystemExit("BLOCKED: configured maximum output exceeds Gemini 3.1 Pro's documented limit")
    if thinking_level not in {"LOW", "MEDIUM", "HIGH"}:
        raise SystemExit("BLOCKED: configured thinking_level is not supported for Gemini 3.1 Pro Preview")
    key = env_value("VERTEX_API_KEY_BULK", ROOT / ".env")
    if not key:
        raise SystemExit("BLOCKED: configured Vertex credential is absent")
    request = make_vertex_request_fn(key, thinking_level=thinking_level,
                                    response_json_schema=SEMANTIC_AUTHORING_SCHEMA)
    policies = allowed_policy_ids("\uacf5\ud1b5", "6-3-1")
    known_conditions = {str(block["condition"]): block for case in author_cases
                        for block in case.get("spec", {}).get("blocked", []) if block.get("condition")}
    known_fields = collect_known_input_fields(author_cases)
    prompt = build_semantic_authoring_prompt(source_bundle, allowed_system_policies=policies,
        known_blocked_conditions=known_conditions, known_input_fields=known_fields)
    preflight_path = RUN_DIR / "module-json-semantic-preflight.json"
    if not preflight_path.exists():
        raise SystemExit("BLOCKED: semantic countTokens/cost preflight is required before generation")
    preflight_record = json.loads(preflight_path.read_text(encoding="utf-8"))
    schema_digest = sha(json.dumps(SEMANTIC_AUTHORING_SCHEMA, sort_keys=True).encode())
    if (preflight_record.get("pipeline") != "semantic-authoring-v1"
            or preflight_record.get("model") != model
            or preflight_record.get("source_bundle_sha256") != bundle_hash
            or preflight_record.get("prompt_sha256") != sha(prompt.encode("utf-8"))
            or preflight_record.get("response_json_schema_sha256") != schema_digest
            or preflight_record.get("max_output_tokens") != output_limit
            or preflight_record.get("thinking_level") != thinking_level):
        raise SystemExit("BLOCKED: preflight does not match semantic request, schema, model, or token settings")
    ledger_path = RUN_DIR / "budget-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if ledger.get("max_usd") != MAX_USD:
        raise SystemExit("BLOCKED: existing cumulative USD limit does not match the authorized $1 cap")
    calls = ledger.get("calls", [])
    if len(calls) < 3 or not __import__("math").isclose(
            sum(float(item["reserved_usd"]) for item in calls), float(ledger["reserved_usd"]), abs_tol=1e-9):
        raise SystemExit("BLOCKED: prior call/reservation ledger is inconsistent; it will not be reset")
    ledger["settlement_summary"] = reconcile_ledger(ledger, config)
    settled = ledger["settlement_summary"]["settled_usage_estimate_usd"]
    unsettled = ledger["settlement_summary"]["unsettled_reservations_usd"]
    if len(calls) >= MAX_CALLS:
        raise SystemExit("BLOCKED: cumulative generation-call cap has been reached")
    ledger["max_generation_calls"] = MAX_CALLS
    ledger["scope"] = "cumulative across the prior 6-1-4 run and this module-authoring run"
    ledger["model"] = model
    settings = {"model": model, "provider": "Vertex AI Express Mode",
                "thinking_level": thinking_level, "max_output_tokens": output_limit,
                "response_mime_type": "application/json", "temperature": 0,
                "response_json_schema_sha256": sha(json.dumps(SEMANTIC_AUTHORING_SCHEMA, sort_keys=True).encode()),
                "sdk_http_retries": 0, "model_limit_max_output_tokens": 65536}
    settings_path = RUN_DIR / "module-json-semantic-model-settings.json"
    write_json(settings_path, settings)
    input_rate = float(config["input_usd_per_million"])
    output_rate = float(config["output_usd_per_million"])
    if input_rate > 4.0 or output_rate > 18.0:
        raise SystemExit("BLOCKED: configured price exceeds the documented standard-global tier")
    call_sequence = len(calls)
    last_truncation = False

    def model_call(current_prompt: str) -> str:
        nonlocal call_sequence, last_truncation
        if len(ledger["calls"]) >= MAX_CALLS:
            raise RuntimeError("cumulative generation-call cap reached")
        counter = getattr(request, "count_input_tokens", None)
        if not callable(counter):
            raise RuntimeError("provider countTokens preflight required; no text-length estimate fallback")
        content_tokens = counter(model, pdf_bytes, current_prompt)
        schema_tokens = counter(model, b"", json.dumps(SEMANTIC_AUTHORING_SCHEMA, separators=(",", ":")))
        input_tokens = content_tokens + schema_tokens
        request_input_rate, request_output_rate = ((input_rate, output_rate)
            if input_tokens <= 200000 else (4.0, 18.0))
        reserve = exact_cost(input_tokens, output_limit, request_input_rate, request_output_rate)
        current_settlement = reconcile_ledger(ledger, config)
        settled_now = current_settlement["settled_usage_estimate_usd"]
        open_reservations = current_settlement["unsettled_reservations_usd"]
        if settled_now + open_reservations + reserve > MAX_USD:
            raise RuntimeError("settled usage plus unsettled reservations plus next maximum exceeds $1; request not sent")
        call_sequence += 1
        call_record = {"id": f"generation-{call_sequence}", "pipeline": "pipeline.calculation_modules.author_semantic_candidate",
            "executor": "json_interpreter", "model": model, "prompt_sha256": sha(current_prompt.encode("utf-8")),
            "source_bundle_sha256": bundle_hash, "input_tokens_counted": input_tokens,
            "content_tokens_counted": content_tokens, "schema_tokens_counted_conservatively": schema_tokens,
            "thinking_level": thinking_level, "max_output_tokens": output_limit,
            "request_settings": settings, "input_usd_per_million": request_input_rate,
            "output_usd_per_million": request_output_rate, "reserved_usd": reserve, "state": "reserved-before-request"}
        ledger["reserved_usd"] += reserve
        ledger["calls"].append(call_record)
        write_json(ledger_path, ledger)
        try:
            raw, actual_input, actual_output = request(model, pdf_bytes, current_prompt, output_limit)
        except Exception as exc:
            call_record.update({"state": "request-failed-or-response-lost", "error_type": type(exc).__name__})
            write_json(ledger_path, ledger)
            raise
        metadata = dict(request.last_response_metadata or {})
        actual = exact_cost(actual_input, actual_output, request_input_rate, request_output_rate)
        ledger["actual_usd"] += actual
        call_record.update({"state": "response-received", "actual_cost_estimate_usd": actual,
                            "actual_input_tokens": actual_input,
                            "answer_tokens": metadata.get("answer_tokens"),
                            "reasoning_tokens": metadata.get("reasoning_tokens"),
                            "output_tokens_billed": metadata.get("output_tokens_billed"),
                            "finish_reason": metadata.get("finish_reason"),
                            "model_version": metadata.get("model_version"),
                            "response_id": metadata.get("response_id"),
                            "request_settings": settings})
        raw_dir = RUN_DIR / "module-json-raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        raw_path = raw_dir / f"{call_record['id']}.json"
        raw_path.write_text(json.dumps({"response_text": raw, "provider_response": metadata.get("raw_response"),
                                        "usage_and_finish": {key: metadata.get(key) for key in (
                                            "finish_reason", "prompt_block_reason", "prompt_tokens",
                                            "answer_tokens", "reasoning_tokens", "output_tokens_billed",
                                            "total_tokens", "model", "model_version", "response_id")}},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        call_record["raw_response_path"] = str(raw_path.relative_to(ROOT))
        ledger["settlement_summary"] = reconcile_ledger(ledger, config)
        if actual > reserve or settled_now + actual + open_reservations > MAX_USD:
            call_record["state"] = "budget_reservation_mismatch"
            write_json(ledger_path, ledger)
            raise RuntimeError("actual token use exceeded the reserved/cumulative amount; no further call allowed")
        write_json(ledger_path, ledger)
        if metadata.get("finish_reason") == "MAX_TOKENS":
            last_truncation = True
            raise ResponseTruncatedError(
                f"finish_reason=MAX_TOKENS; answer_tokens={metadata.get('answer_tokens')}; "
                f"reasoning_tokens={metadata.get('reasoning_tokens')}; same-settings retry suppressed")
        if metadata.get("prompt_block_reason") not in (None, "BLOCK_REASON_UNSPECIFIED"):
            raise RuntimeError(f"provider blocked the prompt: {metadata['prompt_block_reason']}")
        return raw

    author_result = author_semantic_candidate(source_bundle, author_cases, model=model_call,
        max_repairs=2, allowed_system_policies=policies,
        output_dir=RUN_DIR / "module-json-candidates",
        attempt_log=RUN_DIR / "module-json-semantic-authoring-attempts.jsonl")
    ledger["settlement_summary"] = reconcile_ledger(ledger, config)
    write_json(ledger_path, ledger)
    result_record = {"pipeline": "pipeline.calculation_modules.author_semantic_candidate",
        "executor": "json_interpreter", "model_settings": settings,
        "authoring_result": author_result, "candidate_generated": author_result.get("status") == "candidate",
        "finish_reason": ledger["calls"][-1].get("finish_reason") if len(ledger["calls"]) > 3 else None,
        "truncated": last_truncation, "generation_calls_total": len(ledger["calls"]),
        "historical_max_reserved_usd": ledger["settlement_summary"]["historical_max_reservations_usd"],
        "settled_usage_estimate_usd": ledger["settlement_summary"]["settled_usage_estimate_usd"],
        "unsettled_reservations_usd": ledger["settlement_summary"]["unsettled_reservations_usd"],
        "remaining_budget_usd": ledger["settlement_summary"]["remaining_budget_usd"]}
    if author_result.get("status") == "candidate":
        candidate = json.loads(Path(author_result["path"]).read_text(encoding="utf-8"))
        final_path = ROOT / "evals" / "calculation_modules" / "formwork_final_evaluation_cases.json"
        # Final cases enter the trusted evaluator only after authoring succeeds.
        final_cases = load_case_file(final_path)
        final_rows = [{"case_id": case["id"], "passed": not run_candidate_case(candidate,
                       {**case, "allowed_system_policies": sorted(policies)})}
                      for case in final_cases]
        final_pass = all(row["passed"] for row in final_rows)
        eval_record = {"independent": True, "sent_to_model": False,
                       "passed": sum(row["passed"] for row in final_rows), "total": len(final_rows),
                       "cases": final_rows, "candidate_sha256": sha(Path(author_result["path"]).read_bytes())}
        write_json(Path(author_result["path"]).with_suffix(".evaluation.json"), eval_record)
        result_record["final_evaluation"] = {"passed": final_pass, "cases": final_rows}
        if final_pass:
            result_record["api_chat_aggregate_xlsx"] = _verify_api_contract_v2(candidate)
    write_json(RUN_DIR / "module-json-semantic-run-result.json", result_record)
    print(json.dumps(result_record, ensure_ascii=False))


def evaluate(spec: dict, cases_path: Path) -> tuple[list[dict], list[str]]:
    case_file = json.loads(cases_path.read_text(encoding="utf-8"))
    rows, issues = [], []
    for case in case_file["cases"]:
        result = adjusted_daily_crew(spec, case["inputs"], labor_only=True)
        expect = case["expected"]
        observed: dict[str, str] = {"status": result.get("status", "missing")}
        if result.get("status") == "computed":
            observed["daily_volume_m3"] = str(result["daily_volume_m3"])
            observed["work_days"] = str(result["work_days"])
            for trade, amount in result.get("person_days", {}).items():
                observed[f"person_days.{trade}"] = str(amount)
            for name, amount in result.get("equipment_days", {}).items():
                observed[f"equipment_days.{name}"] = str(amount)
        passed = all(observed.get(key) == value for key, value in expect.items())
        rows.append({"case_id": case["id"], "kind": case["kind"], "passed": passed})
        if not passed:
            issues.append(f"case={case['id']} behavior={case['kind']} mismatch")
    return rows, issues


def validate_candidate(raw: str, section_chunks: list[dict]) -> tuple[dict, list[str]]:
    issues: list[str] = []
    try:
        parsed = parse_response(raw)
    except Exception as exc:
        return {}, [f"response_contract:{type(exc).__name__}"]
    draft = parsed["draft"]
    if draft.get("division") != "공통" or draft.get("section_no") != "6-1-4":
        issues.append("section_identity_mismatch")
    if parsed["calc_type"] != "daily_crew" or draft.get("quantity_model", {}).get("name") != "adjusted_daily_crew":
        issues.append("unsupported_or_wrong_calculator")
    if not {186, 187}.issubset(set(draft.get("source_pages", []))):
        issues.append("source_pages_incomplete")
    by_id = chunks_by_id_from_list(section_chunks)
    citation_issues = check_citations(by_id, parsed.get("citations", []))
    if citation_issues:
        issues.append("citations_invalid")
    required_table_ids = {"p186-t1", "p187-t0", "p187-t1", "p187-t3"}
    cited_table_ids = {item.get("table_id") for item in parsed.get("citations", [])
                       if isinstance(item, dict) and item.get("table_id")}
    if not required_table_ids.issubset(cited_table_ids):
        issues.append("calculation_table_citations_incomplete")
    policy_names = {"height_deduction_percent", "height_deduction_source", "deduction_rate",
                    "accumulation_method", "calculation_source"}
    if any(item.get("name") in policy_names for item in draft.get("inputs", [])):
        issues.append("asks_user_for_calculation_policy")
    for rule in ("p186-t1", "p187-t0", "p187-t1", "p187-t3"):
        table = next((t for t in draft.get("tables", []) if t.get("id") == rule), None)
        if table is None:
            issues.append(f"source_table_missing:{rule}")
    if any("배관타설" in str(rule) for rule in draft.get("blocked", [])):
        issues.append("source_labor_note_blocked")
    return parsed, issues


def execute() -> None:
    model, pdf_bytes, base_prompt, section_chunks, config = setup()
    preflight_record = json.loads((RUN_DIR / "module-json-semantic-preflight.json").read_text(encoding="utf-8"))
    if preflight_record["model"] != model or preflight_record["source_pdf_sha256"] != sha(PDF_PATH.read_bytes()):
        raise SystemExit("BLOCKED: preflight does not match current model/source")
    key = env_value("VERTEX_API_KEY_BULK", ROOT / ".env")
    if not key:
        raise SystemExit("BLOCKED: configured credential absent")
    request = make_vertex_request_fn(key)
    authoring_rows, author_issues = [], []
    candidate = None
    ledger = load_ledger()
    if ledger["reserved_usd"] > MAX_USD or len(ledger["calls"]) >= MAX_CALLS:
        raise SystemExit("BLOCKED: cumulative budget/call cap reached")
    for attempt in range(1, 4):
        prompt = base_prompt if attempt == 1 else base_prompt + REPAIR_SUFFIX.format(
            issues="\n".join(author_issues))
        input_tokens = request.count_input_tokens(model, pdf_bytes, prompt)
        reserve = exact_cost(input_tokens, MAX_OUTPUT_TOKENS, config["input_usd_per_million"],
                             config["output_usd_per_million"])
        if len(ledger["calls"]) + 1 > MAX_CALLS or ledger["reserved_usd"] + reserve > MAX_USD:
            write_json(RUN_DIR / "budget-ledger.json", ledger)
            raise SystemExit("BLOCKED: cumulative budget/call limit would be exceeded; no generation sent")
        call_id = f"generation-{attempt}"
        ledger["reserved_usd"] += reserve
        ledger["calls"].append({"id": call_id, "reserved_usd": reserve,
                                "input_tokens_counted": input_tokens,
                                "max_output_tokens": MAX_OUTPUT_TOKENS,
                                "state": "reserved-before-request"})
        write_json(RUN_DIR / "budget-ledger.json", ledger)
        try:
            text, actual_input, actual_output = request(model, pdf_bytes, prompt, MAX_OUTPUT_TOKENS)
        except Exception as exc:
            ledger["calls"][-1].update({"state": "request-failed-or-response-lost",
                                        "error_type": type(exc).__name__})
            write_json(RUN_DIR / "budget-ledger.json", ledger)
            raise SystemExit(f"Generation request failed; reservation retained, no retry: {type(exc).__name__}") from None
        actual = exact_cost(actual_input, actual_output, config["input_usd_per_million"],
                            config["output_usd_per_million"])
        ledger["actual_usd"] += actual
        ledger["calls"][-1].update({"state": "response-received", "input_tokens": actual_input,
                                    "output_tokens_including_thoughts": actual_output,
                                    "actual_usd_estimate": actual})
        write_json(RUN_DIR / "budget-ledger.json", ledger)
        raw_path = RUN_DIR / "raw" / f"{call_id}.json"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(text, encoding="utf-8")
        candidate, candidate_issues = validate_candidate(text, section_chunks)
        if not candidate_issues:
            authoring_rows, author_issues = evaluate(candidate["draft"], AUTHOR_PATH)
            if all(row["passed"] for row in authoring_rows):
                write_json(RUN_DIR / "candidate.json", candidate)
                write_json(RUN_DIR / "authoring-evaluation.json", {"passed": True, "cases": authoring_rows})
                break
            author_issues = [f"case={row['case_id']} behavior={row['kind']} mismatch"
                             for row in authoring_rows if not row["passed"]]
        else:
            author_issues = candidate_issues
        write_json(RUN_DIR / f"attempt-{attempt}-authoring-failures.json", {"issues": author_issues})
    if candidate is None or not authoring_rows or not all(row["passed"] for row in authoring_rows):
        write_json(RUN_DIR / "run-result.json", {"candidate_generated": False,
                   "authoring_passed": False, "final_evaluation": "not-run",
                   "generation_calls": len(ledger["calls"]),
                   "reserved_usd": ledger["reserved_usd"],
                   "actual_usd_estimate": ledger["actual_usd"],
                   "reason": "all generation responses failed the JSON contract before authoring evaluation"})
        raise SystemExit("Authoring did not pass within the initial plus two repair limit")
    final_rows, final_issues = evaluate(candidate["draft"], FINAL_PATH)
    write_json(RUN_DIR / "final-evaluation.json", {"independent": True, "cases": final_rows,
               "passed": not final_issues, "failures": final_issues})
    write_json(RUN_DIR / "run-result.json", {"authoring_passed": True,
               "final_evaluation_passed": not final_issues,
               "generation_calls": len(ledger["calls"]), "reserved_usd": ledger["reserved_usd"],
               "actual_usd_estimate": ledger["actual_usd"], "candidate": "candidate.json"})
    if final_issues:
        raise SystemExit("Independent final evaluation failed; no final-case repair was attempted")
    print("Authoring and independent final evaluation passed. Candidate remains unregistered.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preflight", "execute", "module-json"))
    args = parser.parse_args()
    if args.mode == "preflight":
        preflight()
    elif args.mode == "module-json":
        execute_module_json()
    else:
        execute()
