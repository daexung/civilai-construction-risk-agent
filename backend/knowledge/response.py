"""Verified answer construction promoted from local trial 5b. No trial routes or file logging."""
from __future__ import annotations
import hashlib,json,re,time
from backend.api import local_trial_answer as ta
CAPS={'attempts':30}
ANSWER_TIMEOUT_MS=20_000
def defaultdict_list():
    from collections import defaultdict
    return defaultdict(list)
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

class ResponseBuilder:
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

