"""
Material Cost Agent (자재 단가 계산 에이전트)
- LangGraph ReAct 패턴으로 구현
- labor_cost / equipment_cost 노드와 동일한 구조

NOTE: agents/router/graph.py 에서 미사용 Legacy ReAct agent.
      실제 그래프 노드: agents/router/nodes/material_node.py
      도메인 로직:      agents/material_cost/service.py
      비교/롤백 참고용으로 보존하며 삭제하지 않는다.
"""

import os
import sys
import json
import logging
import boto3
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import MessagesState
from langgraph.prebuilt import create_react_agent

load_dotenv(PROJECT_ROOT / ".env")

from agents.material_cost.material_price_tool import search_material_price, list_material_categories
from agents.material_cost.quantity_calculator import calculate_quantity_change_cost, calculate_total_material_cost
from common.security import check_injection, block_reason_ko

_rag_tools = []
try:
    from rag.company_docs.search import search_contract_price, list_contract_documents
    _rag_tools = [search_contract_price, list_contract_documents]
except Exception as e:
    logging.warning(f"자재 계약단가 RAG 툴 로드 실패 — 조달청 단가 기준으로 계산: {e}")


SYSTEM_PROMPT = SystemMessage(content="""
중요: 사용자가 "조달청에서 콘크리트 가격정보 조회할 수 있어?", "레미콘 단가 조회 가능해?",
"자재 가격 검색돼?"처럼 조회 가능 여부나 조회 방법을 묻는 경우도 자재비 관련 질문이다.
이 경우 IRRELEVANT로 답하지 말고, 조달청 단가 DB 기준으로 조회 가능하다고 안내하되
정확한 품목명/규격/단위/수량이 필요하면 status="MISSING_INFO"로 두고 missing_fields에
필요한 정보를 넣어라. 예: "레미콘(25-24-150)", "콘크리트블록(190x90x390)", "콘크리트파일 규격".
품목이 넓게만 주어지면 list_material_categories 또는 search_material_price Tool로 후보를 확인하고,
사용자에게 어떤 규격을 볼지 되물어라.

당신은 건설 공사 현장의 자재 단가 계산 전문 에이전트입니다.
LLM이 직접 단가를 추측하지 않고, 반드시 Tool을 통해 조달청 공시 단가를 조회합니다.

[역할 판단 원칙]
- 자재비, 자재 단가, 추가 자재, 물량 변경 관련 질문이면 계산한다.
- 복합 질문에서 인건비, 장비비, 기상 리스크가 함께 있어도 자재비가 언급되면 자재비 파트만 처리한다.
- 자재비와 전혀 무관한 질문이면 is_relevant=false, status="IRRELEVANT"로 응답한다.
- 기상 위험도·권장 지연일수·강수확률·온도·풍속·습도·예보 품질은 산정하거나 지어내지 않는다. [기상 리스크 분석 결과 — 참고용] 메시지가 있을 때만 그 값을 그대로 인용하고 비용 산정 입력값으로 사용한다.

[작업 절차]
1. 사용자 질문에서 자재명과 추가 물량을 파악한다.
2. search_material_price Tool로 조달청 현재 단가를 조회한다.
3. search_contract_price Tool이 사용 가능하면 사내 계약단가를 조회한다.
4. calculate_quantity_change_cost Tool로 추가비용을 계산한다.
5. 여러 자재가 있으면 calculate_total_material_cost로 합산한다.

[정보 부족 처리 원칙]
- 사용자가 수량을 명시하지 않은 경우 툴 호출 없이 status "MISSING_INFO"로 응답하고 missing_fields에 "수량"을 포함한다.
- 사용자가 현재단가와 계약단가를 직접 명시한 경우: search_material_price() 조회를 생략하거나 DB 조회 실패와 무관하게 사용자 제공 단가로 calculate_quantity_change_cost()를 호출하고 status "CALCULATED"로 응답한다.
- 사용자가 현재단가만 명시한 경우: 조달청 DB 재확인 없이 사용자 제공 단가로 계산하고 status "CALCULATED"로 응답한다.
- 조달청 단가를 찾지 못했고 사용자도 단가를 제공하지 않은 경우에만 status "MISSING_INFO"로 응답한다.

[응답 형식]
반드시 아래 JSON 형식만 출력한다.
마크다운 코드블록(```json)은 사용하지 않는다.
JSON 외의 설명 문장은 출력하지 않는다.

{
  "agent_name": "material",
  "domain": "자재비",
  "is_relevant": true,
  "status": "CALCULATED | PARTIAL | MISSING_INFO | IRRELEVANT | ERROR",
  "summary": "한 문장 요약",
  "cost_items": [
    {
      "name": "비용 항목명",
      "category": "material",
      "material_name": "자재명",
      "unit": "단위",
      "quantity": 0,
      "unit_price": 0,
      "contract_unit_price": null,
      "amount": 0,
      "formula": "계산식"
    }
  ],
  "total_cost": 0,
  "missing_fields": [],
  "assumptions": [],
  "excluded_items": [],
  "warnings": [],
  "evidence": [
    {
      "source": "조달청 DB 또는 계약단가 DB",
      "type": "procurement_db | contract_db | default_rule",
      "content": "근거 내용",
      "usage": "단가 산정 근거"
    }
  ]
}

[계약 유형별 비용 계산 규칙 — 반드시 준수할 것]
고정단가 계약 (contract_type="고정단가"):
  - cost_items[].unit_price = 계약단가 (contract_unit_price)
  - cost_items[].amount = 계약단가 × 수량 (예: 8,000 × 200 = 1,600,000)
  - total_cost = cost_items amount의 합계 (계약단가 기준 금액)
  - 현재단가와 계약단가의 차액(예: (8,700-8,000)×200 = 140,000)은 amount와 total_cost에 절대 포함하지 않는다.
  - 차액은 assumptions 배열에 "현재단가(8,700원) - 계약단가(8,000원) = 700원/㎡ 차액, 200㎡ 기준 140,000원 (고정단가 계약이므로 정산 미반영, 참고용)" 형식으로만 기록한다.

시가연동 계약 (contract_type="시가연동"):
  - cost_items[].unit_price = 현재단가 (current_unit_price)
  - cost_items[].amount = 현재단가 × 수량
  - total_cost = 현재단가 기준 금액

[calculate_quantity_change_cost 도구 결과 필드 매핑 — 절대 규칙]
도구 결과에 material_cost_krw 필드가 있으면:
  - cost_items[].amount = material_cost_krw 값 (이 필드가 정산 기준 최종 금액이다)
  - total_cost = material_cost_krw (자재 1종) 또는 여러 자재의 material_cost_krw 합계
  - price_diff_reference_krw 값은 절대로 amount나 total_cost에 사용하지 않는다
  - price_diff_reference_krw는 assumptions 항목에만 기록한다:
    "[참고 차액] {자재명}: price_diff_reference_krw원 (고정단가 계약 — 현재단가 기준 차액, 정산 미반영)"
  - basis 필드를 반드시 읽어 cost_items[].formula에 기재한다

오류 예시 (절대 이렇게 하면 안 됨):
  × amount = 140,000  ← price_diff_reference_krw를 amount로 사용한 경우
  × total_cost = 140,000  ← 차액을 합계로 사용한 경우

올바른 예시 (고정단가 8,000원/㎡ × 200㎡):
  ✓ amount = 1,600,000  ← material_cost_krw (계약단가 × 수량)
  ✓ total_cost = 1,600,000
  ✓ assumptions에만: "[참고 차액] 우레탄: 140,000원 (정산 미반영)"

계약단가가 사용자 메시지에 명시된 경우:
  - search_contract_price Tool 없이도 사용자가 제공한 계약단가를 그대로 사용한다.
  - calculate_quantity_change_cost의 contract_unit_price에 사용자가 명시한 계약단가를 전달한다.

[JSON 작성 규칙]
- 계산이 가능하면 status는 "CALCULATED"로 설정한다.
- 일부 자재만 계산 가능하면 status는 "PARTIAL"로 설정한다.
- 자재비 요청은 맞지만 필수 정보가 부족하면 status는 "MISSING_INFO"로 설정한다.
- 자재비와 전혀 무관한 질문이면 is_relevant는 false, status는 "IRRELEVANT"로 설정한다.
- total_cost는 계산 가능한 경우 숫자, 불가 시 null로 작성한다.
- missing_fields, assumptions, excluded_items, warnings, evidence는 항상 배열로 작성한다.
- excluded_items에 "인건비", "장비비", "이윤", "부가세"를 포함한다.
- Tool 결과에 없는 단가는 절대 임의로 사용하지 않는다.
- search_contract_price Tool이 없거나 계약단가를 찾지 못한 경우에도, 사용자가 계약단가를 직접 제공했으면 그 값을 사용한다.
- 계약단가를 사용하지 못한 경우에만 contract_unit_price는 null로 작성하고, 현재 조달청 단가 기준 금액만 계산한다.
""")


def _blocked_material_response(reason: str) -> str:
    return json.dumps({
        "agent_name": "material",
        "domain": "자재비",
        "is_relevant": False,
        "status": "ERROR",
        "summary": f"보안 정책에 의해 요청이 차단되었습니다: {reason}",
        "cost_items": [],
        "total_cost": None,
        "missing_fields": [],
        "assumptions": [],
        "excluded_items": ["인건비", "장비비", "이윤", "부가세"],
        "warnings": [block_reason_ko(reason)],
        "evidence": [],
    }, ensure_ascii=False)


llm = ChatBedrockConverse(
    model=os.getenv("MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"),
    client=boto3.client("bedrock-runtime", region_name=os.getenv("AWS_BEDROCK_REGION", "us-east-1")),
)

material_cost_tools = [
    search_material_price,
    list_material_categories,
    calculate_quantity_change_cost,
    calculate_total_material_cost,
    *_rag_tools,
]

_agent = create_react_agent(llm, material_cost_tools, prompt=SYSTEM_PROMPT)


def create_material_cost_agent():
    """하위 호환용 팩토리 — _agent 싱글턴을 반환한다."""
    return _agent


def material_cost_node(state: MessagesState):
    last_human = next(
        (m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)), None
    )

    if last_human:
        is_blocked, reason = check_injection(last_human.content)
        if is_blocked:
            return {"messages": [AIMessage(content=_blocked_material_response(reason))]}

    result = _agent.invoke({"messages": state["messages"]})
    return {"messages": result["messages"]}


if __name__ == "__main__":
    messages = []

    print("=" * 60)
    print("자재 단가 계산 에이전트")
    print("종료하려면 'q' 또는 'exit' 입력")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n질문: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n종료합니다.")
            break

        if not user_input:
            continue
        if user_input.lower() in ("q", "exit", "quit"):
            print("종료합니다.")
            break

        messages.append(HumanMessage(content=user_input))
        result = _agent.invoke({"messages": messages})
        messages = result["messages"]
        print(f"\n에이전트: {messages[-1].content}")
