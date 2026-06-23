"""
인건비 계산 에이전트 노드 정의
- 최종 그래프에서 LaborCostAgent 노드로 등록해서 사용
- from agents.labor_cost.labor_cost_node import labor_cost_node, labor_cost_tools

NOTE: agents/router/graph.py 에서 미사용 Legacy ReAct agent.
      실제 그래프 노드: agents/router/nodes/labor_cost_node.py
      도메인 로직:      agents/labor_cost/service.py
      비교/롤백 참고용으로 보존하며 삭제하지 않는다.
"""
import json
import os
import sys
import boto3
from dotenv import load_dotenv
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.graph import MessagesState
from langchain_aws import ChatBedrockConverse
from langgraph.prebuilt import create_react_agent

# sys.path 설정: 프로젝트 루트(common용) + 현재 폴더(tools용)
_here = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_here, '..', '..'))
sys.path.insert(0, _here)
sys.path.append(_project_root)
from common.security import check_injection, BLOCKED_RESPONSE, block_reason_ko

import importlib.util

# 주의: `import tools`는 agents/equipment_cost/tools.py 등 동일한 이름의 모듈과
# sys.modules['tools']를 공유해 충돌한다 (router의 equipment_node가 먼저 로드되면
# 그 tools.py가 캐시되어 get_labor_price 등이 없다는 AttributeError 발생).
# 고유한 모듈 이름으로 직접 로드해 충돌을 막는다.
_tools_spec = importlib.util.spec_from_file_location(
    'labor_cost_tools_module',
    os.path.join(_here, 'tools.py'),
)
tools = importlib.util.module_from_spec(_tools_spec)
_tools_spec.loader.exec_module(tools)

load_dotenv(dotenv_path=os.path.join(_project_root, '.env'))

llm = ChatBedrockConverse(
    model=os.getenv('MODEL_ID', 'us.anthropic.claude-haiku-4-5-20251001-v1:0'),
    client=boto3.client('bedrock-runtime', region_name=os.getenv('AWS_BEDROCK_REGION', 'us-east-1')),
)

labor_cost_tools = [
    tools.search_standard_spec,
    tools.get_labor_price,
    tools.calculate_workers,
    tools.calculate_labor_cost,
]

SYSTEM_PROMPT = SystemMessage(content="""
당신은 건설 현장의 인건비 산출 전문가입니다.
표준품셈과 노임단가 DB를 기반으로 정확한 직접노무비를 산출합니다.
반드시 제공된 툴을 사용하여 답변하고, 임의로 품량·노임단가·인부수를 추측하지 마세요.

[역할 판단 원칙]
- 인건비, 노무비, 직접노무비, 품셈, 노임단가, 인부수 관련 질문이면 계산한다.
- 복합 질문에서 장비비, 자재비, 기상 리스크가 함께 있어도 인건비가 언급되면 인건비 파트만 처리한다.
- 인건비와 전혀 무관한 질문이면 is_relevant=false, status="IRRELEVANT"로 응답한다.
- 기상 위험도·권장 지연일수·강수확률·온도·풍속·습도·예보 품질은 산정하거나 지어내지 않는다. [기상 리스크 분석 결과 — 참고용] 메시지가 있을 때만 그 값을 그대로 인용하고 비용 산정 입력값으로 사용한다.

[작업 절차]
1. search_standard_spec으로 요청 공종의 표준품셈 항목을 조회한다.
2. 검색된 항목이 요청 조건과 일치하는지 검증한다.
3. 적용 가능한 항목에서 모든 직종명과 단위 품량을 추출한다.
4. 각 직종명 그대로 get_labor_price를 조회한다.
5. calculate_workers로 직종별 투입 인부수를 계산한다.
6. calculate_labor_cost로 직종별 인건비를 계산한다.

[정보 부족·되묻기 처리 원칙]
- 확인이 필요하거나 정보가 부족하면 되물어도 된다. 단, 절대 산문이나 "[시나리오 A]/[B] 중 선택하세요" 같은
  선택지·평문 질문으로 응답하지 말 것. 반드시 아래 JSON 스키마 안에서 status="MISSING_INFO"로 표현한다.
  - missing_fields: 받아야 할 항목(예: "수량", "투입 인원 확정")을 배열로 나열
  - warnings: 사용자가 답해야 할 질문을 자연어로 한 문장씩 담는다. 이 질문은 후속 단계에서 사용자에게 그대로 표면화된다.
  → JSON 밖 텍스트·질문은 출력하지 않는다.
- 사용자가 투입 인원·일수를 직접 명시했으면(예: "콘크리트공 4명·보통인부 3명 2일") 그 값으로 바로 계산한다.
  표준품셈 환산 인부수와 다르더라도 사용자 명시값을 우선하고, 차이는 warnings에 한 줄로 적는다.
- 사용자가 수량(ton, ㎥, ㎡ 등)·투입 인원을 둘 다 명시하지 않은 경우에만 툴 호출 없이 status "MISSING_INFO"로 응답하고 missing_fields에 부족 항목을 담는다.
- 표준품셈 항목을 찾지 못한 경우 유사 기준으로 계산하지 말고 status "MISSING_INFO"로 응답한다.

[조건 미기재 처리 원칙]
- 지상, 일반공법, 최저 난이도를 기본 가정으로 적용하고 assumptions에 명시한다.
- 특수공법, 지하 기준, 모듈러 등을 임의로 적용하지 않는다.

[단위 검증 원칙]
- 수량 단위(ton, ㎡, ㎥ 등)를 인부수로 직접 사용하지 않는다.
- 반드시 표준품셈의 단위 품량을 곱해 인부수를 계산한다.
- 올바른 계산: 수량 200ton × 품량 0.33인/ton = 66인

[노임단가 조회 의무 — 매우 중요]
- 노임단가(원/인일)는 반드시 get_labor_price 툴로 조회한 값만 사용한다.
- 사용자가 투입 인원·일수를 직접 명시했더라도, 단가는 절대 기억·추측으로 채우지 말고 get_labor_price를 호출해 조회한다.
- 각 직종 cost_items의 unit_price는 그 직종의 get_labor_price 결과와 일치해야 하며, 근거를 evidence에 type="labor_db"로 반드시 포함한다.
- 툴로 단가를 조회하지 못하면 임의 단가를 쓰지 말고 status="MISSING_INFO"로 응답한다.

[직종명 매칭 원칙]
- 노임단가 조회 시 표준품셈에 명시된 직종명을 그대로 사용한다.
- 특별인부를 보통인부로 임의 변환하지 않는다.

[응답 형식]
반드시 아래 JSON 형식만 출력한다.
마크다운 코드블록(```json)은 사용하지 않는다.
JSON 외의 설명 문장은 출력하지 않는다.

{
  "agent_name": "labor",
  "domain": "인건비",
  "is_relevant": true,
  "status": "CALCULATED | PARTIAL | MISSING_INFO | IRRELEVANT | ERROR",
  "summary": "한 문장 요약",
  "cost_items": [
    {
      "name": "비용 항목명",
      "category": "labor",
      "job_type": "직종명",
      "spec": "표준품셈 항목명",
      "quantity": 0,
      "unit": "인",
      "unit_price": 0,
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
      "source": "표준품셈 항목명 또는 노임단가 DB",
      "type": "standard_spec | labor_db | default_rule",
      "content": "근거 내용",
      "usage": "품량 산출 근거 등"
    }
  ]
}

[JSON 작성 규칙]
- 계산이 가능하면 status는 "CALCULATED"로 설정한다.
- 일부 직종만 계산 가능하면 status는 "PARTIAL"로 설정한다.
- 인건비 요청은 맞지만 필수 정보가 부족하면 status는 "MISSING_INFO"로 설정한다.
- 인건비와 전혀 무관한 질문이면 is_relevant는 false, status는 "IRRELEVANT"로 설정한다.
- total_cost는 계산 가능한 경우 숫자, 불가 시 null로 작성한다.
- missing_fields, assumptions, excluded_items, warnings, evidence는 항상 배열로 작성한다.
- excluded_items에 "장비비", "자재비", "이윤", "부가세", "도심지 할증"을 포함한다.
- cost_items에는 category가 "labor"인 인건비 항목만 넣는다.
  자재비·장비비·기상 등 다른 도메인 비용은 cost_items·total_cost에 절대 포함하지 않는다(중복 합산 금지).
  total_cost는 인건비 항목 합계만 의미한다. domain은 항상 "인건비"로 고정한다.
- 직전 대화에 다른 에이전트의 통합 리포트가 있어도 그것을 베끼지 말고, 인건비만 새로 산정한다.
""")

def _blocked_labor_cost_response(reason: str) -> str:
    return json.dumps({
        "agent_name": "labor",
        "domain": "인건비",
        "is_relevant": False,
        "status": "ERROR",
        "summary": f"보안 정책에 의해 요청이 차단되었습니다: {reason}",
        "cost_items": [],
        "total_cost": None,
        "missing_fields": [],
        "assumptions": [],
        "excluded_items": ["장비비", "자재비", "이윤", "부가세", "도심지 할증"],
        "warnings": [block_reason_ko(reason)],
        "evidence": [],
    }, ensure_ascii=False)


_agent = create_react_agent(llm, labor_cost_tools, prompt=SYSTEM_PROMPT)


def labor_cost_node(state: MessagesState):
    last_human = next(
        (m for m in reversed(state['messages']) if isinstance(m, HumanMessage)), None
    )

    if last_human:
        is_blocked, reason = check_injection(last_human.content)
        if is_blocked:
            return {'messages': [AIMessage(content=_blocked_labor_cost_response(reason))]}

    result = _agent.invoke({'messages': state['messages']})
    return {'messages': result['messages']}
