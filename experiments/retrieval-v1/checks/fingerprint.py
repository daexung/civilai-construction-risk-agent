"""DB 내용 지문: 원문 릴리스와 청킹 묶음의 테이블별 행 수와 내용 해시(시각 열 제외). 다른 DB와도 비교할 수 있다.

  python -B experiments/retrieval-v1/checks/fingerprint.py [출력 경로]
"""
import json
import sys
from pathlib import Path

import psycopg

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import chunking as ch  # noqa: E402
import db  # noqa: E402

RELEASE_TABLES = ['documents', 'nodes', 'sections', 'toc_entries', 'source_records', 'record_cells', 'corrections',
                  'search_records', 'source_relations', 'edges', 'edge_candidates']


def table_hash(c, table, where, arg, ignore_ids=False):
    # 행 전체를 글로 바꿔 정렬한 뒤 해시한다(정렬 순서가 행 순서에 의존하지 않음)
    # ignore_ids: release_id·chunk_set_id 열을 빼고 해시한다(ID가 다른 두 버전의 내용 비교용)
    e = "(to_jsonb(t) - 'release_id' - 'chunk_set_id')::text" if ignore_ids else 't::text'
    n, h = c.execute(f"""select count(*), md5(coalesce(string_agg({e}, E'\\n' order by {e}), ''))
                         from rag_knowledge.{table} t where {where} = %s""", (arg,)).fetchone()
    return {'rows': n, 'md5': h}


def fingerprint(dsn, release_id, chunk_set_id, ignore_ids=False):
    with psycopg.connect(dsn) as c:
        rel = {t: table_hash(c, t, 'release_id', release_id, ignore_ids) for t in RELEASE_TABLES}
        chs = {t: table_hash(c, t, 'chunk_set_id', chunk_set_id, ignore_ids) for t in ch.TABLES}
        st = {'release': c.execute('select status from rag_knowledge.releases where release_id=%s', (release_id,)).fetchone(),
              'chunk_set': c.execute('select status from rag_knowledge.chunk_sets where chunk_set_id=%s', (chunk_set_id,)).fetchone()}
    return {'release_id': release_id, 'chunk_set_id': chunk_set_id, 'status': {k: v and v[0] for k, v in st.items()},
            'release_tables': rel, 'chunk_tables': chs}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    fp = fingerprint(db.dsn(), ch.DEFAULT_RELEASE, 'cs-37f81b5cfb1b-46f4f035c0fa')
    text = json.dumps(fp, ensure_ascii=False, indent=1)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text, encoding='utf-8')
    print(text)
