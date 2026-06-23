"""기상 에이전트 노드"""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, '../../..'))
_AGENTS = os.path.abspath(os.path.join(_HERE, '../..'))
sys.path.insert(0, _ROOT)
sys.path.insert(0, _AGENTS)

import httpx
from langchain_core.messages import HumanMessage
from langgraph.types import Command, Send

from weather_risk.models import WeatherRiskRequest, WorkType
from weather_risk.services.weather_risk_service import analyze_weather_risk
from weather_risk.clients.exceptions import KmaApiError
from project_store import get_project
from logger import get_logger

log = get_logger(__name__)
KST = ZoneInfo("Asia/Seoul")

# ── 텍스트 위치 → 위경도 변환 ─────────────────────────────────────────
_KR_COORDS: dict[str, tuple[float, float]] = {
    # 서울 주요 행정구역
    "문래": (37.5172, 126.8957),
    "영등포": (37.5263, 126.8962),
    "마포": (37.5663, 126.9014),
    "강남": (37.4979, 127.0276),
    "강서": (37.5509, 126.8495),
    "구로": (37.4954, 126.8874),
    "종로": (37.5735, 126.9790),
    "중구": (37.5640, 126.9975),
    "성동": (37.5633, 127.0369),
    "동대문": (37.5744, 127.0095),
    "성북": (37.5894, 127.0167),
    "노원": (37.6542, 127.0568),
    "강북": (37.6396, 127.0257),
    "도봉": (37.6688, 127.0472),
    "은평": (37.6027, 126.9291),
    "서대문": (37.5791, 126.9368),
    "서울": (37.5665, 126.9780),
    # 기타 주요 도시
    "부산": (35.1796, 129.0756),
    "인천": (37.4563, 126.7052),
    "대구": (35.8714, 128.6014),
    "대전": (36.3504, 127.3845),
    "광주": (35.1595, 126.8526),
    "울산": (35.5384, 129.3114),
    "수원": (37.2636, 127.0286),
    "성남": (37.4449, 127.1389),
    "용인": (37.2410, 127.1775),
    "고양": (37.6583, 126.8320),
    "안양": (37.3943, 126.9568),
    "화성": (37.1994, 126.8316),
    "평택": (36.9921, 127.1130),
    "시흥": (37.3800, 126.8030),
}


def _geocode_location(location_text: str) -> tuple[float, float] | None:
    """텍스트 주소 → (위도, 경도). 실패 시 None."""
    for key, coords in _KR_COORDS.items():
        if key in location_text:
            log.debug(f"내부 좌표 사전 매핑: {location_text!r} → {key} {coords}")
            return coords
    try:
        r = httpx.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location_text, "format": "json", "limit": 1, "countrycodes": "kr"},
            headers={"User-Agent": "construction-risk-agent/1.0"},
            timeout=5.0,
        )
        results = r.json()
        if results:
            lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
            log.debug(f"Nominatim 지오코딩: {location_text!r} → ({lat}, {lon})")
            return lat, lon
    except Exception as e:
        log.warning(f"Nominatim 지오코딩 실패: {e}")
    return None


def _build_request_from_inputs(inputs: dict) -> WeatherRiskRequest | None:
    """state['inputs']에서 WeatherRiskRequest 구성. 필수값 없으면 None."""
    location_text = (inputs.get("location") or {}).get("text")
    date_start_str = (inputs.get("date_range") or {}).get("start")
    date_end_str = (inputs.get("date_range") or {}).get("end")
    work_type_enum = (inputs.get("work_type") or {}).get("weather_enum")

    if not location_text:
        log.warning("inputs에 location_text 없음 → weather 분석 불가")
        return None
    if not date_start_str or not date_end_str:
        log.warning("inputs에 date_range 없음 → weather 분석 불가")
        return None
    if not work_type_enum:
        log.warning("inputs에 work_type(weather_enum) 없음 → weather 분석 불가")
        return None

    coords = _geocode_location(location_text)
    if not coords:
        log.warning(f"위치 변환 실패: {location_text!r} → weather 분석 불가")
        return None

    try:
        date_start = datetime.fromisoformat(date_start_str)
        date_end = datetime.fromisoformat(date_end_str)
    except ValueError as e:
        log.warning(f"날짜 파싱 실패: {e}")
        return None

    try:
        return WeatherRiskRequest(
            project_id="ADHOC",
            site_name=location_text,
            latitude=coords[0],
            longitude=coords[1],
            work_type=WorkType(work_type_enum),
            scheduled_start=date_start,
            scheduled_end=date_end,
            query_type="SHORT_TERM",
        )
    except Exception as e:
        log.warning(f"WeatherRiskRequest 구성 실패: {e}")
        return None


def _cost_request_message(response_json: dict) -> HumanMessage:
    """기상 리스크 분석 결과를 장비/인건비 에이전트용 비용 산정 요청 메시지로 변환."""
    risk = response_json.get('risk_result', {}) or {}
    site = response_json.get('site', {}) or {}
    work = response_json.get('work', {}) or {}
    risk_level = risk.get('risk_level', '-')
    stoppage = risk.get('work_stoppage_required', False)
    delay_days = risk.get('delay_day_equivalent') or 0

    # FULL_DAY 정책 보정: 작업 중단이 필요하면 시간 환산값(delay_day_equivalent)이
    # 최소 지연일수(minimum_delay_days)보다 작아도 최소 일수를 적용한다.
    # (예: 콘크리트 타설 중단 0.5일 → 정책상 최소 1일)
    policy = risk.get('delay_policy') or {}
    min_days = policy.get('minimum_delay_days')
    if stoppage and min_days:
        delay_days = max(delay_days, min_days)

    return HumanMessage(content=(
        f"[기상 리스크 분석 결과 — 참고용]\n"
        f"현장: {site.get('site_name', '-')} / 공종: {work.get('work_type', '-')}\n"
        f"위험도: {risk_level} / 작업 중단 필요: {'예' if stoppage else '아니오'}\n"
        f"기상 분석 권장 지연일수: {delay_days}일\n\n"
        f"[일수·수량 적용 우선순위]\n"
        f"1. 사용자가 원문에서 직접 명시한 대기일수·지연일수·투입 인원/일수가 있으면 그 값을 최우선으로 사용한다.\n"
        f"   (예: '펌프카 1대 1일 대기', '콘크리트공 4명·보통인부 3명 2일 추가 투입')\n"
        f"2. 사용자가 명시하지 않은 항목에 한해, 위 기상 분석 권장 지연일수({delay_days}일)를 참고값으로 사용한다.\n"
        f"3. 기상 권장 지연일수가 사용자 명시 수치를 덮어쓰지 않는다. "
        f"   특히 권장 지연일수가 0일이어도 사용자가 대기/투입을 명시했으면 그 값으로 비용을 산정한다.\n\n"
        f"위 원칙에 따라 장비 대기 비용과 인건비를 산정해 주세요."
    ))


def weather_node(state: dict) -> Command:
    """
    기상 리스크 평가 노드.

    입력:
        state['project_id']: 프로젝트 ID
    출력:
        Command(update={'weather_response': ...}, goto=...)
        - 분석 성공: 비용 산정 요청 메시지를 추가해 equipment/labor_cost로 병렬 핸드오프
        - 분석 실패: synthesize로 직행 (비용 산정 불가)
    """
    log.debug('weather_node 진입')
    _inp = state.get('inputs') or {}
    print(
        f'[기상 노드] 진입'
        f'  project_id={state.get("project_id")!r}'
        f'  location={(_inp.get("location") or {}).get("text")!r}'
        f'  work_type={(_inp.get("work_type") or {}).get("raw_text")!r}'
        f'  date_start={(_inp.get("date_range") or {}).get("start")!r}'
        f'  date_end={(_inp.get("date_range") or {}).get("end")!r}'
    )

    # weather_skip 가드: extractor_node가 지원 공종이 아니라고 판단했음에도 이 노드에 도달한 경우
    # (방어 코드 — 정상 흐름에서는 extractor_node가 이 노드를 건너뜀)
    if state.get('weather_skip'):
        log.warning('weather_node: weather_skip=True 신호 수신 — extractor 라우팅 오류 의심, aggregator로 진행')
        return Command(
            update={},
            goto='aggregator',
        )

    def _fail(error_json: dict) -> Command:
        return Command(
            update={'weather_response': json.dumps(error_json, ensure_ascii=False)},
            goto='aggregator',
        )

    try:
        # 1. WeatherRiskRequest 확보 — project_id 우선, 없으면 inputs fallback
        project_id = state.get('project_id')
        inputs = state.get('inputs') or {}

        if project_id:
            try:
                # inputs에 사용자 입력 날짜가 있으면 query_date로 전달 (없으면 오늘 기본값)
                date_start_str = (inputs.get('date_range') or {}).get('start')
                query_date = None
                if date_start_str:
                    try:
                        query_date = datetime.fromisoformat(date_start_str)
                    except ValueError:
                        log.warning(f'project_id 경로: date_start 파싱 실패 {date_start_str!r}, 오늘 날짜 사용')
                request = get_project(project_id, query_date=query_date)
                print(f'[기상 노드] project_id={project_id!r}  query_date={query_date.date() if query_date else "오늘(기본값)"}')
                log.debug(f'프로젝트 로드: {project_id} → {request.site_name}')
            except KeyError:
                log.error(f'프로젝트 없음: {project_id}')
                return _fail({'status': 'ERROR', 'error': f'프로젝트를 찾을 수 없습니다: {project_id}'})
        else:
            log.info('project_id 없음 → inputs 기반 WeatherRiskRequest 구성 시도')
            request = _build_request_from_inputs(inputs)
            if request is None:
                location_text = (inputs.get("location") or {}).get("text") or "알 수 없음"
                return _fail({
                    'status': 'ERROR',
                    'error': (
                        f"위치({location_text!r}) 또는 날짜·공종 정보가 부족해 "
                        "기상 리스크를 분석할 수 없습니다."
                    ),
                })
            log.debug(f'inputs 기반 요청 구성 완료: {request.site_name}')

        # 2. 기상 리스크 분석
        # TODO: messages에서 날짜/시간 파싱이 필요하면
        #       get_project(project_id, query_date=파싱된날짜) 형태로 확장
        response = analyze_weather_risk(request)
        log.info(f'기상 리스크 평가 완료: {response.risk_result.risk_level}')

        weather_response_str = response.model_dump_json(ensure_ascii=False)

        # 4. 플래너(LLM)가 고른 비용 에이전트로만 핸드오프한다.
        # 순수 기상 질문이면 target_agents가 비어 있고, 이때는 비용 산정 없이
        # aggregator로 직행한다 (프리셋으로 장비·인력을 강제 호출하지 않는다).
        targets = state.get('target_agents') or []
        if not targets:
            print('\n[기상 에이전트] 완료 → 비용 에이전트 없음, aggregator로 진행')
            return Command(
                update={'weather_response': weather_response_str},
                goto='aggregator',
            )

        # 비용 에이전트가 비용을 산정할 수 있도록 분석 결과를 메시지로 추가해 핸드오프.
        # mode='json'으로 직렬화해야 enum이 값(예: 'CONCRETE_POURING', 'LOW')으로
        # 변환된다. 기본 model_dump()는 enum 객체를 그대로 둬서 메시지에
        # 'WorkType.CONCRETE_POURING' 같은 repr이 새어 나간다.
        cost_request = _cost_request_message(response.model_dump(mode='json'))
        payload = {**state, 'messages': state['messages'] + [cost_request]}

        print(f'\n[기상 에이전트] 완료 → {targets}로 전달')
        return Command(
            update={'weather_response': weather_response_str},
            goto=[Send(a, payload) for a in targets],
        )

    except KmaApiError as e:
        log.exception(f'기상청 API 에러: {e}')
        return _fail({'status': 'ERROR', 'error': f'기상 데이터 조회 실패: {str(e)}'})
    except Exception as e:
        log.exception(f'weather_node 예외: {e}')
        return _fail({'status': 'ERROR', 'error': f'기상 평가 중 오류 발생: {str(e)}'})
