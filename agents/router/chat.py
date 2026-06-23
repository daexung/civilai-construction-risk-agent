"""
대화형 실행 스크립트
실행: python chat.py (construction_risk_agent-router 폴더에서)
종료: 'q' 또는 'quit' 입력
"""
from langchain_core.messages import HumanMessage, AIMessage
from graph import graph
from logger import get_logger

log = get_logger(__name__)

# 프로젝트 선택 UI가 아직 없어 sample_projects.json의 기본 프로젝트로 고정
# (test.py와 동일한 기본값)
DEFAULT_PROJECT_ID = "PJT-001"

_STUB_MARKER = "미구현"  # stub 응답 필터링 키워드


def _is_stub(resp: str) -> bool:
    """미구현 stub 응답이면 True."""
    return resp is not None and _STUB_MARKER in resp


def print_result(state: dict, verbose: bool = False):
    """synthesize 노드가 만든 최종 답변을 출력. verbose=True면 에이전트별 원본 응답도 함께 출력."""
    if verbose:
        for key, label in [
            ("weather_response", "기상 에이전트"),
            ("equipment_response", "장비 에이전트"),
            ("labor_cost_response", "인건비 에이전트"),
            ("material_response", "자재 에이전트"),
        ]:
            resp = state.get(key)
            if resp and not _is_stub(resp):
                print(f"\n[{label}]\n{resp}")
        print("\n" + "─" * 60)

    final_response = state.get("final_response")
    if final_response and not _is_stub(final_response):
        print(f"\n{final_response}")
    else:
        print("\n답변을 생성하지 못했습니다.")


def _extract_ai_text(state: dict) -> str:
    """다음 턴 컨텍스트로 쓸 AI 응답 텍스트 — synthesize 노드의 최종 답변을 사용."""
    resp = state.get("final_response", "")
    return resp if resp and not _is_stub(resp) else ""


def main():
    print("건설 리스크 에이전트 (종료: q)\n")
    log.info("=== 대화 세션 시작 ===")
    history = []  # 대화 히스토리 누적

    while True:
        query = input("질문: ").strip()
        if not query or query.lower() in ("q", "quit"):
            log.info("=== 대화 세션 종료 ===")
            break

        log.info(f"질문: {query}")
        history.append(HumanMessage(content=query))

        print()
        try:
            result = graph.invoke({
                "messages": history,
                "project_id": DEFAULT_PROJECT_ID,
            })
        except Exception:
            log.exception("graph.invoke 실패")
            print("\n오류가 발생했습니다. 다시 시도해 주세요.")
            print("\n" + "─" * 60 + "\n")
            continue

        print_result(result)

        log.debug("--- 처리 완료 ---")

        # AI 응답을 히스토리에 추가 — 다음 턴에서 컨텍스트로 사용
        ai_text = _extract_ai_text(result)
        if ai_text:
            history.append(AIMessage(content=ai_text))

        print("\n" + "─" * 60 + "\n")


if __name__ == "__main__":
    main()
