"""v2 상담 길 오프라인 시험(모델·DB 호출 0): Q1 합치기, Q3 근거 검사, 계산 질문 갈래, 상담 연결."""
from backend.agent.estimate import dialogue as d
from backend.agent.v2 import qa

CANDS = [
    {"alias": "C1", "chunk_id": "t1", "kind": "table", "status": "ok", "title": "공통부문 6-1-4 콘크리트 펌프차 타설",
     "frame": ["기준: (㎥당)"], "lines": {1: "붐 21m | 0.05", 2: "붐 32m | 0.06"}},
    {"alias": "C2", "chunk_id": "t2", "kind": "table", "status": "membership_unconfirmed", "title": "토목부문 터널 방수",
     "frame": [], "lines": {1: "방수공 | 0.1"}},
]


def pick(**kw):
    raw = {"picks": [{"candidate": "C1", "lines": ["C1.1", "C1.2"], "role": "answer"}],
           "target_match": [{"target": "펌프카 타설", "candidate": "C1", "source_term": "콘크리트 펌프차 타설", "same_thing": "yes"}],
           "missing_conditions": [], "no_answer_reason": "none"}
    raw.update(kw)
    return qa.check_pick(raw, CANDS)


def test_supported_when_term_is_in_source():
    c = pick()
    assert c["status"] == "supported" and c["answer"] == {"t1": [1, 2]} and not c["reasons"]
    assert qa.answer_question({"message": "펌프카 타설 품 얼마임"}, c) == "콘크리트 펌프차 타설 품 얼마임"


def test_fake_lines_and_candidates_are_dropped():
    fake = [{"candidate": "C9", "lines": ["C9.1"], "role": "answer"},
            {"candidate": "C1", "lines": ["C1.7", "C2.1", "1"], "role": "answer"}]
    c = pick(picks=fake, target_match=[])
    assert c["status"] == "not_found" and len(c["dropped"]) == 4
    c = pick(picks=fake)  # 가짜 줄은 버리지만, Q2가 대상으로 짚은 C1은 남긴다
    assert len(c["dropped"]) == 4 and c["answer"] == {"t1": [1, 2]}


def test_invented_source_term_needs_confirmation_text():
    c = pick(target_match=[{"target": "펌프카", "candidate": "C1", "source_term": "펌프카 장비", "same_thing": "yes"}])
    assert c["status"] == "supported"  # 값은 답하되
    assert c["reasons"][0]["rule"] == "target_term_unconfirmed"  # 같은 대상인지 확인을 붙인다
    assert qa.answer_question({"message": "q"}, c) == "q"  # 확인 못 한 용어는 답 쓰기에 넘기지 않는다


def test_missing_condition_still_answers_with_ask():
    c = pick(missing_conditions=["붐 길이"])
    assert c["status"] == "supported"
    assert "붐 길이" in qa._confirm_asks(c)[0]["text"]


def test_different_target_is_not_found():
    c = pick(target_match=[{"target": "지붕 방수", "candidate": "C1", "source_term": "콘크리트 펌프차 타설", "same_thing": "no"}])
    assert c["status"] == "not_found" and not c["answer"]


def test_unconfirmed_table_membership_needs_confirmation():
    c = pick(picks=[{"candidate": "C2", "lines": ["C2.1"], "role": "answer"}],
             target_match=[{"target": "방수", "candidate": "C2", "source_term": "방수", "same_thing": "yes"}])
    assert c["status"] == "needs_confirmation"


def test_merge_hits_and_request():
    assert qa.merge_hits([["a", "b"], ["b", "c"]], 2) == ["b", "a"]
    r = qa.qa_request("m", [{"target": {"user_text": "펌프카", "evidence": "펌프카", "search_terms": ["콘크리트 펌프차"]},
                             "conditions": [], "asks": "품"}])
    assert qa.queries_of(r) == ["콘크리트 펌프차", "품"]
    assert qa.queries_of(qa.qa_request("m", [])) == ["m"]


def _req(kind, wants, quantity):
    return {"kind": kind, "estimate_mode": "none" if kind == "qa" else "new", "wants": wants, "asks": "",
            "target": {"user_text": "방수", "evidence": "방수", "search_terms": ["방수"]},
            "quantity": {"value": "200", "unit": "㎡", "evidence": "200㎡"} if quantity else None,
            "conditions": [], "card_answer": None}


def test_calculation_question_goes_to_estimate_for_labor():
    msg = "방수 200㎡ 몇 명 며칠"
    out = {"route": "work", "requests": [_req("qa", "calculate", True)]}
    res = {"status": "ok", "output": out}
    assert d._v2_label(res) == "estimate"
    token = d._V2_LABEL.set((msg, "estimate", out))
    try:
        plan = d._v2_plan(msg)
        assert plan["goal"] == "labor" and plan["items"][0]["request_text"] == "방수 200㎡"
        assert d._v2_qa_requests(msg) == []
    finally:
        d._V2_LABEL.reset(token)


def test_value_question_stays_qa_and_mixed_is_cost():
    out = {"route": "work", "requests": [_req("qa", "value", False)]}
    assert d._v2_label({"status": "ok", "output": out}) == "qa"
    token = d._V2_LABEL.set(("m", "qa", out))
    try:
        assert len(d._v2_qa_requests("m")) == 1 and d._v2_plan("m") is None
    finally:
        d._V2_LABEL.reset(token)
    mixed = {"route": "work", "requests": [_req("qa", "calculate", True), _req("estimate", "calculate", True)]}
    token = d._V2_LABEL.set(("m", "estimate", mixed))
    try:
        assert d._v2_plan("m")["goal"] == "cost"
    finally:
        d._V2_LABEL.reset(token)


def test_answer_prompt_examples_pass_q5_check():
    """새 Q4 지시문의 예시 출력이 Q5 숫자·위치 검사를 통과하는지(지시문과 검사가 어긋나지 않게)."""
    import json, re
    from backend.api import local_trial_answer as ta
    p = qa._qa_prompt()
    line = {"n": 1, "text": "점검공 | 단위 인 | 소형 0.8 | 대형 1.6", "display": "점검공 | 단위 인 | 소형 0.8 | 대형 1.6", "page": 1, "search_uid": None}
    provided = {"S1": {"chunk_id": "x", "kind": "표", "frame": ["기준: (개소당)", "머리글: 구분 | 단위 | 소형 | 대형"],
                       "label": "", "n_total": 1, "lines": {1: line}}}
    examples = re.findall(r'질문: "([^"]+)"\n출력: (\{.*\})', p)
    assert len(examples) == 4
    states = [ta.validate(json.loads(out), q, provided)["state"] for q, out in examples]
    assert states == ["answered", "answered", "answered", "condition_unconfirmed"], states


def test_named_candidate_is_kept_when_lines_are_empty():
    c = pick(picks=[], target_match=[{"target": "펌프카", "candidate": "C1", "source_term": "콘크리트 펌프차", "same_thing": "unsure"}])
    assert c["status"] == "supported" and c["answer"] == {"t1": [1, 2]}
    assert c["reasons"][0]["rule"] == "target_term_unconfirmed"
    c = pick(picks=[], target_match=[{"target": "펌프카", "candidate": "C1", "source_term": "없는 말", "same_thing": "yes"}])
    assert c["status"] == "not_found"  # 원문에 없는 용어로 짚은 후보는 쓰지 않는다
