"""
REPORT intent 질문에서 비용/기상 계산에 필요한 입력값을 추출해 state['inputs']를 채운다.
분류(intent/domains/needs_weather/target_agents)는 router_node가 이미 완료한 상태로 진입.
"""
import json
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..')))
_PROJECT_ROOT = os.path.abspath(os.path.join(_HERE, '..', '..', '..'))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import boto3
from langchain_core.messages import HumanMessage, AIMessage
from langgraph.types import Command, Send

from bedrock_models import get_extractor_model_id
from logger import get_logger

log = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

# 추출 전용 상수 (분류보다 긴 JSON 출력 필요)
_EXTRACT_MAX_TOKENS = 768
_EXTRACT_TEMPERATURE = 0.0

# boto3 클라이언트 모듈 레벨 싱글턴
_bedrock = boto3.client(
    "bedrock-runtime",
    region_name=os.getenv("AWS_BEDROCK_REGION", "us-east-1"),
)

# ── work_type 키워드 → WeatherRiskRequest WorkType enum (결정론적 매핑) ──────────────
# 순서 중요: 더 구체적인 키워드가 먼저 오도록 정렬
_WORK_TYPE_MAP: list[tuple[list[str], str]] = [
    (
        ["콘크리트 타설", "타설", "레디믹스트", "레미콘",
         "기초타설", "슬래브타설", "벽체타설", "기둥타설", "콘크리트공사"],
        "CONCRETE_POURING",
    ),
    (
        ["철골 세우기", "철골 설치", "철골 조립", "철골공사", "철골 작업",
         "철골세우기", "스틸구조", "H빔 설치", "H빔설치"],
        "STEEL_ERECTION",
    ),
    (
        ["방수공사", "방수 공사", "방수 작업", "우레탄 방수", "도막방수", "시트방수",
         "아스팔트방수", "방수처리", "방수시공"],
        "WATERPROOFING",
    ),
]


def _map_work_type_to_enum(work_type_text: str | None) -> str | None:
    """한국어 공종명 → WeatherRiskRequest WorkType enum 값. 매핑 실패 시 None."""
    if not work_type_text:
        return None
    for keywords, enum_val in _WORK_TYPE_MAP:
        if any(kw in work_type_text for kw in keywords):
            return enum_val
    return None


_EXTRACT_SYSTEM_PROMPT = """당신은 건설 현장 질문 분석기입니다.
다음 대화 전체에서 비용/기상 계산에 필요한 입력값을 추출해 JSON으로만 응답하세요.
여러 턴에 걸쳐 제공된 정보를 모두 종합하세요. 불명확하거나 언급되지 않은 값은 null로 두세요. 추측하지 마세요.

날짜 변환 규칙 (KST 기준 ISO 8601):
- "이번 주": 오늘(월요일 기준) ~ 일요일, start=월요일 08:00, end=일요일 16:00
- "다음 주": 다음 주 월요일 08:00 ~ 일요일 16:00
- "오늘": 오늘 08:00 ~ 16:00
- "내일": 내일 08:00 ~ 16:00
- 단일 날짜: start=해당일 08:00, end=해당일 16:00
- 형식: "2026-06-21T08:00:00+09:00"

내부 필드명 규칙 (반드시 아래 이름 그대로 사용, 다른 이름 사용 금지):
- quantities 항목 키: material_name(자재명), quantity(수량), unit(단위)
- rates 항목 키: material_name(자재명), current_unit_price(현재단가), contract_unit_price(계약단가 없으면 null), unit(수량단위 예:㎡·ton·m), contract_type(고정단가 또는 시가연동)
- workers 항목 키: job_type(직종명), count(인원수)
- equipments 항목 키: equipment_name(장비명 예:펌프카·크레인·믹서트럭), standby_days(대기/지연일수, 반드시 숫자), quantity(대수, 언급 없으면 1), spec(장비 규격 예:25m³·50t·16t, 언급 없으면 null)
  * 장비 대기비·장비 지연비용이 언급된 경우에만 채울 것. 자재나 인력은 rates/workers에 담을 것.
  * "펌프카 25m³" → equipment_name="펌프카", spec="25m³" (25를 quantity로 쓰지 말 것)
- duration_days: 작업 기간·지연 일수 숫자 (예: "1일 지연" → 1, "3일 공사" → 3). 장비 대기나 작업 지연 일수가 언급되면 반드시 여기에도 기입.

응답 형식 예시 (JSON 블록만, 설명 없이):
{
  "location_text": "서울 마포구" 또는 null,
  "date_raw_text": "이번 주" 또는 null,
  "date_start_iso": "2026-06-22T08:00:00+09:00" 또는 null,
  "date_end_iso": "2026-06-28T16:00:00+09:00" 또는 null,
  "work_type_text": "콘크리트 타설" 또는 null,
  "quantities": [{"material_name": "우레탄 방수재", "quantity": 200, "unit": "㎡"}],
  "rates": [{"material_name": "우레탄 방수재", "current_unit_price": 8700, "contract_unit_price": 8000, "unit": "㎡", "contract_type": "고정단가"}],
  "workers": [{"job_type": "방수공", "count": 2}, {"job_type": "보통인부", "count": 2}],
  "equipments": [{"equipment_name": "펌프카", "standby_days": 1, "quantity": 1, "spec": "25m³"}],
  "duration_days": 1,
  "contract_type": "고정단가"
}"""


def _build_extractor_context(messages: list) -> str:
    """전체 대화를 추출기 입력용 텍스트로 구성한다."""
    lines = []
    for msg in messages:
        content = msg.content if hasattr(msg, "content") else ""
        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        if not content:
            continue
        if isinstance(msg, HumanMessage) or (hasattr(msg, "type") and msg.type == "human"):
            lines.append(f"사용자: {content}")
        elif isinstance(msg, AIMessage) or (hasattr(msg, "type") and msg.type == "ai"):
            lines.append(f"AI: {content[:1500]}")
    return "\n".join(lines)


def _extract_inputs_from_query(context: str) -> dict:
    """LLM 호출로 대화 전체에서 구조화 입력값 추출. 파싱 실패 시 빈 dict 반환."""
    try:
        today = datetime.now(KST).strftime("%Y-%m-%d (%A)")
        user_content = f"오늘 날짜: {today} KST\n\n대화 내용:\n{context}"

        response = _bedrock.converse(
            modelId=get_extractor_model_id(),
            system=[{"text": _EXTRACT_SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": user_content}]}],
            inferenceConfig={"maxTokens": _EXTRACT_MAX_TOKENS, "temperature": _EXTRACT_TEMPERATURE},
        )

        raw = response["output"]["message"]["content"][0]["text"].strip()
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            log.warning("extractor_node: LLM 응답에서 JSON 블록을 찾지 못함")
            return {}
        return json.loads(m.group())
    except json.JSONDecodeError as e:
        log.warning(f"extractor_node: JSON 파싱 실패 — {e}")
        return {}
    except Exception as e:
        log.warning(f"extractor_node: LLM 호출 실패 — {e}")
        return {}


def _build_inputs(extracted: dict) -> dict:
    """LLM 추출 결과로 state['inputs'] 구조 구성."""
    location_text = extracted.get("location_text")
    date_start = extracted.get("date_start_iso")
    date_end = extracted.get("date_end_iso")
    work_type_text = extracted.get("work_type_text")
    weather_enum = _map_work_type_to_enum(work_type_text)

    missing_fields: list[str] = []
    if not location_text:
        missing_fields.append("location")
    if not date_start:
        missing_fields.append("date_range")

    # equipments 항목 → rates에 equipment 키로 병합
    # equipment_node의 _STRONG_EQUIP_KEYS("equipment_name", "standby_days" 등)로 인식되도록
    equip_rates: list[dict] = []
    for eq in (extracted.get("equipments") or []):
        if not isinstance(eq, dict):
            continue
        eq_name = (eq.get("equipment_name") or eq.get("equipment_type") or "").strip()
        if not eq_name:
            continue
        equip_rates.append({
            "equipment_name": eq_name,
            "standby_days": eq.get("standby_days"),
            "quantity": eq.get("quantity") or 1,
            "spec": eq.get("spec"),
        })
    rates_combined = list(extracted.get("rates") or []) + equip_rates

    return {
        "location": {
            "text": location_text,
            "latitude": None,   # project_store 조회 결과로 채워짐 (weather_node)
            "longitude": None,
            # TODO(추후): 지오코딩 API 연동 — location_text가 있고 project_id 없을 때
            # Kakao Local API 또는 Nominatim으로 텍스트 → 위도/경도 변환 필요.
            # 현재: project_id → project_store 우선, 텍스트만 있으면 위치 확인 불가로 처리됨.
        },
        "date_range": {
            "raw_text": extracted.get("date_raw_text"),
            "start": date_start,
            "end": date_end,
        },
        "work_type": {
            "raw_text": work_type_text,
            "weather_enum": weather_enum,
        },
        "quantities": extracted.get("quantities") or [],
        "rates": rates_combined,
        "workers": extracted.get("workers"),
        "duration_days": extracted.get("duration_days"),
        "contract_type": extracted.get("contract_type"),
        "missing_fields": missing_fields,
    }


def extractor_node(state: dict) -> Command:
    """
    REPORT intent 질문에서 입력값을 추출하고 weather/cost agent로 라우팅한다.

    router_node가 이미 intent/domains/needs_weather/target_agents/missing_for_cost를
    결정한 상태로 진입. 이 노드는 추출과 라우팅만 담당한다.
    """
    log.debug("extractor_node 진입")

    # 1. 전체 대화 컨텍스트 구성
    messages = state.get("messages", [])
    context = _build_extractor_context(messages)

    # 2. LLM으로 입력값 추출 (전체 대화 기반)
    extracted = _extract_inputs_from_query(context)
    log.debug(f"extractor_node 추출 결과: {extracted}")

    # 3. inputs dict 구성
    inputs = _build_inputs(extracted)
    print(
        f'[추출기] location={inputs["location"]["text"]!r}'
        f'  work_type={inputs["work_type"]["raw_text"]!r}'
        f'  duration_days={inputs["duration_days"]}'
        f'  rates={inputs["rates"]}'
        f'  quantities_count={len(inputs["quantities"])}'
    )

    # 4. weather_skip 결정
    #    work_type_text가 언급됐지만 지원 공종(WeatherRiskRequest.WorkType)이 아닐 때만 skip.
    #    work_type_text가 None이면 project_store 기반 weather_node가 공종을 자체 판단하도록 skip하지 않음.
    needs_weather: bool = state.get("needs_weather", False)
    target_agents: list = state.get("target_agents") or []
    work_type_text = inputs["work_type"]["raw_text"]
    weather_enum = inputs["work_type"]["weather_enum"]
    weather_skip = needs_weather and bool(work_type_text) and weather_enum is None

    if weather_skip:
        log.info(f"extractor_node: weather_skip=True (공종 미지원: {work_type_text!r})")

    # weather_skip 시 synthesize_node가 이유를 알 수 있도록 weather_response 선점
    weather_response_skip: str | None = None
    if weather_skip:
        weather_response_skip = json.dumps(
            {
                "status": "SKIPPED",
                "reason": f"'{work_type_text}' 공종은 기상 리스크 분석 대상이 아닙니다. "
                           "지원 공종: 콘크리트 타설, 철골 세우기/설치, 방수공사.",
            },
            ensure_ascii=False,
        )

    update: dict = {"inputs": inputs, "weather_skip": weather_skip}
    if weather_response_skip is not None:
        update["weather_response"] = weather_response_skip

    updated_state = {**state, **update}

    # 5. 라우팅
    if needs_weather and not weather_skip:
        log.info(f"extractor_node → weather (weather_enum={weather_enum!r})")
        return Command(update=update, goto="weather")

    if weather_skip:
        # weather_node 건너뜀; 비용 agent가 있으면 직행, 없으면 aggregator
        if target_agents:
            log.info(f"extractor_node → {target_agents} (weather_skip)")
            return Command(update=update, goto=[Send(a, updated_state) for a in target_agents])
        log.info("extractor_node → aggregator (weather_skip, 비용 도메인 없음)")
        return Command(update=update, goto="aggregator")

    # cost only (needs_weather=False)
    if target_agents:
        log.info(f"extractor_node → cost only: {target_agents}")
        return Command(update=update, goto=[Send(a, updated_state) for a in target_agents])

    log.warning("extractor_node: target_agents 없음 → aggregator")
    return Command(update=update, goto="aggregator")
