"""오프라인 검색 결과로 절 선택 기준을 비교한다."""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AGENT_OFFLINE"] = "1"

from agent.nodes.retrieve import retrieve  # noqa: E402
from agent.nodes.select import MARGIN, decide, select  # noqa: E402
from agent.rules.specs import specs_by_section  # noqa: E402
from agent.state import new_state  # noqa: E402


QUESTIONS = Path(__file__).with_name("rag_questions.json")
AMBIGUOUS = [
    {"id": "a01", "query": "콘크리트 작업 비용", "expect": "ask"},
    {"id": "a02", "query": "콘크리트 타설 작업 비용", "expect": "ask"},
    {"id": "a03", "query": "철근 작업 인건비", "expect": "ask"},
]
MARGINS = (1.0, 1.25, 1.5, 2.0, 3.0)


def classify(expected: str, result: dict) -> str:
    decision = result["decision"]
    if decision == "ask":
        return "ask"
    chosen = result["candidates"][0]["section_no"]
    return "correct" if chosen == expected else "wrong"


def main() -> int:
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    questions = [
        {"id": item["id"], "query": item["query"], "expect": item["expect_section"]}
        for group in ("questions", "evidence_checks") for item in data[group]
        if "query" in item and "expect_section" in item
    ] + AMBIGUOUS
    cases = []
    for question in questions:
        state = new_state(question["query"])
        state.update(retrieve(state))
        cases.append((question, state))

    specs = specs_by_section()
    trials = []
    print("MARGIN | correct | wrong | ask | ambiguous ask")
    for margin in MARGINS:
        outcomes = [(question, decide(state["hits"], specs, margin)) for question, state in cases]
        counts = {label: sum(classify(q["expect"], result) == label for q, result in outcomes)
                  for label in ("correct", "wrong", "ask")}
        ambiguous_ask = sum(result["decision"] == "ask" for q, result in outcomes if q["expect"] == "ask")
        trials.append((margin, counts, ambiguous_ask, outcomes))
        print(f"{margin:g} | {counts['correct']} | {counts['wrong']} | {counts['ask']} | {ambiguous_ask}/3")

    zero_wrong = [trial for trial in trials if trial[1]["wrong"] == 0]
    pool = zero_wrong or trials
    chosen = min(pool, key=lambda trial: (trial[1]["wrong"], trial[1]["ask"], trial[0]))
    margin, counts, _, outcomes = chosen
    print(f"SELECTED MARGIN {margin:g} (zero-wrong: {bool(zero_wrong)})")
    if MARGIN != margin:
        print(f"FAIL: select.MARGIN={MARGIN:g}, selected={margin:g}")
        return 1

    for question, state in cases:
        result = select(state)
        expected = question["expect"]
        outcome = classify(expected, {**result["selection"], "candidates": result["candidates"]})
        if outcome != "correct":
            picked = result["candidates"][0]["section_no"] if result["candidates"] else "-"
            print(f"{outcome.upper()} {question['id']}: expected={expected}, decision={result['selection']['decision']}, top={picked}")
    print(f"FINAL correct={counts['correct']} wrong={counts['wrong']} ask={counts['ask']}")
    return 0 if counts["wrong"] == 0 and chosen[2] == len(AMBIGUOUS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
