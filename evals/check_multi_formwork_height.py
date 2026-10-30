"""Offline check: formwork height asked/answered in a multi-item estimate, then edited 7m -> 10m.

Retrieval is mocked; no model, embedding, remote DB or server is used.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update(AGENT_MODE="tools", AGENT_LLM="off", AGENT_OFFLINE="1")

from backend.agent.estimate import dialogue, tools  # noqa: E402
from backend.agent.nodes.fill import extract_inputs  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.api import dialogue_service  # noqa: E402
from backend.agent.tools.source import citation  # noqa: E402

TEXT = "레미콘 타설 100㎥ + 합판거푸집 200㎡ 비용 견적"
SPECS = list(load_specs().values())
FORM = next(s for s in SPECS if s["section_no"] == "6-3-1" and s["division"] == "공통" and any(f["name"] == "height" for f in s["inputs"]))


def hit(query: str) -> dict:
    spec = FORM if "거푸집" in query else next(s for s in SPECS if s["section_no"] == "6-1-1" and s["division"] == "공통")
    return {"rank": 1, "section_no": spec["section_no"], "division": spec["division"],
            "section": f"{spec['section_no']} {spec['title']}", "page": 193, "table_id": None,
            "text": spec["title"], "chunk_id": "mock", "ref": spec["id"]}


def height(state, item_id):
    return state["session"]["items"][item_id].get("conditions", {}).get("height")


def main() -> None:
    # 1. extractor: unit-bearing numeric condition, not a volume
    for text, want in (("수직고 7m", "7"), ("7미터", "7"), ("12 m 입니다", "12"), ("120m3 높이 7m", "7")):
        assert extract_inputs(text, FORM)[0].get("height") == want, text
    for text in ("7cm", "10", "7m 10m"):  # wrong unit / no unit / two values: never guessed
        assert "height" not in extract_inputs(text, FORM)[0], text
    print("PASS extractor reads 7m/7미터 as height; wrong unit, bare number, two values are not applied")

    graph = dialogue.build_dialogue_graph()
    tid = "multi-formwork-height"
    with patch.object(tools, "retrieve", side_effect=lambda s: {"hits": [hit(s["query"])], "search_info": {
            "method": "mock", "api_calls": 0, "warnings": []}}), \
            patch.object(citation, "_pages", return_value=defaultdict(lambda: {"printed_page": None, "division": None})):
        scoped = dialogue_service.respond(graph, tid, {"message": TEXT})
        r = dialogue_service.respond(graph, tid, {
            "answers": {q["name"]: "계산에 포함" for q in scoped["questions"]},
            "refs": {q["name"]: q["ref"] for q in scoped["questions"]}})
        state = dialogue.load(graph, tid)
        ids = list(state["session"]["item_order"])
        form_id = next(i for i in ids if state["session"]["items"][i].get("selected_spec_id") == FORM["id"])
        other_id = next(i for i in ids if i != form_id)
        for _ in range(10):  # answer cards like the UI would, until the formwork height question shows up
            hq = next((q for q in r["questions"] if q["name"] == f"{form_id}::height"), None)
            if hq or not r["questions"]:
                break
            q = next((x for x in r["questions"] if x["name"].startswith(other_id) or x["name"].endswith("::continue")),
                     r["questions"][0])
            value = (False if q["name"].endswith("scattered_small_volume") else q["choices"][-1]) if q.get("choices") else "100"
            r = dialogue_service.respond(graph, tid, {"answers": {q["name"]: value}, "refs": {q["name"]: q["ref"]}})
        state = dialogue.load(graph, tid)
        assert hq["unit"] == "m" and not hq["choices"], hq
        print("PASS height question exposes unit and no choices (UI renders a number input)")

        # 2. free-text reply to the pending height question lands on the formwork item only
        before_other = state["session"]["items"][other_id]["input_revision"]
        r = dialogue_service.respond(graph, tid, {"message": "수직고 7m"})
        state = dialogue.load(graph, tid)
        assert height(state, form_id) == "7", (height(state, form_id), r["answer"])
        assert state["session"]["items"][other_id]["input_revision"] == before_other
        print("PASS chat reply '수직고 7m' stored on the formwork item; sibling untouched")

        # 3. finish the remaining cards, then compare results
        def finish(r):
            for _ in range(12):
                if not r["questions"]:
                    return r
                q = r["questions"][0]
                name = q["name"].split("::", 1)[-1]
                value = (False if name in ("is_roof_slab", "crane_used", "lifting_equipment_used") else
                         q["choices"][0] if q.get("choices") else "100")
                r = dialogue_service.respond(graph, tid, {"answers": {q["name"]: value}, "refs": {q["name"]: q["ref"]}})
            return r
        r = finish(r)
        state = dialogue.load(graph, tid)
        items = state["session"]["items"]
        print("STATUS", {i: items[i].get("status") for i in ids}, r.get("status"))
        before_form, before_other_result = items[form_id].get("computed_result"), items[other_id].get("computed_result")
        total7 = (state["session"].get("statement") or {}).get("totals", {}).get("contract_amount")
        # 4. edit 7 -> 10 recalculates the formwork item only
        rev = state["session"]["items"][form_id]["input_revision"]
        r = dialogue_service.respond(graph, tid, {"message": "거푸집 수직고 10m로 바꿔"})
        state = dialogue.load(graph, tid)
        assert height(state, form_id) == "10", (height(state, form_id), r["answer"])
        assert state["session"]["items"][form_id]["input_revision"] > rev
        assert state["session"]["items"][other_id]["input_revision"] == before_other
        r = finish(r)
        state = dialogue.load(graph, tid)
        items = state["session"]["items"]
        print("STATUS10", {i: items[i].get("status") for i in ids}, r.get("status"))
        assert items[form_id].get("computed_result") != before_form, "formwork not recalculated"
        assert items[other_id].get("computed_result") == before_other_result
        total10 = (state["session"].get("statement") or {}).get("totals", {}).get("contract_amount")
        print("TOTALS", total7, total10)
        assert total7 != total10
        print("PASS edit to 10m re-applied to the formwork item; sibling untouched")


if __name__ == "__main__":
    main()
