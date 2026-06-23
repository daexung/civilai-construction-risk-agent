"""
표준품셈 PDF → 텍스트 추출 → 청킹 → 임베딩 → PostgreSQL(pgvector) 저장
pdfplumber 사용으로 테이블 구조 보존, (일당) 항목 → 인/단위 자동 환산
실행: python rag/labor_cost/embed.py
"""
import os
import re
import sys
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

import pdfplumber
import psycopg2
from pgvector.psycopg2 import register_vector
from langchain_aws import BedrockEmbeddings

PDF_PATH    = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'raw', 'labor_cost', '2026+건설공사표준품셈원문정오표1차+반영.PDF')
EMBED_MODEL = 'amazon.titan-embed-text-v2:0'
VECTOR_DIM  = 1024
MIN_CHUNK_LEN = 80

CHAPTERS = [
    ('철근콘크리트공사', 185 - 1, 214 - 1),
    ('철골공사',        625 - 1, 634 - 1),
    ('방수공사',        659 - 1, 665 - 1),
]

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     os.getenv("DB_PORT", "5432"),
    "dbname":   os.getenv("DB_NAME", "material_cost"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def get_connection():
    conn = psycopg2.connect(**DB_CONFIG)
    register_vector(conn)
    return conn


# ─────────────────────────────────────────
# 1. 테이블 → 마크다운 문자열
# ─────────────────────────────────────────
def table_to_md(table: list) -> str:
    if not table:
        return ''
    lines = []
    for row in table:
        cells = [str(c).replace('\n', '/') if c is not None else '' for c in row]
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


# ─────────────────────────────────────────
# 2. (일당) 테이블 → 인/단위 환산
# ─────────────────────────────────────────
WORKER_KEYWORDS = ['콘크리트공', '보통인부', '철근공', '형틀목공', '방수공',
                   '특별인부', '철골공', '도장공', '미장공', '조적공']

def try_convert_daily(table: list, unit: str) -> str:
    results = []
    for row in table:
        if not row or not any(row):
            continue
        jobs = []
        workers_per_day = []
        daily_output = None
        found_workers_col = False

        for ci, cell in enumerate(row):
            if cell is None:
                continue
            s = str(cell).strip()
            if any(kw in s for kw in WORKER_KEYWORDS):
                jobs = [j.strip() for j in s.split('\n') if j.strip()]
            if jobs and re.match(r'^[\d.]+(\n[\d.]+)*$', s):
                if not found_workers_col:
                    workers_per_day = [float(v) for v in s.split('\n') if v.strip()]
                    found_workers_col = True
                else:
                    try:
                        v = float(s)
                        if v >= 1.0 and daily_output is None:
                            daily_output = v
                    except ValueError:
                        pass

        if jobs and workers_per_day and daily_output and daily_output > 0:
            for job, wpd in zip(jobs, workers_per_day):
                rate = wpd / daily_output
                results.append(
                    f'  {job}: {wpd}인/일 ÷ {daily_output}{unit}/일 = {rate:.4f}인/{unit}'
                )

    return '\n'.join(results)


# ─────────────────────────────────────────
# 3. 챕터 전체 텍스트 추출 → 청킹 → (일당) 환산 주석 삽입
# ─────────────────────────────────────────
def extract_and_chunk(pdf_path: str, start_page: int, end_page: int) -> list:
    text_parts = []
    page_meta = []

    with pdfplumber.open(pdf_path) as pdf:
        for pno in range(start_page, end_page + 1):
            pg = pdf.pages[pno]
            txt = pg.extract_text() or ''
            tables = pg.extract_tables() or []
            if txt.strip():
                text_parts.append(txt.strip())
            is_daily = '(일당)' in txt
            unit = 'ton' if ('ton' in txt or '(ton)' in txt) and '㎥' not in txt else '㎥'
            page_meta.append((pno, is_daily, unit, tables))

    full_text = '\n'.join(text_parts)
    raw = re.split(r'(?m)^(?=\d+-\d+-\d+)', full_text)
    chunks = [c.strip() for c in raw if len(c.strip()) >= MIN_CHUNK_LEN]

    chunk_map: dict[str, int] = {}
    for ci, chunk in enumerate(chunks):
        m = re.match(r'(\d+-\d+-\d+)', chunk)
        if m:
            chunk_map[m.group(1)] = ci

    for pno, is_daily, unit, tables in page_meta:
        if not is_daily:
            continue
        pg_text = text_parts[pno - start_page] if (pno - start_page) < len(text_parts) else ''
        section_codes = [sc for sc in re.findall(r'\d+-\d+-\d+', pg_text) if sc in chunk_map]
        for t in tables:
            conv = try_convert_daily(t, unit)
            if not conv:
                continue
            for sc in section_codes:
                ci = chunk_map[sc]
                if '[※ 일당' not in chunks[ci]:
                    chunks[ci] += f'\n\n[※ 일당→{unit}당 환산]\n{conv}'
                    break

    return chunks


# ─────────────────────────────────────────
# 4. DB 테이블 초기화
# ─────────────────────────────────────────
def init_table(conn, reset: bool = False):
    cur = conn.cursor()
    cur.execute("CREATE SCHEMA IF NOT EXISTS rag")
    if reset:
        cur.execute("DROP TABLE IF EXISTS rag.standard_spec")
        print("기존 테이블 삭제 완료")
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS rag.standard_spec (
            id            TEXT PRIMARY KEY,
            chapter       TEXT,
            section_code  TEXT,
            content       TEXT,
            embedding     vector({VECTOR_DIM})
        )
    """)
    conn.commit()
    cur.close()
    print("[INFO] rag.standard_spec 테이블 준비 완료")


# ─────────────────────────────────────────
# 5. 임베딩 + PostgreSQL 저장
# ─────────────────────────────────────────
def embed_and_store():
    embedder = BedrockEmbeddings(
        model_id=EMBED_MODEL,
        region_name=os.getenv('AWS_BEDROCK_REGION'),
    )
    conn = get_connection()
    init_table(conn, reset=True)
    cur = conn.cursor()

    for chapter_name, start, end in CHAPTERS:
        print(f'처리 중: {chapter_name} ({start + 1}~{end + 1}p)')
        chunks = extract_and_chunk(PDF_PATH, start, end)
        print(f'  청크 수: {len(chunks)}개')

        embeddings = embedder.embed_documents(chunks)

        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            m = re.match(r'(\d+-\d+-\d+)', chunk)
            section_code = m.group(1) if m else ''
            chunk_id = f'{chapter_name}_{i}'

            cur.execute("""
                INSERT INTO rag.standard_spec (id, chapter, section_code, content, embedding)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    content   = EXCLUDED.content,
                    embedding = EXCLUDED.embedding
            """, (chunk_id, chapter_name, section_code, chunk, emb))

        conn.commit()
        print(f'  {chapter_name} 저장 완료')

    cur.execute("SELECT COUNT(*) FROM rag.standard_spec")
    total = cur.fetchone()[0]
    cur.close()
    conn.close()
    print(f'\n임베딩 완료: 총 {total}개 청크 저장')


if __name__ == '__main__':
    embed_and_store()
