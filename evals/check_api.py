"""오프라인으로 채팅 API의 상태 전환과 thread_id 규칙을 검사한다."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["AGENT_OFFLINE"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

CLIENT = TestClient(app)

PUMP_ANSWERS = {"pump_size": "32m", "slump_band": "15㎝", "facility_type": "Type-Ⅱ", "site_type": "Type-Ⅱ",
                "placement": "붐", "vibrator_used": True, "reset_status": "없음", "concrete_supply": "관급",
                "work_category": "기타 토목공사", "duration": "1~6개월", "contractor_type": "종합건설업",
                "project_scale": "이 견적만"}


def main() -> int:
    checks = []

    outside = CLIENT.post("/api/chat", json={"message": "오늘 현장 날씨 어때?"}).json()
    checks.append(("A1", outside["status"] == "OUT_OF_SCOPE" and not outside["questions"]))

    evidence = CLIENT.post("/api/chat", json={"message": "합판거푸집 설치 인건비"}).json()
    checks.append(("A2", evidence["status"] == "EVIDENCE_ONLY" and len(evidence["evidence"]) == 3))

    missing = CLIENT.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용",
                                              "basis_date": "2026-10-01"}).json()
    thread_id = missing["thread_id"]
    checks.append(("A3", missing["status"] == "MISSING_INFO" and len(missing["questions"]) == 8
                   and missing["work"]["section_no"] == "6-1-4"))

    computed = CLIENT.post("/api/chat", json={"thread_id": thread_id, "answers": PUMP_ANSWERS}).json()
    computed_lines = {line["name"]: line for line in computed.get("result", {}).get("lines", [])}
    checks.append(("A4", computed["status"] == "PARTIAL" and len(computed["inputs"]) == 14
                   and all(item["source"] in ("질문", "답변", "선택", "기본값") for item in computed["inputs"])
                   and computed_lines.get("콘크리트공", {}).get("value") == "8"
                   and computed_lines.get("콘크리트펌프차", {}).get("kind") == "equipment"
                   and computed_lines.get("콘크리트펌프차", {}).get("value") == "2"
                   and computed["result"]["review_status"] == "미완료"
                   and computed["statement"]["totals"] == {
                       "materials": 178360, "labor": 4922974, "expenses": 2263523,
                       "net_cost": 7364857, "management": 589188, "profit": 1166352,
                       "total_cost": 9120397, "vat": 912039, "contract_amount": 10032436
                   }))

    reused = CLIENT.post("/api/chat", json={"thread_id": thread_id, "message": "새 질문"}).json()
    checks.append(("A5", reused["thread_id"] != thread_id))

    health = CLIENT.get("/api/health").json()
    checks.append(("A6", health == {"status": "ok"}))

    blocked_start = CLIENT.post("/api/chat", json={"message": "철근콘크리트 벽체 260㎥ 펌프차로 타설 비용"}).json()
    blocked_answers = {**PUMP_ANSWERS, "reset_status": "있음"}
    blocked = CLIENT.post("/api/chat", json={"thread_id": blocked_start["thread_id"], "answers": blocked_answers}).json()
    checks.append(("A7", blocked["status"] == "BLOCKED" and blocked["result"]["input"] == "reset_status"
                   and bool(blocked["result"]["source"]) and blocked["message"] == blocked["result"]["reason"]))

    unit_lines = {line["name"]: line for line in computed["result"].get("unit_lines", [])}
    checks.append(("A8", computed["result"].get("unit_basis", {}).get("per") == "1㎥"
                   and computed["result"]["unit_basis"]["places"] == 4
                   and unit_lines.get("콘크리트공", {}).get("applied") == "0.0308"
                   and unit_lines.get("콘크리트펌프차", {}).get("exact") == "4/65"
                   and computed_lines["콘크리트공"]["value"] == "8"))

    checks.append(("A9 응답에 llm_info 포함",
                   computed.get("llm_info", {}).get("provider") == "vertex"
                   and computed["llm_info"].get("model") == "gemini-3.5-flash-lite"
                   and computed["llm_info"].get("attempts") == 0
                   and "VERTEX_API_KEY" not in str(computed["llm_info"])))

    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    print(f"통과 {sum(passed for _, passed in checks)} / 전체 {len(checks)}")
    if not all(passed for _, passed in checks):
        print("A3:", missing)
        print("A4:", computed)
        print("A7:", blocked)
    return 0 if all(passed for _, passed in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
