"""검색 순위로 작업 절을 고른다."""

from agent.rules.specs import specs_by_section
from agent.state import AgentState


# check_select.py의 26개 질문에서 오답 0건인 후보 중 되묻기 최소값.
MARGIN = 2.0


def decide(hits: list[dict], specs: dict[str, list[dict]], margin: float = MARGIN) -> dict:
    """청크 순위와 명세 목록으로 결정·후보·이유를 돌려준다."""
    by_section: dict[str, dict] = {}
    for hit in hits:
        section_no = hit.get("section_no")
        if not section_no or section_no.count("-") != 2:
            continue
        group = by_section.setdefault(section_no, {
            "section_no": section_no, "section": hit["section"],
            "score": 0.0, "has_spec": bool(specs.get(section_no)),
        })
        group["score"] += 1 / hit["rank"]

    candidates = sorted(by_section.values(), key=lambda group: (-group["score"], group["section_no"]))[:3]
    if not candidates:
        return {"decision": "ask", "candidates": [], "reason": "작업 절을 찾지 못했습니다"}

    first = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    if second and first["score"] <= margin * second["score"]:
        return {"decision": "ask", "candidates": candidates,
                "reason": f"상위 절 {first['section_no']}와 {second['section_no']}의 검색 점수가 비슷합니다"}
    if not first["has_spec"]:
        return {"decision": "no_spec", "candidates": candidates,
                "reason": f"{first['section_no']} 절의 계산 명세가 없습니다"}
    return {"decision": "chosen", "candidates": candidates,
            "reason": f"{first['section_no']} 절의 검색 점수가 가장 높습니다",
            "spec_id": specs[first["section_no"]][0]["id"]}


def select(state: AgentState) -> dict:
    result = decide(state["hits"], specs_by_section())
    decision = result["decision"]
    update = {"candidates": result["candidates"],
              "selection": {"decision": decision, "reason": result["reason"]}}
    if decision == "chosen":
        update["spec_id"] = result["spec_id"]
    elif decision == "ask":
        names = ", ".join(item["section"] for item in result["candidates"])
        update.update(status="MISSING_INFO", reason=f"어느 공종인지 알려 주세요: {names}" if names else result["reason"])
    else:
        update.update(status="EVIDENCE_ONLY", reason=result["reason"])
    return update
