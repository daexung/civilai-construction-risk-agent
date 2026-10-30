"""작업 종류에 따라 물량 단위가 달라지는 공종(토목 1-9-3: 지주 개 · 와이어 m · 철망 ㎡)의 상담 동작.

외부 호출 없음(검색은 직접 넣은 후보). 확인: 작업 종류를 알기 전에는 물량을 묻지 않음 · 단위 검증 ·
작업 종류를 바꾸면 이전 결과가 무효가 되고 새 단위로 다시 묻는 것 · 계산 단위 기준(1m/1㎡) · 형제 항목은 그대로.
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

from backend.agent.estimate import tools  # noqa: E402
from backend.agent.rules.specs import load_specs  # noqa: E402
from backend.agent.tools.source import citation  # noqa: E402


def values(**items):
    return {name: {"value": value, "evidence": str(value)} for name, value in items.items()}


def main() -> int:
    spec = next(s for s in load_specs().values() if s["division"] == "토목" and s["section_no"] == "1-9-3")
    hit = {"rank": 1, "section_no": "1-9-3", "division": "토목", "section": f"1-9-3 {spec['title']}", "page": 200,
           "table_id": None, "text": spec["title"], "chunk_id": "mock"}
    with patch.object(citation, "_pages", return_value=defaultdict(lambda: {"printed_page": None, "division": None})):
        session = tools.new_estimate("낙석방지책 설치")
        tools.find_work(session, hits=[hit])
        current = lambda: session["items"][session["item_order"][0]]  # 세션은 갱신 때 항목 사본을 만든다
        first = tools.compute_labor(session)
        assert [q["field"] for q in first["missing"]] == ["work_type"], first["missing"]  # 단위를 모르는 물량은 묻지 않는다
        tools.set_conditions(session, "와이어 설치", values=values(work_type="와이어 설치"), source="answer")
        asked = {q["field"]: q for q in tools.compute_labor(session)["missing"]}
        assert asked["quantity"]["unit"] == "m", asked
        wrong = tools.set_conditions(session, "500㎡", quantity={"value": "500", "unit": "㎡", "evidence": "500㎡"}, source="text")
        assert wrong["rejected"].get("quantity"), wrong
        tools.set_conditions(session, "500m", quantity={"value": "500", "unit": "m", "evidence": "500m"}, source="text")
        tools.set_conditions(session, "x", values=values(scaffold_wire=False), source="answer")
        wire = tools.compute_labor(session)
        assert wire["status"] == "ok" and wire["data"]["unit_basis"]["per"] == "1m", wire
        assert wire["data"]["person_days"] == {"특별인부": "10", "보통인부": "5"}, wire["data"]["person_days"]  # 500m÷200m/일
        assert tools.estimate_cost(session)["status"] == "ok" and current()["status"] == "PRICED"
        revision = current()["input_revision"]
        tools.set_conditions(session, "철망 설치로", values=values(work_type="철망 설치"), source="answer")
        assert current()["input_revision"] > revision and current()["status"] != "PRICED"  # 이전 결과 무효화
        after = tools.compute_labor(session)
        quantity_question = next(q for q in after["missing"] if q["field"] == "quantity")
        assert quantity_question["unit"] == "㎡" and "맞지 않아요" in quantity_question["reason"], quantity_question
        tools.set_conditions(session, "720㎡", quantity={"value": "720", "unit": "㎡", "evidence": "720㎡"}, source="text")
        tools.set_conditions(session, "x", values=values(scaffold_mesh=False), source="answer")
        mesh = tools.compute_labor(session)
        assert mesh["data"]["unit_basis"]["per"] == "1㎡" and mesh["data"]["person_days"] == {"특별인부": "8", "보통인부": "4"}
        assert tools.estimate_cost(session)["status"] == "ok"
    print("PASS 토목 1-9-3: 작업 종류별 물량 단위 질문·검증·변경 시 무효화·1m/1㎡ 계산 기준")
    return 0


if __name__ == "__main__":
    sys.exit(main())
