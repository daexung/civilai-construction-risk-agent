"""
인건비 에이전트 단독 테스트
- 실행: python agents/labor_cost/test_agent.py
"""
from langgraph.graph import StateGraph, MessagesState, START
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import ToolNode, tools_condition
import logging
import tools

logging.basicConfig(level=logging.WARNING, format='%(message)s')
from labor_cost_node import labor_cost_node, labor_cost_tools

# 테스트용 그래프 구성
workflow = StateGraph(MessagesState)
workflow.add_node('LaborCostAgent', labor_cost_node)
workflow.add_node('LaborCostAgent_tools', ToolNode(labor_cost_tools))

workflow.add_edge(START, 'LaborCostAgent')
workflow.add_conditional_edges(
    'LaborCostAgent',
    tools_condition,
    {'tools': 'LaborCostAgent_tools', '__end__': '__end__'},
)
workflow.add_edge('LaborCostAgent_tools', 'LaborCostAgent')

app = workflow.compile()

if __name__ == '__main__':
    while True:
        user_input = input('\nUSER: ')
        if user_input == 'q':
            break
        prompt = {'messages': [HumanMessage(content=user_input)]}
        for evt in app.stream(prompt, stream_mode='values'):
            msg = evt['messages'][-1]
            if msg.type != 'human':
                print('LaborCostAgent:', msg.content)
