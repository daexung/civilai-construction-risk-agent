import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import LocalTrial from './LocalTrial';
import { askTrial, trialHealth } from '../localTrialApi';

jest.mock('../localTrialApi', () => ({ askTrial: jest.fn(), trialHealth: jest.fn(), trialPageUrl: (p) => `/page/${p}.png` }));

const src = (id, extra = {}) => ({ id, role: 'primary', division: '건축부문', section_no: '6-4-3', section_title: '방수모르타르 바름', kind: '표',
  frame: [], lines: [{ n: 1, text: '미장공 0.056', selected: true }], pdf_page: 662, printed_page: 606, flags: [], note: null, ...extra });
const base = { request_id: 'r', reasons: [], confirmations: [], sources: [], related: [], review_material: [], diagnostic: [], alternatives: [],
  generation: { source: 'status_template' }, versions: { release_id: 'rk-x-37f81b5cfb1b', chunk_set_id: 'cs', policy: '4h(현재 기본)', select_verified_code_sha256: 'h' } };

let root, container;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  window.HTMLElement.prototype.scrollIntoView = jest.fn();
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
  trialHealth.mockReset().mockResolvedValue({}); askTrial.mockReset();
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

async function ask(response) {
  askTrial.mockResolvedValueOnce(response);
  await act(async () => root.render(<LocalTrial />));
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: '질문' } }));
  await act(async () => Simulate.submit(container.querySelector('form')));
  return container.querySelector('[data-testid="trial-answer"]');
}

test('confirmed answer shows its sources as normal evidence with the exact cited line marked', async () => {
  const lines = [{ n: 1, text: '미장공 0.056', selected: true, cited: true }, { n: 2, text: '보통인부 0.04', selected: false, cited: false }];
  const card = await ask({ ...base, status: 'supported', status_label: '근거 있음', search_status: 'supported', answer_status: 'confirmed',
    answer_status_label: '답변 확인', answer_status_reason: { code: 'verified', text: '원문 위치 확인을 통과했어요.' }, answer: '0.056인입니다.',
    sources: [src('a', { lines, cited: true })], generation: { source: 'llm' },
    value_claims: [{ value: '0.056', unit: '인', location: 'S1.1', declared: true, column_name: '미장공 (인)', row_label: '15㎜', alignment: 'column_row', conditions: [{ number: 15, ok: true, where: 'row' }] }] });
  expect(card.dataset.status).toBe('supported');
  expect(card.dataset.answerStatus).toBe('confirmed');
  expect(card.querySelector('.lt-badge').textContent).toBe('답변 확인');
  expect(card.textContent).toContain('출처 (정상 답변 근거)');
  expect(card.querySelectorAll('[data-testid="trial-source"]').length).toBe(1);
  expect(card.querySelectorAll('[data-cited="true"]').length).toBe(1);
  expect(card.querySelector('[data-testid="trial-values"]').textContent).toContain('0.056');
});

test('confirmed answer keeps uncited normal evidence folded away from the main source list', async () => {
  const cited = src('a', { cited: true, lines: [{ n: 1, text: '③ 9-1-1을 따른다', selected: true, cited: true }] });
  const other = src('b', { cited: false, section_no: '6-4-1', lines: [{ n: 1, text: '다른 설명', selected: false, cited: false }] });
  const card = await ask({ ...base, status: 'supported', status_label: '근거 있음', answer_status: 'confirmed', answer_status_label: '답변 확인',
    answer: '9-1-1을 따라요.', sources: [other, cited], generation: { source: 'llm' } });
  expect(card.querySelectorAll('[data-testid="trial-source"]').length).toBe(1);
  expect(card.querySelector('[data-testid="trial-source"]').textContent).toContain('인용');
  const folded = card.querySelector('[data-testid="trial-uncited"]');
  expect(folded.tagName).toBe('DETAILS');
  expect(folded.textContent).toContain('인용하지 않았어요');
  expect(folded.querySelectorAll('[data-cited="true"]').length).toBe(0);
});

test('search supported but condition not matched is not shown as confirmed and keeps the source open', async () => {
  const card = await ask({ ...base, status: 'supported', status_label: '근거 있음', search_status: 'supported', answer_status: 'condition_unconfirmed',
    answer_status_label: '질문 조건 확인 필요', answer_status_reason: { code: 'model_unmatched', text: '조건에 맞는 값을 확인하지 못했어요.' },
    answer: '읽은 원문에서 질문의 조건에 맞는 값을 확인하지 못했어요.', confirmations: [{ code: 'condition_unconfirmed', text: '조건을 확인해 주세요' }],
    sources: [src('a', { lines: [{ n: 1, text: '철판두께 0.6 | 규격 250', selected: true, cited: false }] })], generation: { source: 'verified_source', code: 'model_unmatched' } });
  expect(card.dataset.answerStatus).toBe('condition_unconfirmed');
  expect(card.querySelector('.lt-badge').textContent).toBe('질문 조건 확인 필요');
  expect(card.textContent).not.toContain('답변 확인');
  expect(card.textContent).not.toContain('출처 (정상 답변 근거)');
  expect(card.textContent).toContain('읽은 원문');
  expect(card.querySelectorAll('[data-testid="trial-source"]').length).toBe(1);
  expect(card.querySelectorAll('[data-cited="true"]').length).toBe(0);
  expect(card.querySelector('[data-testid="trial-values"]')).toBeNull();
});

test('validation failure shows source-check-needed and keeps internal codes inside the collapsed test info', async () => {
  const card = await ask({ ...base, status: 'supported', status_label: '근거 있음', search_status: 'supported', answer_status: 'source_check_needed',
    answer_status_label: '원문 확인 필요', answer_status_reason: { code: 'validation_failed', text: '검증을 통과하지 못해 원문만 보여 드려요.' },
    answer: '근거 원문을 아래에 그대로 보여 드려요.', sources: [src('a')], generation: { source: 'verified_source', code: 'numbers', model: 'gemini-x' } });
  expect(card.querySelector('.lt-badge').textContent).toBe('원문 확인 필요');
  const tech = card.querySelector('[data-testid="trial-tech"]');
  expect(tech.tagName).toBe('DETAILS');
  expect(tech.hasAttribute('open')).toBe(false);
  const outside = card.textContent.replace(tech.textContent, '');
  expect(outside).not.toContain('gemini-x');
  expect(outside).not.toContain('rk-x-37f81b5cfb1b');
  expect(outside).not.toContain('validation_failed');
});

test('needs_confirmation never shows a confirmed-source area and keeps review material separate', async () => {
  const card = await ask({ ...base, status: 'needs_confirmation', status_label: '확인 필요', answer: '확정 답변을 드리기 어려워요.',
    confirmations: [{ code: 'x', text: '확인해 주세요' }], related: [src('rel')], review_material: [src('rev')] });
  expect(card.textContent).not.toContain('출처 (정상 답변 근거)');
  expect(card.querySelectorAll('[data-testid="trial-source"]').length).toBe(0);
  expect(card.querySelectorAll('[data-testid="trial-review-source"]').length).toBe(1);
  expect(card.querySelectorAll('[data-testid="trial-related-source"]').length).toBe(1);
  expect(card.textContent).toContain('자동 답변·계산에 쓰지 않았어요');
});

test('not_found shows no sources and no document-wide claim', async () => {
  const card = await ask({ ...base, status: 'not_found', status_label: '근거를 찾지 못함', answer: '현재 읽은 범위에서 질문에 맞는 근거를 찾지 못했어요. 문서 전체에 해당 작업이 없다는 뜻은 아니에요.' });
  expect(card.querySelectorAll('.lt-source').length).toBe(0);
  expect(card.textContent).toContain('근거를 찾지 못함');
});

test('disabled option or network failure is shown without crashing', async () => {
  askTrial.mockRejectedValueOnce(new Error('TRIAL_DISABLED'));
  await act(async () => root.render(<LocalTrial />));
  act(() => Simulate.change(container.querySelector('textarea'), { target: { value: '질문' } }));
  await act(async () => Simulate.submit(container.querySelector('form')));
  expect(container.querySelector('[role="alert"]').textContent).toContain('꺼져');
});
