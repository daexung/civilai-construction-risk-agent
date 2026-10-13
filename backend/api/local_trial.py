"""5·5b단계 로컬 시험 연결: 현재(4h) 근거 검색 정책을 로컬 화면에서 시험하는 전용 경로.

켜고 끄기
- 기본 꺼짐. `LOCAL_TRIAL_RETRIEVAL=on`일 때만 `/api/local-trial/*`가 동작한다(꺼져 있으면 404).
- 독립 실행: `python -m uvicorn backend.api.local_trial:app --host 127.0.0.1 --port 8010` (원격 저장·회원·사용량·분석을 초기화하지 않는다).
- 기존 `backend/api/main.py`에는 같은 옵션이 켜졌을 때만 이 라우터를 붙인다(꺼져 있으면 기존 동작 그대로).

이 모듈이 하는 일
- 사용자 질문 → 현재 검색·선택(`experiments/retrieval-v1/src/select_verified.py`, 4h 최종 정책) → 상태·근거 분류 → 설명·출처.
- 정상 답변 근거만 답변 생성 문맥으로 쓴다. 검토용 원문과 진단 후보는 모델에 합쳐 주지 않고 별도로만 보여 준다.
- 5b: 검색 상태(supported 등)와 답변 상태(답변 확인·질문 조건 확인 필요·원문 확인 필요…)를 나눈다. 모델은 원문 위치(S1.3)만 고르고
  인용문·출처는 코드가 모델에 준 줄에서 가져온다(답변 계층 로직은 `local_trial_answer.py`).
- 원격 Supabase·대화 저장·사용량 차감·피드백·분석 이벤트를 호출하지 않는다. 시험 기록은 로컬 파일에만 남긴다.
검색 규칙을 고치지 않는다(G02 불필요 보류·N19 자료 없음 미달 등 현재 한계를 그대로 드러낸다).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from backend.api import local_trial_answer as ta

ROOT = Path(__file__).resolve().parents[2]
RETRIEVAL = ROOT / 'experiments/retrieval-v1'
TRIAL_DIR = RETRIEVAL / 'pilots/step05b'
PRIOR_CACHES = [RETRIEVAL / 'pilots' / d / 'cache' for d in ('step05', 'step04h', 'step04g', 'step04f', 'step04e', 'step04d')]
PDF = ROOT / 'data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'
PAGE_MAP = ROOT / 'data/processed/page_map.json'
CAPS = {'attempts': 30, 'cost_usd': 1.0}
ANSWER_TIMEOUT_MS = 20_000
STATUS_LABEL = {'supported': '근거 있음', 'needs_confirmation': '확인 필요', 'not_found': '근거를 찾지 못함'}

REASON_TEXT = {
    'target_term_unconfirmed': '질문의 표현 {terms}이(가) 원문에 같은 글자로 없고 같은 대상인지 확인하지 못했어요.',
    'term_absent_in_corpus': '질문의 표현 {terms}이(가) 원문에 같은 글자로 없고 맞는 근거도 고르지 못했어요.',
    'target_mismatch_warning': '추가 대조에서 선택한 원문이 질문의 대상·작업과 다를 수 있다는 경고가 나왔어요. 참고 판정이라 원문을 지우지는 않았고 검토용으로만 보여 드려요.',
    'unconfirmed_chunk': '선택한 원문 설명이 어느 표에 속하는지 확정되지 않았어요.',
    'attribution_unconfirmed': '표의 제목이나 소속이 확정되지 않아 이 표가 질문 대상이 맞는지 확인이 필요해요.',
    'reference_unresolved': '원문이 가리키는 다른 절의 기준을 확정하지 못했어요.',
    'budget_required': '필요한 원문 일부를 모두 읽지 못했어요.',
    'list_incomplete': '목록 중 판단을 보류한 절이 있어요.',
    'list_scope_unverified': '질문 범위가 넓거나 부문이 정해지지 않아 목록이 빠짐없는지 확인하지 못했어요.',
    'list_from_section_catalog': '근거 줄 대신 절 목록으로 정리한 결과예요.',
    'negation_unverified': '질문의 부정·제외 조건을 근거 글로 확인하지 못했어요.',
    'division_choice_required': '같은 번호의 절이 여러 부문에 있어요. 어느 부문인지 골라 주세요.',
    'review_material_retained': '관련 표를 함께 읽었지만 소속 관계가 확정되지 않아 검토용으로만 보여 드려요.',
    'confirmation_context_unconfirmed': '관련 원문의 소속·수식이 확정되지 않아 검토용으로만 보여 드려요.',
    'unselected_unconfirmed_related': '질문과 관련 있어 보이는 원문이 있지만 소속이 확정되지 않았어요.',
    'rows_rejected': '선택한 표 행을 원문에서 확인하지 못했어요.',
    'rejected_primary_item': '선택한 근거 일부를 원문에서 확인하지 못했어요.',
    'model_missing': '질문에 필요한 조건이 더 있을 수 있어요.',
    'competing_alternative': '질문만으로는 구별되지 않는 비슷한 표가 더 있어요.',
    'query_rewritten': '질문을 바꿔 다시 찾은 결과라 같은 뜻인지 확인이 필요해요.',
    'no_primary': '질문에 맞는 근거를 하나로 정하지 못했어요.',
}
CONFIRM_ASK = {
    'target_term_unconfirmed': '질문의 {terms}이(가) 원문의 어떤 표현에 해당하는지 확인해 주세요.',
    'unconfirmed_chunk': '아래 검토용 원문의 소속 표를 원문에서 직접 확인해 주세요.',
    'attribution_unconfirmed': '표 제목과 적용 대상이 질문과 같은지 원문에서 확인해 주세요.',
    'reference_unresolved': '원문이 가리키는 다른 절의 기준을 따로 확인해 주세요.',
    'list_scope_unverified': '찾으려는 부문이나 공종 범위를 좁혀 주세요.',
    'division_choice_required': '부문(공통·토목·건축·기계설비·유지관리)을 알려 주세요.',
    'negation_unverified': '제외 조건이 적용되는지 원문에서 확인해 주세요.',
}


class AskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    request_id: str | None = None

    @field_validator('message')
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError('빈 질문')
        return v


def _enabled() -> bool:
    return os.environ.get('LOCAL_TRIAL_RETRIEVAL', 'off') == 'on'


class Engine:
    """검색 엔진(원문 DB 읽기 전용)과 선택기를 한 번만 만들고 질문마다 실행한다."""

    def __init__(self):
        for p in (str(RETRIEVAL / 'src'), str(ROOT)):
            if p not in sys.path:
                sys.path.insert(0, p)
        os.environ.setdefault('AGENT_LLM', 'on')
        import retrieve as rv  # noqa: WPS433
        import select_verified as sv  # noqa: WPS433
        from backend.agent.tools.llm import client as llm  # noqa: WPS433
        self.rv, self.sv, self.llm = rv, sv, llm
        TRIAL_DIR.mkdir(parents=True, exist_ok=True)
        self.ledger = TRIAL_DIR / 'ledger_05b.jsonl'
        self.caller = sv.ModelCaller(self.ledger, TRIAL_DIR / 'cache', CAPS, tag='', fallback_cache_dirs=PRIOR_CACHES)
        self.rt = rv.Retriever()
        self.vs = sv.VerifiedSelector(self.rt, self.caller)
        self.lock = threading.Lock()
        self.pages = json.loads(PAGE_MAP.read_text(encoding='utf-8'))['pages'] if PAGE_MAP.exists() else {}
        self.versions = self.vs.versions()
        self.qa_model = json.loads(llm.CONFIG_PATH.read_text(encoding='utf-8')).get('qa_model', llm.model_name())
        self.prompt = (Path(__file__).with_name('local_trial_qa.md')).read_text(encoding='utf-8')
        self._pdf = None

    # ---------- 원문·출처 ----------
    def page_info(self, pdf_page: int | None) -> dict:
        if not pdf_page:
            return {'pdf_page': None, 'printed_page': None}
        return {'pdf_page': pdf_page, 'printed_page': (self.pages.get(str(pdf_page)) or {}).get('printed_page')}

    def source_of(self, cid: str, role: str, validated: dict, note: str | None = None) -> dict | None:
        st = self.vs.store
        ch = st.chunk.get(cid)
        if ch is None or ch['kind'] == 'work':
            return None
        sec = self.vs.sel.sec.get(ch['section_id'], {})
        quotes = validated.get(cid, [])
        selected_text = {q['text'] for q in quotes}
        legend, notes = {}, {}
        lines = [{'n': ln['n'], 'text': ln['text'], 'display': ta.compact(ln['text'], legend, notes), 'selected': ln['text'] in selected_text,
                  'page': ln.get('page'), 'search_uid': ln.get('search_uid')} for ln in st.lines(cid)]
        pdf_page = next((ln['page'] for ln in lines if ln.get('page')), None)
        if pdf_page is None:
            m = re.search(r'full-p(\d+)', cid)
            pdf_page = int(m.group(1)) if m else sec.get('first_page')
        flags = []
        if ch['status'] != 'ok':
            flags.append(ch['status'])
        flags += [i.split(':')[0] for i in ch['issues']]
        return {'id': cid, 'role': role, 'division': sec.get('division'), 'section_no': sec.get('number'), 'section_title': sec.get('title'),
                'kind': '표' if ch['kind'] == 'table' else '설명', 'frame': st.frame(cid), 'lines': lines, **self.page_info(pdf_page),
                'shared_legend': [{'n': k, 'text': t} for k, t in sorted(notes.items())],
                'flags': sorted(set(flags)), 'note': note}

    # ---------- 질문 실행 ----------
    def totals(self) -> tuple[int, float]:
        return self.caller.totals()

    def ask(self, question: str, request_id: str) -> dict:
        t0 = time.perf_counter()
        att, cost = self.totals()
        if att >= CAPS['attempts'] - 3 or cost >= CAPS['cost_usd'] * 0.97:
            return {'request_id': request_id, 'status': 'error', 'status_label': '시험 한도 도달', 'search_status': 'error',
                    'answer_status': 'error', 'answer_status_label': '시험 한도 도달', 'answer_status_reason': {'code': 'trial_cap', 'text': '이번 시험의 호출 한도에 도달했어요.'},
                    'answer': None,
                    'reasons': [{'code': 'trial_cap', 'text': '이번 시험의 호출 한도에 도달해 더 이상 질문을 처리하지 않아요.'}], 'sources': [], 'review_material': [], 'diagnostic': [],
                    'alternatives': [], 'confirmations': [], 'generation': {'source': 'none'}, 'timing_ms': 0}
        with self.lock:
            api0 = self.rt.api_calls
            result = self.vs.run(question, qid=request_id, run_id='local-trial', fallback=False)
            new_api = self.rt.api_calls - api0
            if new_api:
                with open(self.ledger, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({'run_id': 'local-trial', 'qid': request_id, 'role': 'query_embedding', 'ok': True, 'attempts': new_api,
                                        'cost_usd': round(new_api * 30 / 1e6 * 0.20, 7), 'started': time.strftime('%Y-%m-%dT%H:%M:%S')}, ensure_ascii=False) + '\n')
        search_ms = round((time.perf_counter() - t0) * 1000)
        resp = self.build_response(question, request_id, result)
        resp['timing_ms'] = {'search_select': search_ms, 'total': round((time.perf_counter() - t0) * 1000)}
        self.log(question, request_id, result, resp)
        return resp

    def build_response(self, question: str, request_id: str, r: dict) -> dict:
        f = r['final']
        status = f.get('status', 'needs_confirmation')
        if r.get('method') == 'structural_number_lookup':
            return self.scope_response(request_id, r)
        validated = defaultdict_list()
        for p in r.get('validated', {}).get('primary', []) + r.get('validated', {}).get('supporting', []):
            validated[p['chunk_id']] = p.get('quotes', [])
        answer_ids = list(f.get('answer_evidence_chunks', []))
        review_ids = list(f.get('review_chunks', []))
        sources = [s for c in answer_ids if (s := self.source_of(c, 'answer', validated))]
        review = [s for c in review_ids if (s := self.source_of(c, 'review', validated, self.review_note(c, r)))]
        diag = [{'id': d['chunk_id'], 'label': self.short_label(d['chunk_id']), 'why': d.get('why') or '', 'in_context': bool(d.get('in_context'))}
                for d in r.get('diagnostic_candidates', []) if d['chunk_id'] not in set(answer_ids) | set(review_ids)]
        reasons, asks = self.user_reasons(f, r)
        alt = [{'division': a['division'], 'number': a['number'], 'title': a['title'], 'pdf_page': a.get('first_page')} for a in r.get('alternatives', [])]
        gen = {'source': 'none'}
        answer = None
        if status == 'supported':
            gen = self.generate(question, sources, request_id)
            cited = {(c['chunk_id'], c['line']) for c in gen.get('citations', [])}
            for s in sources:       # 출처 카드·'답변에 인용' 표시는 실제 인용 위치에서만 만든다
                for ln in s['lines']:
                    ln['cited'] = (s['id'], ln['n']) in cited
                s['cited'] = any(ln['cited'] for ln in s['lines'])
        a_status, a_code = ta.answer_state(status, gen if status == 'supported' else None)
        if a_status == 'confirmed':
            answer = gen['text']
        elif a_status == 'condition_unconfirmed':
            answer = ta.condition_text(gen.get('unmatched', []))
            asks = [{'code': 'condition_unconfirmed', 'text': '질문의 조건(두께·규격·종류 등)과 같은 행·열이 아래 원문 표에 있는지 확인해 주세요.'}] + \
                   [{'code': f'unmatched_{i}', 'text': f'질문의 “{u}” 조건이 원문의 어느 칸에 해당하는지 확인해 주세요.'} for i, u in enumerate(gen.get('unmatched', []))] + asks
        elif a_status == 'source_check_needed':
            answer = '근거 원문을 아래에 그대로 보여 드려요. ' + ta.REASON_TEXT.get(a_code, ta.REASON_TEXT['validation_failed'])
        elif a_status == 'needs_confirmation':
            answer = '확정 답변을 드리기 어려워요. 아래 확인할 것과 원문을 먼저 확인해 주세요.' + (' 관련 원문은 검토용으로만 보여 드려요.' if review or sources else '')
            gen = {'source': 'status_template'}
        else:
            answer = '현재 읽은 범위에서 질문에 맞는 근거를 찾지 못했어요. 문서 전체에 해당 작업이 없다는 뜻은 아니에요.'
            gen = {'source': 'status_template'}
            sources, review = [], []     # 관련 없는 후보를 근거로 보이지 않는다
        related = []
        if status == 'needs_confirmation':
            related, sources = sources, []      # 확정 답변이 없으므로 '출처(정상 답변 근거)'로 보이지 않게 한다
        return {'request_id': request_id, 'status': status, 'status_label': STATUS_LABEL.get(status, status), 'search_status': status,
                'answer_status': a_status, 'answer_status_label': ta.STATE_LABEL[a_status],
                'answer_status_reason': {'code': a_code, 'text': ta.REASON_TEXT.get(a_code, '')},
                'answer': answer, 'reasons': reasons,
                'confirmations': asks, 'sources': sources, 'related': related, 'review_material': review, 'diagnostic': diag, 'alternatives': alt, 'generation': gen,
                'citations': gen.get('citations', []), 'value_claims': gen.get('values', []),
                'list': self.list_out(r), 'applicability': f.get('applicability', 'unknown'),
                'versions': {'release_id': self.versions['release_id'], 'chunk_set_id': self.versions['chunk_set_id'],
                             'policy': '4h(현재 기본)', 'select_verified_code_sha256': self.versions['select_verified_code_sha256'][:12]}}

    def scope_response(self, request_id: str, r: dict) -> dict:
        alt = [{'division': a['division'], 'number': a['number'], 'title': a['title'], 'pdf_page': a.get('first_page')} for a in r.get('alternatives', [])]
        return {'request_id': request_id, 'status': 'needs_confirmation', 'status_label': STATUS_LABEL['needs_confirmation'], 'search_status': 'needs_confirmation',
                'answer_status': 'needs_confirmation', 'answer_status_label': ta.STATE_LABEL['needs_confirmation'],
                'answer_status_reason': {'code': 'division_choice_required', 'text': REASON_TEXT['division_choice_required']},
                'answer': '같은 번호의 절이 여러 부문에 있어서 어느 쪽을 말씀하시는지 먼저 골라 주세요. 아래 절들은 후보일 뿐이고 정답이나 계산 대상으로 정한 것이 아니에요.',
                'reasons': [{'code': 'division_choice_required', 'text': REASON_TEXT['division_choice_required']}],
                'confirmations': [{'code': 'division_choice_required', 'text': CONFIRM_ASK['division_choice_required']}],
                'sources': [], 'related': [], 'review_material': [], 'diagnostic': [], 'alternatives': alt, 'generation': {'source': 'structural_lookup'},
                'citations': [], 'value_claims': [], 'applicability': 'unknown',
                'versions': {'release_id': self.versions['release_id'], 'chunk_set_id': self.versions['chunk_set_id'], 'policy': '4h(현재 기본)',
                             'select_verified_code_sha256': self.versions['select_verified_code_sha256'][:12]}}

    def list_out(self, r: dict) -> dict | None:
        lst = r.get('list')
        if not lst:
            return None
        sec = self.vs.sel.sec
        inc = [{'section_id': s, 'division': sec[s]['division'], 'number': sec[s]['number'], 'title': sec[s]['title'], 'pdf_page': sec[s].get('first_page')}
               for s in lst.get('included', []) if s in sec]
        return {'scope': lst.get('scope'), 'included': inc, 'uncertain_n': len(lst.get('uncertain', [])),
                'candidates_processed': lst.get('candidates_processed'), 'scope_completeness': lst.get('scope_completeness'),
                'note': '요청한 범위의 목록이 빠짐없는지는 확인하지 못했어요. 확인된 범위는 위 절들이에요.'}

    def short_label(self, cid: str) -> str:
        ch = self.vs.store.chunk.get(cid)
        if not ch:
            return cid
        sec = self.vs.sel.sec.get(ch['section_id'], {})
        return f"{sec.get('division', '')} {sec.get('number', '')} {sec.get('title', '')}".strip()

    def review_note(self, cid: str, r: dict) -> str:
        ch = self.vs.store.chunk.get(cid, {})
        if any(i.startswith('membership_unconfirmed') for i in ch.get('issues', [])):
            return '소속 미확정 설명(어느 표에 속하는지 확정되지 않음)'
        if any(i.startswith('formula_unresolved') for i in ch.get('issues', [])):
            return '수식 미확정 설명'
        if any(x['chunk_id'] == cid for x in r.get('retained_review', [])):
            return '인접 설명 연쇄로 닿는 표(소속 관계 미확정)'
        if cid in (r['final'].get('confirmation_only_chunks') or []):
            return '확인이 끝나지 않아 검토용으로만 쓰는 선택 근거'
        return '검토용 원문'

    def user_reasons(self, f: dict, r: dict) -> tuple[list[dict], list[dict]]:
        out, asks, seen = [], [], set()
        for x in f.get('reasons', []):
            code = x['rule']
            if code == 'alias_confirmed' or code in seen or code not in REASON_TEXT:
                continue
            seen.add(code)
            terms = ', '.join(f"`{t}`" for t in x.get('terms', [])) if x.get('terms') else ''
            out.append({'code': code, 'text': REASON_TEXT[code].format(terms=terms or '질문의 표현')})
            if code in CONFIRM_ASK:
                asks.append({'code': code, 'text': CONFIRM_ASK[code].format(terms=terms or '질문의 표현')})
        return out, asks

    # ---------- 답변 생성(검색이 supported일 때만) ----------
    def generate(self, question: str, sources: list[dict], request_id: str = '') -> dict:
        """모델이 원문 위치를 고르고 코드가 인용문을 가져온다. 반환 dict: state(answered|condition_unconfirmed|failed), code, text, citations, values."""
        ctx, provided, truncated = ta.build_context(sources)
        gen = {'source': 'verified_source', 'model': self.qa_model, 'context_chars': len(ctx), 'truncated': truncated,
               'provided': {a: {'chunk_id': p['chunk_id'], 'lines': sorted(p['lines'])} for a, p in provided.items()}}
        if not ctx:
            return {**gen, 'state': 'failed', 'code': 'no_context'}
        if truncated:
            return {**gen, 'state': 'failed', 'code': 'context_budget'}
        if self.totals()[0] >= CAPS['attempts'] - 2:
            return {**gen, 'state': 'failed', 'code': 'cap_reached'}
        payload = f'질문: {question}\n\n근거 자료:\n{ctx}'
        t = time.perf_counter()
        with self.lock:
            self.caller.usage.clear()
            try:
                res = self.llm.generate(payload, self.prompt, response_schema=ta.QA_SCHEMA, timeout_ms=ANSWER_TIMEOUT_MS, model=self.qa_model)
                err = None
            except Exception as exc:  # 생성 실패·시간 초과는 원문 표시로 전환한다(모델 답변 성공으로 세지 않는다)
                res, err = None, type(exc).__name__ + ':' + str(exc)[:80]
            usage = list(self.caller.usage)
        gen['latency_ms'] = round((time.perf_counter() - t) * 1000)
        pin = sum(u.get('prompt') or 0 for u in usage) or int(0.7 * (len(payload) + len(self.prompt)))
        pout = sum((u.get('output') or 0) + (u.get('thoughts') or 0) for u in usage)
        cost = round(pin / 1e6 * self.sv.PRICE['input_per_m'] + pout / 1e6 * self.sv.PRICE['output_per_m'], 5)
        gen['attempts'] = max(len(usage), getattr(res, 'attempts', 0) or 0, 1)
        gen['usage'] = {'prompt_tokens': pin, 'output_tokens': pout, 'cost_usd': cost}
        self.ledger_add(request_id, ok=res is not None, attempts=gen['attempts'], latency=time.perf_counter() - t, cost=cost)
        if err:
            return {**gen, 'state': 'failed', 'code': 'generation_failed', 'error': err}
        gen['provider'] = getattr(res, 'provider', None)
        try:
            raw = json.loads(res.text)
        except ValueError:
            return {**gen, 'state': 'failed', 'code': 'schema', 'raw_text': str(res.text)[:200]}
        out = ta.validate(raw, question, provided)
        gen.update(out)
        gen['model_status'] = raw.get('status') if isinstance(raw, dict) else None
        if out['state'] == 'answered':
            gen['source'] = 'llm'
        if out['state'] != 'answered' and isinstance(raw, dict):
            # 시험 기록용(화면 답변에는 쓰지 않는다): 확정하지 못한 모델 출력의 일부를 남겨 원인을 확인할 수 있게 한다.
            ev = raw.get('evidence') if isinstance(raw.get('evidence'), list) else []
            gen['raw'] = {'conclusion': str(raw.get('conclusion'))[:300], 'explanation': str(raw.get('explanation'))[:300],
                          'evidence': [{k: str(e.get(k))[:40] for k in ('location', 'value', 'unit')} for e in ev if isinstance(e, dict)][:6],
                          'unmatched_conditions': [str(u)[:60] for u in raw.get('unmatched_conditions', [])][:5] if isinstance(raw.get('unmatched_conditions'), list) else []}
        return gen

    def ledger_add(self, qid: str, ok: bool, attempts: int, latency: float, cost: float) -> None:
        # 단가는 select_verified의 PRICE(ai.google.dev 공개값 추정, Vertex 공식 가격 미확인)를 실제 토큰 수에 곱해 계산한다.
        with open(self.ledger, 'a', encoding='utf-8') as f:
            f.write(json.dumps({'run_id': 'local-trial-5b', 'qid': qid, 'role': 'answer', 'ok': ok, 'attempts': attempts, 'cost_usd': cost,
                                'latency_sec': round(latency, 2), 'started': time.strftime('%Y-%m-%dT%H:%M:%S')}, ensure_ascii=False) + '\n')

    def log(self, question: str, request_id: str, r: dict, resp: dict) -> None:
        f = r['final']
        rec = {'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'request_id': request_id, 'question': question, 'status': resp['status'],
               'answer_status': resp.get('answer_status'), 'answer_status_reason': (resp.get('answer_status_reason') or {}).get('code'),
               'citation_locations': [c['location'] for c in resp.get('citations', [])], 'value_claims': resp.get('value_claims', []),
               'method': r.get('method'),
               'reasons': [x['rule'] for x in f.get('reasons', [])], 'selected': [p['chunk_id'] for p in r.get('validated', {}).get('primary', []) + r.get('validated', {}).get('supporting', [])],
               'answer_evidence': f.get('answer_evidence_chunks', []), 'review': f.get('review_chunks', []),
               'diagnostic': [d['chunk_id'] for d in r.get('diagnostic_candidates', [])], 'confirmed': f.get('confirmed_chunks', []),
               'absent_terms': r.get('absent_terms'), 'generation': {k: v for k, v in resp.get('generation', {}).items() if k not in ('citations', 'values', 'text')},
               'timing_ms': resp.get('timing_ms'), 'model_calls': [(c.get('role'), c.get('cached'), c.get('attempts')) for c in r.get('calls', [])]}
        with open(TRIAL_DIR / 'trial_log.jsonl', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + '\n')

    # ---------- 쪽 이미지 ----------
    def page_png(self, page: int) -> bytes:
        import pymupdf
        if self._pdf is None:
            self._pdf = pymupdf.open(str(PDF))
        if page < 1 or page > len(self._pdf):
            raise LookupError('쪽 범위 오류')
        return self._pdf[page - 1].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), alpha=False).tobytes('png')


def defaultdict_list():
    from collections import defaultdict
    return defaultdict(list)


_ENGINE: Engine | None = None
_ENGINE_LOCK = threading.Lock()


def engine() -> Engine:
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = Engine()
    return _ENGINE


router = APIRouter(prefix='/api/local-trial')


def _guard() -> None:
    if not _enabled():
        raise HTTPException(status_code=404, detail='local trial disabled')


@router.get('/health')
def trial_health() -> dict:
    _guard()
    e = engine()
    att, cost = e.totals()
    return {'enabled': True, 'policy': '4h(현재 기본)', 'release_id': e.versions['release_id'], 'chunk_set_id': e.versions['chunk_set_id'],
            'attempts_used': att, 'cost_used_usd': round(cost, 4), 'caps': CAPS, 'answer_model': e.qa_model,
            'remote_calls': 'none (Supabase·저장·사용량·분석 미사용)'}


@router.post('/ask')
def trial_ask(payload: AskRequest) -> JSONResponse:
    _guard()
    rid = payload.request_id or uuid.uuid4().hex[:12]
    try:
        return JSONResponse(engine().ask(payload.message, rid))
    except Exception as exc:  # 연결·검색 오류는 숨기지 않고 구분해 알린다
        TRIAL_DIR.mkdir(parents=True, exist_ok=True)
        with open(TRIAL_DIR / 'trial_log.jsonl', 'a', encoding='utf-8') as fh:
            fh.write(json.dumps({'at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'request_id': rid, 'question': payload.message, 'error': type(exc).__name__ + ': ' + str(exc)[:200]},
                                ensure_ascii=False) + '\n')
        raise HTTPException(status_code=500, detail={'code': 'LOCAL_TRIAL_ERROR', 'message': '시험 경로에서 오류가 났어요. 실행 기록을 확인해 주세요.'}) from exc


@router.get('/page/{page}.png')
def trial_page(page: int) -> Response:
    _guard()
    try:
        return Response(engine().page_png(page), media_type='image/png')
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


app = FastAPI(title='품셈이 로컬 시험(5단계)')
app.add_middleware(CORSMiddleware, allow_origins=['http://127.0.0.1:3010', 'http://localhost:3010'], allow_methods=['GET', 'POST'], allow_headers=['*'])
app.include_router(router)


@app.get('/api/health')
def health() -> dict:
    return {'status': 'ok', 'local_trial': _enabled()}
