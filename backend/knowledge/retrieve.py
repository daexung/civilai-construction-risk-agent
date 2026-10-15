"""키워드(BM25)·벡터 결합 검색(RRF)과 근거 조회(evidence.Reader) 연결(4단계).

  python -B experiments/retrieval-v1/src/retrieve.py "콘크리트 표면 마무리 기준" [--mode hybrid|bm25|vector]

- 기존 구성을 그대로 쓴다: backend/agent/tools/search/bm25.py의 BM25(Index, tokens), RRF K=60, 방식마다 후보 20개.
  질문 임베딩은 공통 경로 backend/shared/embedding.py(키 번갈아 사용)와 질문 캐시를 쓴다. 답변 모델은 호출하지 않는다.
- work·rule·table을 하나의 논리 색인에서 검색한다. 질문 유형으로 종류를 제외하지 않는다.
- 같은 원문 인용에서 파생된 조각(공종 조각의 적용 범위 인용과 설명 조각 등)은 같은 절 안에서만 줄이고, 줄인 것은 기록한다.
- 질문에 'OO부문'이 명시될 때만 그 부문으로 한정한다(기존 개발 규칙). 정규화는 검색용으로만 적용하고 원문 숫자·단위는 바꾸지 않는다.
- 벡터·원문·청킹 버전이 맞지 않으면 거부한다.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import psycopg

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
from . import db  # noqa: E402
from . import embed_index as ei  # noqa: E402
from . import evidence as ev  # noqa: E402
from backend.agent.tools.search.bm25 import Index, tokens  # noqa: E402,F401
from backend.shared import embedding as emb  # noqa: E402

CONFIG = {
    'candidates_per_method': 20, 'rrf_k': 60, 'top_sections': 5, 'evidence_sections': 3, 'chunks_per_section': 2,
    'evidence_depth': 1, 'evidence_budget_tokens': 4000, 'dedup_overlap': 0.8,
    'normalization': [['펌프카', '펌프차'], ['루베', '㎥'], ['입방미터', '㎥'], ['평방미터', '㎡'], ['m3', '㎥'], ['m2', '㎡']],
    'division_filter': '질문에 \'OO부문\'이 명시된 경우만',
    'group_target_search': {'top_children': 3, 'confirm': False},
}
DIVISIONS = {'공통부문': '공통부문', '토목부문': '토목부문', '건축부문': '건축부문', '기계설비부문': '기계설비부문', '유지관리부문': '유지관리부문'}


def config_hash():
    return hashlib.sha256(json.dumps(CONFIG, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def code_hash():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def normalize(q):
    """검색용 정규화. 원문 글은 바꾸지 않는다."""
    for a, b in CONFIG['normalization']:
        q = re.sub(rf'(?<![A-Za-z]){re.escape(a)}(?![A-Za-z0-9])', b, q) if a[0].isascii() else q.replace(a, b)
    return q


def explicit_division(q):
    for d in DIVISIONS:
        if d in q:
            return d
    return None


class Retriever:
    def __init__(self, conn=None, embed_queries=True, vectors=True):
        self.own = conn is None
        self.conn = conn or psycopg.connect(db.dsn())
        self.conn.read_only = True
        self.reader = ev.Reader(self.conn, ei.CS)
        items, rid = ei.load_inputs(self.conn)
        self.items = items
        self.by_id = {x['chunk_id']: x for x in items}
        self.has_vectors = vectors
        self.manifest = {'ready': False, 'all_inputs_sha256': ei.sha('\n'.join(x['input_sha256'] for x in items))}
        if vectors:
            manifest_path = ei.BASE / 'manifest.json'
            if not manifest_path.exists():
                raise RuntimeError('벡터 색인이 준비되지 않음(manifest 없음): embed_index.py export')
            self.manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            if not self.manifest.get('ready'):
                raise RuntimeError(f"벡터 색인이 ready가 아님: 누락 {self.manifest.get('missing_count')}개")
            if (self.manifest['chunk_set_id'], self.manifest['release_id']) != (ei.CS, rid):
                raise RuntimeError('벡터의 청킹 묶음·원문 버전이 현재 조회 버전과 다름')
            if (self.manifest['model'], self.manifest['dim'], self.manifest['input_format']) != (ei.CFG.model, ei.CFG.dim, ei.INPUT_FORMAT):
                raise RuntimeError('벡터의 모델·차원·입력 형식이 현재 설정과 다름')
            import pyarrow.parquet as pq
            rows = pq.read_table(ei.BASE / 'vectors.parquet').to_pylist()
            by_id = {r['chunk_id']: r for r in rows}
            if len(by_id) != len(items) or set(by_id) != set(self.by_id):
                raise RuntimeError('Vector/chunk coverage mismatch')
            for x in items:
                r = by_id[x['chunk_id']]
                if (r['input_sha256'], r['model'], r['dim'], r['input_format']) != (x['input_sha256'], ei.CFG.model, ei.CFG.dim, ei.INPUT_FORMAT):
                    raise RuntimeError('Vector input/version mismatch')
            if hashlib.sha256((ei.BASE / 'vectors.parquet').read_bytes()).hexdigest() != self.manifest['vectors_parquet_sha256']:
                raise RuntimeError('Vector checksum mismatch')
            self.matrix = np.asarray([by_id[x['chunk_id']]['vector'] for x in items], dtype=np.float32)
            if not np.isfinite(self.matrix).all() or np.any(np.linalg.norm(self.matrix,axis=1)==0):
                raise RuntimeError('Invalid vectors')
            self.matrix /= np.linalg.norm(self.matrix, axis=1, keepdims=True)
        self.ids = [x['chunk_id'] for x in items]
        self.pos = {c: i for i, c in enumerate(self.ids)}
        self.division_of = np.array([x['division'] or '' for x in items])
        chunk_dicts = [{'chunk_id': x['chunk_id'], 'text': x['text'], 'division': x['division']} for x in items]
        self.bm25_all = Index(chunk_dicts)
        self.bm25_div = {}
        self.chunk_dicts = chunk_dicts
        # 원문 인용 겹침(파생 조각 판별)
        self.quotes = defaultdict(set)
        for cid, uid in self.conn.execute("""select chunk_id, search_uid from rag_knowledge.chunk_sources
                                             where chunk_set_id=%s and role in ('body', 'scope_quote')""", (ei.CS,)).fetchall():
            self.quotes[cid].add(uid)
        self.q_cache = ei.load_cache(ei.QUERY_CACHE) if vectors else {}
        self.embed_queries = embed_queries
        self.client = None
        self.api_calls = 0
        self.api_new_vectors = 0
        self.api_cache_hits = 0

    def close(self):
        if self.own:
            self.conn.close()

    # --- 질문 임베딩 ---
    def query_vector(self, q):
        if len(self.q_cache) >= 128:
            self.q_cache.clear()
        packed = emb.query_input(q, ei.CFG)
        key = (emb.sha256(packed), ei.CFG.provider, ei.CFG.model, ei.CFG.dim, ei.QUERY_FORMAT, 'query')
        if key in self.q_cache:
            self.api_cache_hits += 1
            return ei.dec(self.q_cache[key]['vector_f32_b64']), 0.0
        if not self.embed_queries:
            raise RuntimeError('질문 벡터가 캐시에 없고 임베딩 호출이 꺼져 있음')
        if self.client is None:
            self.client, _ = ei.make_client()
        t = time.perf_counter()
        for attempt in range(5):
            try:
                self.api_calls += 1
                v = emb.embed_texts(self.client, [packed], config=ei.CFG, task='query')
                ei.check_vectors(v, 1)
                break
            except Exception as e:
                if emb.retryable_error(e) and attempt < 4:
                    time.sleep(min(30, 2 ** (attempt + 1)))
                    continue
                raise RuntimeError(f'질문 임베딩 실패({type(e).__name__})') from None
        sec = time.perf_counter() - t
        row = {'input_sha256': key[0], 'provider': key[1], 'model': key[2], 'dim': key[3], 'input_format': key[4],
               'purpose': 'query', 'vector_f32_b64': ei.enc(v[0]), 'query_text_sha256': emb.sha256(q),
               'created': time.strftime('%Y-%m-%dT%H:%M:%S')}
        ei.append_rows(ei.QUERY_CACHE, [row])
        self.q_cache[key] = row
        self.api_new_vectors += 1
        return np.asarray(v[0], dtype=np.float32), sec

    # --- 검색 ---
    def _bm25(self, q, division):
        if division is None:
            idx, sub = self.bm25_all, None
        else:
            if division not in self.bm25_div:
                sub = [c for c in self.chunk_dicts if c['division'] == division]
                self.bm25_div[division] = Index(sub) if sub else None
            idx = self.bm25_div[division]
        if idx is None:
            return []
        return [(s, c['chunk_id']) for s, c in idx.search(q, CONFIG['candidates_per_method'])]

    def _vector(self, vec, division):
        scores = self.matrix @ (vec / np.linalg.norm(vec))
        if division is not None:
            scores = np.where(self.division_of == division, scores, -2.0)
        top = np.argsort(-scores)[:CONFIG['candidates_per_method']]
        return [(float(scores[i]), self.ids[i]) for i in top if scores[i] > -2.0]

    def search(self, query, mode='hybrid', restrict_sections=None):
        """질문 하나의 후보. mode: bm25 | vector | hybrid. restrict_sections가 있으면 그 절의 조각만(상위 묶음 하위 절 탐색)."""
        t0 = time.perf_counter()
        if mode != 'bm25' and not self.has_vectors:
            raise RuntimeError('벡터 없이 열었으므로 bm25 모드만 가능')
        nq = normalize(query)
        division = explicit_division(query)
        embed_sec = 0.0
        bm, vc = [], []
        if mode in ('bm25', 'hybrid'):
            bm = self._bm25(nq, division)
        vec = None
        if mode in ('vector', 'hybrid'):
            vec, embed_sec = self.query_vector(nq)
            vc = self._vector(vec, division)
        if restrict_sections is not None:
            keep = {c for c, x in self.by_id.items() if x['section_id'] in restrict_sections}
            # 제한 탐색은 하위 절 안 전체에서 다시 순위를 낸다(후보 20개 컷 이후 필터가 아님)
            if mode in ('bm25', 'hybrid'):
                sub = Index([c for c in self.chunk_dicts if c['chunk_id'] in keep]) if keep else None
                bm = [(s, c['chunk_id']) for s, c in sub.search(nq, CONFIG['candidates_per_method'])] if sub else []
            if vec is not None:
                scores = self.matrix @ (vec / np.linalg.norm(vec))
                idx = [self.pos[c] for c in keep]
                order = sorted(idx, key=lambda i: -scores[i])[:CONFIG['candidates_per_method']]
                vc = [(float(scores[i]), self.ids[i]) for i in order]
        ranks = defaultdict(dict)
        for r, (s, c) in enumerate(bm, 1):
            ranks[c]['bm25'] = (r, s)
        for r, (s, c) in enumerate(vc, 1):
            ranks[c]['vector'] = (r, s)
        K = CONFIG['rrf_k']
        fused = sorted(({'chunk_id': c, 'score': sum(1 / (K + v[0]) for v in rk.values()),
                         'bm25_rank': rk.get('bm25', (None,))[0], 'bm25_score': rk.get('bm25', (None, None))[1],
                         'vector_rank': rk.get('vector', (None,))[0], 'cosine': rk.get('vector', (None, None))[1]}
                        for c, rk in ranks.items()), key=lambda x: (-x['score'], x['chunk_id']))
        # 파생 조각 줄이기: 같은 절 안에서 원문 인용이 80% 이상 이미 선택된 조각에 담긴 조각만 줄인다
        kept, dropped = [], []
        covered = defaultdict(list)
        for h in fused:
            x = self.by_id[h['chunk_id']]
            q = self.quotes.get(h['chunk_id'], set())
            dup_of = None
            if q:
                for other in covered[x['section_id']]:
                    if len(q & self.quotes[other]) / len(q) >= CONFIG['dedup_overlap']:
                        dup_of = other
                        break
            if dup_of:
                dropped.append({**h, 'reason': 'derived_duplicate', 'duplicate_of': dup_of})
            else:
                kept.append(h)
                covered[x['section_id']].append(h['chunk_id'])
        sections, seen = [], {}
        for h in kept:
            sid = self.by_id[h['chunk_id']]['section_id']
            if sid not in seen:
                seen[sid] = {'section_id': sid, 'division': self.by_id[h['chunk_id']]['division'], 'best_score': h['score'], 'chunks': []}
                sections.append(seen[sid])
            seen[sid]['chunks'].append(h)
        return {'query': query, 'normalized_query': nq, 'division_filter': division, 'mode': mode,
                'bm25': [{'rank': r, 'score': s, 'chunk_id': c} for r, (s, c) in enumerate(bm, 1)],
                'vector': [{'rank': r, 'cosine': s, 'chunk_id': c} for r, (s, c) in enumerate(vc, 1)],
                'fused': kept, 'dropped': dropped, 'sections': sections,
                'top_cosine': vc[0][0] if vc else None, 'top_bm25': bm[0][0] if bm else None,
                'timing_ms': {'embed_api': round(embed_sec * 1000, 1), 'search': round((time.perf_counter() - t0 - embed_sec) * 1000, 1)}}

    # --- 검색 + 근거 조회 ---
    def retrieve(self, query, mode='hybrid', with_evidence=True):
        r = self.search(query, mode)
        r['evidence'] = []
        r['group_target_search'] = []
        r['extra_searches'] = 0
        if not with_evidence:
            return r
        t = time.perf_counter()
        for sec in r['sections'][:CONFIG['evidence_sections']]:
            ids = [h['chunk_id'] for h in sec['chunks'][:CONFIG['chunks_per_section']]]
            res = self.reader.read(ids, CONFIG['evidence_depth'], CONFIG['evidence_budget_tokens'], include_cells=False)
            r['evidence'].append({'section_id': sec['section_id'], 'selected_chunks': ids, 'result': res})
            # 상위 묶음 참조는 하위 절 목록만 오므로 질문으로 하위 절 후보를 좁힌다(확정하지 않음)
            for u in res['unresolved_references']:
                if u['kind'] == 'group_target_not_expanded' and r['extra_searches'] < 2:
                    kids = [k['section_id'] for k in u['children']]
                    sub = self.search(query, mode, restrict_sections=set(kids))
                    r['extra_searches'] += 1
                    cands = [{'section_id': s['section_id'], 'best_score': s['best_score'],
                              'chunk_ids': [c['chunk_id'] for c in s['chunks'][:2]]} for s in sub['sections'][:CONFIG['group_target_search']['top_children']]]
                    r['group_target_search'].append({'edge_id': u['edge_id'], 'from_section': sec['section_id'], 'children': len(kids),
                                                    'candidates': cands, 'selected': None,
                                                    'status': 'candidates_not_confirmed' if cands else 'unresolved',
                                                    'note': '후보만 제시한다. 한 절을 적용 확정으로 고르지 않는다.'})
        r['timing_ms']['evidence'] = round((time.perf_counter() - t) * 1000, 1)
        return r


def versions(rt):
    return {'chunk_set_id': ei.CS, 'release_id': rt.reader.rid, 'model': ei.CFG.model, 'dim': ei.CFG.dim, 'input_format': ei.INPUT_FORMAT,
            'vectors_sha256': rt.manifest.get('vectors_parquet_sha256'), 'all_inputs_sha256': rt.manifest['all_inputs_sha256'],
            'config_sha256': config_hash(), 'code_sha256': code_hash(), 'evidence_code_sha256': hashlib.sha256((HERE / 'evidence.py').read_bytes()).hexdigest()}




