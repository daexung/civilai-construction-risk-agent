"""Offline regression for docs/plans/APPLICABILITY-HOTFIX-PLAN.md.

Reproduces 공통2-7-7 경사형 가설 계단 with height 8m (limit 6m) and confirms:
- the irrelevant width question stops once height alone decides the block (partial input);
- the boundary case height=6/width=0.9 still computes normally;
- the parent response status/message/result are BLOCKED with the real reason, not the
  generic "진행 상태를 갱신했어요" template text or a swallowed ANSWERED/result=null.

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
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.api import dialogue_service  # noqa: E402
from backend.agent.tools.source import citation  # noqa: E402

SPECS = list(load_specs().values())
STAIR = next(s for s in SPECS if s["section_no"] == "2-7-7" and s["division"] == "공통")


def hit(query: str) -> dict:
    return {"rank": 1, "section_no": STAIR["section_no"], "division": STAIR["division"],
            "section": f"{STAIR['section_no']} {STAIR['title']}", "page": 106, "table_id": None,
            "text": STAIR["title"], "chunk_id": "mock", "ref": STAIR["id"]}


def answer_by_name(graph, tid, r, name, value):
    q = next(x for x in r["questions"] if x["name"].endswith(name))
    return dialogue_service.respond(graph, tid, {"answers": {q["name"]: value}, "refs": {q["name"]: q["ref"]}})


def has_question(r, name) -> bool:
    return any(x["name"].endswith(name) for x in r["questions"])


def start(graph, tid) -> dict:
    """Message + scope confirmation card, like the UI's first two turns."""
    r = dialogue_service.respond(graph, tid, {"message": "가설 계단 견적"})
    return dialogue_service.respond(graph, tid, {
        "answers": {q["name"]: "계산에 포함" for q in r["questions"]},
        "refs": {q["name"]: q["ref"] for q in r["questions"]}})


def main() -> None:
    graph = dialogue.build_dialogue_graph()
    patches = (patch.object(tools, "retrieve", side_effect=lambda s: {"hits": [hit(s["query"])],
                            "search_info": {"method": "mock", "api_calls": 0, "warnings": []}}),
               patch.object(citation, "_pages", return_value=defaultdict(lambda: {"printed_page": None, "division": None})))

    # 1. Height alone (8m, over the 6m limit) must stop the unrelated width question and block.
    with patches[0], patches[1]:
        tid = "applicability-hotfix-height-only"
        r = start(graph, tid)
        assert has_question(r, "height"), [q["name"] for q in r["questions"]]
        r = answer_by_name(graph, tid, r, "height", "8")
        assert not has_question(r, "width"), ("width should not be asked once height alone blocks", r["questions"])
        assert r["status"] == "BLOCKED", r["status"]
        assert "6m" in r["message"] and r["message"] != "작업별 진행 상태를 갱신했어요. 확인이 필요한 항목은 아래 카드에서 답하고, 남은 작업은 계속 진행을 눌러 주세요.", r["message"]
        assert r.get("result") and r["result"].get("citations"), r.get("result")
        print("PASS height=8m blocks without asking width; status/message/result carry the real reason")

    # 2. Boundary values (height=6, width=0.9) must still compute normally (no block).
    with patches[0], patches[1]:
        tid = "applicability-hotfix-boundary"
        r = start(graph, tid)
        r = answer_by_name(graph, tid, r, "height", "6")
        r = answer_by_name(graph, tid, r, "width", "0.9")
        assert r["status"] not in ("BLOCKED", "ERROR"), (r["status"], r["message"])
        print(f"PASS height=6/width=0.9 boundary computes normally (status={r['status']})")

    # 3. "안됐어" after a block repeats the same block reason, not a generic progress line.
    with patches[0], patches[1]:
        tid = "applicability-hotfix-repeat"
        r = start(graph, tid)
        r = answer_by_name(graph, tid, r, "height", "8")
        assert r["status"] == "BLOCKED"
        again = dialogue_service.respond(graph, tid, {"message": "안됐어"})
        assert again["status"] == "BLOCKED" and "6m" in again["message"], again["message"]
        print("PASS repeating '안됐어' keeps the same block reason instead of a stuck progress message")


    # 4. Free-text correction recovers a blocked item: height 8m -> "높이를 6m로 정정해줘" unblocks,
    #    asks the remaining width, and a valid width completes a real PARTIAL calculation.
    with patches[0], patches[1]:
        tid = "applicability-hotfix-recover"
        r = start(graph, tid)
        r = answer_by_name(graph, tid, r, "height", "8")
        assert r["status"] == "BLOCKED"
        r = dialogue_service.respond(graph, tid, {"message": "높이를 6m로 정정해줘"})
        assert r["status"] != "BLOCKED", r["message"]
        assert has_question(r, "width"), [q["name"] for q in r["questions"]]
        for _ in range(10):
            if not r["questions"]:
                break
            qq = r["questions"][0]
            name = qq["name"].split("::", 1)[-1]
            value = {"width": "0.9"}.get(name, qq["choices"][0] if qq.get("choices") else "18")
            r = dialogue_service.respond(graph, tid, {"answers": {qq["name"]: value}, "refs": {qq["name"]: qq["ref"]}})
        assert r["status"] == "PARTIAL", r["status"]
        print("PASS '높이를 6m로 정정해줘' unblocks, keeps asking only width, reaches real PARTIAL calculation")

    # 5. A bare, unlabeled number is never guessed onto height or width.
    from backend.agent.nodes.fill import extract_inputs
    assert extract_inputs("6m", STAIR)[0] == {}
    print("PASS bare '6m' (no field label) is not assigned to height or width")

    # 6. Restoring a session saved before this hotfix (missing the new optional
    #    applicability_scope/blocked_citations/blocked_input keys) must not crash and must
    #    still surface the BLOCKED reason AND the applicability scope guidance (limits/title) for
    #    the actual selected spec, rebuilt at the response boundary — not just reason/result.
    with patches[0], patches[1]:
        tid = "applicability-hotfix-legacy-restore"
        r = start(graph, tid)
        r = answer_by_name(graph, tid, r, "height", "8")
        assert r["status"] == "BLOCKED"
        assert r.get("applicability_scope") and any("6m" in limit["reason"]
            for limit in r["applicability_scope"]["limits"]), r.get("applicability_scope")
        state = dialogue.load(graph, tid)
        legacy_item = tools._item(state["session"])
        before_revision = legacy_item["input_revision"]
        for key in ("applicability_scope", "blocked_citations", "blocked_input"):
            legacy_item.pop(key, None)
        config = dialogue.config(tid)
        graph.update_state(config, {"session": state["session"]})
        restored = dialogue_service.restore(graph, tid)
        assert restored["status"] == "BLOCKED", restored["status"]
        assert "6m" in restored["message"], restored["message"]
        assert restored.get("result") is not None, restored.get("result")
        scope = restored.get("applicability_scope")
        assert scope is not None, "legacy restore must rebuild applicability_scope from the selected spec"
        assert scope["title"] == r["applicability_scope"]["title"], (scope, r["applicability_scope"])
        assert any("6m" in limit["reason"] for limit in scope["limits"]), scope["limits"]
        reloaded = dialogue.load(graph, tid)
        assert tools._item(reloaded["session"])["input_revision"] == before_revision, \
            "restore must not bump the stored session's input_revision"
        print("PASS restoring a legacy session without the new optional fields rebuilds the "
              "applicability scope (title/limits) from the selected spec, keeps the BLOCKED reason, "
              "and does not mutate the stored session")


if __name__ == "__main__":
    main()
