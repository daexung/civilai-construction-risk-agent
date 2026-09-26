"""품량 단계 노드(얇은 어댑터).

에이전트가 질문에서 추출·검증한 조건(공법·구조물·물량)을 품량 계산기의 입력으로 옮겨 넘기기만 한다.
계산·검증·거부 판단은 모두 agent/tools/calc/quantity.py가 한다. 이 노드는 값을 바꾸거나 추정하지 않는다.
"""

from agent.tools.calc.quantity import compute
from agent.tools.calc.unit_price import quantity_conditions
from agent.rules.section_6 import SUPPORTED_CASE


def quantity_step(inputs: dict) -> dict:
    """{'method', 'structure', 'volume_m3'} → quantity.compute 결과(status 'computed' 또는 'refused')."""
    case = {**SUPPORTED_CASE, "method": inputs["method"], "structure": inputs["structure"]}
    return compute(SUPPORTED_CASE["section_no"], quantity_conditions(case), str(inputs["volume_m3"]))
