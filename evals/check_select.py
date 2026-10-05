"""BM25와 하이브리드 검색 결과로 절 선택 기준을 비교한다."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["INDEX_CONFIG"] = str(ROOT / "evals/index_configs/6chapter_studio.json")

from agent.nodes.retrieve import get_search, retrieve  # noqa: E402
from agent.nodes.select import MARGIN, decide  # noqa: E402
from agent.rules.specs import specs_by_section  # noqa: E402
from agent.state import new_state  # noqa: E402
from shared.embedding import MODEL, api_key  # noqa: E402


QUESTIONS = Path(__file__).with_name("rag_questions.json")
HYBRID_HITS = Path(__file__).parent / "results/select_hybrid_hits.json"
MARGINS = (1.25, 1.5, 2.0, 2.5, 3.0, 4.0)

# 각 기존 질문이 확인하는 검색 조건.
NOTES = {
    "q01": "인력운반 타설의 기본 절",
    "q02": "펌프차 타설의 기본 절",
    "q03": "표면 마무리의 절",
    "q04": "철근 현장가공의 절",
    "q05": "합판 거푸집 설치·해체의 절",
    "q06": "강재 거푸집 사용횟수의 절",
    "q07": "PSC빔 제작의 절",
    "q08": "교량받침 설치의 절",
    "q09": "PC기둥 설치의 절",
    "q10": "인력 타설의 간접비 근거 절",
    "q11": "별도 공법의 절",
    "n01": "펌프차 인력 조건의 절",
    "n02": "합판 거푸집 재사용 조건의 절",
    "n03": "교량받침 인력 표현의 절",
    "n04": "흐름관 설치의 절",
    "n05": "절 번호만 있는 질문",
    "n06": "절 번호와 품명이 함께 있는 질문",
    "n07": "절 번호와 Type 조건이 함께 있는 질문",
    "n08": "펌프차 현장조건의 절",
    "n09": "펌프차 압송관 비용의 절",
    "n10": "PSC빔 그라우팅의 절",
    "v01": "레디믹스트콘크리트의 근거 절",
    "v02": "펌프차 인력품의 근거 절",
}
EXTRA = [
    {"id": "a01", "query": "콘크리트 타설 노무비 알려줘", "expect": "ask", "note": "타설 공법이 없는 질문"},
    {"id": "a02", "query": "타설 비용 계산해줘", "expect": "ask", "note": "공종·공법이 모두 없는 질문"},
    {"id": "a03", "query": "철근 작업 인건비", "expect": "ask", "note": "철근 작업 범위가 모호한 질문"},
    {"id": "a04", "query": "철근콘크리트 작업중인데 타설해야해 비용 계산해줘", "expect": "ask", "note": "구조물만 있고 타설 공법이 없는 질문"},
    {"id": "a05", "query": "콘크리트 작업 비용", "expect": "ask", "note": "작업 종류가 빠진 질문"},
    {"id": "a06", "query": "콘크리트 타설 작업 비용", "expect": "ask", "note": "타설 공법이 빠진 질문"},
    {"id": "c01", "query": "레미콘 타설 노무비 알려줘", "expect": "6-1-1", "note": "레미콘 타설과 펌프차 혼동 여부"},
    {"id": "c02", "query": "레미콘 인력운반 타설 100㎥ 노무비", "expect": "6-1-1", "note": "인력운반 조건의 명시적 검색"},
    {"id": "c03", "query": "콘크리트 펌프차 타설 비용", "expect": "6-1-4", "note": "펌프차 명시 시 계산 명세 절"},
    {"id": "c04", "query": "현장비빔 타설 노무비", "expect": "6-1-2", "note": "현장비빔 타설 절"},
    {"id": "c05", "query": "합판거푸집 설치 인건비", "expect": "6-3-1", "note": "합판거푸집 설치 절"},
]


def questions() -> list[dict]:
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    existing = [
        {"id": item["id"], "query": item["query"], "expect": item["expect_section"],
         "note": NOTES[item["id"]]}
        for group in ("questions", "evidence_checks") for item in data[group]
        if "query" in item and "expect_section" in item
    ]
    return existing + EXTRA


def collect(cases: list[dict], offline: bool) -> list[dict] | None:
    if offline:
        os.environ["AGENT_OFFLINE"] = "1"
    else:
        os.environ.pop("AGENT_OFFLINE", None)
        try:
            api_key()
        except (RuntimeError, SystemExit):
            print("HYBRID SKIPPED: GEMINI_API_KEY 없음")
            return None
    get_search.cache_clear()
    rows = []
    for case in cases:
        try:
            result = retrieve(new_state(case["query"]))
        except Exception as exc:
            if offline:
                raise
            print(f"HYBRID SKIPPED: {case['id']} 검색 실패 ({type(exc).__name__})")
            return None
        method = result["search_info"]["method"]
        if not offline and method != "hybrid":
            print(f"HYBRID SKIPPED: {case['id']}에서 검색 방식이 {method}(으)로 변경됨")
            return None
        rows.append({**case, "hits": result["hits"], "search_info": result["search_info"]})
    return rows


def save_hybrid(rows: list[dict]) -> None:
    HYBRID_HITS.parent.mkdir(parents=True, exist_ok=True)
    payload = {"date": datetime.now(timezone.utc).date().isoformat(), "model": MODEL,
               "questions": rows}
    HYBRID_HITS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"HYBRID HITS SAVED: {HYBRID_HITS.relative_to(ROOT)}")


def reuse_hybrid(cases: list[dict]) -> list[dict]:
    payload = json.loads(HYBRID_HITS.read_text(encoding="utf-8"))
    rows = payload["questions"]
    if payload["model"] != MODEL or [
        (row["id"], row["query"], row["expect"]) for row in rows
    ] != [(case["id"], case["query"], case["expect"]) for case in cases]:
        raise ValueError("저장된 모델 또는 질문 목록이 현재 평가와 다릅니다")
    if any(row["search_info"]["method"] != "hybrid" for row in rows):
        raise ValueError("저장된 결과에 하이브리드가 아닌 검색이 포함돼 있습니다")
    print(f"HYBRID HITS REUSED: {HYBRID_HITS.relative_to(ROOT)} ({payload['date']}, {MODEL})")
    return rows


def classify(expected: str, result: dict) -> str:
    if result["decision"] in ("ask", "provisional"):
        return "ask"
    chosen = result["candidates"][0]["section_no"]
    return "correct" if chosen == expected else "wrong"


def evaluate(mode: str, rows: list[dict], specs: dict) -> list[tuple]:
    trials = []
    ambiguous = sum(row["expect"] == "ask" for row in rows)
    print(f"\n{mode}: MARGIN | correct | wrong | ask | ambiguous ask | provisional top correct")
    for margin in MARGINS:
        outcomes = [(row, decide(row["hits"], specs, margin)) for row in rows]
        counts = {label: sum(classify(row["expect"], result) == label for row, result in outcomes)
                  for label in ("correct", "wrong", "ask")}
        ambiguous_ask = sum(result["decision"] in ("ask", "provisional") for row, result in outcomes
                            if row["expect"] == "ask")
        provisional = [(row, result) for row, result in outcomes if result["decision"] == "provisional"]
        top_correct = sum(result["candidates"][0]["section_no"] == row["expect"]
                          for row, result in provisional)
        trials.append((margin, counts, outcomes))
        print(f"{margin:g} | {counts['correct']} | {counts['wrong']} | {counts['ask']} | {ambiguous_ask}/{ambiguous} | {top_correct}/{len(provisional)}")
    return trials


def choose(trials: list[tuple]) -> tuple:
    zero_wrong = [trial for trial in trials if trial[1]["wrong"] == 0]
    if not zero_wrong:
        print("하이브리드에서 wrong 0건인 MARGIN 후보가 없습니다")
    return min(zero_wrong or trials, key=lambda trial: (trial[1]["wrong"], trial[1]["ask"], trial[0]))


def details(mode: str, rows: list[dict], specs: dict, margin: float) -> None:
    print(f"\n{mode} MARGIN {margin:g}: wrong/ask 전체")
    for row in rows:
        result = decide(row["hits"], specs, margin)
        label = classify(row["expect"], result)
        if label == "correct":
            continue
        top = ", ".join(f"{item['section_no']}={item['score']:.3f}" for item in result["candidates"])
        print(f"{label.upper()} {row['id']} | {row['query']} | 기대 {row['expect']} | {top or '-'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse", action="store_true", help="저장된 하이브리드 hits 재사용")
    args = parser.parse_args()
    cases = questions()
    specs = specs_by_section()
    offline = collect(cases, offline=True)
    evaluate("BM25", offline, specs)

    if args.reuse:
        hybrid = reuse_hybrid(cases)
    else:
        hybrid = collect(cases, offline=False)
        if hybrid is not None:
            save_hybrid(hybrid)
    if hybrid is None:
        details("BM25", offline, specs, MARGIN)
        print(f"MARGIN {MARGIN:g} 유지: 하이브리드 측정 불가")
        return 0

    hybrid_trials = evaluate("HYBRID", hybrid, specs)
    chosen = choose(hybrid_trials)
    margin = chosen[0]
    print(f"\n하이브리드 채택 MARGIN {margin:g}: {chosen[1]}")
    details("BM25", offline, specs, margin)
    details("HYBRID", hybrid, specs, margin)
    if MARGIN != margin:
        print(f"select.MARGIN={MARGIN:g}; 측정 채택값={margin:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
