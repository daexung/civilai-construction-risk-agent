import os
import time
import logging
from dotenv import load_dotenv
from langchain_core.tools import tool
import psycopg2

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     os.getenv("DB_PORT", "5432"),
    "dbname":   os.getenv("DB_NAME", "construction_risk_agent"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
    "connect_timeout": 10,  # 기본값(OS 타임아웃, 수십~수백초)이 아닌 10초로 빠르게 실패
}

_MAX_RETRIES = 3
_RETRY_DELAY_SEC = 2


def _get_pg_connection():
    """
    여러 에이전트가 동시에 같은 RDS 호스트로 접속을 시도할 때 간헐적으로 발생하는
    연결 타임아웃(psycopg2.OperationalError: Operation timed out)에 대응하기 위해
    짧은 connect_timeout과 재시도를 적용한다.
    """
    last_err = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return psycopg2.connect(**DB_CONFIG)
        except psycopg2.OperationalError as e:
            last_err = e
            logging.warning(f'DB 연결 시도 {attempt}/{_MAX_RETRIES} 실패: {e}')
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY_SEC)
    raise last_err


# ── 코어 함수들 (순수 dict 반환, ReAct agent에 노출되지 않음) ─────────────────

def _get_equipment_by_work_type_core(work_type: str) -> dict:
    """공종별 장비 목록 조회 로직. 결과를 dict로 반환.

    # TODO(Tier 2): 코어를 직접 호출하는 deterministic 노드를 만들 때
    # 이 함수가 raise하는 psycopg2.OperationalError 등 DB 예외를 노드 쪽에서도
    # 별도로 처리해야 함. 현재는 예외가 @tool 셸을 통해 그대로 전파됨.
    """
    conn = _get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            SELECT priority, equipment_type, spec, daily_rental_rate, standby_rate, is_standard, year
            FROM equipment_cost.equipment_rental
            WHERE work_type LIKE %s OR work_type LIKE '%%공통%%'
            ORDER BY
                CASE priority WHEN '주요' THEN 1 WHEN '조건부' THEN 2 ELSE 3 END,
                equipment_type,
                is_standard DESC,
                daily_rental_rate
            ''',
            (f'%{work_type}%',),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {"found": False, "query": work_type, "year": None, "items": []}

    year = rows[0][6]
    items = []
    for r in rows:
        priority, eq_type, spec, rate, standby, is_std, _ = r
        items.append({
            "priority": priority,
            "equipment_type": eq_type,
            "spec": spec,
            "daily_rental_rate": rate,
            "standby_rate": standby,
            "is_standard": bool(is_std),
        })

    logging.info(f'get_equipment_by_work_type: {work_type} → {len(rows)}건')
    return {"found": True, "query": work_type, "year": year, "items": items}


def _get_equipment_rental_rate_core(equipment_type: str) -> dict:
    """장비별 임대단가 조회 로직. 결과를 dict로 반환.

    # TODO(Tier 2): 코어를 직접 호출하는 deterministic 노드를 만들 때
    # 이 함수가 raise하는 psycopg2.OperationalError 등 DB 예외를 노드 쪽에서도
    # 별도로 처리해야 함. 현재는 예외가 @tool 셸을 통해 그대로 전파됨.
    """
    conn = _get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            SELECT equipment_type, spec, daily_rental_rate, standby_rate, is_standard, year
            FROM equipment_cost.equipment_rental
            WHERE equipment_type LIKE %s
            ORDER BY is_standard DESC, daily_rental_rate
            ''',
            (f'%{equipment_type}%',),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {"found": False, "query": equipment_type, "items": []}

    items = []
    for r in rows:
        items.append({
            "equipment_type": r[0],
            "spec": r[1],
            "daily_rental_rate": r[2],
            "standby_rate": r[3],
            "is_standard": bool(r[4]),
            "year": r[5],
        })

    logging.info(f'get_equipment_rental_rate: {equipment_type} → {len(rows)}건')
    return {"found": True, "query": equipment_type, "items": items}


def _get_equipment_cost_range_core(equipment_type: str, delay_days: float) -> dict:
    """규격별 대기 비용 범위 계산 로직. 결과를 dict로 반환.

    # TODO(Tier 2): 코어를 직접 호출하는 deterministic 노드를 만들 때
    # 이 함수가 raise하는 psycopg2.OperationalError 등 DB 예외를 노드 쪽에서도
    # 별도로 처리해야 함. 현재는 예외가 @tool 셸을 통해 그대로 전파됨.
    """
    conn = _get_pg_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            '''
            SELECT equipment_type, spec, daily_rental_rate, standby_rate, is_standard
            FROM equipment_cost.equipment_rental
            WHERE equipment_type LIKE %s
            ORDER BY daily_rental_rate
            ''',
            (f'%{equipment_type}%',),
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "found": False,
            "query": equipment_type,
            "equipment_name": None,
            "delay_days": delay_days,
            "standby_rate": None,
            "std_note": None,
            "standard": None,
            "minimum": None,
            "maximum": None,
        }

    standby_rate = rows[0][3]

    def calc(rate):
        return int(rate * standby_rate * delay_days)

    # 표준 규격 선택: is_standard=1 우선, 없으면 중간값
    std_row = next((r for r in rows if r[4] == 1), None)
    if std_row is None:
        std_row = rows[len(rows) // 2]
        std_note = '(중간값 자동 선택)'
    else:
        std_note = '(DB 표준 규격)'

    min_row = rows[0]
    max_row = rows[-1]

    logging.info(
        f'get_equipment_cost_range: {equipment_type} {delay_days}일 → 표준 {calc(std_row[2]):,}원'
    )
    return {
        "found": True,
        "query": equipment_type,
        "equipment_name": std_row[0],
        "delay_days": delay_days,
        "standby_rate": standby_rate,
        "std_note": std_note,
        "standard": {
            "spec": std_row[1],
            "daily_rental_rate": std_row[2],
            "standby_cost": calc(std_row[2]),
        },
        "minimum": {
            "spec": min_row[1],
            "daily_rental_rate": min_row[2],
            "standby_cost": calc(min_row[2]),
        },
        "maximum": {
            "spec": max_row[1],
            "daily_rental_rate": max_row[2],
            "standby_cost": calc(max_row[2]),
        },
    }


def _calculate_standby_cost_core(
    daily_rental_rate: int, standby_rate: float, delay_days: float
) -> dict:
    """장비 대기 추가 비용 계산 로직. 결과를 dict로 반환.

    반환 필드:
      daily_rental_rate(int) — 1일 임대단가
      standby_rate(float)    — 대기요율 (0.0~1.0)
      standby_day_rate(int)  — 1일 대기단가 = int(daily_rental_rate × standby_rate)
      delay_days(float)      — 장비 대기 일수
      total(int)             — 대기 추가 비용 = int(standby_day_rate × delay_days)
    """
    standby_day_rate = int(daily_rental_rate * standby_rate)
    total = int(standby_day_rate * delay_days)
    logging.info(
        f'calculate_standby_cost: {daily_rental_rate:,}원 × {standby_rate} × {delay_days}일 = {total:,}원'
    )
    return {
        "daily_rental_rate": daily_rental_rate,
        "standby_rate": standby_rate,
        "standby_day_rate": standby_day_rate,
        "delay_days": delay_days,
        "total": total,
    }


# ── @tool 셸 함수들 (입출력 시그니처 동결 — ReAct agent가 호출) ──────────────

@tool
def get_equipment_by_work_type(work_type: str) -> str:
    """
    공종명으로 해당 공종에 투입되는 장비 목록과 임대단가를 조회한다.
    장비명을 모를 때 공종명만으로 장비 대기 비용을 산정하려면 이 도구를 가장 먼저 호출한다.

    work_type: 공종명. 예: '철골 세우기', '콘크리트 타설', '방수공사'
    - 부분 일치 검색 가능. 예: '철골'만 입력해도 '철골 세우기' 결과 반환.
    - 필요구분: 주요(필수 투입) / 조건부(상황에 따라) / 보조(보조 역할)
    - is_standard=1 인 항목이 해당 장비의 표준 규격이다.
    """
    core = _get_equipment_by_work_type_core(work_type)
    if not core["found"]:
        return (
            f"'{core['query']}' 공종을 DB에서 찾을 수 없습니다.\n"
            f"지원 공종: 철골 세우기, 콘크리트 타설, 방수공사\n"
            f"장비명을 직접 입력하려면 get_equipment_rental_rate를 사용하세요."
        )

    lines = [f"[{core['query']}] 공종 투입 장비 목록 ({core['year']} 기준):"]
    for item in core["items"]:
        std_mark = ' ★표준' if item["is_standard"] else ''
        lines.append(
            f"  [{item['priority']}] {item['equipment_type']} / {item['spec']}{std_mark}"
            f" — 1일: {item['daily_rental_rate']:,}원, 대기요율: {item['standby_rate']*100:.0f}%"
        )
    return '\n'.join(lines)


@tool
def get_equipment_rental_rate(equipment_type: str) -> str:
    """
    장비 종류로 1일 임대단가와 대기요율을 조회한다.
    장비명을 이미 알고 있을 때 사용한다. 모를 경우 get_equipment_by_work_type을 먼저 호출한다.

    equipment_type: DB의 장비명 기준.
    예: 크레인(타이어), 크레인(무한궤도), 트럭탑재형크레인, 타워크레인,
        콘크리트 펌프차, 콘크리트 믹서트럭, 고소작업차, 지게차, 발전기
    - 부분 일치 검색 가능.
    - ★표준 표시 항목이 규격 미명시 시 기본 선택값이다.
    """
    core = _get_equipment_rental_rate_core(equipment_type)
    if not core["found"]:
        return f'DB에 없는 장비입니다: {core["query"]}'

    lines = []
    for item in core["items"]:
        std_mark = ' ★표준' if item["is_standard"] else ''
        lines.append(
            f'[{item["equipment_type"]} / {item["spec"]}{std_mark}]'
            f' 1일 임대단가: {item["daily_rental_rate"]:,}원,'
            f' 대기요율: {item["standby_rate"]*100:.0f}%'
            f' ({item["year"]} 기준)'
        )
    return '\n'.join(lines)


@tool
def get_equipment_cost_range(equipment_type: str, delay_days: float) -> str:
    """
    규격이 명시되지 않은 경우 사용한다.
    표준 규격(★) 기준 비용과 최소·최대 규격 비용을 한 번에 계산해 반환한다.

    equipment_type: 장비명. 예: '크레인(타이어)', '콘크리트 펌프차', '타워크레인'
    delay_days: 장비 대기 일수

    반환: 표준 규격 대기 비용 + 최소/최대 규격 비용 범위
    - 표준 규격이 없으면 중간값을 표준으로 사용한다.
    - 계산 결과에서 표준 규격 비용을 대표값으로 사용하고, 범위를 참고값으로 제시한다.
    """
    core = _get_equipment_cost_range_core(equipment_type, delay_days)
    if not core["found"]:
        return f'DB에 없는 장비입니다: {core["query"]}'

    sr = core["standard"]
    mr = core["minimum"]
    xr = core["maximum"]
    lines = [
        f'[{core["equipment_name"]}] 규격별 대기 비용 ({core["delay_days"]}일, 대기요율 {core["standby_rate"]*100:.0f}%)',
        f'',
        f'  ★ 표준 규격 {core["std_note"]}',
        f'    {sr["spec"]} — {sr["daily_rental_rate"]:,}원/일 × {core["standby_rate"]} × {core["delay_days"]}일 = {sr["standby_cost"]:,}원',
        f'',
        f'  ▼ 최소 규격',
        f'    {mr["spec"]} — {mr["daily_rental_rate"]:,}원/일 × {core["standby_rate"]} × {core["delay_days"]}일 = {mr["standby_cost"]:,}원',
        f'',
        f'  ▲ 최대 규격',
        f'    {xr["spec"]} — {xr["daily_rental_rate"]:,}원/일 × {core["standby_rate"]} × {core["delay_days"]}일 = {xr["standby_cost"]:,}원',
        f'',
        f'  → 비용 범위: {mr["standby_cost"]:,}원 ~ {xr["standby_cost"]:,}원',
        f'  → 대표값(표준 규격): {sr["standby_cost"]:,}원',
    ]
    return '\n'.join(lines)


@tool
def calculate_standby_cost(daily_rental_rate: int, standby_rate: float, delay_days: float) -> str:
    """
    장비 1대의 대기 추가 비용을 계산한다.
    규격이 확정된 경우(사용자 명시 또는 표준 규격 선택 후) 사용한다.
    규격이 미명시인 경우에는 get_equipment_cost_range를 사용한다.

    daily_rental_rate : 1일 임대단가 (원)
    standby_rate      : 대기요율 (0.0~1.0). 일반적으로 0.5
    delay_days        : 장비 대기 일수
    """
    core = _calculate_standby_cost_core(daily_rental_rate, standby_rate, delay_days)
    return (
        f'  1일 임대단가: {core["daily_rental_rate"]:,}원\n'
        f'  대기요율: {core["standby_rate"]*100:.0f}%\n'
        f'  1일 대기단가: {core["standby_day_rate"]:,}원\n'
        f'  지연일수: {core["delay_days"]}일\n'
        f'  대기 추가 비용: {core["standby_day_rate"]:,}원 × {core["delay_days"]}일 = {core["total"]:,}원'
    )


@tool
def calculate_total_standby_cost(costs: str) -> str:
    """
    여러 장비의 대기 비용을 합산한다.
    costs: 장비별 대기 비용을 쉼표로 구분한 문자열 (원 단위 정수)
    예: "765000,495000,320000" → 합계 1,580,000원
    """
    try:
        cost_list = [int(c.strip()) for c in costs.split(',') if c.strip()]
    except ValueError:
        return '비용 파싱 오류: 쉼표로 구분된 정수 문자열을 입력하세요. 예: "765000,495000"'

    total = sum(cost_list)
    lines = [f'  장비 {i+1}: {c:,}원' for i, c in enumerate(cost_list)]
    logging.info(f'calculate_total_standby_cost: {cost_list} → 합계 {total:,}원')
    return '장비별 대기 비용:\n' + '\n'.join(lines) + f'\n합계: {total:,}원'
