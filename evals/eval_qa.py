"""검토자용 실제 상담 채점. run_quick에서는 실행하지 않는다."""
import argparse
import json
import os
import random
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.rules.scope import enabled_divisions
from agent.nodes.retrieve import retrieve
from agent.nodes.answer import answer, qa_model
from agent.nodes.qa_context import load_sections

AMBIGUOUS = ['콘크리트 타설할 때 콘크리트공 품이 얼마야?', '거푸집 설치 해체 품 알려줘', '철근 가공 조립 품은 어떻게 돼?', '보도블록 깔 때 품이 어떻게 돼?', '도장 공사 품은 어떻게 잡아?']
SEED = 191

def correct_section_cited(qa, expected, *, chunks=None):
    """원본 청크의 부문·절 또는 답변의 명시적인 부문·절 표기를 판정한다."""
    division, section_no = expected
    if not division or not section_no:
        return None
    if chunks is None:
        chunks = {c["chunk_id"]: c for group in load_sections().values() for c in group}
    for cite in qa.get("citations", []):
        chunk = chunks.get(cite.get("chunk_id"), {})
        if (chunk.get("division"), chunk.get("section_no")) == expected:
            return True
    text = "\n".join([qa.get("conclusion", "")] + [
        c.get("section", "") + " " + c.get("summary", "") for c in qa.get("comparisons", [])])
    return bool(re.search(rf"(?<![가-힣]){re.escape(division)}\s+{re.escape(section_no)}(?![\d-])", text))


def evaluate(cases, model):
    rows = []
    for case in cases:
        start = time.monotonic()
        state = {"query": case["question"]}
        state.update(retrieve(state))
        result = answer(state, model=model)
        expected = (case.get("division"), case.get("section_no"))
        correct = correct_section_cited(result["qa"], expected)
        rows.append({"id": case["id"], "question": case["question"], "expected": expected,
                     "correct_section_cited": correct, "latency_ms": round((time.monotonic()-start)*1000, 1),
                     "search": state["search_info"], "candidate_count": len(result["candidates"]),
                     "comparison_filled": bool(result["qa"]["comparisons"]), **result})
    return rows

def not_found_counts(rows):
    return {kind: sum(r["qa"].get("not_found", False) and
                     r["qa"].get("not_found_kind", "section_not_found") == kind for r in rows)
            for kind in ("section_not_found", "section_found_value_missing")}
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=qa_model())
    args = parser.parse_args()
    if os.environ.get("AGENT_LLM") != "on":
        parser.error("실제 채점은 AGENT_LLM=on으로 실행하세요")
    enabled = set(enabled_divisions())
    pool = [json.loads(line) for line in (ROOT / "evals/scope_sample.jsonl").read_text(encoding="utf-8").splitlines() if line]
    pool = [c for c in pool if c["division"] in enabled]
    cases = random.Random(SEED).sample(pool, 30)
    rows = evaluate(cases, args.model)
    ambiguous = evaluate([{"id": f"ambiguous-{i}", "question": q} for i, q in enumerate(AMBIGUOUS, 1)], args.model)
    summary = {"count": len(rows), "correct_section_citation_rate": sum(r["correct_section_cited"] for r in rows)/len(rows),
               "safety_pass_rate": sum(r["answer_source"] == "llm" for r in rows)/len(rows),
               "not_found_rate": sum(r["qa"]["not_found"] for r in rows)/len(rows),
               "mean_latency_ms": sum(r["latency_ms"] for r in rows)/len(rows),
               "max_latency_ms": max(r["latency_ms"] for r in rows),
               "ambiguous_comparison_pass": sum(r["candidate_count"] >= 2 and r["comparison_filled"] and r["answer_source"] == "llm" for r in ambiguous)}
    summary["not_found_kind_counts"] = not_found_counts(rows)
    stamp = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    results = ROOT / "evals/results"; results.mkdir(exist_ok=True)
    model_slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", args.model)
    path = results / f"qa_{model_slug}_{stamp}.json"
    path.write_text(json.dumps({"model": args.model, "seed": SEED, "enabled_divisions": sorted(enabled), "summary": summary, "items": rows, "ambiguous": ambiguous}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    review = results / f"qa_review_{stamp}.md"
    old = review.read_text(encoding="utf-8") if review.exists() else "# 상담 답변 사람 검토\n"
    marker = f"## {args.model}\n"
    if marker in old:
        start = old.index(marker); end = old.find("\n## ", start+len(marker)); old = old[:start]+(old[end:] if end >= 0 else "")
    text = marker
    for r in rows[:10]:
        text += f"\n### {r['id']} · {r['question']}\n\n정답 절: {r['expected']} · 출처: {r['answer_source']} · 오류: {r['llm_info']['error']}\n\n{r['answer']}\n"
        for c in r["qa"]["citations"]:
            text += f"\n- [{c['chunk_id']}] {c['quote']}\n"
    review.write_text(old.rstrip()+"\n\n"+text, encoding="utf-8")
    print("| 지표 | 결과 |\n|---|---|")
    for key, value in summary.items():
        if isinstance(value, dict):
            for kind, count in value.items(): print(f"| {key}.{kind} | {count} |")
        else:
            print(f"| {key} | {value} |")
    print(path); print(review)
    print("\n| 비교 질문 | 후보 | LLM 비교 |\n|---|---:|---|")
    for r in ambiguous: print(f"| {r['question']} | {r['candidate_count']} | {r['comparison_filled'] and r['answer_source'] == 'llm'} |")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
