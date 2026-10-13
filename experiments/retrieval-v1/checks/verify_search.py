"""결합 검색 동작 검사(4단계). 질문 임베딩 API를 호출하지 않는다. 검색 품질 평가가 아니라 동작·버전 거부 검사다.

  python -B experiments/retrieval-v1/checks/verify_search.py

벡터가 일부만 있어도 실행한다: 캐시에 있는 조각 벡터를 가짜 질문 벡터로 써서 순위 결합·한정·중복 줄이기를 확인한다.
결과: out/verification_runs/<청킹 묶음 ID>/<run_id>/verification.json
"""
import json
import re
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'checks'))
import embed_index as ei  # noqa: E402
import retrieve as rv  # noqa: E402
import run_records as rr  # noqa: E402


def main():
    checks = []

    def check(name, ok, detail=None):
        checks.append({'name': name, 'passed': bool(ok), 'detail': detail})

    # 정규화: 검색용만, 원문 숫자·단위는 보존
    check('정규화: 펌프카·루베·m3', rv.normalize('펌프카 100루베 300m3') == '펌프차 100㎥ 300㎥', rv.normalize('펌프카 100루베 300m3'))
    check('정규화: 영문 속 m3는 건드리지 않음', rv.normalize('cm3 2m3') == 'cm3 2㎥', rv.normalize('cm3 2m3'))
    check('부문 명시일 때만 한정', rv.explicit_division('건축부문 도장 품') == '건축부문' and rv.explicit_division('도장 품') is None)

    # 입력 포장: 공식 형식, 같은 문맥을 두 번 넣지 않음
    s, h = ei.pack_document('[표] 공통부문 6-1-1\n본문')
    check('문서 입력 포장 = title: none | text: …', s == 'title: none | text: [표] 공통부문 6-1-1\n본문' and len(h) == 64, s[:40])
    check('질문 입력 포장 = task: search result | query: …',
          ei.emb.query_input('콘크리트', ei.CFG) == 'task: search result | query: 콘크리트')

    rt = rv.Retriever(vectors=False)
    cache = ei.load_cache(ei.CACHE)
    mat = np.zeros((len(rt.items), ei.CFG.dim), dtype=np.float32)
    have = []
    for i, x in enumerate(rt.items):
        r = cache.get(ei.doc_key(x))
        if r:
            mat[i] = ei.dec(r['vector_f32_b64'])
            have.append(i)
    check('시험용: 캐시의 조각 벡터가 있음', len(have) >= 32, len(have))
    rt.matrix, rt.has_vectors = mat, True
    fixed = {}
    rt.query_vector = lambda q: (fixed[q], 0.0)

    # T1 결합 순위: 가짜 질문 벡터 = 한 조각의 벡터
    a = next(rt.items[i] for i in have if rt.items[i]['kind'] == 'table' and len(rt.items[i]['text']) > 300)
    query = re.sub(r'\s+', ' ', a['text'].split('\n')[-1])[:50]
    fixed[rv.normalize(query)] = mat[rt.pos[a['chunk_id']]]
    hyb = rt.search(query, 'hybrid')
    top = hyb['fused'][0]
    check('결합: 벡터 1위 조각이 결합 1위이고 점수가 RRF 식과 같음',
          top['chunk_id'] == a['chunk_id'] and top['vector_rank'] == 1 and
          abs(top['score'] - (1 / 61 + (1 / (60 + top['bm25_rank']) if top['bm25_rank'] else 0))) < 1e-12, top)
    vo = rt.search(query, 'vector')
    check('벡터만: BM25 후보 없음, 키워드만: 벡터 후보 없음', not vo['bm25'] and not rt.search(query, 'bm25')['vector'])
    check('후보 수 20개 이하', len(hyb['bm25']) <= 20 and len(hyb['vector']) <= 20)

    # T3 부문 한정
    q3 = '건축부문 ' + query
    fixed[rv.normalize(q3)] = mat[rt.pos[a['chunk_id']]]
    r3 = rt.search(q3, 'hybrid')
    divs = {rt.by_id[c['chunk_id']]['division'] for c in r3['bm25'] + r3['vector']}
    check('부문 명시 시 후보가 그 부문에만 있음', divs <= {'건축부문'} and r3['division_filter'] == '건축부문', sorted(divs))

    # T4 파생 조각 줄이기: 적용 범위 인용이 같은 공종 조각과 설명 조각
    pair = None
    for cid, q in rt.quotes.items():
        if cid.startswith('w:') and q:
            sec = rt.by_id[cid]['section_id']
            for other, q2 in rt.quotes.items():
                if other != cid and rt.by_id[other]['section_id'] == sec and len(q & q2) / len(q) >= rv.CONFIG['dedup_overlap'] and rt.pos[other] in have:
                    pair = (cid, other)
                    break
        if pair:
            break
    if pair:
        w, r_ = pair
        qq = re.sub(r'\s+', ' ', rt.by_id[r_]['text'].split('\n')[-1])[:50]
        fixed[rv.normalize(qq)] = mat[rt.pos[r_]]
        d = rt.search(qq, 'hybrid')
        ids_kept = [h['chunk_id'] for h in d['fused']]
        dropped = {x['chunk_id']: x for x in d['dropped']}
        check('파생 조각 줄이기: 같은 절에서 원문 인용이 80% 이상 겹치는 조각은 줄이고 기록함',
              not ({w, r_} <= set(ids_kept)) and any(x['reason'] == 'derived_duplicate' and x['duplicate_of'] for x in d['dropped']) and
              any(s['section_id'] == rt.by_id[r_]['section_id'] for s in d['sections']), {'pair': pair, 'dropped': list(dropped)[:2]})
    else:
        check('파생 조각 줄이기 시험용 쌍을 찾음', False, '쌍 없음(벡터가 일부만 있음)')

    # T5 제한 탐색
    secs = {rt.by_id[a['chunk_id']]['section_id']}
    r5 = rt.search(query, 'hybrid', restrict_sections=secs)
    check('제한 탐색: 결과가 지정한 절 안에만 있음', r5['fused'] and all(rt.by_id[h['chunk_id']]['section_id'] in secs for h in r5['fused']))

    # T6/T7 버전·준비 상태 거부
    mf = ei.BASE / 'manifest.json'
    ready = mf.exists() and json.loads(mf.read_text(encoding='utf-8')).get('ready')
    try:
        rv.Retriever(vectors=True).close()
        raised = False
    except RuntimeError:
        raised = True
    check('벡터 색인이 ready가 아니면 벡터 검색을 거부(ready면 열림)', raised == (not ready), {'ready': bool(ready)})
    with tempfile.TemporaryDirectory() as td:
        old_base = ei.BASE
        ei.BASE = Path(td)
        (Path(td) / 'manifest.json').write_text(json.dumps({'ready': True, 'chunk_set_id': 'cs-other', 'release_id': 'rk-other',
                                                          'model': ei.CFG.model, 'dim': ei.CFG.dim, 'input_format': ei.INPUT_FORMAT}), encoding='utf-8')
        try:
            rv.Retriever(vectors=True).close()
            mism = False
        except RuntimeError as e:
            mism = '다름' in str(e)
        finally:
            ei.BASE = old_base
    check('청킹 묶음·원문 버전이 다른 벡터는 거부', mism)

    # T10 근거 조회 연결(키워드 모드, 임베딩 없음)
    r10 = rt.retrieve('콘크리트 표면 마무리 기준', 'bm25')
    ev0 = r10['evidence'][0]['result'] if r10['evidence'] else None
    check('검색 → 근거 조회 연결: 같은 청킹 묶음·원문 버전과 적용 여부 unknown',
          ev0 and ev0['versions']['chunk_set_id'] == ei.CS and ev0['versions']['release_id'] == rt.reader.rid and ev0['applicability'].startswith('unknown'),
          ev0 and ev0['versions'])
    v = rv.versions(rt)
    check('버전 기록에 설정·코드 해시가 있음', len(v['config_sha256']) == 64 and len(v['code_sha256']) == 64 and v['chunk_set_id'] == ei.CS)
    rt.close()
    return checks


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    run = rr.start(ei.CS, 'verify_search', None, note='결합 검색 동작 검사(질문 임베딩 호출 없음)')
    try:
        checks = main()
        res = {'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks),
               'note': '동작·버전 거부 검사. 검색 품질 평가가 아니다.', 'checks': checks}
        meta = rr.finish(run, {'verification.json': res}, res['failed'] == 0, {'passed': res['passed'], 'failed': res['failed']})
    except BaseException as e:
        rr.fail(run, e)
        raise
    for c in checks:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['name'] + ('' if c['passed'] else f"  -> {str(c['detail'])[:200]}"))
    print('run', meta['run_id'], meta['status'])
    sys.exit(0 if meta['status'] == 'passed' else 1)
