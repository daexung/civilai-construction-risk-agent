import React, { useCallback, useEffect, useRef, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import ChatArea from './components/ChatArea';
import Landing from './landing/Landing';
import BetaNotice from './landing/BetaNotice';
import Terms from './landing/Terms';
import Privacy from './landing/Privacy';
import ToastContainer from './components/ToastContainer';
import { ChatTurn, ChoiceValue, UsageStatus } from './types';
import { sendChat, listConversations, readConversation, deleteConversation, renameConversation, importGuestConversation, getUsage, UsageError } from './api';
import { showToast } from './toast';
import './App.css';
import { trackEvent, trackPage } from './analytics';
import { authClient, AuthCallback, loginWithGoogle } from './auth';
import type { User } from '@supabase/supabase-js';
import LoginDialog from './components/LoginDialog';
import SettingsDialog from './components/SettingsDialog';
import DeleteConversationDialog from './components/DeleteConversationDialog';
import RenameConversationDialog from './components/RenameConversationDialog';
import FeedbackDialog from './components/FeedbackDialog';
import DeleteAccountDialog from './components/DeleteAccountDialog';

interface Conversation {
  id: string;
  title: string;
  threadId: string | null;
  turns: ChatTurn[];
  saved?: boolean;
  loaded?: boolean;
}
interface ConversationStore { activeId: string | null; conversations: Conversation[]; }
const HISTORY_KEY = 'poomsemi-chat-history-v1';
const TAB_HISTORY_KEY = 'poomsemi-chat-tab-v1';
const EMPTY_TURNS: ChatTurn[] = [];
const emptyStore = (): ConversationStore => ({ activeId: null, conversations: [] });
function readTabHistory(): { owner: string | null; store: ConversationStore } | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(TAB_HISTORY_KEY) ?? 'null');
    if (!value || !Number.isFinite(value.updatedAt) || Date.now() - value.updatedAt > 86400000
      || !(value.owner === null || typeof value.owner === 'string')
      || !(value.store?.activeId === null || typeof value.store?.activeId === 'string')
      || !Array.isArray(value.store?.conversations)
      || !value.store.conversations.every((chat: Conversation) => chat && typeof chat.id === 'string'
        && typeof chat.title === 'string' && Array.isArray(chat.turns))) return null;
    return value;
  } catch { return null; }
}
function readConversations(): ConversationStore {
  const cached = readTabHistory();
  return cached?.owner === null ? cached.store : emptyStore();
}

export default function App() {
  const [initialHistory] = useState(readTabHistory);
  const restored = useRef(initialHistory);
  const [pathname, setPathname] = useState(window.location.pathname);
  useEffect(() => { trackPage(pathname); }, [pathname]);
  const [store, setStore] = useState<ConversationStore>(readConversations);
  const current = store.conversations.find(chat => chat.id === store.activeId);
  const turns = current?.turns ?? EMPTY_TURNS;
  const threadId = current?.threadId ?? null;
  const [loading, setLoading] = useState(false);
  const pendingRequest = useRef(false);
  const [usage, setUsage] = useState<UsageStatus | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [authInitializing, setAuthInitializing] = useState(!!authClient);
  const [loginOpen, setLoginOpen] = useState(false);
  const [loginError, setLoginError] = useState('');
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [deleteAccountOpen, setDeleteAccountOpen] = useState(false);
  const [logoutLoading, setLogoutLoading] = useState(false);
  const [logoutError, setLogoutError] = useState('');
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyOwner, setHistoryOwner] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState('');
  const [renameTarget, setRenameTarget] = useState<string | null>(null);
  const [renaming, setRenaming] = useState(false);
  const [renameError, setRenameError] = useState('');
  const renamePending = useRef(false);
  const [migrating, setMigrating] = useState(false);
  const [migrationError, setMigrationError] = useState('');
  const [migrationRetry, setMigrationRetry] = useState(0);
  const storeRef = useRef(store);
  storeRef.current = store;
  const accountRef = useRef<string | null>(null);
  const accountId = user?.id ?? null;
  const restoringConversation = turns.length === 0 && (authInitializing || historyLoading || !!(accountId && historyOwner !== accountId));
  accountRef.current = accountId;
  useEffect(() => { setDeleteTarget(null); setRenameTarget(null); }, [accountId]);
  useEffect(() => {
    if (pathname !== '/chat' || authInitializing) return;
    let active = true;
    setUsage(null);
    const refresh = () => { getUsage(!!accountId).then(value => { if (active) setUsage(value); }).catch(() => {}); };
    refresh();
    window.addEventListener('focus', refresh);
    return () => { active = false; window.removeEventListener('focus', refresh); };
  }, [accountId, authInitializing, pathname]);
  useEffect(() => {
    if (!usage) return;
    let active = true;
    const timer = window.setTimeout(() => {
      getUsage(!!accountId).then(value => { if (active) setUsage(value); })
        .catch(() => { if (active) setUsage(null); });
    }, Math.max(100, Date.parse(usage.resets_at) - Date.now() + 100));
    return () => { active = false; window.clearTimeout(timer); };
  }, [usage, accountId]);
  const displayName = user?.user_metadata?.full_name || user?.user_metadata?.name || user?.email?.split('@')[0];
  const accountName = user ? (typeof displayName === 'string' && displayName.trim() ? displayName.trim() : '내 계정') : null;

  useEffect(() => {
    try { localStorage.removeItem(HISTORY_KEY); } catch { /* Storage may be blocked. */ }
    if (!authClient) return;
    let active = true;
    let previousId: string | null = null;
    authClient.auth.getSession().then(({ data }) => { if (active) { previousId = data.session?.user.id ?? null; setUser(data.session?.user ?? null); } })
      .catch(() => { if (active) showToast('로그인 상태를 확인하지 못했습니다.', 'error'); })
      .finally(() => { if (active) setAuthInitializing(false); });
    const { data: { subscription } } = authClient.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      const nextId = session?.user.id ?? null;
      if (previousId && previousId !== nextId) { restored.current = null; setHistoryOwner(null); setStore(emptyStore()); }
      previousId = nextId;
      setUser(session?.user ?? null);
    });
    return () => { active = false; subscription.unsubscribe(); };
  }, []);

  useEffect(() => {
    if (!accountId) return;
    const userId = accountId;
    let active = true;
    setHistoryLoading(true);
    const selected = restored.current?.owner === userId ? restored.current.store.activeId : null;
    // Authentication is already resolved; fetch the list and selected transcript together.
    Promise.allSettled([listConversations(), selected ? readConversation(selected) : Promise.resolve(null)]).then(([listResult, transcriptResult]) => {
      if (!active || accountRef.current !== userId) return;
      restored.current = null;
      if (listResult.status === 'rejected') throw listResult.reason;
      const rows = listResult.value;
      const restoredTurns = transcriptResult.status === 'fulfilled' ? transcriptResult.value : null;
      const selectedRow = restoredTurns ? rows.find(row => row.id === selected) : undefined;
      if (selected && transcriptResult.status === 'rejected' && transcriptResult.reason?.message !== 'NOT_FOUND') {
        showToast('이전 대화를 불러오지 못했습니다. 왼쪽 목록에서 다시 선택해 주세요.', 'error');
      }
      setStore(prev => ({ activeId: prev.activeId ?? selectedRow?.id ?? null,
        conversations: [...prev.conversations,
          ...rows.filter(row => !prev.conversations.some(chat => chat.id === row.id))
            .map(row => ({ ...row, threadId: row.id, saved: true, loaded: row.id === selectedRow?.id,
              turns: row.id === selectedRow?.id ? restoredTurns ?? [] : [] }))] }));
    }).catch(() => { if (active) showToast('저장된 대화를 불러오지 못했습니다. 새로고침해 주세요.', 'error'); })
      .finally(() => { if (active) { setHistoryLoading(false); setHistoryOwner(userId); } });
    return () => { active = false; setHistoryLoading(false); };
  }, [accountId]);

  useEffect(() => {
    if (authInitializing || historyLoading || (accountId && historyOwner !== accountId)) return;
    try {
      sessionStorage.setItem(TAB_HISTORY_KEY, JSON.stringify({ owner: accountId, updatedAt: Date.now(),
        store: { activeId: store.activeId, conversations: store.conversations.filter(chat => !chat.saved) } }));
    } catch { /* A full or blocked tab cache must not interrupt chatting. */ }
  }, [store, accountId, authInitializing, historyLoading, historyOwner]);

  useEffect(() => {
    if (!accountId || loading || authLoading || deleting || renaming) return;
    const temporary = storeRef.current.conversations.filter(chat => !chat.saved && chat.threadId);
    if (!temporary.length) { setMigrationError(''); return; }
    const userId = accountId;
    let active = true;
    setMigrating(true);
    setMigrationError('');
    (async () => {
      let failed = false;
      for (const chat of temporary) {
        if (!active || accountRef.current !== userId) break;
        try {
          const savedId = await importGuestConversation(chat.threadId!, chat.id, userId);
          if (!active || accountRef.current !== userId) break;
          if (chat.title !== chat.turns.find(turn => turn.role === 'user')?.text?.replace(/\s+/g, ' ').trim()) {
            await renameConversation(savedId, chat.title.slice(0, 200), userId);
            if (!active || accountRef.current !== userId) break;
          }
          setStore(prev => ({ activeId: prev.activeId === chat.id ? savedId : prev.activeId,
            conversations: prev.conversations.filter(item => item.id !== savedId || item.id === chat.id).map(item => item.id === chat.id
              ? { ...item, id: savedId, threadId: savedId, saved: true, loaded: true,
                  turns: item.turns.map(turn => turn.response ? { ...turn, response: { ...turn.response, thread_id: savedId } } : turn) } : item) }));
        } catch { failed = true; }
      }
      if (active) { setMigrating(false); if (failed) setMigrationError('임시 대화를 저장하지 못했습니다. 새로고침 전에 다시 시도해 주세요.'); }
    })();
    return () => { active = false; setMigrating(false); };
  }, [accountId, loading, authLoading, deleting, renaming, migrationRetry]);

  const handleLogin = async () => {
    setAuthLoading(true);
    setLoginError('');
    try { setUser(await loginWithGoogle()); setLoginOpen(false); showToast('Google 계정으로 로그인했습니다.'); }
    catch (error) { setLoginError(error instanceof Error ? error.message : '로그인에 실패했습니다.'); }
    finally { setAuthLoading(false); }
  };
  const handleLogout = async () => {
    setLogoutLoading(true);
    setLogoutError('');
    try {
      const result = await authClient?.auth.signOut({ scope: 'local' });
      if (result?.error) throw result.error;
      setUser(null);
      restored.current = null;
      setHistoryOwner(null);
      setStore(emptyStore());
      setSettingsOpen(false);
    } catch { setLogoutError('로그아웃에 실패했습니다. 다시 시도해 주세요.'); }
    finally { setLogoutLoading(false); }
  };

  const handleAccountDeleted = () => {
    authClient?.auth.signOut({ scope: 'local' }).catch(() => {});
    restored.current = null;
    setDeleteAccountOpen(false); setSettingsOpen(false); setUser(null); setStore(emptyStore()); setUsage(null);
    showToast('회원탈퇴가 완료되었습니다.');
  };

  const handleError = useCallback((err: unknown) => {
    if (err instanceof UsageError) {
      if (err.usage) setUsage(err.usage);
      showToast(err.message, 'error');
      return;
    }
    const msg = err instanceof Error ? err.message : '';
    const text =
      msg === 'NETWORK_ERROR' ? '네트워크 연결을 확인해주세요.' :
      msg === 'SERVER_ERROR'  ? '서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.' :
      msg === 'AUTH_REQUIRED' ? '로그인을 확인할 수 없습니다. 다시 로그인해 주세요.' :
      msg === 'NOT_FOUND' ? '대화를 찾을 수 없거나 임시 대화가 만료되었습니다.' :
                                 'API 서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해주세요.';
    showToast(text, 'error');
  }, []);

  const send = useCallback(async (
    userLabel: string,
    body: { message?: string; answers?: Record<string, ChoiceValue> },
    thread: string | null,
    conversationId = store.activeId ?? uuidv4(),
  ) => {
    if (pendingRequest.current) return;
    pendingRequest.current = true;
    const startedAt = performance.now();
    const requestUserId = user?.id ?? null;
    const existingChat = store.conversations.find(chat => chat.id === conversationId);
    // Guest threads become member threads only after the server confirms the import.
    const saved = existingChat ? !!existingChat.saved : !!user;
    const userTurn: ChatTurn = { id: uuidv4(), role: 'user', text: userLabel, sentAtMs: Date.now() };
    setStore(prev => {
      const existing = prev.conversations.find(chat => chat.id === conversationId);
      const chat: Conversation = existing
        ? { ...existing, turns: [...existing.turns, userTurn] }
        : { id: conversationId, title: userLabel.replace(/\s+/g, ' ').trim(), threadId: null, turns: [userTurn], saved, loaded: true };
      return { activeId: conversationId, conversations: [chat, ...prev.conversations.filter(item => item.id !== conversationId)] };
    });
    setLoading(true);
    trackEvent('question_submitted', { member: saved });
    try {
      const response = await sendChat({ thread_id: thread, ...body,
        ...(saved ? { conversation_id: conversationId, request_id: uuidv4(), user_label: userLabel } : {}) });
      if (requestUserId && accountRef.current !== requestUserId) return;
      if (response.usage) setUsage(response.usage);
      const assistantTurn: ChatTurn = { id: uuidv4(), role: 'assistant', response,
        elapsedMs: performance.now() - startedAt, receivedAtMs: Date.now() };
      setStore(prev => ({ ...prev, conversations: prev.conversations.map(chat => chat.id === conversationId
        ? { ...chat, threadId: response.thread_id, turns: [...chat.turns, assistantTurn] } : chat) }));
    } catch (err) {
      handleError(err);
    } finally {
      pendingRequest.current = false;
      setLoading(false);
    }
  }, [handleError, store.activeId, store.conversations, user]);

  const handleSendMessage = useCallback((text: string) => send(text, { message: text }, threadId), [send, threadId]);

  const handleSendAnswers = useCallback((answers: Record<string, ChoiceValue>, summary: string) => {
    return send(summary, { answers }, threadId);
  }, [send, threadId]);

  // 결과 카드의 조건만 바꿔 같은 카드를 새 계산으로 교체한다(공종 입력은 서버가 그대로 둔다).
  const handleChangeConditions = useCallback(async (turnId: string, conditions: Record<string, string>) => {
    if (!threadId || !store.activeId || pendingRequest.current) return;
    pendingRequest.current = true;
    const conversationId = store.activeId;
    const startedAt = performance.now();
    setLoading(true);
    try {
      const requestUserId = user?.id ?? null;
      const response = await sendChat({ thread_id: threadId, conditions,
        ...(current?.saved ? { conversation_id: conversationId, request_id: uuidv4(), user_label: '현장 조건 반영' } : {}) });
      if (accountRef.current !== requestUserId) return;
      if (response.usage) setUsage(response.usage);
      const elapsedMs = performance.now() - startedAt;
      const receivedAtMs = Date.now();
      setStore(prev => ({ ...prev, conversations: prev.conversations.map(chat => chat.id === conversationId
        ? current?.saved ? { ...chat, turns: [...chat.turns,
            { id: uuidv4(), role: 'user', text: '현장 조건 반영', sentAtMs: Date.now() },
            { id: uuidv4(), role: 'assistant', response, elapsedMs, receivedAtMs }] }
          : { ...chat, turns: chat.turns.map(turn => turn.id === turnId ? { ...turn, response, elapsedMs, receivedAtMs } : turn) } : chat) }));
    } catch (err) {
      handleError(err);
    } finally {
      pendingRequest.current = false;
      setLoading(false);
    }
  }, [threadId, handleError, store.activeId, current, user]);

  const handleNewChat = useCallback(() => {
    setStore(prev => ({ ...prev, activeId: null }));
  }, []);

  const handleSendExample = useCallback((text: string) => {
    return send(text, { message: text }, null, uuidv4());
  }, [send]);

  const handleSelectConversation = async (id: string) => {
    if (loading || historyLoading) return;
    const chat = store.conversations.find(item => item.id === id);
    if (chat?.saved && !chat.loaded) {
      const userId = user?.id;
      setHistoryLoading(true);
      try {
        const savedTurns = await readConversation(id);
        if (accountRef.current !== userId) return;
        setStore(prev => ({ ...prev, activeId: id, conversations: prev.conversations.map(item => item.id === id
          ? { ...item, turns: savedTurns, loaded: true } : item) }));
      } catch (error) { handleError(error); }
      finally { setHistoryLoading(false); }
      return;
    }
    setStore(prev => ({ ...prev, activeId: id }));
  };

  const handleRenameConversation = async (title: string) => {
    const chat = storeRef.current.conversations.find(item => item.id === renameTarget);
    if (!chat || renamePending.current || loading || historyLoading || migrating) return;
    const userId = accountId;
    renamePending.current = true;
    setRenaming(true);
    setRenameError('');
    try {
      if (chat.saved) {
        if (!userId) throw new Error('AUTH_REQUIRED');
        await renameConversation(chat.id, title, userId);
      }
      if (accountRef.current !== userId) return;
      setStore(prev => ({ ...prev, conversations: prev.conversations.map(item => item.id === chat.id ? { ...item, title } : item) }));
      setRenameTarget(null);
      showToast('대화 이름을 변경했습니다.');
    } catch { setRenameError('대화 이름을 변경하지 못했습니다. 다시 시도해 주세요.'); }
    finally { renamePending.current = false; setRenaming(false); }
  };

  const handleDeleteConversation = async () => {
    const chat = store.conversations.find(item => item.id === deleteTarget);
    if (!chat || deleting || loading || historyLoading) return;
    const userId = accountId;
    setDeleting(true);
    setDeleteError('');
    try {
      try { await deleteConversation(chat.id, !!chat.saved, chat.threadId); }
      catch (error) { if (!(error instanceof Error) || error.message !== 'NOT_FOUND') throw error; }
      if (accountRef.current !== userId) return;
      setStore(prev => ({ activeId: prev.activeId === chat.id ? null : prev.activeId,
        conversations: prev.conversations.filter(item => item.id !== chat.id) }));
      setDeleteTarget(null);
      showToast('대화를 삭제했습니다.');
    } catch { setDeleteError('대화를 삭제하지 못했습니다. 다시 시도해 주세요.'); }
    finally { setDeleting(false); }
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
    if (pathname !== '/chat' || authInitializing || historyLoading || (accountId && historyOwner !== accountId)) return;
    const query = new URLSearchParams(window.location.search).get('q');
    if (!query) return;
    window.history.replaceState({}, '', '/chat');
    handleSendExample(query);
  }, [pathname, handleSendExample, authInitializing, historyLoading, accountId, historyOwner]);

  if (pathname === '/auth/callback') return <AuthCallback />;
  if (pathname === '/terms' || pathname === '/terms/') return <Terms />;
  if (pathname === '/privacy' || pathname === '/privacy/') return <Privacy />;

  if (pathname !== '/chat') {
    return <Landing onStart={() => navigate('/chat')} onExample={(question) => navigate(`/chat?q=${encodeURIComponent(question)}`)} />;
  }

  return (
    <div className="app">
      <ToastContainer />
      <BetaNotice variant="chat" onStart={() => {}} onFeedback={() => setFeedbackOpen(true)} />
      {user && migrationError && <div className="chat-migration-notice" role="alert"><span>{migrationError}</span><button onClick={() => setMigrationRetry(value => value + 1)}>다시 시도</button></div>}
      <ChatArea
        ratingUserId={current?.saved ? accountId ?? undefined : undefined}
        onRatingSaved={(answerId, value) => setStore(prev => ({ ...prev, conversations: prev.conversations.map(chat => ({ ...chat,
          turns: chat.turns.map(turn => turn.response?.answer_id === answerId ? { ...turn, response: { ...turn.response, answer_rating: value } } : turn) })) }))}
        usage={usage}
        onLogout={handleLogout}
        logoutBusy={logoutLoading || loading || migrating || authLoading}
        logoutError={logoutError}
        accountLabel={accountName}
        authLoading={authLoading}
        onLogin={() => { setLoginError(''); setLoginOpen(true); }}
        onSettings={() => { setLogoutError(''); setSettingsOpen(true); }}
        onFeedback={() => setFeedbackOpen(true)}
        conversations={store.conversations.map(chat => ({ id: chat.id, title: chat.title + (user && !chat.saved ? ' · 임시' : '') }))}
        activeConversationId={store.activeId}
        onSelectConversation={handleSelectConversation}
        onDeleteConversation={id => { setDeleteError(''); setDeleteTarget(id); }}
        onRenameConversation={id => { setRenameError(''); setRenameTarget(id); }}
        turns={turns}
        restoring={restoringConversation}
        loading={loading || restoringConversation || historyLoading || authInitializing || deleting || renaming || migrating || authLoading}
        generating={loading}
        inputDisabled={!!(user && current && !current.saved && migrationError) || !!(usage && (usage.remaining === 0 || usage.service_remaining === 0))}
        onSendMessage={handleSendMessage}
        onSendAnswers={handleSendAnswers}
        onChangeConditions={handleChangeConditions}
        onNewChat={handleNewChat}
        onSendExample={handleSendExample}
      />
      {loginOpen && <LoginDialog busy={authLoading} error={loginError} onClose={() => setLoginOpen(false)} onGoogleLogin={handleLogin} />}
      {feedbackOpen && <FeedbackDialog key={accountId ?? 'guest'} userId={accountId ?? undefined} onClose={() => setFeedbackOpen(false)} />}
      {deleteAccountOpen && user && <DeleteAccountDialog key={user.id} userId={user.id} email={user.email ?? ''} onClose={() => setDeleteAccountOpen(false)} onDeleted={handleAccountDeleted} />}
      {settingsOpen && <SettingsDialog usage={usage} accountName={accountName} accountEmail={user?.email ?? null} busy={logoutLoading || loading || migrating} error={logoutError} onClose={() => setSettingsOpen(false)} onLogout={handleLogout} onDeleteAccount={() => { setSettingsOpen(false); setDeleteAccountOpen(true); }} onLogin={() => { setSettingsOpen(false); setLoginError(''); setLoginOpen(true); }} />}
      {deleteTarget && <DeleteConversationDialog title={store.conversations.find(chat => chat.id === deleteTarget)?.title ?? '대화'} busy={deleting} error={deleteError} onClose={() => setDeleteTarget(null)} onDelete={handleDeleteConversation} />}
      {renameTarget && <RenameConversationDialog key={renameTarget} title={store.conversations.find(chat => chat.id === renameTarget)?.title ?? '대화'} busy={renaming} error={renameError} onClose={() => setRenameTarget(null)} onSave={handleRenameConversation} />}
    </div>
  );
}
