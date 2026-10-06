import React, { useEffect, useState } from 'react';
import { createClient, User } from '@supabase/supabase-js';

const url = process.env.REACT_APP_SUPABASE_URL;
const key = process.env.REACT_APP_SUPABASE_PUBLISHABLE_KEY;
export const authClient = url && key ? createClient(url, key, {
  auth: { flowType: 'pkce', detectSessionInUrl: true, persistSession: true, autoRefreshToken: true },
}) : null;

export function loginWithGoogle(reauthenticate = false): Promise<User> {
  if (!authClient) return Promise.reject(new Error('로그인 설정이 준비되지 않았습니다.'));
  const client = authClient;
  // Open before the async OAuth request so the browser recognizes the user gesture.
  const popup = window.open('about:blank', 'poomsemi-google-login', 'popup,width=520,height=680');
  if (!popup) return Promise.reject(new Error('로그인 팝업을 허용해 주세요. 현재 대화는 그대로 유지됩니다.'));
  return new Promise((resolve, reject) => {
    let settled = false;
    let completing = false;
    const finish = (user?: User, error?: string) => {
      if (settled) return;
      settled = true;
      clearInterval(timer);
      window.removeEventListener('message', receive);
      popup.close();
      if (user) resolve(user); else reject(new Error(error ?? '로그인이 취소됐습니다.'));
    };
    const receive = async (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== popup ||
          event.data?.type !== 'poomsemi-auth-complete' || completing) return;
      completing = true;
      if (!event.data.ok) { finish(undefined, 'Google 로그인에 실패했습니다. 다시 시도해 주세요.'); return; }
      const { data, error } = await client.auth.getSession();
      finish(data.session?.user, error?.message);
    };
    window.addEventListener('message', receive);
    const deadline = Date.now() + 5 * 60 * 1000;
    const timer = window.setInterval(() => {
      if (!completing && (popup.closed || Date.now() > deadline)) finish();
    }, 500);
    client.auth.signInWithOAuth({ provider: 'google', options: {
      redirectTo: `${window.location.origin}/auth/callback`, skipBrowserRedirect: true,
      ...(reauthenticate ? { queryParams: { prompt: 'select_account' } } : {}),
    } }).then(({ data, error }) => {
      if (settled) return;
      if (error || !data.url) finish(undefined, '로그인을 시작하지 못했습니다. 다시 시도해 주세요.');
      else popup.location.href = data.url;
    }).catch(() => finish(undefined, '로그인 서버에 연결할 수 없습니다.'));
  });
}

export function AuthCallback() {
  const [message, setMessage] = useState('로그인을 확인하고 있습니다.');
  useEffect(() => {
    let active = true;
    const complete = async () => {
      if (!authClient) { setMessage('로그인 설정을 확인해 주세요.'); return; }
      const { data, error } = await authClient.auth.getSession();
      if (!active) return;
      const ok = !error && Boolean(data.session);
      // Send only completion status, never access or refresh tokens.
      if (window.opener) window.opener.postMessage({ type: 'poomsemi-auth-complete', ok }, window.location.origin);
      setMessage(ok ? '로그인했습니다. 원래 대화 화면으로 돌아가 주세요.' : '로그인에 실패했습니다. 원래 화면에서 다시 시도해 주세요.');
      window.history.replaceState({}, '', '/auth/callback');
    };
    complete().catch(() => { if (active) setMessage('로그인 확인에 실패했습니다. 다시 시도해 주세요.'); });
    return () => { active = false; };
  }, []);
  return <main style={{ padding: 32 }}><p role="status">{message}</p></main>;
}
