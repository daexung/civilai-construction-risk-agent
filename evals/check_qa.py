"""상담 노드 오프라인 검사. 외부 호출과 키 읽기 없음."""
import copy
import json
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["AGENT_LLM"] = "off"
os.environ["AGENT_OFFLINE"] = "1"
from backend.agent.nodes.answer import answer, validate, match_quote, TIMEOUT_MS
from backend.agent.nodes.qa_context import build_context, LIMIT, TOTAL_LIMIT, FIRST_LIMIT, load_sections, supplement_table
from backend.agent.graph import build_graph
from backend.agent.state import new_state
from evals.eval_qa import correct_section_cited, not_found_counts
from pipeline.chunk import has_label_shift


def main():
    checks = []
    def check(name, ok):
        checks.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name)
    check("grade source chunk division instead of display label", correct_section_cited(
        {"citations": [{"chunk_id": "p368-t0"}]}, ("토목", "1-5-4")))
    las = next(c for c in load_sections()[("건축", "9-1-5")] if c["chunk_id"] == "p681-t0")
    supplemented = supplement_table(las)
    check("broken p681 table supplemented from PDF", "0.14" in supplemented["pdf_text"] and
          "[p681-t0 원문텍스트 · 표 구조 불확실]" in supplemented["text"] and "pdf_text" not in las)
    without_bbox = copy.deepcopy(las); without_bbox["source"]["bbox"] = None
    section_text = supplement_table(without_bbox)["pdf_text"]
    check("PDF without bbox scoped to section", "0.14" in section_text and "9-2-1" not in section_text)
    las_qa = {"not_found": False, "conclusion": "미장공 0.14인입니다.", "explanation": "",
              "comparisons": [], "citations": [{"chunk_id": "p681-t0", "quote": "미장공 인 0.14"}]}
    check("PDF supplement accepted as same chunk citation", validate(las_qa, [{
        "section": "건축 9-1-5 라스 붙임", "section_no": "9-1-5", "chunks": [supplemented]}]) is None)
    synthetic = copy.deepcopy(las_qa); synthetic["conclusion"] = "681인입니다."
    check("supplement marker ID is not numerical evidence", validate(synthetic, [{
        "section": "건축 9-1-5 라스 붙임", "section_no": "9-1-5", "chunks": [supplemented]}]) == "numbers")
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
    repeated = copy.deepcopy(qa)
    repeated["comparisons"] = [{"section": one[0]["section"], "summary": "인원 2인 적용"}]
    deduplicated = run(repeated)
    check("single comparison matching first citation section is omitted from body",
          deduplicated["answer_source"] == "llm" and
          f"{one[0]['section']}: 인원 2인 적용" not in deduplicated["answer"])
    requests = []
    def fake(prompt, system, **options):
        requests.append((json.loads(prompt), system, options))
        return json.dumps(qa, ensure_ascii=False)
    answer(state, contexts=many, generate_fn=fake, model="review-model")
    check("three full contexts sent to model", len(requests[0][0]["sections"]) == 3 and "[주]" in requests[0][0]["sections"][0]["text"])
    check("model override and total budget", requests[0][2]["model"] == "review-model" and requests[0][2]["timeout_ms"] == TIMEOUT_MS)
    check("new context and timeout limits", LIMIT == 4000 and TIMEOUT_MS == 12000)
    limited = build_context(hits[:1], sections=long_sections, specs=specs, limit=LIMIT)
    check("default context bounded and notes retained", limited[0]["truncated"] and len(limited[0]["text"]) <= 4000 and "[주]" in limited[0]["text"] and "비고" in limited[0]["text"])
    tower = build_context([{"rank": 1, "division": "기계설비", "section_no": "8-1-3",
        "section": "8-1-3 냉각탑 설치", "chunk_id": "p746-t0"}], specs={},
        query="냉각탑 용량이 100이고 5층 건물 옥상에 1회 설치할 때 품은?")
    fifth = next(c for c in tower[0]["chunks"] if c["chunk_id"] == "p747-t0")
    check("5 floor cooling tower uses PDF text only", "11" in fifth.get("pdf_text", "") and
          "원문텍스트 · 이름 줄 밀림" in fifth["text"] and "구분 100 | 비계공" not in fifth["text"] and
          "구분 100 | 특별인부" not in fifth["text"])
    parsed_rows = [json.loads(line) for line in (ROOT / "data/processed/parsed.all.jsonl").read_text(encoding="utf-8").splitlines()
                   if line.strip() and json.loads(line).get("table_id") == "p747-t0"]
    check("same group duplicate labels plus unnamed numeric row flagged", has_label_shift(parsed_rows))
    check("equal named values without unnamed row stay valid", not has_label_shift([r for r in parsed_rows if not re.search(r"\|\s*\d+회\s", r["text"])]))
    check("first section within 8000 characters", 0 < len(tower[0]["text"]) <= FIRST_LIMIT and FIRST_LIMIT == 8000)
    large_sections = copy.deepcopy(sections)
    for group in large_sections.values():
        group[0]["text"] = "내용 2인 " * 2000
    distributed = build_context(hits, sections=large_sections, specs=specs, query="내용 품")
    check("three section total within 12000", len(distributed) == 3 and sum(len(c["text"]) for c in distributed) <= TOTAL_LIMIT and TOTAL_LIMIT == 12000)
    with patch("backend.agent.nodes.answer.time.monotonic", side_effect=[0, 0, 12.001, 12.001]):
        timed = run(qa)
    check("late LLM response replaced by template", timed["answer_source"] == "template" and timed["llm_info"]["error"] == "timeout")
    spaced = copy.deepcopy(qa); spaced["citations"][0]["quote"] = "인원  2인\n적용"
    check("quote whitespace normalized", run(spaced)["answer_source"] == "llm")
    table_context = copy.deepcopy(one)
    table_context[0]["chunks"][0]["text"] = "콘크리트공 | 단위 인 | 작업조 철근콘크리트 4"
    table_qa = copy.deepcopy(qa)
    table_qa.update(conclusion="콘크리트공 4인", citations=[{
        "chunk_id": "p1-x0", "quote": "콘크리트공 인 작업조 철근콘크리트 4"}])
    out = run(table_qa, table_context)
    check("table separators and headers normalized", out["answer_source"] == "llm" and
          out["qa"]["citations"][0]["quote"] == table_context[0]["chunks"][0]["text"])
    check("fuzzy 0.84 fails", match_quote("가" * 84 + "나" * 16, "가" * 100) is None)
    check("fuzzy 0.86 passes", match_quote("가" * 86 + "나" * 14, "가" * 100) == ("fuzzy", "가" * 100))
    fuzzy_context = copy.deepcopy(one)
    fuzzy_context[0]["chunks"][0]["text"] = "가" * 100
    fuzzy_qa = copy.deepcopy(qa)
    fuzzy_qa.update(conclusion="기준을 확인했습니다.", citations=[{
        "chunk_id": "p1-x0", "quote": "가" * 86 + "나" * 14}])
    out = run(fuzzy_qa, fuzzy_context)
    check("fuzzy records match and displays original", out["answer_source"] == "llm" and
          out["qa"]["citations"][0]["quote_match"] == "fuzzy" and
          out["qa"]["citations"][0]["quote"] == "가" * 100 and "나" not in out["answer"])
    question_qa = copy.deepcopy(qa)
    question_qa["conclusion"] = "시공량 123인 기준입니다."
    question_state = {**state, "query": "시공량 123인 기준 품 알려줘"}
    out = answer(question_state, contexts=one, generate_fn=lambda *a, **k: json.dumps(question_qa, ensure_ascii=False))
    check("question numbers allowed", out["answer_source"] == "llm")
    fallback_context = copy.deepcopy(one)
    fallback_context[0]["chunks"][0].update(kind="table", section="6-1-1 공종", text=
        "6-1-1 공종\n설명 | 단위 | 수량\n보통인부 | 단위 인 | 수량 3\n콘크리트공 | 단위 인 | 수량 2\n콘크리트공 | 단위 인 | 수량 2")
    fallback_context[0]["chunks"][1]["text"] = fallback_context[0]["chunks"][0]["text"]
    out = answer({"query": "콘크리트공 품", "hits": hits}, contexts=fallback_context)
    quotes = [c["quote"] for c in out["qa"]["citations"]]
    check("fallback shows content instead of heading", quotes and all(not q.startswith("6-1-1") and q != "설명 | 단위 | 수량" for q in quotes))
    check("fallback prioritizes overlapping table row", quotes[0] == "콘크리트공 | 단위 인 | 수량 2")
    check("fallback deduplicates content and combined answer", len(quotes) == len(set(quotes)) and
          all(out["answer"].count(q) == 1 for q in quotes) and out["answer"].count(fallback_context[0]["section"]) == 1)
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
    bad = copy.deepcopy(qa); bad["not_found"] = True; bad["conclusion"] = "999 기준 없음"; out = run(bad, many)
    check("not found normalized without citations", out["qa"]["not_found"] and not out["qa"]["citations"] and "999" not in out["answer"])
    check("weak candidates mean section not found", out["qa"]["not_found_kind"] == "section_not_found")
    missing = run(bad)
    check("chosen section value missing keeps two source lines", missing["qa"]["not_found_kind"] == "section_found_value_missing" and
          "질문하신 조건의 값" in missing["answer"] and len(missing["qa"]["citations"]) == 2)
    no_spec = build_context(hits[:1], sections=sections, specs={})
    missing_no_spec = run(bad, no_spec)
    check("dominant section without spec means value missing", missing_no_spec["qa"]["not_found_kind"] == "section_found_value_missing")
    check("evaluation counts not found kinds", not_found_counts([out, missing, missing_no_spec]) == {
        "section_not_found": 1, "section_found_value_missing": 2})
    for phrase in ("금지되어", "지시", "규칙상", "제공된 문맥", "원문에 직접 곱셈", "곱하거나", "환산하지", "주의하여", "안내합니다", "제시된 자료", "주어진 원문"):
        leaked = copy.deepcopy(qa); leaked["explanation"] = phrase + " 답변합니다."
        leak_out = run(leaked)
        check("instruction leakage rejected: " + phrase, leak_out["answer_source"] == "template" and leak_out["llm_info"]["error"] == "instruction_leak")
    check("empty candidates skip llm", answer(state, contexts=[], generate_fn=lambda *a, **k: (_ for _ in ()).throw(AssertionError()))["qa"]["not_found"])
    check("bad JSON fallback", answer(state, contexts=one, generate_fn=lambda *a, **k: "bad")["llm_info"]["error"] == "JSONDecodeError")
    check("bad schema fallback", run({})["llm_info"]["error"] == "schema")
    with patch("backend.agent.nodes.answer.client.generate", side_effect=AssertionError("external call")):
        check("off skips client", answer(state, contexts=one)["answer_source"] == "template")
    with patch("backend.agent.graph.route", return_value={"route": "qa"}), patch("backend.agent.graph.retrieve", return_value={"hits": hits}), patch("backend.agent.graph.select", side_effect=AssertionError("select called")), patch("backend.agent.nodes.answer.build_context", return_value=one):
        graph = build_graph()
        output = graph.invoke(new_state("품 알려줘"), {"configurable": {"thread_id": "qa-check"}})
        check("qa graph ANSWERED and no select", output["status"] == "ANSWERED" and not output.get("result"))
    from backend.api.main import _build_response
    response = _build_response("qa", answer(state, contexts=real))
    check("API resolves label image and chunk id", bool(response["qa"]["citations"]) and all(c["label"] and c["image_url"] and c["chunk_id"] for c in response["qa"]["citations"]))
    print(f"통과 {sum(checks)} / 전체 {len(checks)}")
    return 0 if all(checks) else 1
if __name__ == "__main__":
    raise SystemExit(main())
