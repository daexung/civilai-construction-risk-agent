"""
장비 대기 비용 DB 초기화
- data/raw/건설기계_공종별_필요장비_정리.csv 를 읽어 PostgreSQL DB에 적재
- 1일손료 = 시간당손료 × 8시간
- 대기요율 기본값 = 0.5 (표준 50%)
- is_standard: 장비 유형별 표준 규격에 1 마킹 (규격 미명시 시 기본 선택값)
- 실행: python db/equipment_cost/init_db.py (프로젝트 루트에서)
- 필요 환경변수(.env): DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD
"""
import csv
import os
import psycopg2
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE_DIR, '..', '..', 'data', 'raw', 'equipment_cost', '건설기계_공종별_필요장비_정리.csv')

load_dotenv(os.path.join(BASE_DIR, '..', '..', '.env'))

DB_CONFIG = {
    'host':     os.getenv('DB_HOST', 'localhost'),
    'port':     os.getenv('DB_PORT', '5432'),
    'dbname':   os.getenv('DB_NAME', 'construction_risk'),
    'user':     os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', ''),
}

STANDBY_RATE  = 0.5  # 표준 대기요율 50%
HOURS_PER_DAY = 8    # 1일 작업시간

# 장비 유형별 표준 규격 (규격 미명시 시 기본 선택)
STANDARD_SPECS = {
    '크레인(타이어)':        '50ton',
    '크레인(무한궤도)':      '50ton(버킷용량 1.91㎥)',
    '트럭탑재형크레인':      '5ton',
    '타워크레인':            '50×12',
    '콘크리트 펌프차':       '32m, 80~95㎥/hr',
    '콘크리트 믹서트럭':     '6.0㎥',
    '고소작업차':            '3ton',
    '지게차':                '3.5ton',
    '발전기':                '100㎾',
    '건설용펌프(자흡식)':    '80㎜(3.73㎾×15㎜)',
    '모르타르 펌프':         '7.46㎾',
    '수중모터펌프':          '100㎜',
    '아스팔트 디스트리뷰터': '3800ℓ(1000G/A)',
    '아스팔트 스프레이어':   '300ℓ',
    '용접기(교류)':          '300Amp',
    '용접기(직류)':          '300Amp',
    '절단기':                '5.08~15.24㎝',
    '콘크리트 믹서':         '0.20㎥',
    '콘크리트 진동기':       '0.75㎾(전기식)',
    '콘크리트펌프':          '20~26㎥/hr(30㎾)',
}


def get_connection():
    return psycopg2.connect(**DB_CONFIG)


def init():
    if not os.path.exists(CSV_PATH):
        print(f'ERROR: CSV file not found at {CSV_PATH}')
        return

    with open(CSV_PATH, encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))

    records = []
    for r in rows:
        hourly   = int(r['시간당손료_원'])
        daily    = hourly * HOURS_PER_DAY
        std_spec = STANDARD_SPECS.get(r['장비명'], '')
        is_std   = 1 if (std_spec and r['규격'] == std_spec) else 0
        records.append((
            r['공종'], r['필요구분'], r['장비명'], r['분류번호'], r['규격'],
            hourly, daily, STANDBY_RATE, is_std, r['용도_메모'],
        ))

    conn = get_connection()
    cur = conn.cursor()

    cur.execute('CREATE SCHEMA IF NOT EXISTS equipment_cost')
    cur.execute('DROP TABLE IF EXISTS equipment_cost.equipment_rental')
    cur.execute('''
        CREATE TABLE equipment_cost.equipment_rental (
            id                SERIAL PRIMARY KEY,
            work_type         TEXT    NOT NULL,
            priority          TEXT    NOT NULL,
            equipment_type    TEXT    NOT NULL,
            classification_no TEXT,
            spec              TEXT    NOT NULL,
            hourly_rate       INTEGER NOT NULL,
            daily_rental_rate INTEGER NOT NULL,
            standby_rate      REAL    NOT NULL DEFAULT 0.5,
            is_standard       INTEGER NOT NULL DEFAULT 0,
            memo              TEXT,
            year              INTEGER NOT NULL DEFAULT 2026
        )
    ''')

    cur.executemany(
        '''INSERT INTO equipment_cost.equipment_rental
           (work_type, priority, equipment_type, classification_no, spec,
            hourly_rate, daily_rental_rate, standby_rate, is_standard, memo)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
        records,
    )

    conn.commit()

    cur.execute('SELECT work_type, COUNT(*) FROM equipment_cost.equipment_rental GROUP BY work_type ORDER BY work_type')
    for wt, cnt in cur.fetchall():
        print(f'  [{wt}]: {cnt}개')

    cur.close()
    conn.close()
    print(f'DB 초기화 완료: {DB_CONFIG["dbname"]}.equipment_cost.equipment_rental')
    print(f'  총 {len(records)}개 장비 적재')


if __name__ == '__main__':
    init()
