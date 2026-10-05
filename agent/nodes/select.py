"""검색 순위로 작업 절을 고른다."""

from agent.rules.specs import specs_by_section
from agent.state import AgentState


# check_select.py 하이브리드 34문항: 4.0은 오답 0·되묻기 20, 3.0은 오답 2.
MARGIN = 4.0


def decide(hits: list[dict], specs: dict[tuple[str, str], list[dict]], margin: float = MARGIN) -> dict:
    """청크 순위와 명세 목록으로 결정·후보·이유를 돌려준다."""
    by_section: dict[tuple[str | None, str], dict] = {}
    for hit in hits:
        section_no = hit.get("section_no")
        if not section_no or section_no.count("-") != 2:
            continue
        division = hit.get("division", "공통")  # Old saved 6장 hits predate this field.
        key = (division, section_no)
        group = by_section.setdefault(key, {
            "division": division, "section_no": section_no,
            "section": (f"{division} {section_no} {specs[key][0]['title']}" if specs.get(key)
                        else f"{division} {hit['section']}" if division else hit["section"]),
            "score": 0.0, "has_spec": bool(specs.get(key)),
        })
        group["score"] += 1 / hit["rank"]

    candidates = sorted(by_section.values(), key=lambda group: (-group["score"],
                        group["division"] or "", group["section_no"]))[:3]
    if not candidates:
        return {"decision": "ask", "candidates": [], "reason": "작업 절을 찾지 못했습니다"}

    first = candidates[0]
    second = candidates[1] if len(candidates) > 1 else None
    if second and first["score"] < margin * second["score"]:
        return {"decision": "provisional", "confirmed": False, "candidates": candidates,
                "reason": f"상위 절 {first['section']}와 {second['section']}의 검색 점수가 비슷합니다",
                "spec_id": specs[(first["division"], first["section_no"])][0]["id"] if first["has_spec"] else ""}
    if not first["has_spec"]:
        return {"decision": "no_spec", "confirmed": True, "candidates": candidates,
                "reason": f"{first['section']} 절의 계산 명세가 없습니다"}
    return {"decision": "chosen", "confirmed": True, "candidates": candidates,
            "reason": f"{first['section']} 절의 검색 점수가 가장 높습니다",
            "spec_id": specs[(first["division"], first["section_no"])][0]["id"]}


def select(state: AgentState) -> dict:
    result = decide(state["hits"], specs_by_section())
    decision = result["decision"]
    update = {"candidates": result["candidates"],
              "selection": {"decision": decision, "confirmed": result.get("confirmed", False),
                            "reason": result["reason"]}}
    if decision in ("chosen", "provisional"):
        update["spec_id"] = result["spec_id"]
    elif decision == "ask":
        names = ", ".join(item["section"] for item in result["candidates"])
        update.update(status="MISSING_INFO", reason=f"어느 공종인지 알려 주세요: {names}" if names else result["reason"])
    else:
        update.update(status="EVIDENCE_ONLY", reason=result["reason"])
    return update
