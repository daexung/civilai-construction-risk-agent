const mockSession = jest.fn();
jest.mock('./auth', () => ({ authClient: { auth: { getSession: mockSession } } }));
const { sendChat, listConversations, downloadEstimate } = require('./api');

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
