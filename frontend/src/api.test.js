const mockSession = jest.fn();
jest.mock('./auth', () => ({ authClient: { auth: { getSession: mockSession } } }));
const { sendChat, listConversations, downloadEstimate, importGuestConversation } = require('./api');

beforeEach(() => {
  mockSession.mockReset().mockResolvedValue({ data: { session: { access_token: 'member-token' } } });
  global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => ({ thread_id: 'saved' }) });
});
afterEach(() => jest.restoreAllMocks());

test('member writes send a bearer token while guest threads remain temporary after login', async () => {
  await sendChat({ conversation_id: 'saved', request_id: 'request', message: '질문' });
  expect(fetch.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer member-token');
  await sendChat({ thread_id: 'temporary', message: '임시 대화' });
  expect(fetch.mock.calls[1][1].headers.get('Authorization')).toBeNull();
  expect(fetch.mock.calls[1][1].headers.get('X-Guest-Session')).toBe(fetch.mock.calls[0][1].headers.get('X-Guest-Session'));
});

test('missing or rejected member authentication never falls back to guest storage', async () => {
  mockSession.mockResolvedValue({ data: { session: null } });
  await expect(listConversations()).rejects.toThrow('AUTH_REQUIRED');
  expect(fetch).not.toHaveBeenCalled();
  mockSession.mockResolvedValue({ data: { session: { access_token: 'expired' } } });
  fetch.mockResolvedValue({ ok: false, status: 401 });
  await expect(listConversations()).rejects.toThrow('AUTH_REQUIRED');
  expect(fetch).toHaveBeenCalledTimes(1);
});

test('member export authenticates through headers and keeps tokens out of URLs', async () => {
  fetch.mockResolvedValue({ ok: true, blob: async () => new Blob(['xlsx']) });
  URL.createObjectURL = jest.fn(() => 'blob:download');
  URL.revokeObjectURL = jest.fn();
  jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  await downloadEstimate('saved-conversation-id');
  expect(fetch.mock.calls[0][0]).toBe('/api/export/saved-conversation-id.xlsx');
  expect(fetch.mock.calls[0][1].headers.get('Authorization')).toBe('Bearer member-token');
});

test('guest import sends both credentials and does not accept browser transcripts', async () => {
  fetch.mockResolvedValue({ ok: true, json: async () => ({ id: 'member-conversation' }) });
  expect(await importGuestConversation('guest-thread', 'member-conversation')).toBe('member-conversation');
  const [url, options] = fetch.mock.calls[0];
  expect(url).toBe('/api/conversations/import-guest');
  expect(options.headers.get('Authorization')).toBe('Bearer member-token');
  expect(options.headers.get('X-Guest-Session').length).toBeGreaterThan(32);
  expect(JSON.parse(options.body)).toEqual({ thread_id: 'guest-thread', conversation_id: 'member-conversation' });
});

test('daily limit errors preserve the server message and remaining usage', async () => {
  const usage = { limit: 5, used: 5, remaining: 0 };
  fetch.mockResolvedValue({ ok: false, status: 429, json: async () => ({ detail: { code: 'PERSONAL_DAILY_LIMIT', message: '오늘 5회를 모두 사용했습니다.', usage } }) });
  await expect(sendChat({ message: '질문' })).rejects.toMatchObject({ message: '오늘 5회를 모두 사용했습니다.', usage });
});

test('guest import stops before sending if the signed-in account changes', async () => {
  mockSession.mockResolvedValue({ data: { session: { access_token: 'b-token', user: { id: 'B' } } } });
  await expect(importGuestConversation('guest-thread', 'member-conversation', 'A')).rejects.toThrow('AUTH_REQUIRED');
  expect(fetch).not.toHaveBeenCalled();
});
