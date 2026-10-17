import React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { ChatLoadingSkeleton } from './App';

test('chat loading fallback is accessible, chat-shaped, and inert', async () => {
  const container = document.createElement('div');
  const root = createRoot(container);
  global.IS_REACT_ACT_ENVIRONMENT = true;
  await act(async () => root.render(<ChatLoadingSkeleton />));

  expect(container.querySelector('main[aria-label="채팅 화면을 불러오는 중"]').getAttribute('aria-busy')).toBe('true');
  expect(container.querySelector('[role="status"]').textContent).toBe('화면을 여는 중입니다');
  expect(container.querySelector('.chat-loading-sidebar')).not.toBeNull();
  expect(container.querySelector('.chat-loading-header')).not.toBeNull();
  expect(container.querySelector('.chat-loading-composer')).not.toBeNull();
  expect(container.querySelectorAll('button, a, input, textarea')).toHaveLength(0);
  await act(async () => root.unmount());
});
