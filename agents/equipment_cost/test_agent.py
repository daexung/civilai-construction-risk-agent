"""
장비 대기 비용 에이전트 단독 테스트
- 실행: python agents/equipment_cost/test_agent.py (프로젝트 루트에서)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')))

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, MessagesState, START
from langgraph.prebuilt import ToolNode, tools_condition
from equipment_cost_node import equipment_cost_node, equipment_cost_tools

TEST_QUERIES = [
    "굴착기 0.7㎥ 1대가 우천으로 3일 대기 중입니다. 추가 비용이 얼마나 발생하나요?",
    "콘크리트 펌프카 붐식 36m와 크레인 50ton이 공정 지연으로 2일간 대기할 때 총 장비 대기 비용은?",
    "덤프트럭 15ton 3대가 5일 대기하면 대기 비용이 얼마야?",
]


def build_graph():
    workflow = StateGraph(MessagesState)
    workflow.add_node('EquipmentCostAgent', equipment_cost_node)
    workflow.add_node('EquipmentCostAgent_tools', ToolNode(equipment_cost_tools))
    workflow.add_edge(START, 'EquipmentCostAgent')
    workflow.add_conditional_edges(
        'EquipmentCostAgent',
        tools_condition,
        {'tools': 'EquipmentCostAgent_tools', '__end__': '__end__'},
    )
    workflow.add_edge('EquipmentCostAgent_tools', 'EquipmentCostAgent')
    return workflow.compile()


def run_test(graph, query: str):
    print(f'\n{"="*60}')
    print(f'질문: {query}')
    print('='*60)

    final = None
    for evt in graph.stream({'messages': [HumanMessage(content=query)]}, stream_mode='values'):
        msg = evt['messages'][-1]
        if msg.type == 'ai' and not getattr(msg, 'tool_calls', None):
            final = msg.content

    print(final or '[응답 없음]')


if __name__ == '__main__':
    graph = build_graph()
    for q in TEST_QUERIES:
        run_test(graph, q)
