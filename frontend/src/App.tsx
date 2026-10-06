import React, { useCallback, useEffect, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import ChatArea from './components/ChatArea';
import Landing from './landing/Landing';
import Terms from './landing/Terms';
import ToastContainer from './components/ToastContainer';
import { ChatTurn, ChoiceValue } from './types';
import { sendChat } from './api';
import { showToast } from './toast';
import './App.css';
import { authClient, AuthCallback, loginWithGoogle } from './auth';
import type { User } from '@supabase/supabase-js';
import LoginDialog from './components/LoginDialog';

interface Conversation {
  id: string;
  title: string;
  threadId: string | null;
  turns: ChatTurn[];
}
interface ConversationStore { activeId: string | null; conversations: Conversation[]; }
const HISTORY_KEY = 'poomsemi-chat-history-v1';
const EMPTY_TURNS: ChatTurn[] = [];
function readConversations(): ConversationStore {
  // Guest transcripts stay in this tab's memory; Auth sessions have separate storage.
  return { activeId: null, conversations: [] };
}

export default function App() {
  const [pathname, setPathname] = useState(window.location.pathname);
  const [store, setStore] = useState<ConversationStore>(readConversations);
  const current = store.conversations.find(chat => chat.id === store.activeId);
  const turns = current?.turns ?? EMPTY_TURNS;
  const threadId = current?.threadId ?? null;
  const [loading, setLoading] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginError, setLoginError] = useState('');

  useEffect(() => {
    try { localStorage.removeItem(HISTORY_KEY); } catch { /* Storage may be blocked. */ }
    if (!authClient) return;
    let active = true;
    let previousId: string | null = null;
    authClient.auth.getSession().then(({ data }) => { if (active) { previousId = data.session?.user.id ?? null; setUser(data.session?.user ?? null); } });
    const { data: { subscription } } = authClient.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      const nextId = session?.user.id ?? null;
      if (previousId && previousId !== nextId) setStore(readConversations());
      previousId = nextId;
      setUser(session?.user ?? null);
    });
    return () => { active = false; subscription.unsubscribe(); };
  }, []);

  const handleLogin = async () => {
    setAuthLoading(true);
    setLoginError('');
    try { setUser(await loginWithGoogle()); setLoginOpen(false); showToast('Google 계정으로 로그인했습니다.'); }
    catch (error) { setLoginError(error instanceof Error ? error.message : '로그인에 실패했습니다.'); }
    finally { setAuthLoading(false); }
  };
  const handleLogout = async () => {
    const result = await authClient?.auth.signOut();
    if (result?.error) { showToast('로그아웃에 실패했습니다. 다시 시도해 주세요.', 'error'); return; }
    setUser(null);
    setStore(readConversations());
  };

  const handleError = useCallback((err: unknown) => {
    const msg = err instanceof Error ? err.message : '';
    const text =
      msg === 'NETWORK_ERROR' ? '네트워크 연결을 확인해주세요.' :
      msg === 'SERVER_ERROR'  ? '서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.' :
                                 'API 서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해주세요.';
    showToast(text, 'error');
  }, []);

  const send = useCallback(async (
    userLabel: string,
    body: { message?: string; answers?: Record<string, ChoiceValue> },
    thread: string | null,
    conversationId = store.activeId ?? uuidv4(),
  ) => {
    const startedAt = performance.now();
    const userTurn: ChatTurn = { id: uuidv4(), role: 'user', text: userLabel, sentAtMs: Date.now() };
    setStore(prev => {
      const existing = prev.conversations.find(chat => chat.id === conversationId);
      const chat: Conversation = existing
        ? { ...existing, turns: [...existing.turns, userTurn] }
        : { id: conversationId, title: userLabel.replace(/\s+/g, ' ').trim(), threadId: null, turns: [userTurn] };
      return { activeId: conversationId, conversations: [chat, ...prev.conversations.filter(item => item.id !== conversationId)] };
    });
    setLoading(true);
    try {
      const response = await sendChat({ thread_id: thread, ...body });
      const assistantTurn: ChatTurn = { id: uuidv4(), role: 'assistant', response,
        elapsedMs: performance.now() - startedAt, receivedAtMs: Date.now() };
      setStore(prev => ({ ...prev, conversations: prev.conversations.map(chat => chat.id === conversationId
        ? { ...chat, threadId: response.thread_id, turns: [...chat.turns, assistantTurn] } : chat) }));
    } catch (err) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  }, [handleError, store.activeId]);

  const handleSendMessage = useCallback((text: string) => send(text, { message: text }, threadId), [send, threadId]);

  const handleSendAnswers = useCallback((answers: Record<string, ChoiceValue>, summary: string) => {
    return send(summary, { answers }, threadId);
  }, [send, threadId]);

  // 결과 카드의 조건만 바꿔 같은 카드를 새 계산으로 교체한다(공종 입력은 서버가 그대로 둔다).
  const handleChangeConditions = useCallback(async (turnId: string, conditions: Record<string, string>) => {
    if (!threadId || !store.activeId) return;
    const conversationId = store.activeId;
    const startedAt = performance.now();
    setLoading(true);
    try {
      const response = await sendChat({ thread_id: threadId, conditions });
      const elapsedMs = performance.now() - startedAt;
      const receivedAtMs = Date.now();
      setStore(prev => ({ ...prev, conversations: prev.conversations.map(chat => chat.id === conversationId
        ? { ...chat, turns: chat.turns.map(turn => turn.id === turnId ? { ...turn, response, elapsedMs, receivedAtMs } : turn) } : chat) }));
    } catch (err) {
      handleError(err);
    } finally {
      setLoading(false);
    }
  }, [threadId, handleError, store.activeId]);

  const handleNewChat = useCallback(() => {
    setStore(prev => ({ ...prev, activeId: null }));
  }, []);

  const handleSendExample = useCallback((text: string) => {
    return send(text, { message: text }, null, uuidv4());
  }, [send]);

  const handleSelectConversation = (id: string) => {
    if (loading) return;
    setStore(prev => ({ ...prev, activeId: id }));
  };

  const navigate = useCallback((path: string) => {
    window.history.pushState({}, '', path);
    setPathname(window.location.pathname);
  }, []);

  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);

  useEffect(() => {
    if (pathname !== '/chat') return;
    const query = new URLSearchParams(window.location.search).get('q');
    if (!query) return;
    window.history.replaceState({}, '', '/chat');
    handleSendExample(query);
  }, [pathname, handleSendExample]);

  if (pathname === '/auth/callback') return <AuthCallback />;
  if (pathname === '/terms' || pathname === '/terms/') return <Terms />;

  if (pathname !== '/chat') {
    return <Landing onStart={() => navigate('/chat')} onExample={(question) => navigate(`/chat?q=${encodeURIComponent(question)}`)} />;
  }

  return (
    <div className="app">
      <ToastContainer />
      <ChatArea
        accountLabel={user?.email ?? null}
        authLoading={authLoading}
        onLogin={() => { setLoginError(''); setLoginOpen(true); }}
        onLogout={handleLogout}
        conversations={store.conversations.map(chat => ({ id: chat.id, title: chat.title }))}
        activeConversationId={store.activeId}
        onSelectConversation={handleSelectConversation}
        turns={turns}
        loading={loading}
        onSendMessage={handleSendMessage}
        onSendAnswers={handleSendAnswers}
        onChangeConditions={handleChangeConditions}
        onNewChat={handleNewChat}
        onSendExample={handleSendExample}
      />
      {loginOpen && <LoginDialog busy={authLoading} error={loginError} onClose={() => setLoginOpen(false)} onGoogleLogin={handleLogin} />}
    </div>
  );
}
