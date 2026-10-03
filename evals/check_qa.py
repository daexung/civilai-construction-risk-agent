"""상담 노드 오프라인 검사. 외부 호출과 키 읽기 없음."""
import copy
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AGENT_LLM"] = "off"
os.environ["AGENT_OFFLINE"] = "1"
from agent.nodes.answer import answer, validate
from agent.nodes.qa_context import build_context
from agent.graph import build_graph
from agent.state import new_state
from evals.eval_qa import correct_section_cited


def main():
    checks = []
    def check(name, ok):
        checks.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name)
    check("grade source chunk division instead of display label", correct_section_cited(
        {"citations": [{"chunk_id": "p368-t0"}]}, ("토목", "1-5-4")))
    check("grade explicit comparison or conclusion", all(correct_section_cited(value, ("토목", "1-5-4"), chunks={}) for value in (
        {"comparisons": [{"section": "토목 1-5-4 아스팔트 기층", "summary": "기준 적용"}]},
        {"conclusion": "토목 1-5-4 기준을 적용합니다."})))
    check("grade rejects different division and partial section", not any(correct_section_cited(value, ("토목", "1-5-4"), chunks={}) for value in (
        {"conclusion": "건축 1-5-4 기준"}, {"conclusion": "토목 1-5-40 기준"},
        {"citations": [{"chunk_id": "missing"}]})))
    sections, hits = {}, []
    for i in range(1, 5):
        no = f"6-1-{i}"
        chunks = [{"chunk_id": f"p{i}-x{j}", "division": "공통", "section_no": no,
                   "section": no + " 공종", "source": {"page": i}, "text": text}
                  for j, text in enumerate(("인원 2인 적용", "[주] 조건 3일", "비고 적용 기준"))]
        sections[("공통", no)] = chunks
        hits.append({"rank": i, "division": "공통", "section_no": no, "section": no + " 공종", "chunk_id": chunks[0]["chunk_id"]})
    specs = {("공통", "6-1-1"): [{"title": "공통", "id": "test"}]}
    one = build_context(hits[:1], sections=sections, specs=specs)
    many = build_context(hits, sections=sections, specs=specs)
    check("chosen one section", len(one) == 1)
    check("provisional three sections", len(many) == 3)
    check("notes and remarks in page order", "[주]" in one[0]["text"] and "비고" in one[0]["text"] and [c["chunk_id"] for c in one[0]["chunks"]] == ["p1-x0", "p1-x1", "p1-x2"])
    check("division boundary", len(one[0]["chunks"]) == 3)
    long_sections = copy.deepcopy(sections)
    long_sections[("공통", "6-1-1")][0]["text"] = "인원 2인 " * 1500
    short = build_context(hits[:1], sections=long_sections, specs=specs, limit=200)
    check("bounded and marked truncation", short[0]["truncated"] and len(short[0]["text"]) <= 200)
    check("truncated context retains notes", "[주]" in short[0]["text"] and "비고" in short[0]["text"])
    # Real section grouping must also retain notes beyond the retrieved snippet.
    real = build_context([{"rank": 1, "division": "공통", "section_no": "6-1-4", "section": "6-1-4", "chunk_id": "p186-x16"}])
    check("real source record order", [c["chunk_id"] for c in real[0]["chunks"]][:3] == ["p186-x6", "p186-t1", "p186-x16"])
    check("real section context", bool(real[0]["chunks"]) and real[0]["text"])
    qa = {"not_found": False, "conclusion": "인원 2인 적용", "explanation": "조건을 확인하세요.", "comparisons": [], "citations": [{"chunk_id": "p1-x0", "quote": "인원 2인 적용"}]}
    state = {"query": "품 알려줘", "hits": hits}
    def run(value, contexts=one):
        return answer(state, contexts=contexts, generate_fn=lambda *a, **k: json.dumps(value, ensure_ascii=False))
    check("valid uses llm", run(qa)["answer_source"] == "llm")
    requests = []
    def fake(prompt, system, **options):
        requests.append((json.loads(prompt), system, options))
        return json.dumps(qa, ensure_ascii=False)
    answer(state, contexts=many, generate_fn=fake, model="review-model")
    check("three full contexts sent to model", len(requests[0][0]["sections"]) == 3 and "[주]" in requests[0][0]["sections"][0]["text"])
    check("model override and total budget", requests[0][2]["model"] == "review-model" and requests[0][2]["timeout_ms"] == 15000)
    spaced = copy.deepcopy(qa); spaced["citations"][0]["quote"] = "인원  2인\n적용"
    check("quote whitespace normalized", run(spaced)["answer_source"] == "llm")
    bad = copy.deepcopy(qa); bad["comparisons"] = [{"section": "공통 6-1-1", "summary": "999인"}]
    check("comparison numbers checked", run(bad)["llm_info"]["error"] == "numbers")
    multi = copy.deepcopy(qa); multi["comparisons"] = [{"section": c["section"], "summary": "인원 2인 적용"} for c in many]
    check("multiple comparisons accepted", run(multi, many)["answer_source"] == "llm")

    changes = [("numbers", "conclusion", "인원 999인"), ("money", "conclusion", "2원"),
               ("money", "conclusion", "만원"), ("money", "conclusion", "₩2"),
               ("section", "explanation", "6-1-9 기준")]
    for error, field, value in changes:
        bad = copy.deepcopy(qa); bad[field] = value; out = run(bad)
        check(error + " fallback " + value, out["answer_source"] == "template" and out["llm_info"]["error"] == error)
    for error, citation in [("chunk_id", {"chunk_id": "missing", "quote": "공통"}), ("quote", {"chunk_id": "p1-x0", "quote": "다른 문장"}), ("quote", {"chunk_id": "p1-x0", "quote": " "}), ("money", {"chunk_id": "p1-x0", "quote": "2원"})]:
        bad = copy.deepcopy(qa); bad["citations"] = [citation]; out = run(bad)
        check(error + " citation fallback", out["answer_source"] == "template" and out["llm_info"]["error"] == error)
    bad = copy.deepcopy(qa); bad["citations"] = []
    check("requires citation", run(bad)["llm_info"]["error"] == "citations_missing")
    bad = copy.deepcopy(qa); bad["not_found"] = True; bad["conclusion"] = "999 기준 없음"; out = run(bad)
    check("not found normalized without citations", out["qa"]["not_found"] and not out["qa"]["citations"] and "999" not in out["answer"])
    check("empty candidates skip llm", answer(state, contexts=[], generate_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError()))["qa"]["not_found"])
    check("bad JSON fallback", answer(state, contexts=one, generate_fn=lambda *a, **k: "bad")["llm_info"]["error"] == "JSONDecodeError")
    check("bad schema fallback", run({})["llm_info"]["error"] == "schema")
    with patch("agent.nodes.answer.client.generate", side_effect=AssertionError("external call")):
        check("off skips client", answer(state, contexts=one)["answer_source"] == "template")
    with patch("agent.graph.route", return_value={"route": "qa"}), patch("agent.graph.retrieve", return_value={"hits": hits}), patch("agent.graph.select", side_effect=AssertionError("select called")), patch("agent.nodes.answer.build_context", return_value=one):
        graph = build_graph()
        output = graph.invoke(new_state("품 알려줘"), {"configurable": {"thread_id": "qa-check"}})
        check("qa graph ANSWERED and no select", output["status"] == "ANSWERED" and not output.get("result"))
    from api.main import _build_response
    response = _build_response("qa", answer(state, contexts=real))
    check("API resolves label image and chunk id", bool(response["qa"]["citations"]) and all(c["label"] and c["image_url"] and c["chunk_id"] for c in response["qa"]["citations"]))
    print(f"통과 {sum(checks)} / 전체 {len(checks)}")
    return 0 if all(checks) else 1
if __name__ == "__main__":
    raise SystemExit(main())
