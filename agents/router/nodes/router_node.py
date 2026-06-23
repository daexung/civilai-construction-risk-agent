"""라우터 노드 — intent 분류 후 Command로 다음 노드에 핸드오프"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..')))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from langchain_core.messages import HumanMessage, AIMessage
from langgraph.graph import END
from langgraph.types import Command
from router import classify_question
from common.security import check_injection, BLOCKED_RESPONSE
from logger import get_logger

log = get_logger(__name__)

# ── 표준품셈 RAG 검색 (LOOKUP/standard_spec 경로) ────────────────────

_LIST_QUERY_TERMS = (
    "리스트", "목록", "가지고 있는", "보유", "전체 항목", "등록된", "보유 중",
    "전체 알려", "전체 보여",
)


def _detect_rag_source(query: str) -> str:
    if any(term in query for term in ("시방서", "표준시방서")):
        return "standard_specification"
    if any(term in query for term in ("계약", "특약", "계약서")):
        return "contract"
    return "standard_spec"


def _detect_rag_query_type(query: str) -> str:
    return "list_items" if any(term in query for term in _LIST_QUERY_TERMS) else "item_search"


def _build_rag_query(query: str) -> str:
    cleaned = query
    remove_terms = (
        "표준품셈에서", "표준품셈", "품셈", "표준시방서", "시방서",
        "계약 기준", "계약서", "계약", "특약", "기준", "근거",
        "알려줘", "알려 주세요", "알려주세요", "찾아줘", "찾아 주세요",
        "찾아주세요", "보여줘", "보여 주세요", "보여주세요", "항목", "공종",
        "리스트", "목록", "현재", "가지고 있는", "보유 중인", "보유", "전체",
        "기준들을", "들을", "에서",
    )
    for term in remove_terms:
        cleaned = cleaned.replace(term, " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    compact = cleaned.replace(" ", "")
    if "철골세우기" in compact or "철골" in cleaned:
        return "철골 세우기"
    if "콘크리트" in cleaned and "타설" in cleaned:
        return "콘크리트 타설"
    return cleaned or query


def _extract_keywords(search_query: str) -> list[str]:
    stopwords = {
        "표준품셈", "품셈", "기준", "근거", "알려줘", "찾아줘", "항목", "공종",
        "리스트", "목록", "현재", "가지고", "있는", "보유", "전체", "들을",
        "를", "을", "은", "는", "이", "가",
    }
    return [
        token
        for token in re.split(r"\s+", search_query.strip())
        if token and token not in stopwords and len(token) > 1
    ]


def _extract_rag_item_name(content: str) -> str | None:
    for line in content.splitlines():
        clean = line.strip()
        if not clean or clean.startswith("[주의"):
            continue
        return clean
    return None


def _is_keyword_relevant(search_query: str, content: str, item_name: str | None) -> bool:
    keywords = _extract_keywords(search_query)
    if not keywords:
        return False
    haystack = f"{item_name or ''}\n{content}"
    item_text = item_name or ""
    matched_in_all = [k for k in keywords if k in haystack]
    matched_in_item = [k for k in keywords if k in item_text]
    if len(matched_in_item) == len(keywords):
        return True
    return len(matched_in_all) == len(keywords)


def _list_standard_spec_items(limit: int = 50) -> dict:
    from agents.labor_cost.tools import _get_pg_connection

    conn = _get_pg_connection()
    cur = conn.cursor()
    cur.execute("SELECT content FROM rag.standard_spec LIMIT %s", [limit * 3])
    rows = cur.fetchall()
    cur.close()
    conn.close()

    items = []
    seen = set()
    for idx, (content,) in enumerate(rows, start=1):
        item_name = _extract_rag_item_name(str(content))
        if not item_name or item_name in seen:
            continue
        seen.add(item_name)
        items.append({
            "document": "2026 건설공사 표준품셈",
            "item_name": item_name,
            "page": None,
            "chunk_id": f"row_{idx}",
        })
        if len(items) >= limit:
            break

    return {
        "status": "success",
        "rag_query_type": "list_items",
        "rag_source": "standard_spec",
        "query": "",
        "search_query": "",
        "content": "",
        "items": items,
        "evidence": [],
    }


def _search_standard_spec_for_rag(query: str) -> dict:
    rag_source = _detect_rag_source(query)
    rag_query_type = _detect_rag_query_type(query)
    rag_query = _build_rag_query(query)

    if rag_source != "standard_spec":
        label = "표준시방서" if rag_source == "standard_specification" else "계약 기준"
        return {
            "status": "not_available",
            "rag_query_type": rag_query_type,
            "rag_source": rag_source,
            "query": rag_query,
            "search_query": rag_query,
            "content": "",
            "evidence": [],
            "message": f"현재 {label} RAG 문서는 연결되어 있지 않습니다.",
        }

    if rag_query_type == "list_items":
        try:
            return _list_standard_spec_items()
        except Exception as e:
            log.exception(f"RAG_QA 표준품셈 목록 조회 실패: {e}")
            return {
                "status": "error",
                "rag_query_type": "list_items",
                "rag_source": rag_source,
                "query": "",
                "search_query": "",
                "content": "",
                "items": [],
                "evidence": [],
                "warnings": [f"표준품셈 항목 목록 조회 실패: {e}"],
            }

    log.info(f"RAG_QA 표준품셈 검색 실행: query={rag_query!r}")

    try:
        from agents.labor_cost.tools import _get_pg_connection, embedder

        query_vector = embedder.embed_query(rag_query)
        conn = _get_pg_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT content, embedding <=> %s::vector AS distance
            FROM rag.standard_spec
            ORDER BY distance
            LIMIT 5
        """, [query_vector])
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return {
                "status": "no_result",
                "rag_query_type": "item_search",
                "rag_source": rag_source,
                "query": rag_query,
                "search_query": rag_query,
                "distance": None,
                "content": "",
                "evidence": [],
            }

        selected = None
        for content, distance in rows:
            item_name = _extract_rag_item_name(str(content))
            if _is_keyword_relevant(rag_query, str(content), item_name):
                selected = (str(content), float(distance), item_name, True)
                break

        if selected is None:
            content, distance = rows[0]
            selected = (str(content), float(distance), _extract_rag_item_name(str(content)), False)

        content, distance, item_name, keyword_relevant = selected
        distance = float(distance)

        if distance <= 0.45:
            status = "success"
        elif keyword_relevant and distance <= 0.60:
            status = "success"
        elif keyword_relevant and item_name and all(k in item_name for k in _extract_keywords(rag_query)):
            status = "success"
        elif distance <= 0.60:
            status = "low_confidence"
        else:
            status = "no_result"

        if not keyword_relevant:
            status = "no_result"

        evidence = [] if status != "success" else [{
            "source": "rag.standard_spec",
            "document": "2026 건설공사 표준품셈",
            "item_name": item_name,
            "query": rag_query,
            "search_query": rag_query,
            "distance": distance,
            "chunk_id": "top_match",
            "page": None,
            "content": content[:1200],
            "type": "standard_spec",
        }]

        return {
            "status": status,
            "rag_query_type": "item_search",
            "rag_source": rag_source,
            "query": rag_query,
            "search_query": rag_query,
            "distance": distance,
            "keyword_relevant": keyword_relevant,
            "content": content if status == "success" else "",
            "candidate_preview": content[:300] if status == "low_confidence" else "",
            "evidence": evidence,
        }
    except Exception as e:
        log.exception(f"RAG_QA 표준품셈 검색 실패: {e}")
        return {
            "status": "error",
            "rag_query_type": rag_query_type,
            "rag_source": rag_source,
            "query": rag_query,
            "search_query": rag_query,
            "content": "",
            "evidence": [],
            "warnings": [f"표준품셈 RAG 검색 실패: {e}"],
        }


# ── LOOKUP 도메인별 핸들러 ─────────────────────────────────────────────

_KNOWN_JOB_TYPES = [
    "보통인부", "철근공", "콘크리트공", "형틀목공", "방수공", "철골공",
    "도장공", "미장공", "타일공", "비계공", "전기공", "배관공", "용접공",
]

_KNOWN_MATERIALS = [
    "H파일", "PHC파일", "철근", "레미콘", "시멘트", "블록", "합판",
    "단열재", "유리", "타일", "도료", "페인트", "형강", "강관",
]


def _extract_labor_job_type(query: str) -> str | None:
    for job in _KNOWN_JOB_TYPES:
        if job in query:
            return job
    match = re.search(r"([가-힣]{2,5}(?:공|인부|기사|기능공))", query)
    return match.group(1) if match else None


def _extract_material_name(query: str) -> str | None:
    compact_query = re.sub(r"\s+", "", query)
    for mat in _KNOWN_MATERIALS:
        if mat in query or mat.lower() in compact_query.lower():
            return mat
    match = re.search(r"([가-힣A-Za-z0-9-]+)\s*(?:자재비|단가|가격|시세)", query)
    if match:
        name = match.group(1).strip()
        if len(name) >= 2:
            return name
    return None


def _lookup_labor_price(query: str) -> dict:
    # TODO(Tier 2): extractor가 job_type을 정확히 제공하면 아래 임시 추출 로직 교체
    job_type = _extract_labor_job_type(query)
    if not job_type:
        return {
            "status": "no_result",
            "rag_source": "labor_db",
            "rag_query_type": "item_search",
            "query": query,
            "content": "",
            "evidence": [],
            "message": "직종명을 인식하지 못했습니다. 예: '보통인부', '철근공'",
        }
    try:
        from agents.labor_cost.tools import get_labor_price
        result_str = get_labor_price.invoke({"job_type": job_type})
        return {
            "status": "success",
            "rag_source": "labor_db",
            "rag_query_type": "item_search",
            "query": job_type,
            "search_query": job_type,
            "content": result_str,
            "evidence": [{"source": "labor_cost.labor_cost", "content": result_str}],
        }
    except Exception as e:
        log.exception(f"노임단가 조회 실패: {e}")
        return {
            "status": "error",
            "rag_source": "labor_db",
            "rag_query_type": "item_search",
            "query": job_type,
            "content": "",
            "evidence": [],
            "warnings": [f"노임단가 조회 실패: {e}"],
        }


def _lookup_material_price(query: str) -> dict:
    # TODO(Tier 2): extractor가 material_name을 정확히 제공하면 아래 임시 추출 로직 교체
    material_name = _extract_material_name(query)
    if not material_name:
        return {
            "status": "no_result",
            "rag_source": "material_db",
            "rag_query_type": "item_search",
            "query": query,
            "content": "",
            "evidence": [],
            "message": "자재명을 인식하지 못했습니다. 예: '철근', '레미콘'",
        }
    try:
        from agents.material_cost.material_price_tool import search_material_price
        result_str = search_material_price.invoke({"material_name": material_name})
        return {
            "status": "success",
            "rag_source": "material_db",
            "rag_query_type": "item_search",
            "query": material_name,
            "search_query": material_name,
            "content": result_str,
            "evidence": [{"source": "material_prices", "content": result_str[:800]}],
        }
    except Exception as e:
        log.exception(f"자재 단가 조회 실패: {e}")
        return {
            "status": "error",
            "rag_source": "material_db",
            "rag_query_type": "item_search",
            "query": material_name,
            "content": "",
            "evidence": [],
            "warnings": [f"자재 단가 조회 실패: {e}"],
        }


def _handle_lookup(query: str, lookup_domain: str) -> dict:
    if lookup_domain == "standard_spec":
        return _search_standard_spec_for_rag(query)
    if lookup_domain == "labor":
        return _lookup_labor_price(query)
    if lookup_domain == "material":
        return _lookup_material_price(query)
    if lookup_domain == "company_docs":
        # TODO(Tier 2): company_docs RAG 검색 미구현
        return {
            "status": "not_available",
            "rag_source": "company_docs",
            "rag_query_type": "item_search",
            "query": query,
            "content": "",
            "evidence": [],
            "message": "계약/견적/기성 문서 LOOKUP은 아직 지원되지 않습니다.",
        }
    # unknown 또는 기타 — standard_spec 시도
    return _search_standard_spec_for_rag(query)


# ── 장비 키워드·지연일 안전망 (LLM 분류 후 router_node 보정) ─────────────
_EQUIP_KEYWORDS = (
    "장비 대기비", "대기비", "펌프카", "콘크리트 펌프차",
    "크레인", "믹서트럭", "장비비", "장비 대기", "임대료", "임차료",
)

_DELAY_DAY_RE = re.compile(
    r"(\d+\s*일|하루|이틀|사흘|나흘)\s*(지연|대기|연장|추가)",
    re.IGNORECASE,
)


def _has_explicit_equipment_request(query: str) -> bool:
    """질문에 장비 대기비 관련 키워드가 명시적으로 있는지 확인."""
    compact = re.sub(r"\s+", "", query)
    return any(kw.replace(" ", "") in compact for kw in _EQUIP_KEYWORDS)


def _has_explicit_delay_days(query: str) -> bool:
    """질문에 '1일 지연', '하루 대기' 같은 명시적 지연일 표현이 있는지 확인."""
    return bool(_DELAY_DAY_RE.search(query))


def _postprocess_equipment_and_duration(
    query: str,
    domains: list[str],
    missing_for_cost: list[str],
) -> tuple[list[str], list[str]]:
    """LLM 분류 결과를 보정한다.

    - 명시적 지연일 표현 → 'duration' missing 제거
    - 장비 키워드 → 'equipment' 도메인 강제 추가
    """
    changed = False

    if "duration" in missing_for_cost and _has_explicit_delay_days(query):
        missing_for_cost = [m for m in missing_for_cost if m != "duration"]
        changed = True

    if _has_explicit_equipment_request(query) and "equipment" not in domains:
        domains = list(domains) + ["equipment"]
        changed = True

    if changed:
        print(f'[라우터] 보정 후: domains={domains}, missing_for_cost={missing_for_cost}')

    return domains, missing_for_cost


# ── 분류 입력 구성 ────────────────────────────────────────────────────

def _build_classify_input(messages: list) -> tuple[str, str]:
    """분류용 입력 구성. Returns (latest_query, classify_input)."""
    latest_query = next(
        (m.content for m in reversed(messages) if isinstance(m, HumanMessage)),
        '',
    )

    prior = messages[:-1] if messages else []
    prior_lines = [
        f"{'사용자' if isinstance(m, HumanMessage) else 'AI'}: {m.content}"
        for m in prior
        if isinstance(m, (HumanMessage, AIMessage)) and isinstance(m.content, str) and m.content.strip()
    ]
    if not prior_lines:
        return latest_query, latest_query

    prior_text = "\n".join(prior_lines)[-1500:]
    classify_input = (
        f"[이전 대화 맥락 — 분류 참고용]\n{prior_text}\n\n"
        f"[현재 분류할 사용자 메시지]\n{latest_query}"
    )
    return latest_query, classify_input


# ── 라우터 노드 ───────────────────────────────────────────────────────

_OUT_OF_DOMAIN_RESPONSE = (
    "저는 건설전문 AI입니다. 건설 현장 관련 질문에만 답변드릴 수 있어요.\n\n"
    "기상 리스크, 인건비 산출, 장비 비용, 자재 가격 중 궁금한 게 있으시면 말씀해 주세요."
)


def router_node(state: dict) -> Command:
    log.debug('router_node 진입')
    latest_query, classify_input = _build_classify_input(state['messages'])

    # 입구 보안 검사
    is_blocked, reason = check_injection(latest_query)
    if is_blocked:
        log.warning(f'router_node 보안 차단: reason={reason}')
        print(f'\n[라우터] 보안 차단 ({reason}) → 요청 거절')
        structured_response = {
            'answer_type': 'CHAT',
            'title': '보안 차단 안내',
            'message': BLOCKED_RESPONSE,
            'summary': {
                'total_additional_cost': None,
                'risk_level': None,
                'expected_delay': None,
                'main_cause': '보안 정책에 의해 요청이 차단되었습니다.',
            },
            'cost_breakdown': [],
            'calculation_details': [],
            'evidence': [],
            'items': [],
            'assumptions': [],
            'missing_info': [],
            'rag_query_type': None,
            'rag_status': None,
            'rag_source': None,
            'rag_search_query': None,
            'rag_distance': None,
            'rag_items': [],
        }
        return Command(
            update={
                'final_response': BLOCKED_RESPONSE,
                'structured_response': structured_response,
                'messages': [AIMessage(content=BLOCKED_RESPONSE)],
            },
            goto=END,
        )

    plan = classify_question(classify_input)
    intent = plan['intent']
    domains = plan.get('domains') or []
    lookup_domain = plan.get('lookup_domain', 'unknown')
    missing_for_cost = plan.get('missing_for_cost') or []

    print(f'\n[라우터] intent={intent}, domains={domains}, lookup={lookup_domain} - {plan["reason"]}')

    # ── OUT_OF_DOMAIN ─────────────────────────────────────────────────
    if intent == 'OUT_OF_DOMAIN':
        log.info("router_node: OUT_OF_DOMAIN → redirect → END")
        return Command(
            update={
                'intent': intent,
                'domains': [],
                'answer_type': 'CHAT',
                'question_type': None,
                'needs_weather': False,
                'target_agents': [],
                'final_response': _OUT_OF_DOMAIN_RESPONSE,
                'messages': [AIMessage(content=_OUT_OF_DOMAIN_RESPONSE)],
            },
            goto=END,
        )

    # ── CHAT ──────────────────────────────────────────────────────────
    if intent == 'CHAT':
        log.info("router_node: CHAT → synthesize")
        return Command(
            update={
                'intent': intent,
                'domains': [],
                'answer_type': 'CHAT',
                'question_type': 'B',
                'needs_weather': False,
                'target_agents': [],
            },
            goto='synthesize',
        )

    # ── LOOKUP ────────────────────────────────────────────────────────
    if intent == 'LOOKUP':
        log.info(f"router_node: LOOKUP (lookup_domain={lookup_domain}) → synthesize")
        rag_result = _handle_lookup(latest_query, lookup_domain)
        return Command(
            update={
                'intent': intent,
                'domains': [],
                'answer_type': 'RAG_QA',
                'question_type': 'B',
                'needs_weather': False,
                'target_agents': [],
                'rag_result': rag_result,
            },
            goto='synthesize',
        )

    # ── CLARIFY ───────────────────────────────────────────────────────
    if intent == 'CLARIFY':
        log.info("router_node: CLARIFY → synthesize")
        return Command(
            update={
                'intent': intent,
                'domains': [],
                'answer_type': 'MISSING_INFO',
                'question_type': 'B',
                'needs_weather': False,
                'target_agents': [],
            },
            goto='synthesize',
        )

    # ── REPORT ────────────────────────────────────────────────────────
    # LLM 분류 후 보정: 장비 키워드·명시적 지연일 안전망
    domains, missing_for_cost = _postprocess_equipment_and_duration(
        latest_query, domains, missing_for_cost
    )

    # domains가 비어 있으면 필수 입력이 부족한 것으로 간주 → CLARIFY
    if not domains:
        log.warning("router_node: REPORT with empty domains → CLARIFY")
        return Command(
            update={
                'intent': intent,   # 분류값 그대로 보존 ('REPORT'), 라우팅만 CLARIFY로
                'domains': [],
                'answer_type': 'MISSING_INFO',
                'question_type': 'B',
                'needs_weather': False,
                'target_agents': [],
            },
            goto='synthesize',
        )

    needs_weather = 'weather' in domains
    cost_domains = [d for d in domains if d != 'weather']

    update = {
        'intent': intent,
        'domains': domains,
        'answer_type': 'RISK_REPORT' if needs_weather else 'COST_REPORT',
        'question_type': 'A' if needs_weather else 'B',
        'needs_weather': needs_weather,
        'target_agents': cost_domains,
        'missing_for_cost': missing_for_cost,
    }

    # 모든 REPORT는 extractor_node를 거쳐 입력값 추출 후 라우팅됨
    log.info(f"router_node 분기: weather={needs_weather}, cost={cost_domains} → extractor")
    print(f'[라우터] needs_weather={needs_weather}, target_agents={cost_domains}, missing_for_cost={missing_for_cost}')
    return Command(update=update, goto='extractor')
