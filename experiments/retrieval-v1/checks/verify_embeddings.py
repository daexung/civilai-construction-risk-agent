"""벡터 캐시 무결성 검사(4단계). API를 호출하지 않는다. 일부만 있어도 현재 상태를 기록한다(ready 여부 포함).

  python -B experiments/retrieval-v1/checks/verify_embeddings.py
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.dont_write_bytecode = True
WORK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORK / 'src'))
sys.path.insert(0, str(WORK / 'checks'))
import embed_index as ei  # noqa: E402
import run_records as rr  # noqa: E402


def main():
    items, rid = ei.load_inputs()
    by_hash = {x['input_sha256']: x for x in items}
    cache = ei.load_cache(ei.CACHE)
    rows = list(cache.values())
    checks = []

    def check(name, ok, detail=None):
        checks.append({'name': name, 'passed': bool(ok), 'detail': detail})

    mat = np.stack([ei.dec(r['vector_f32_b64']) for r in rows]) if rows else np.zeros((0, ei.CFG.dim), np.float32)
    norms = np.linalg.norm(mat, axis=1) if len(rows) else np.zeros(0)
    check('캐시 벡터 차원이 설정과 같음', mat.shape[1:] == (ei.CFG.dim,), mat.shape)
    check('유한값이고 0벡터가 없음', bool(np.isfinite(mat).all()) and not (norms == 0).any())
    check('길이가 1에 가까움(공식 문서: 3072차원은 정규화됨)', bool(len(rows)) and float(np.abs(norms - 1).max()) < 1e-3,
          {'min': float(norms.min()) if len(rows) else None, 'max': float(norms.max()) if len(rows) else None})
    check('캐시 행의 제공자·모델·차원·입력 형식·용도가 현재 설정과 같음',
          all((r['provider'], r['model'], r['dim'], r['input_format'], r['purpose']) == (ei.CFG.provider, ei.CFG.model, ei.CFG.dim, ei.INPUT_FORMAT, 'document')
              for r in rows))
    stale = [r['chunk_id'] for r in rows if r['input_sha256'] not in by_hash]
    check('모든 캐시 행의 입력 해시가 현재 청킹 묶음 입력과 같음(옛 입력 없음)', not stale, stale[:5])
    mism = [r['chunk_id'] for r in rows if r['input_sha256'] in by_hash and ei.pack_document(by_hash[r['input_sha256']]['text'])[1] != r['input_sha256']]
    check('입력 해시를 DB 글에서 다시 계산해도 같음', not mism, mism[:5])
    covered = [x['chunk_id'] for x in items if ei.doc_key(x) in cache]
    missing = [x['chunk_id'] for x in items if ei.doc_key(x) not in cache]
    mf = json.loads((ei.BASE / 'manifest.json').read_text(encoding='utf-8')) if (ei.BASE / 'manifest.json').exists() else None
    check('manifest의 ready가 실제 대응과 맞음(누락이 있으면 ready=false)', mf is not None and mf['ready'] == (not missing), mf and {'ready': mf['ready'], 'missing': mf['missing_count']})
    return {'chunk_set_id': ei.CS, 'release_id': rid, 'targets': len(items), 'unique_inputs': len(by_hash), 'cached_unique_inputs': len(rows),
            'chunks_with_vector': len(covered), 'chunks_missing_vector': len(missing), 'ready': not missing,
            'all_inputs_sha256': ei.sha('\n'.join(x['input_sha256'] for x in items)), 'checks': checks,
            'passed': sum(c['passed'] for c in checks), 'failed': sum(not c['passed'] for c in checks),
            'note': '일부만 있으면 ready=false가 정상 상태다. 전체 5,764개 완료로 보고하지 않는다.'}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    run = rr.start(ei.CS, 'verify_embeddings', None, note='벡터 캐시 무결성(API 호출 없음)')
    try:
        res = main()
        meta = rr.finish(run, {'verification.json': res}, res['failed'] == 0, {'passed': res['passed'], 'failed': res['failed'], 'ready': res['ready']})
    except BaseException as e:
        rr.fail(run, e)
        raise
    for c in res['checks']:
        print(('PASS ' if c['passed'] else 'FAIL ') + c['name'])
    print({k: res[k] for k in ('targets', 'unique_inputs', 'cached_unique_inputs', 'chunks_with_vector', 'chunks_missing_vector', 'ready')})
    print('run', meta['run_id'], meta['status'])
