"""route부터 fill까지의 에이전트를 터미널에서 실행한다."""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
from uuid import uuid4

from langgraph.types import Command

from backend.agent.graph import build_graph
from backend.agent.rules.specs import load_specs
from backend.agent.state import new_state


def _console_utf8() -> None:
    if os.name == "nt":
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    for stream in (sys.stdout, sys.stderr, sys.stdin):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def _print_questions(payload: dict) -> None:
    print(payload.get("reason", "계산 조건을 확인해 주세요"))
    for number, question in enumerate(payload["questions"], 1):
        print(f"{number}. {question['ask']}")
        choices = question.get("choices")
        if choices:
            options = ", ".join(str(item) for item in choices) if isinstance(choices, list) else str(choices)
            print(f"   선택지: {options}")
        if question.get("hint"):
            hint = question["hint"]
            print(f"   힌트: {hint['matched']} → {hint['value']} (확인 필요)")
        if question["name"] == "work":
            print(f"   기본값: {question['default']} (확인 전에는 적용하지 않음)")
        if question.get("reason"):
            print(f"   확인 이유: {question['reason']}")


def _print_summary(state: dict) -> None:
    print(f"상태: {state.get('status', 'RUNNING')}")
    if state.get("search_info"):
        search = state["search_info"]
        print(f"검색: {search['method']} (임베딩 API {search['api_calls']}회)")
    selection = state.get("selection", {})
    spec_id = state.get("spec_id", "")
    spec = load_specs().get(spec_id) if spec_id else None
    candidates = state.get("candidates", [])
    section = (selection.get("section") or (spec["title"] if spec else None)
               or (candidates[0]["section"] if candidates else "없음"))
    print(f"공종: {section} | spec_id: {spec_id or '없음'}")
    inputs = state.get("inputs", {})
    sources = state.get("input_sources", {})
    if inputs:
        print("입력:")
        for name, value in inputs.items():
            print(f"  {name}: {value} ({sources.get(name, '출처 없음')})")
    if state.get("status") == "EVIDENCE_ONLY":
        print("상위 근거:")
        for number, hit in enumerate(state.get("hits", [])[:3], 1):
            print(f"  {number}. {hit['section']} | PDF {hit['page']}쪽")
    elif state.get("status") == "RUNNING" and not state.get("questions"):
        print("계산 준비 완료 — gate·compute는 다음 단계")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", help="공사비 질문")
    parser.add_argument("--offline", action="store_true", help="BM25 검색만 사용")
    parser.add_argument("--answer", action="append", default=[], help="되묻기에 대한 답. 여러 번 지정 가능")
    args = parser.parse_args(argv)
    _console_utf8()
    if args.offline:
        os.environ["AGENT_OFFLINE"] = "1"
    graph = build_graph()
    config = {"configurable": {"thread_id": uuid4().hex}}
    state = graph.invoke(new_state(args.query), config)
    answer_index = 0
    while state.get("__interrupt__"):
        payload = state["__interrupt__"][0].value
        _print_questions(payload)
        if answer_index < len(args.answer):
            reply = args.answer[answer_index]
            answer_index += 1
            print(f"답: {reply}")
        else:
            try:
                reply = input("답> ")
            except EOFError:
                print("답변 입력이 없어 중단했습니다.", file=sys.stderr)
                return 2
        state = graph.invoke(Command(resume=reply), config)
    _print_summary(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
