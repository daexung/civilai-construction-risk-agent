"""v2 라우터 실제 호출 점검: router_testset.jsonl 46문.

실행: $env:AGENT_LLM='on'; .venv/Scripts/python.exe -m evals.run_v2_router_live
비교: work+estimate→estimate, work+qa만→qa, out_of_scope→out_of_scope. clarify는 따로 센다.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

from backend.agent.v2.router import route_turn

load_dotenv(".env")
ROOT = Path(__file__).parent


def to_label(res: dict) -> str:
    if res["status"] != "ok":
        return res["status"]
    out = res["output"]
    if out["route"] != "work":
        return out["route"]
    return "estimate" if any(q["kind"] == "estimate" for q in out["requests"]) else "qa"


def main():
    rows = [json.loads(x) for x in (ROOT / "router_testset.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    tally, calls, misses, detail = Counter(), 0, [], []
    for row in rows:
        ctx = row.get("context")
        previous = None
        if ctx:  # 시험 세트의 예전 맥락 모양을 v2 입력으로 옮긴다
            previous = {"kind": "estimate_result" if ctx.get("previous_route") == "estimate" else "qa_answer",
                        "work": ctx.get("work"), "last_answer_summary": str(ctx.get("result", ""))}
        res = route_turn(row["q"], previous)
        got = to_label(res)
        calls += res["calls_used"]
        if res["output"]:
            tally.update(f"wants:{q['kind']}.{q['wants']}" for q in res["output"]["requests"])
        tally["match" if got == row["label"] else got if got in ("clarify", "output_error", "failed") else "wrong"] += 1
        if got != row["label"]:
            misses.append({"id": row["id"], "q": row["q"], "want": row["label"], "got": got,
                           "errors": res["errors"][:2]})
        detail.append({"id": row["id"], "q": row["q"], "boundary": row.get("boundary", False),
                       "has_context": bool(ctx), "want": row["label"], "got": got,
                       "calls": res["calls_used"], "output": res["output"]})
    if len(sys.argv) > 1:  # 문항별 결과 저장: python -m evals.run_v2_router_live out.json
        Path(sys.argv[1]).write_text(json.dumps(detail, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"total": len(rows), **tally, "ai_calls": calls}, ensure_ascii=False))
    for m in misses:
        print(json.dumps(m, ensure_ascii=False))


if __name__ == "__main__":
    main()
