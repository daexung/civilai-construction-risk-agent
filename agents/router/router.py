"""
건설 리스크 라우터 — 질문 분류만 담당.
HTTP 디스패치는 LangGraph(graph.py)가 처리하므로 이 파일은 classify_question()만 노출한다.
"""
import json
import os
import re
import boto3
from config import MAX_TOKENS, TEMPERATURE
from bedrock_models import get_router_model_id
from logger import get_logger

log = get_logger(__name__)

# boto3 클라이언트 모듈 레벨 싱글턴 (호출마다 재생성 방지)
_bedrock = boto3.client(
    "bedrock-runtime",
    region_name=os.getenv("AWS_BEDROCK_REGION", "us-east-1"),
)

# 허용된 도메인 (graph 노드 이름 기준). weather는 domains 리스트로 전달.
_COST_DOMAINS = ("equipment", "material", "labor_cost")
_ALL_DOMAINS = ("weather", "equipment", "material", "labor_cost")
_INTENTS = {"OUT_OF_DOMAIN", "CHAT", "LOOKUP", "CLARIFY", "REPORT"}
_LOOKUP_DOMAINS = {"standard_spec", "labor", "material", "company_docs", "unknown"}

# ── 기상 안전망용 regex (LLM 분류 후 보정) ──────────────────────────
_CURRENT_QUERY_MARKER = "[현재 분류할 사용자 메시지]"
_WEATHER_EXCLUDED_RE = re.compile(
    r"(날씨|기상)(?:\s*영향)?\s*(?:은|는)?\s*(?:제외(?:하고)?|빼고)",
    re.IGNORECASE,
)
_WEATHER_SETTLED_NO_IMPACT_RE = re.compile(
    r"맑음|장비\s*대기(?:는|가)?\s*(?:없|없습니다)|예상\s*지연\s*0\s*일|"
    r"기상\s*추가비용\s*0\s*원|(?:날씨|기상)\s*영향\s*(?:은|는)?\s*(?:없이|없음|없|없습니다)",
    re.IGNORECASE,
)
_EXPLICIT_WEATHER_CHECK_RE = re.compile(
    r"이번\s*주\s*가능|비\s*예보|강풍|폭우|폭염|기상\s*확인|날씨\s*확인|"
    r"기상\s*리스크\s*분석|날씨\s*어때|비\s*오",
    re.IGNORECASE,
)
_QUANTITY_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:ton|톤|t|kg|㎏|m/t|mt|㎡|m2|m²|㎥|m3|m³|m|개|본|장|매|대|일)",
    re.IGNORECASE,
)
_MATERIAL_COST_TERMS = (
    "자재비", "자재", "재료비", "자재단가", "단가", "비용", "금액", "얼마",
)
_MATERIAL_TERMS = (
    "철근", "레미콘", "시멘트", "h파일", "h 파일", "phc파일", "phc 파일",
    "블록", "합판", "단열재", "유리", "타일", "도료", "페인트", "형강", "강관",
)


def _latest_user_query(query: str) -> str:
    """분류 입력에 이전 대화가 섞여 있어도 현재 사용자 메시지만 추출한다."""
    if _CURRENT_QUERY_MARKER in query:
        return query.rsplit(_CURRENT_QUERY_MARKER, 1)[-1].strip()
    return query


def _weather_is_excluded_or_settled(query: str) -> bool:
    current_query = _latest_user_query(query)
    if _WEATHER_EXCLUDED_RE.search(current_query):
        return True
    if _EXPLICIT_WEATHER_CHECK_RE.search(current_query):
        return False
    return bool(_WEATHER_SETTLED_NO_IMPACT_RE.search(current_query))


def _has_quantity(query: str) -> bool:
    return bool(_QUANTITY_RE.search(_latest_user_query(query)))


def _looks_like_material_cost_report(query: str) -> bool:
    current_query = _latest_user_query(query).lower()
    compact = re.sub(r"\s+", "", current_query)
    has_material_term = any(term.replace(" ", "") in compact for term in _MATERIAL_TERMS)
    has_cost_term = any(term in current_query for term in _MATERIAL_COST_TERMS)
    return has_material_term and has_cost_term and _has_quantity(query)


def classify_question(query: str) -> dict:
    """질문을 분석해 intent + domains + missing_for_cost를 반환한다.

    Returns:
        {
          "intent":           "OUT_OF_DOMAIN" | "CHAT" | "LOOKUP" | "CLARIFY" | "REPORT",
          "domains":          list[str],   # REPORT일 때: 질문에서 도출된 도메인만
          "lookup_domain":    str,         # LOOKUP일 때: 어느 소스를 칠지
          "missing_for_cost": list[str],   # REPORT일 때: 비용 산정에 필요하지만 누락된 입력
          "reason":           str,
        }
    """
    log.debug(f"classify_question 호출 — query={query!r}")
    prompt = f"""다음 건설 현장 질문을 분류하세요.

[건설 도메인 정의]
건설 비용·리스크: 자재비, 인건비, 장비비, 기상 리스크, 공정 지연, 표준품셈, 노임단가 등.
날씨·기상은 "작업 가능/지연" 문맥이면 건설 도메인 안.

[Intent — 반드시 아래 5가지 중 하나]
- OUT_OF_DOMAIN: 건설 도메인과 무관 (영화·음식·일반 상식 등). 인사·기능 문의("안녕", "너 뭐 할 수 있어?")도 포함.
- CHAT: 건설 개념 설명. DB/RAG 검색 없이 바로 답할 수 있는 것.
  예) "표준품셈이 뭐야?", "장비 대기비는 어떤 경우에 청구하나요?"
  구분: 품셈·단가·기준 조회는 LOOKUP. "뭐야?" "무엇인가요?" 같은 순수 개념 질문만 CHAT.
- LOOKUP: DB/RAG 단순 조회·서술. 계산 없음.
  예) "보통인부 노임단가 알려줘", "철근 자재비 알려줘", "철골 세우기 품셈 기준 알려줘",
      "콘크리트공사 품셈 기준 설명해줘", "방수공 품셈 항목 알려줘"
  구분: "알려줘/설명해줘/찾아줘 + 기준/단가/품셈" 조합 → LOOKUP (계산 의도 없음)
- CLARIFY: 날씨 분석도 비용 산정도 모두 불가한 경우. 위치·날짜·공종이 전부 불명확해서
  어떤 답변도 불가능한 경우에만 사용.
  구분: 날씨 분석은 가능한데 비용 수량만 없으면 → REPORT (missing_for_cost로 표시)
  구분: 수량이 명시된 경우("방수 200㎡", "굴착기 1대 3일") → REPORT
- REPORT: 리스크/비용 계산·분석. 날씨 확인·비용 산정 중 어느 하나라도 실행 가능한 경우.
  예) "오늘 날씨 기준 작업 가능할까?" → REPORT, domains=["weather"], missing_for_cost=[]
  예) "마포구 이번 주 콘크리트 타설 우천 리스크+추가비용" → REPORT, domains=["weather"],
      missing_for_cost=["quantity"] (날씨 분석 가능, 타설 물량㎥ 없어 비용 산정 불가)
  예) "방수 200㎡ 자재비+인건비" → REPORT, domains=["material","labor_cost"], missing_for_cost=[]

[domains] — REPORT일 때만, 질문에서 실제로 필요한 도메인만 (빈 배열도 허용)
- "weather"    : 기상/날씨 리스크 분석이 필요
- "labor_cost" : 인건비 계산이 필요
- "material"   : 자재비 계산이 필요
- "equipment"  : 장비비 계산이 필요

중요: "오늘 날씨/기상 기준 작업 가능할까?" 같은 날씨 확인 단독 질문 → domains=["weather"] (비용 도메인 추가 금지)
중요: domains는 질문 내용에서만 도출. 비었다고 자동으로 채우지 않는다.
중요: missing_for_cost가 비어있지 않으면 비용 도메인(labor_cost/material/equipment)을 domains에서 제외하고 domains=["weather"]만 유지.

[missing_for_cost] — REPORT일 때만. 비용 산정에 필요하지만 질문에 없는 입력 목록. 없으면 빈 배열.
값: "quantity"(수량/물량㎥·톤 등), "work_scope"(공종 세부), "duration"(기간/일수)
규칙: 날씨만 요청("작업 가능?") → missing_for_cost=[], domains=["weather"]
규칙: 비용도 요청했지만 수량이 없음 → missing_for_cost=["quantity"], domains=["weather"] (비용 도메인 제외)

[lookup_domain] — LOOKUP일 때만
- "standard_spec": 표준품셈/품셈 기준 RAG 검색
- "labor"        : 노임단가 DB 조회
- "material"     : 자재 단가 DB 조회
- "company_docs" : 계약·견적·기성 문서 RAG 검색
- "unknown"      : 위에 해당 없거나 불명확

질문: {query}

JSON으로만 응답하세요:
{{"intent": "...", "domains": [...], "lookup_domain": "...", "missing_for_cost": [...], "reason": "한 줄 이유"}}"""

    response = _bedrock.invoke_model(
        modelId=get_router_model_id(),
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": MAX_TOKENS,
            "temperature": TEMPERATURE,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )

    result = json.loads(response["body"].read())
    text = result["content"][0]["text"].strip()
    log.debug(f"모델 원본 응답: {text!r}")

    # 마크다운 코드블록 제거
    text = re.sub(r'^```(?:json)?\s*|\s*```$', '', text, flags=re.MULTILINE).strip()

    if not text:
        log.error(f"모델 응답이 비어있음. 원본 응답: {result}")
        raise ValueError(f"모델 응답이 비어있습니다. 원본 응답: {result}")

    _VALID_MISSING = {"quantity", "work_scope", "duration"}

    try:
        parsed = json.loads(text)
        intent = parsed.get("intent", "")
        if intent not in _INTENTS:
            log.warning(f"알 수 없는 intent: {intent!r}, CLARIFY로 대체")
            intent = "CLARIFY"

        raw_domains = parsed.get("domains") or []
        # 허용된 도메인만, _ALL_DOMAINS 순서 유지
        domains = [d for d in _ALL_DOMAINS if d in raw_domains]

        lookup_domain = parsed.get("lookup_domain", "unknown")
        if lookup_domain not in _LOOKUP_DOMAINS:
            lookup_domain = "unknown"

        raw_missing = parsed.get("missing_for_cost") or []
        missing_for_cost = [m for m in raw_missing if m in _VALID_MISSING]

        reason = parsed.get("reason", "")

    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        log.warning(f"분류 파싱 실패 ({e}), CLARIFY로 기본 처리. 원본: {text!r}")
        return {
            "intent": "CLARIFY",
            "domains": [],
            "lookup_domain": "unknown",
            "missing_for_cost": [],
            "reason": "파싱 실패, 추가 정보 요청으로 기본 처리",
        }

    # REPORT + weather인데 사용자가 명시 제외한 경우 제거 (LLM이 놓칠 수 있는 명시 제외 안전망)
    if intent == "REPORT" and "weather" in domains and _weather_is_excluded_or_settled(query):
        domains = [d for d in domains if d != "weather"]
        reason = (f"{reason}; 기상 제외/영향없음 조건 감지, weather 제거").strip("; ")

    # REPORT가 아닌 경우 missing_for_cost는 의미 없으므로 비움
    if intent != "REPORT":
        missing_for_cost = []

    # 수량이 명시된 자재 비용 질문은 단순 LOOKUP이 아니라 material 비용 산정 REPORT로 보정.
    if _looks_like_material_cost_report(query):
        if intent == "LOOKUP" and lookup_domain == "material":
            intent = "REPORT"
            domains = ["material"]
            lookup_domain = "unknown"
            missing_for_cost = []
            reason = (f"{reason}; 수량 포함 자재 비용 질문 감지, material REPORT로 보정").strip("; ")
        elif intent == "REPORT" and "quantity" in missing_for_cost:
            missing_for_cost = [m for m in missing_for_cost if m != "quantity"]
            if "material" not in domains:
                domains.append("material")
            reason = (f"{reason}; 수량 표현 감지, quantity 누락 보정").strip("; ")

    # missing_for_cost가 있으면 해당 비용 도메인은 실행 불가 → cost domains 제거, weather만 유지
    if intent == "REPORT" and missing_for_cost:
        domains = [d for d in domains if d == "weather"]
        reason = (f"{reason}; missing_for_cost={missing_for_cost}, 비용 도메인 제외").strip("; ")

    log.info(
        f"분류 결과: intent={intent}, domains={domains}, "
        f"missing_for_cost={missing_for_cost}, lookup_domain={lookup_domain} — 근거: {reason}"
    )
    return {
        "intent": intent,
        "domains": domains,
        "lookup_domain": lookup_domain,
        "missing_for_cost": missing_for_cost,
        "reason": reason,
    }


if __name__ == "__main__":
    samples = [
        "오늘 날씨 기준 작업 가능할까?",
        "보통인부 노임단가 알려줘",
        "철근 자재비 알려줘",
        "표준품셈이 뭐야?",
        "서울 마포구 이번 주 콘크리트 타설 우천 리스크+추가비용",
        "방수 200㎡ 자재비+인건비",
        "영화 추천해줘",
    ]
    for q in samples:
        r = classify_question(q)
        print(f"[{r['intent']}] domains={r['domains']} lookup={r['lookup_domain']} — {r['reason']}")
        print(f"  질문: {q}\n")
