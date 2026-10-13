"""청킹 묶음의 문서 임베딩(4단계). 공통 경로 backend/shared/embedding.py를 그대로 쓴다(키 번갈아 사용·429 시 다른 키).

  python -B experiments/retrieval-v1/src/embed_index.py plan                 # 호출 없음: 대상 수·캐시·토큰·비용 추정
  python -B experiments/retrieval-v1/src/embed_index.py run --pick32         # 길이·종류가 다른 32개만 실제 호출
  python -B experiments/retrieval-v1/src/embed_index.py run                  # 남은 전체(성공분은 건너뜀). 중단 후 같은 명령으로 재개
  python -B experiments/retrieval-v1/src/embed_index.py export               # 모두 맞을 때만 ready, 벡터 Parquet 저장

- 청킹 묶음·원문 릴리스는 evidence.PINNED의 고정값만 쓴다. 입력은 DB chunks.text(검색용 문맥+원문).
- 입력 포장: 공식 형식 `title: none | text: {text}`. 문맥(절·소제목·기준·머리글)이 이미 text에 있어 제목으로 다시 넣지 않는다.
- 캐시 키: 실제 입력 전체의 SHA-256 + 제공자·모델·차원·입력 형식·용도. 성공분은 호출 직후 파일에 추가하고 다시 호출하지 않는다.
- 비밀값(키)은 출력하지 않는다. 오류는 종류 이름만 기록한다.
"""
import argparse
import base64
import hashlib
import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import psycopg

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))
import db  # noqa: E402
import evidence as ev  # noqa: E402
from backend.shared import embedding as emb  # noqa: E402

CS = ev.DEFAULT_CS
INPUT_FORMAT = 'doc-title-none-v1'      # 입력 포장 버전. 포장이 바뀌면 값을 바꿔 캐시가 섞이지 않게 한다
QUERY_FORMAT = 'query-task-search-result-v1'
CFG = emb.settings()
BASE = WORK / 'out/embeddings' / CS / f'{CFG.provider}-{CFG.model}-{CFG.dim}-{INPUT_FORMAT}'
CACHE = BASE / 'cache.jsonl'
QUERY_CACHE = WORK / 'out/embeddings' / CS / f'{CFG.provider}-{CFG.model}-{CFG.dim}-{QUERY_FORMAT}' / 'queries.jsonl'
MAX_INPUT_TOKENS = 8192                  # 공식 문서(ai.google.dev/gemini-api/docs/embeddings, 2026-10-12 확인)
PRICE_PER_M = {'standard': 0.20, 'batch': 0.10}   # 공식 가격표(ai.google.dev/gemini-api/docs/pricing, 2026-10-09 갱신본, 2026-10-12 확인)


def sha(s):
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def pack_document(text):
    """공통 함수의 입력 포장. 제목은 'none'(공식 형식)이다."""
    chunk = {'section': 'none', 'text': text}
    return emb.document_input(chunk, CFG), emb.document_fingerprint(chunk, CFG)


def load_inputs(conn=None):
    own = conn is None
    conn = conn or psycopg.connect(db.dsn())
    if own:
        conn.read_only = True
    rd = ev.Reader(conn, CS)          # 버전·완료 상태 확인(다르면 거부)
    rows = conn.execute("""select chunk_id, kind, section_id, division, status, ordinal, est_tokens, issues, text
                           from rag_knowledge.chunks where chunk_set_id=%s order by ordinal""", (CS,)).fetchall()
    out = []
    for cid, kind, sec, div, status, ordinal, est_tok, issues, text in rows:
        s, h = pack_document(text)
        out.append({'chunk_id': cid, 'kind': kind, 'section_id': sec, 'division': div, 'status': status, 'ordinal': ordinal,
                    'est_tokens': est_tok, 'issues': issues if isinstance(issues, list) else json.loads(issues), 'text': text,
                    'input': s, 'input_sha256': h})
    if own:
        conn.close()
    return out, rd.rid


def enc(vec):
    return base64.b64encode(np.asarray(vec, dtype='<f4').tobytes()).decode()


def dec(s):
    return np.frombuffer(base64.b64decode(s), dtype='<f4')


def key_of(row):
    return (row['input_sha256'], row['provider'], row['model'], row['dim'], row['input_format'], row['purpose'])


def load_cache(path):
    cache = {}
    if Path(path).exists():
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                cache[key_of(r)] = r
    return cache


def doc_key(item):
    return (item['input_sha256'], CFG.provider, CFG.model, CFG.dim, INPUT_FORMAT, 'document')


def append_rows(path, rows):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + '\n')
        f.flush()


class Counting:
    """키별 요청·429 횟수를 센다. 공통 클라이언트(_StudioEmbeddingClient)의 번갈아 쓰기·429 이어가기는 그대로 둔다."""

    def __init__(self, inner, name):
        self.inner, self.name, self.models = inner, name, self
        self.requests = self.rate_limited = self.errors = 0

    def embed_content(self, **kw):
        self.requests += 1
        try:
            return self.inner.models.embed_content(**kw)
        except Exception as e:
            if emb.rate_limit_error(e):
                self.rate_limited += 1
            else:
                self.errors += 1
            raise


def make_client():
    from google import genai
    keys = emb.api_keys(CFG)
    counters = [Counting(genai.Client(api_key=k), f'key{i + 1}') for i, k in enumerate(keys)]
    return emb._StudioEmbeddingClient(counters), counters


def quota_info(exc):
    """429가 일일 한도인지와 재시도까지 남은 초를 읽는다. 오류 글은 출력하지 않는다(숫자만 꺼낸다)."""
    import re
    txt = str(exc)
    m = re.search(r"'retryDelay': '(\d+)s'", txt)
    return {'daily': 'PerDay' in txt, 'retry_after_sec': int(m.group(1)) if m else None}


def check_vectors(vecs, n):
    if len(vecs) != n:
        raise RuntimeError(f'벡터 수 {len(vecs)} != 입력 수 {n}')
    arr = np.asarray(vecs, dtype=np.float32)
    if arr.shape != (n, CFG.dim):
        raise RuntimeError(f'벡터 모양 {arr.shape}')
    if not np.isfinite(arr).all():
        raise RuntimeError('유한하지 않은 값')
    norms = np.linalg.norm(arr, axis=1)
    if (norms == 0).any():
        raise RuntimeError('0벡터')
    return norms


def pick32(items):
    """길이·종류·상태가 다양한 32개를 결정적으로 고른다(가장 긴 표 3개, 보류·소속 미확정·수식 미확정 포함)."""
    chosen = {}

    def take(xs, k):
        for x in xs:
            if len(chosen) >= 32 or k <= 0:
                break
            if x['chunk_id'] not in chosen:
                chosen[x['chunk_id']] = x
                k -= 1
    by_len = sorted(items, key=lambda x: -len(x['text']))
    take([x for x in by_len if x['kind'] == 'table'], 3)
    take([x for x in items if x['status'] == 'held'], 1)
    take([x for x in items if x['status'] == 'membership_unconfirmed'], 1)
    take([x for x in items if any(i.startswith('formula_unresolved') for i in x['issues'])], 2)
    for kind, k in (('work', 6), ('rule', 8), ('table', 11)):
        xs = sorted([x for x in items if x['kind'] == kind], key=lambda x: len(x['text']))
        step = max(1, len(xs) // k)
        take([xs[min(i * step + step // 2, len(xs) - 1)] for i in range(k)], k)
    take(by_len[::max(1, len(by_len) // 40)], 32 - len(chosen))
    return list(chosen.values())[:32]


def plan(items, rid):
    cache = load_cache(CACHE)
    reuse = sum(doc_key(x) in cache for x in items)
    old = ROOT / 'data/processed/embeddings.all.gemini-embedding-2.parquet'
    old_hit = None
    if old.exists():
        import pyarrow.parquet as pq
        old_hashes = set(pq.read_table(old, columns=['text_sha256']).column('text_sha256').to_pylist())
        old_hit = sum(x['input_sha256'] in old_hashes for x in items)
    est_sum = sum(x['est_tokens'] for x in items)
    chars = sum(len(x['input']) for x in items)
    return {'chunk_set_id': CS, 'release_id': rid, 'targets': len(items), 'by_kind': {k: sum(x['kind'] == k for x in items) for k in ('work', 'rule', 'table')},
            'by_status': {k: sum(x['status'] == k for x in items) for k in sorted({x['status'] for x in items})},
            'provider': CFG.provider, 'model': CFG.model, 'dim': CFG.dim, 'input_format': INPUT_FORMAT,
            'reusable_from_this_cache': reuse, 'old_service_cache_exact_matches': old_hit,
            'input_chars_total': chars, 'est_tokens_sum_chunking_estimate': est_sum,
            'all_inputs_sha256': sha('\n'.join(x['input_sha256'] for x in items)),
            'unique_inputs': len({x['input_sha256'] for x in items})}


# ---------------- 실행 ----------------
def embed_batches(todo, cache, batch=10, pause=1.0, max_attempts=6, log=print):
    cli, counters = make_client()
    stats = {'requests_attempted': 0, 'new_vectors': 0, 'retries': 0, 'failed': [], 'stopped': None, 'norm_min': 9, 'norm_max': 0}
    t0 = time.perf_counter()
    for s in range(0, len(todo), batch):
        part = todo[s:s + batch]
        vecs, non_retry = None, False
        for attempt in range(max_attempts):
            try:
                stats['requests_attempted'] += 1
                vecs = emb.embed_texts(cli, [x['input'] for x in part], config=CFG, task='document')
                norms = check_vectors(vecs, len(part))
                break
            except Exception as e:
                vecs = None
                if emb.rate_limit_error(e):
                    qi = quota_info(e)
                    if qi['daily']:        # 일일 한도: 몇 시간 뒤에야 풀리므로 재시도하지 않고 바로 멈춘다
                        stats['daily_quota_exhausted'] = True
                        stats['retry_after_sec'] = qi['retry_after_sec']
                        stats['last_error_type'] = type(e).__name__
                        break
                if emb.retryable_error(e) and attempt < max_attempts - 1:
                    stats['retries'] += 1
                    wait = min(60, 2 ** (attempt + 1))
                    log(f'  임시 오류({type(e).__name__}), {wait}초 뒤 재시도 ({attempt + 1}/{max_attempts - 1})')
                    time.sleep(wait)
                    continue
                stats['last_error_type'] = type(e).__name__
                non_retry = not emb.retryable_error(e)
                break
        if vecs is None and stats.get('daily_quota_exhausted'):
            stats['stopped'] = 'daily_quota_exhausted'
            stats['not_attempted_from'] = part[0]['chunk_id']
            break
        if vecs is None:
            if len(part) > 1 and non_retry:
                # 한 입력 때문에 실패했을 수 있다: 하나씩 나눠 실패 입력을 가린다(청킹은 바꾸지 않는다)
                for x in part:
                    try:
                        v = emb.embed_texts(cli, [x['input']], config=CFG, task='document')
                        check_vectors(v, 1)
                        row = row_for(x, v[0])
                        append_rows(CACHE, [row])
                        cache[key_of(row)] = row
                        stats['new_vectors'] += 1
                    except Exception as e2:
                        stats['failed'].append({'chunk_id': x['chunk_id'], 'error_type': type(e2).__name__})
                continue
            stats['stopped'] = stats.get('last_error_type', 'unknown')
            stats['failed'] += [{'chunk_id': x['chunk_id'], 'error_type': stats['stopped']} for x in part]
            break
        rows = [row_for(x, v) for x, v in zip(part, vecs)]
        append_rows(CACHE, rows)
        for r in rows:
            cache[key_of(r)] = r
        stats['new_vectors'] += len(rows)
        stats['norm_min'] = min(stats['norm_min'], float(norms.min()))
        stats['norm_max'] = max(stats['norm_max'], float(norms.max()))
        if (s // batch) % 20 == 0:
            log(f'  {stats["new_vectors"]}/{len(todo)} 완료')
        if s + batch < len(todo):
            time.sleep(pause)
    stats['elapsed_sec'] = round(time.perf_counter() - t0, 1)
    stats['per_key'] = {c.name: {'requests': c.requests, 'rate_limited_429': c.rate_limited, 'other_errors': c.errors} for c in counters}
    return stats


def row_for(x, vec):
    return {'chunk_id': x['chunk_id'], 'input_sha256': x['input_sha256'], 'provider': CFG.provider, 'model': CFG.model,
            'dim': CFG.dim, 'input_format': INPUT_FORMAT, 'purpose': 'document', 'vector_f32_b64': enc(vec),
            'created': time.strftime('%Y-%m-%dT%H:%M:%S')}


def export(items, rid):
    """모든 검색 대상의 벡터와 입력 해시가 맞을 때만 ready."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    cache = load_cache(CACHE)
    missing = [x['chunk_id'] for x in items if doc_key(x) not in cache]
    ready = not missing
    manifest = {'chunk_set_id': CS, 'release_id': rid, 'provider': CFG.provider, 'model': CFG.model, 'dim': CFG.dim,
                'input_format': INPUT_FORMAT, 'targets': len(items), 'vectors': len(items) - len(missing), 'missing': missing[:50],
                'missing_count': len(missing), 'ready': ready, 'all_inputs_sha256': sha('\n'.join(x['input_sha256'] for x in items)),
                'cache': str(CACHE.relative_to(WORK)), 'created': time.strftime('%Y-%m-%dT%H:%M:%S')}
    if ready:
        rows = []
        for x in items:
            r = cache[doc_key(x)]
            rows.append({'chunk_id': x['chunk_id'], 'kind': x['kind'], 'section_id': x['section_id'], 'division': x['division'],
                         'status': x['status'], 'input_sha256': x['input_sha256'], 'model': CFG.model, 'dim': CFG.dim,
                         'input_format': INPUT_FORMAT, 'vector': dec(r['vector_f32_b64']).tolist()})
        schema = pa.schema([('chunk_id', pa.string()), ('kind', pa.string()), ('section_id', pa.string()), ('division', pa.string()),
                            ('status', pa.string()), ('input_sha256', pa.string()), ('model', pa.string()), ('dim', pa.int32()),
                            ('input_format', pa.string()), ('vector', pa.list_(pa.float32()))])
        pq.write_table(pa.Table.from_pylist(rows, schema=schema), BASE / 'vectors.parquet')
        manifest['vectors_parquet'] = 'vectors.parquet'
        manifest['vectors_parquet_sha256'] = hashlib.sha256((BASE / 'vectors.parquet').read_bytes()).hexdigest()
    (BASE / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    return manifest


def count_token_sample(items, n_long=150, n_random=150):
    """공식 count_tokens로 실제 토큰 수를 표본 확인한다(호출 비용 없음). 가장 긴 입력과 무작위 표본."""
    cli, _ = make_client()
    raw = cli._clients[0].inner
    long_ = sorted(items, key=lambda x: -len(x['input']))[:n_long]
    rng = np.random.default_rng(20261012)
    rest = [x for x in items if x not in long_]
    rnd = [rest[i] for i in rng.choice(len(rest), size=min(n_random, len(rest)), replace=False)]
    out = []
    for x in long_ + rnd:
        for attempt in range(5):
            try:
                n = raw.models.count_tokens(model=CFG.model, contents=x['input']).total_tokens
                out.append({'chunk_id': x['chunk_id'], 'chars': len(x['input']), 'est': x['est_tokens'], 'tokens': n})
                break
            except Exception as e:
                if emb.retryable_error(e):
                    time.sleep(2 ** attempt)
                    continue
                out.append({'chunk_id': x['chunk_id'], 'chars': len(x['input']), 'est': x['est_tokens'], 'tokens': None, 'error_type': type(e).__name__})
                break
    return out


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    a = argparse.ArgumentParser()
    a.add_argument('cmd', choices=['plan', 'tokens', 'run', 'export'])
    a.add_argument('--pick32', action='store_true')
    a.add_argument('--batch', type=int, default=10)
    a.add_argument('--pause', type=float, default=1.0)
    a.add_argument('--limit', type=int)
    args = a.parse_args()
    items, rid = load_inputs()
    BASE.mkdir(parents=True, exist_ok=True)
    if args.cmd == 'plan':
        p = plan(items, rid)
        (BASE / 'plan.json').write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(p, ensure_ascii=False, indent=1))
    elif args.cmd == 'tokens':
        res = count_token_sample(items)
        ok = [r for r in res if r['tokens']]
        ratio = [r['tokens'] / r['chars'] for r in ok]
        summary = {'sampled': len(res), 'ok': len(ok), 'max_tokens': max(r['tokens'] for r in ok), 'limit': MAX_INPUT_TOKENS,
                   'tokens_per_char_min': round(min(ratio), 4), 'tokens_per_char_mean': round(float(np.mean(ratio)), 4),
                   'tokens_per_char_max': round(max(ratio), 4),
                   'ratio_to_chunking_estimate_mean': round(float(np.mean([r['tokens'] / r['est'] for r in ok])), 3),
                   'ratio_to_chunking_estimate_max': round(max(r['tokens'] / r['est'] for r in ok), 3),
                   'bound_all_inputs_max_tokens': math.ceil(max(ratio) * max(len(x['input']) for x in items)),
                   'errors': [r for r in res if not r['tokens']][:5]}
        (BASE / 'token_sample.json').write_text(json.dumps({'summary': summary, 'rows': res}, ensure_ascii=False, indent=1), encoding='utf-8')
        print(json.dumps(summary, ensure_ascii=False, indent=1))
    elif args.cmd == 'run':
        cache = load_cache(CACHE)
        pool = pick32(items) if args.pick32 else items
        todo, seen = [], set()
        for x in pool:                      # 같은 입력(36개)은 한 번만 호출한다. 벡터는 입력 해시로 공유한다
            if doc_key(x) not in cache and x['input_sha256'] not in seen:
                seen.add(x['input_sha256'])
                todo.append(x)
        if args.limit is not None:
            todo = todo[:args.limit]
        print(f'대상 {len(pool)}개 중 캐시에 이미 있는 것 {sum(doc_key(x) in cache for x in pool)}개, 이번 호출 대상(중복 입력 제외) {len(todo)}개')
        stats = embed_batches(todo, cache, args.batch, args.pause) if todo else {'requests_attempted': 0, 'new_vectors': 0}
        stats.update({'pool': len(pool), 'todo': len(todo), 'pick32': args.pick32, 'time': time.strftime('%Y-%m-%dT%H:%M:%S')})
        with open(BASE / 'runs.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(stats, ensure_ascii=False) + '\n')
        print(json.dumps(stats, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(export(items, rid), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
