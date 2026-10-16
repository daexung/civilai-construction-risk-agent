"""3단계 로컬 항목별 품 경로를 HTTP 경계에서 모의 후보로 확인한다."""
from __future__ import annotations

import os
import sys
import asyncio
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("AGENT_OFFLINE", "1")
os.environ.setdefault("AGENT_LLM", "off")

import httpx  # noqa: E402
from unittest.mock import patch  # noqa: E402
from backend.agent.estimate import tools  # noqa: E402
from backend.agent.estimate.scope import analyze_request  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.tools.source import citation  # noqa: E402
from backend.api import item_labor_trial as trial_api  # noqa: E402

# Reuse the original repository's corpus read-only; the worktree intentionally has no generated corpus.
SOURCE_ROOT = Path(r"C:\Users\user\Desktop\PROJECTS\civilai-construction-risk-agent")
citation.PAGE_MAP = SOURCE_ROOT / "data/processed/page_map.json"
citation.PDF = SOURCE_ROOT / "data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf"
citation.CHUNKS = (SOURCE_ROOT / "data/processed/chunks.all.jsonl"
                   if (SOURCE_ROOT / "data/processed/chunks.all.jsonl").is_file()
                   else SOURCE_ROOT / "data/processed/chunks.jsonl")
citation._pages.cache_clear()
citation._chunks.cache_clear()


class LoopbackClient:
    """HTTP ASGI harness with the same loopback client address as the documented local run."""
    def __init__(self, host: str = "127.0.0.1"):
        self.transport = httpx.ASGITransport(app=trial_api.app, client=(host, 49152))
        self.owners: dict[str, str] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def adopt(self, trial: dict) -> None:
        self.owners[trial["trial_id"]] = trial["owner_token"]

    def _headers(self, path: str, extra: dict | None = None) -> dict:
        parts = path.strip("/").split("/")
        headers = {}
        if len(parts) > 2 and parts[:2] == ["api", "item-labor"]:
            token = self.owners.get(parts[2])
            if token:
                headers["X-Trial-Owner"] = token
        headers.update(extra or {})
        return headers

    def post(self, path: str, *, json: dict, headers: dict | None = None):
        async def send():
            async with httpx.AsyncClient(transport=self.transport, base_url="http://127.0.0.1") as client:
                return await client.post(path, json=json, headers=self._headers(path, headers))
        return asyncio.run(send())

    def get(self, path: str):
        async def send():
            async with httpx.AsyncClient(transport=self.transport, base_url="http://127.0.0.1") as client:
                return await client.get(path, headers=self._headers(path))
        return asyncio.run(send())

    def search(self, trial_id: str, item_id: str, candidates: list[dict]):
        path = f"/api/item-labor/{trial_id}/items/{item_id}/search"
        fixture = {"hits": candidates, "search_info": {"method": "mock-fixture", "queries": [],
                   "api_calls": 0, "query_cache_hit": True, "release_id": "test-fixture",
                   "chunk_set_id": "test-fixture"}}
        with patch.object(trial_api, "_search_candidates", return_value=fixture):
            return self.post(path, json={})


def decisions_for(analysis: dict, *, unconfirmed: str = "exclude_work") -> list[dict]:
    output = []
    for span in analysis["scope_spans"]:
        action = {"requested": "include_work", "excluded": "keep_excluded",
                  "background": "keep_background", "condition": "keep_condition"}.get(
                      span["classification"], unconfirmed)
        choice = {"span_id": span["span_id"], "action": action}
        if span["classification"] == "unconfirmed":
            task = next((task for task in analysis["work_items"] if task["segment_id"] == span["span_id"]), None)
            if task:
                choice["action"] = "include_work"
                choice["work"] = task["work"]
            elif action == "include_work":
                choice["action"] = "keep_condition"
        output.append(choice)
    return output


def hit(spec: dict, rank: int = 1) -> dict:
    return {"section_no": spec["section_no"], "division": spec["division"], "rank": rank,
            "section": f"{spec['section_no']} {spec['title']}", "chunk_id": f"mock-{spec['id']}", "score": 1}


def confirm_text(client: TestClient, text: str) -> tuple[dict, dict]:
    analysis_response = client.post("/api/item-labor/analyze", json={"text": text})
    assert analysis_response.status_code == 200, analysis_response.text
    data = analysis_response.json()
    client.adopt(data)
    analysis = data["analysis"]
    response = client.post(f"/api/item-labor/{data['trial_id']}/confirm",
                           json={"decisions": decisions_for(analysis)})
    assert response.status_code == 200, response.text
    return data, response.json()


def choose_work_and_compute(client: TestClient, trial_id: str, item: dict, candidates: list[dict]) -> dict:
    response = client.search(trial_id, item["item_id"], candidates)
    assert response.status_code == 200, response.text
    current = response.json()
    found = next(row for row in current["items"] if row["item_id"] == item["item_id"])
    if found["questions"] and found["questions"][0]["field"] == "work":
        question = found["questions"][0]
        response = client.post(f"/api/item-labor/{trial_id}/items/{item['item_id']}/answer", json={
            "question_id": question["question_id"], "version": question["version"],
            "value": question["choices"][0]})
        assert response.status_code == 200, response.text
        current = response.json()
    # Answer only the current item's current question. Empty choice sets use a positive sample value.
    for _ in range(15):
        found = next(row for row in current["items"] if row["item_id"] == item["item_id"])
        if found["status"] != "NEEDS_INPUT" or not found["questions"]:
            break
        question = found["questions"][0]
        value = False if question["field"] in ("is_ceiling", "is_exterior") else (
            question["choices"][0] if question.get("choices") else "1")
        response = client.post(f"/api/item-labor/{trial_id}/items/{item['item_id']}/answer", json={
            "question_id": question["question_id"], "version": question["version"], "value": value,
            "unit": question.get("unit")})
        assert response.status_code == 200, response.text
        current = response.json()
    return next(row for row in current["items"] if row["item_id"] == item["item_id"])


def main() -> int:
    checks: list[tuple[str, bool]] = []
    def add(label: str, okay: bool) -> None:
        checks.append((label, bool(okay)))

    trial_api._TRIALS.clear()
    os.environ["LOCAL_TRIAL_ITEM_LABOR"] = "off"
    with LoopbackClient() as client:
        add("trial option off returns 404", client.post("/api/item-labor/analyze", json={"text": "도장 100㎡"}).status_code == 404)

    os.environ["LOCAL_TRIAL_ITEM_LABOR"] = "on"
    trial_api._TRIALS.clear()
    paint = next(spec for spec in load_specs().values() if spec["section_no"] == "11-2-2")
    with LoopbackClient() as client:
        prior_k_service = os.environ.get("K_SERVICE")
        os.environ["K_SERVICE"] = "mock-deployment"
        deployment_blocked = client.post("/api/item-labor/analyze", json={"text": "도장 100㎡"}).status_code == 404
        if prior_k_service is None:
            os.environ.pop("K_SERVICE", None)
        else:
            os.environ["K_SERVICE"] = prior_k_service
        add("deployment marker blocks even a loopback client", deployment_blocked)
        with LoopbackClient(host="192.0.2.10") as external_client:
            external_blocked = external_client.post("/api/item-labor/analyze", json={"text": "도장 100㎡"}).status_code == 404
        add("non-loopback client is always blocked", external_blocked)

        # Search cannot start until an explicit scope receipt exists.
        start = client.post("/api/item-labor/analyze", json={"text": "도장 100㎡ 그리고 방수 20㎡"}).json()
        client.adopt(start)
        before = client.search(start["trial_id"], "w0_2", [hit(paint)])
        add("scope analysis alone cannot start item search", before.status_code in (404, 409))

        normal_text = "수성페인트 롤러칠 2회 벽면 100㎡ 그리고 실내 방수모르타르 10㎜ 바닥 20㎡"
        data, confirmed = confirm_text(client, normal_text)
        paint_item = next(item for item in confirmed["items"] if item["task"] == "도장")
        waterproof = next(item for item in confirmed["items"] if item["task"] == "방수")
        ids = {item["item_id"] for item in confirmed["items"]}
        add("confirmed paint and waterproof preserve separate IDs, with no calculation before search",
            len(ids) == 2 and paint_item["quantity"]["value"] == "100"
            and waterproof["quantity"]["value"] == "20" and paint_item["labor"] is None
            and waterproof["labor"] is None)

        paint_result = choose_work_and_compute(client, data["trial_id"], paint_item, [hit(paint)])
        water_spec = next(spec for spec in load_specs().values() if spec["section_no"] == "6-4-3")
        water_result = choose_work_and_compute(client, data["trial_id"], waterproof, [hit(water_spec)])
        def rates(result):
            return {line["name"]: Fraction(line["exact"])
                    for line in result.get("evidence", {}).get("unit_lines", []) if line.get("kind") == "labor"}
        paint_rates, water_rates = rates(paint_result), rates(water_result)
        paint_days = {role: rate * Fraction(paint_result["quantity"]["value"]) for role, rate in paint_rates.items()}
        water_days = {role: rate * Fraction(water_result["quantity"]["value"]) for role, rate in water_rates.items()}
        add("two confirmed supported jobs each finish existing labor calculation",
            paint_result["status"] == water_result["status"] == "CALCULATED"
            and paint_result["quantity"]["value"] == "100" and water_result["quantity"]["value"] == "20"
            and paint_result["conditions"].get("is_ceiling") is False
            and str(paint_result["conditions"].get("coat_count")) == "2"
            and water_result["conditions"].get("is_exterior") is False
            and water_result["conditions"].get("thickness") == "10㎜이하"
            and paint_days == {"도장공": Fraction("2.4"), "보통인부": Fraction("0.4")}
            and water_days == {"미장공": Fraction("0.94"), "보통인부": Fraction("0.70")})
        add("paint and waterproof labor evidence retains the selected unit tables",
            bool(paint_result["evidence"]["unit_lines"]) and bool(water_result["evidence"]["unit_lines"])
            and any(citation.get("internal_id") == "p693-t1" for line in paint_result["evidence"]["unit_lines"]
                    for citation in line.get("citations", []))
            and any(citation.get("internal_id") == "p662-t2" for line in water_result["evidence"]["unit_lines"]
                    for citation in line.get("citations", []))
            and paint_result["not_calculated_scope"] and water_result["not_calculated_scope"]
            and "not_calculated_scope" in paint_result and "not_calculated_scope" in water_result)

        # A separate unsupported mock candidate keeps a successfully computed sibling result.
        mixed_start, mixed = confirm_text(client, "도장 100㎡ 그리고 방수 20㎡")
        mix_paint = next(item for item in mixed["items"] if item["task"] == "도장")
        mix_unknown = next(item for item in mixed["items"] if item["task"] == "방수")
        mix_paint_result = choose_work_and_compute(client, mixed_start["trial_id"], mix_paint, [hit(paint)])
        unsupported_hit = {"section_no": "99-99-99", "division": "건축", "rank": 1,
                           "section": "99-99-99 모의 후보", "chunk_id": "mock-no-spec", "score": 1}
        mix_unsupported = choose_work_and_compute(client, mixed_start["trial_id"], mix_unknown, [unsupported_hit])
        add("a calculated paint result survives a separate unsupported item",
            mix_paint_result["status"] == "CALCULATED" and mix_unsupported["status"] == "UNSUPPORTED")

        # Separate same-trade tasks get different question ids and stale/cross-task replies are rejected.
        data2, repeated = confirm_text(client, "내부 도장 100㎡ 그리고 외부 도장 20㎡")
        left, right = repeated["items"]
        candidates = [hit(paint)]
        for task in (left, right):
            response = client.search(data2["trial_id"], task["item_id"], candidates)
            assert response.status_code == 200, response.text
        now = client.get(f"/api/item-labor/{data2['trial_id']}").json()
        pending_left = next(item for item in now["items"] if item["item_id"] == left["item_id"])["questions"][0]
        pending_right = next(item for item in now["items"] if item["item_id"] == right["item_id"])["questions"][0]
        add("same-trade instances have separate IDs and question identities",
            left["item_id"] != right["item_id"] and pending_left["question_id"] != pending_right["question_id"]
            and left["quantity"]["value"] == "100" and right["quantity"]["value"] == "20")
        wrong = client.post(f"/api/item-labor/{data2['trial_id']}/items/{right['item_id']}/answer", json={
            "question_id": pending_left["question_id"], "version": pending_left["version"], "value": paint["section_no"]})
        old = client.post(f"/api/item-labor/{data2['trial_id']}/items/{left['item_id']}/answer", json={
            "question_id": pending_left["question_id"], "version": "stale-version", "value": paint["section_no"]})
        add("cross-item and stale question answers are rejected", wrong.status_code == old.status_code == 409)

        # Answer both work and condition questions by their own IDs, then reorder without remapping.
        for task in (right, left):
            now = client.get(f"/api/item-labor/{data2['trial_id']}").json()
            active = next(item for item in now["items"] if item["item_id"] == task["item_id"])["questions"][0]
            response = client.post(f"/api/item-labor/{data2['trial_id']}/items/{task['item_id']}/answer", json={
                "question_id": active["question_id"], "version": active["version"], "value": active["choices"][0]})
            assert response.status_code == 200, response.text
            current = response.json()
            for _ in range(15):
                active_item = next(item for item in current["items"] if item["item_id"] == task["item_id"])
                if active_item["status"] != "NEEDS_INPUT" or not active_item["questions"]:
                    break
                question = active_item["questions"][0]
                value = False if question["field"] == "is_ceiling" else (question["choices"][0] if question.get("choices") else "1")
                response = client.post(f"/api/item-labor/{data2['trial_id']}/items/{task['item_id']}/answer", json={
                    "question_id": question["question_id"], "version": question["version"], "value": value,
                    "unit": question.get("unit")})
                assert response.status_code == 200, response.text
                current = response.json()
        before_order = client.get(f"/api/item-labor/{data2['trial_id']}").json()
        reordered = client.post(f"/api/item-labor/{data2['trial_id']}/reorder", json={"item_ids": [right["item_id"], left["item_id"]]}).json()
        add("reordering leaves IDs, quantities, and pending answers attached",
            [item["item_id"] for item in reordered["items"]] == [right["item_id"], left["item_id"]]
            and {item["item_id"]: item["quantity"]["value"] for item in reordered["items"]}
            == {item["item_id"]: item["quantity"]["value"] for item in before_order["items"]})
        add("both same-trade results are complete before testing result preservation",
            all(item["status"] == "CALCULATED" and item["labor"] is not None for item in before_order["items"]))

        same_confirm = client.post(f"/api/item-labor/{data2['trial_id']}/confirm", json={
            "decisions": decisions_for(analyze_request("내부 도장 100㎡ 그리고 외부 도장 20㎡"))}).json()
        add("repeating the exact range confirmation is idempotent and preserves computed results",
            all(item["status"] == "CALCULATED" and item["labor"] is not None for item in same_confirm["items"]))

        # Editing one item hides only its stale result; the other item record remains intact.
        left_now = next(item for item in reordered["items"] if item["item_id"] == left["item_id"])
        right_before = next(item for item in reordered["items"] if item["item_id"] == right["item_id"])
        edit = client.post(f"/api/item-labor/{data2['trial_id']}/items/{left['item_id']}/edit", json={
            "input_revision": left_now["input_revision"], "quantity": {"value": "110", "unit": "㎡"}})
        edited = edit.json()
        left_edited = next(item for item in edited["items"] if item["item_id"] == left["item_id"])
        right_after = next(item for item in edited["items"] if item["item_id"] == right["item_id"])
        add("editing one quantity invalidates only that item pending reconfirmation",
            edit.status_code == 200 and left_edited["status"] == "SCOPE_CONFIRMATION_REQUIRED"
            and left_edited["labor"] is None and left_edited["quantity"]["value"] == "110"
            and right_before["status"] == "CALCULATED" and right_before["labor"] is not None
            and right_after == right_before)
        denied = client.search(data2["trial_id"], left["item_id"], candidates)
        add("edited item cannot recalculate before its revised scope is confirmed", denied.status_code == 409)
        reconfirm = client.post(f"/api/item-labor/{data2['trial_id']}/items/{left['item_id']}/confirm-edit", json={
            "input_revision": left_edited["input_revision"], "confirmed": True})
        add("explicit item edit confirmation restarts only the edited item", reconfirm.status_code == 200
            and next(item for item in reconfirm.json()["items"] if item["item_id"] == left["item_id"])["quantity"]["value"] == "110"
            and next(item for item in reconfirm.json()["items"] if item["item_id"] == right["item_id"])["quantity"]["value"] == "20")

        # Existing wall is attached as context and is never promoted to a work item.
        _, wall = confirm_text(client, "조적벽에 도장 100㎡")
        add("masonry wall remains background while paint is the sole task",
            len(wall["items"]) == 1 and wall["items"][0]["task"] == "도장"
            and any(span["kind"] == "background" for span in wall["items"][0]["evidence"]["source_spans"]))
        # Excluded scope never appears as a work item or accepts a response target.
        analysis = analyze_request("도장 100㎡, 방수 20㎡는 제외")
        excluded_text = "도장 100㎡, 방수 20㎡는 제외"
        receipt_decisions = decisions_for(analysis)
        excluded_response = client.post("/api/item-labor/analyze", json={"text": excluded_text}).json()
        client.adopt(excluded_response)
        excluded_confirm = client.post(f"/api/item-labor/{excluded_response['trial_id']}/confirm", json={"decisions": receipt_decisions})
        add("excluded waterproof is reported outside work items", excluded_confirm.status_code == 200
            and [item["task"] for item in excluded_confirm.json()["items"]] == ["도장"]
            and bool(excluded_confirm.json()["excluded_scope"]))
        excluded_segment = excluded_confirm.json()["excluded_scope"][0]["segment_id"]
        excluded_answer = client.search(excluded_response["trial_id"], excluded_segment, [hit(paint)])
        add("excluded span cannot be addressed as a work item", excluded_answer.status_code == 409)

        # A quantity answer must preserve the specification's unit, including after rejection.
        unit_trial, unit_result = confirm_text(client, "수성페인트 롤러칠 2회 벽면")
        unit_item = unit_result["items"][0]
        unit_search = client.search(unit_trial["trial_id"], unit_item["item_id"], [hit(paint)]).json()
        quantity_question = next(question for question in unit_search["items"][0]["questions"]
                                 if question["field"] == "quantity")
        wrong_unit = client.post(f"/api/item-labor/{unit_trial['trial_id']}/items/{unit_item['item_id']}/answer", json={
            "question_id": quantity_question["question_id"], "version": quantity_question["version"],
            "value": "100", "unit": "m"})
        still_pending = client.get(f"/api/item-labor/{unit_trial['trial_id']}").json()["items"][0]["questions"]
        same_question = next(question for question in still_pending if question["field"] == "quantity")
        correct_unit = client.post(f"/api/item-labor/{unit_trial['trial_id']}/items/{unit_item['item_id']}/answer", json={
            "question_id": same_question["question_id"], "version": same_question["version"],
            "value": "100", "unit": "㎡"})
        add("quantity unit mismatch is rejected without consuming its question", wrong_unit.status_code == 422
            and same_question["version"] == quantity_question["version"] and correct_unit.status_code == 200
            and correct_unit.json()["items"][0]["quantity"]["value"] == "100")

        # A standalone surface cannot be attached to either of two jobs by position.
        data3 = client.post("/api/item-labor/analyze", json={
            "text": "도장 100㎡ 그리고 바닥면 그리고 방수 20㎡"}).json()
        client.adopt(data3)
        blocked_confirm = client.post(f"/api/item-labor/{data3['trial_id']}/confirm", json={
            "decisions": decisions_for(data3["analysis"])}).json()
        blocked_item = blocked_confirm["items"][0]
        blocked_search = client.search(data3["trial_id"], blocked_item["item_id"], [hit(paint)])
        add("unattached background blocks all affected item searches", blocked_item["status"] == "BLOCKED"
            and blocked_item["labor"] is None and blocked_search.status_code == 409)

    failures = [label for label, okay in checks if not okay]
    for label, okay in checks:
        print(f"{'PASS' if okay else 'FAIL'} {label}")
    print(f"{len(checks) - len(failures)}/{len(checks)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
