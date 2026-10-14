const mockOAuth = jest.fn();
const mockSession = jest.fn();
jest.mock('@supabase/supabase-js', () => ({ createClient: () => ({ auth: {
  signInWithOAuth: mockOAuth, getSession: mockSession,
} }) }));

let loginWithGoogle, popup;
beforeEach(() => {
  jest.resetModules();
  sessionStorage.clear();
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


test('dashboard login redirects the same tab even when popup windows are blocked', async () => {
  window.open.mockReturnValue(null);
  await require('./auth').loginDashboardWithGoogle();
  expect(window.open).not.toHaveBeenCalled();
  expect(mockOAuth).toHaveBeenCalledWith({ provider: 'google', options: {
    redirectTo: `${window.location.origin}/auth/callback`, queryParams: { prompt: 'select_account' },
  } });
  expect(sessionStorage.getItem('poomsemi-dashboard-auth-return')).toBe('/admin');
});

test('dashboard OAuth failure clears the return marker and allows retry', async () => {
  mockOAuth.mockResolvedValueOnce({ data: { url: null }, error: new Error('fixture failure') });
  await expect(require('./auth').loginDashboardWithGoogle()).rejects.toThrow('로그인을 시작하지 못했습니다');
  expect(sessionStorage.getItem('poomsemi-dashboard-auth-return')).toBeNull();
  await require('./auth').loginDashboardWithGoogle();
  expect(sessionStorage.getItem('poomsemi-dashboard-auth-return')).toBe('/admin');
});

test('login return accepts only the dashboard and consumes its marker once', () => {
  const { consumeDashboardLoginReturn } = require('./auth');
  sessionStorage.setItem('poomsemi-dashboard-auth-return', 'https://attacker.example');
  expect(consumeDashboardLoginReturn()).toBeNull();
  expect(sessionStorage.getItem('poomsemi-dashboard-auth-return')).toBeNull();
  sessionStorage.setItem('poomsemi-dashboard-auth-return', '/admin');
  expect(consumeDashboardLoginReturn()).toBe('/admin');
  expect(consumeDashboardLoginReturn()).toBeNull();
});


test('successful same-tab callback returns to the dashboard without a popup', async () => {
  const React = require('react');
  const { createRoot } = require('react-dom/client');
  const { AuthCallback } = require('./auth');
  const descriptor = Object.getOwnPropertyDescriptor(window, 'location');
  const replace = jest.fn();
  Object.defineProperty(window, 'location', { configurable: true, value: { ...window.location, replace } });
  const container = document.createElement('div');
  document.body.appendChild(container);
  const root = createRoot(container);
  const previousAct = global.IS_REACT_ACT_ENVIRONMENT;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  sessionStorage.setItem('poomsemi-dashboard-auth-return', '/admin');
  try {
    await React.act(async () => { root.render(<AuthCallback />); });
    expect(replace).toHaveBeenCalledWith('/admin');
    expect(sessionStorage.getItem('poomsemi-dashboard-auth-return')).toBeNull();
  } finally {
    await React.act(async () => root.unmount());
    container.remove();
    Object.defineProperty(window, 'location', descriptor);
    global.IS_REACT_ACT_ENVIRONMENT = previousAct;
  }
});
