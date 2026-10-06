const mockOAuth = jest.fn();
const mockSession = jest.fn();
jest.mock('@supabase/supabase-js', () => ({ createClient: () => ({ auth: {
  signInWithOAuth: mockOAuth, getSession: mockSession,
} }) }));

let loginWithGoogle, popup;
beforeEach(() => {
  jest.resetModules();
  process.env.REACT_APP_SUPABASE_URL = 'http://127.0.0.1:54321';
  process.env.REACT_APP_SUPABASE_PUBLISHABLE_KEY = 'test-publishable';
  loginWithGoogle = require('./auth').loginWithGoogle;
  popup = { closed: false, close: jest.fn(), location: { href: '' } };
  jest.spyOn(window, 'open').mockReturnValue(popup);
  mockOAuth.mockReset().mockResolvedValue({ data: { url: 'https://accounts.google.com/test' }, error: null });
  mockSession.mockReset().mockResolvedValue({ data: { session: { user: { id: 'A' } } }, error: null });
});
afterEach(() => {
  jest.restoreAllMocks();
  delete process.env.REACT_APP_SUPABASE_URL;
  delete process.env.REACT_APP_SUPABASE_PUBLISHABLE_KEY;
});

test('popup completion requires both the matching origin and window', async () => {
  const promise = loginWithGoogle();
  await Promise.resolve();
  expect(mockOAuth).toHaveBeenCalledWith(expect.objectContaining({ provider: 'google', options: {
    redirectTo: `${window.location.origin}/auth/callback`, skipBrowserRedirect: true,
  } }));
  window.dispatchEvent(new MessageEvent('message', { origin: 'https://attacker.example', source: popup,
    data: { type: 'poomsemi-auth-complete', ok: true } }));
  window.dispatchEvent(new MessageEvent('message', { origin: window.location.origin, source: window,
    data: { type: 'poomsemi-auth-complete', ok: true } }));
  expect(mockSession).not.toHaveBeenCalled();
  window.dispatchEvent(new MessageEvent('message', { origin: window.location.origin, source: popup,
    data: { type: 'poomsemi-auth-complete', ok: true } }));
  await expect(promise).resolves.toEqual({ id: 'A' });
  expect(popup.close).toHaveBeenCalled();
});

test('a blocked popup does not start OAuth or navigate the current chat', async () => {
  window.open.mockReturnValue(null);
  const original = window.location.href;
  await expect(loginWithGoogle()).rejects.toThrow('팝업');
  expect(mockOAuth).not.toHaveBeenCalled();
  expect(window.location.href).toBe(original);
});
