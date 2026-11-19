import React, { act } from 'react';
import { createRoot } from 'react-dom/client';
import { Simulate } from 'react-dom/test-utils';
import App from '../App';
import HelpPage from './HelpPages';
import { QUESTION_EXAMPLES } from './exampleCatalog';
import { PUBLIC_PAGE_META } from './publicPageMeta';
import { trackPage } from '../analytics';

jest.mock('../analytics', () => ({ trackPage: jest.fn() }));
jest.mock('../ChatApp', () => ({ __esModule: true, default: () => { throw new Error('Public help must not initialize chat'); } }));
let root, container;
beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  window.history.replaceState({}, '', '/guide');
  container = document.createElement('div'); document.body.appendChild(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });

test.each(['/guide', '/guide/', '/examples', '/examples/'])('direct %s routes show public content without chat initialization', async path => {
  window.history.replaceState({}, '', path);
  await act(async () => root.render(<App />));
  const page = path.startsWith('/guide') ? 'guide' : 'examples';
  expect(container.querySelector('#help-main h1')).not.toBeNull();
  expect(document.title).toBe(PUBLIC_PAGE_META[page].title);
  expect(trackPage).toHaveBeenCalledWith(`/${page}`);
  expect(container.querySelector('.chat-shell')).toBeNull();
});

test('guide covers current confirmations, limits, partial estimates and guest downloads', async () => {
  await act(async () => root.render(<HelpPage page="guide" />));
  for (const id of ['start', 'question', 'cards', 'result', 'usage', 'faq']) {
    expect(container.querySelector(`#${id}`)).not.toBeNull();
    expect(container.querySelector(`.help-toc a[href="#${id}"]`)).not.toBeNull();
  }
  expect(container.textContent).toContain('30회');
  expect(container.textContent).toContain('미산정');
  expect(container.textContent).toContain('Excel은 로그인 없이도');
  expect(container.querySelectorAll('#faq details')).toHaveLength(5);
  expect(container.querySelector('a[href="/examples"]')).not.toBeNull();
});

test('examples filter by purpose and encode the exact prompt into a chat prefill link', async () => {
  await act(async () => root.render(<HelpPage page="examples" />));
  expect(container.querySelectorAll('.help-example-card')).toHaveLength(QUESTION_EXAMPLES.length);
  for (const example of QUESTION_EXAMPLES) {
    const link = container.querySelector(`#${example.id} > a`);
    const url = new URL(link.href);
    expect(url.pathname).toBe('/chat');
    expect(url.searchParams.get('q')).toBe(example.question);
  }
  act(() => Simulate.click([...container.querySelectorAll('.help-filters button')].find(button => button.textContent === '품셈 상담')));
  expect(container.querySelectorAll('.help-example-card')).toHaveLength(QUESTION_EXAMPLES.filter(example => example.kind === '품셈 상담').length);
  expect(container.querySelector('#automatic-door')).toBeNull();
  expect(container.querySelector('#formwork-height')).not.toBeNull();
  expect(container.querySelector('.help-filters button[aria-pressed="true"]').textContent).toBe('품셈 상담');
  expect(container.querySelector('#estimate-result').textContent).toContain('저장된');
  expect(container.querySelector('#estimate-result').textContent).toContain('미산정 항목');
});
