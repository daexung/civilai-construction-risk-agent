import React, { useState, useEffect, useRef, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import LoginPage from './components/LoginPage';
import ToastContainer from './components/ToastContainer';
import { User, Project, Conversation, Message, ProjectCreateRequest, ProjectRole } from './types';
import {
  fetchQuickConversations, createQuickConversation,
  fetchProjects, createProject, deleteProject,
  fetchConversations, createConversation, deleteConversation, renameConversation,
  fetchMessages,
  registerUnauthorizedHandler,
} from './api';
import { showToast } from './toast';
import { Settings, loadSettings, saveSettings, applyTheme } from './settings';
import {
  MOCK_MODE,
  MOCK_PROJECTS, MOCK_QUICK_CONVS, MOCK_PROJECT_CONVS, MOCK_MESSAGES,
  createMockConversation,
} from './mockData';
import './App.css';

export default function App() {
  const [user, setUser]                        = useState<User | null>(null);
  const [authReady, setAuthReady]              = useState(false);

  const [quickConvs, setQuickConvs]           = useState<Conversation[]>([]);
  const [projects, setProjects]               = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(() => localStorage.getItem('active_project_id'));
  const [projectConvs, setProjectConvs]       = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId]       = useState<string | null>(() => localStorage.getItem('active_conv_id'));
  const [messages, setMessages]               = useState<Message[]>([]);
  const [sidebarOpen, setSidebarOpen]         = useState(true);
  const [showOpenBtn, setShowOpenBtn]         = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [settings, setSettings]              = useState<Settings>(() => {
    const s = loadSettings();
    applyTheme(s.theme);
    return s;
  });

  const handleSettingsChange = (s: Settings) => {
    setSettings(s);
    saveSettings(s);
    applyTheme(s.theme);
  };

  const [loadingProjectConvs, setLoadingProjectConvs] = useState(false);

  const activeConvIdRef = useRef<string | null>(null);
  useEffect(() => { activeConvIdRef.current = activeConvId; }, [activeConvId]);
  const initialLoadDoneRef = useRef(false);
  const messagesCacheRef = useRef<Map<string, Message[]>>(new Map());
  const projectConvsCacheRef = useRef<Map<string, Conversation[]>>(new Map());

  const selectProject = useCallback((id: string | null) => {
    setActiveProjectId(id);
    if (id) localStorage.setItem('active_project_id', id);
    else localStorage.removeItem('active_project_id');
  }, []);

  const selectConv = useCallback((id: string | null) => {
    setActiveConvId(id);
    if (id) localStorage.setItem('active_conv_id', id);
    else localStorage.removeItem('active_conv_id');
  }, []);

  // ── 인증 복원 (새로고침 시) ─────────────────────────────────
  useEffect(() => {
    const storedUser  = localStorage.getItem('auth_user');
    const storedToken = localStorage.getItem('auth_token');
    if (storedUser && storedToken) {
      try { setUser(JSON.parse(storedUser)); } catch {}
    }
    setAuthReady(true);
  }, []);

  // ── 로그인 / 로그아웃 ───────────────────────────────────────
  const handleLogin = useCallback((u: User, token: string) => {
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(u));
    setUser(u);
  }, []);

  const handleLogout = useCallback(() => {
    localStorage.removeItem('auth_token');
    localStorage.removeItem('auth_user');
    localStorage.removeItem('active_project_id');
    localStorage.removeItem('active_conv_id');
    setUser(null);
    setQuickConvs([]);
    setProjects([]);
    setActiveProjectId(null);
    setProjectConvs([]);
    setActiveConvId(null);
    setMessages([]);
    initialLoadDoneRef.current = false;
  }, []);

  // 401 발생 시 자동 로그아웃
  useEffect(() => {
    registerUnauthorizedHandler(() => {
      showToast('세션이 만료됐습니다. 다시 로그인해주세요.', 'error', 4000);
      handleLogout();
    });
  }, [handleLogout]);

  // ── 데이터 로드 ─────────────────────────────────────────────
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    initialLoadDoneRef.current = false;

    if (MOCK_MODE) {
      setQuickConvs(
        MOCK_QUICK_CONVS.map(c => ({ ...c, can_write: c.owner_id === user.user_id }))
      );
      setProjects(
        MOCK_PROJECTS.map(p => ({
          ...p,
          my_project_role: (p.created_by === user.user_id ? 'owner' : 'member') as ProjectRole,
        }))
      );
      initialLoadDoneRef.current = true;
      return;
    }
    // 로그인/새로고침 시 모든 초기 데이터를 병렬로 한 번에 로드
    const initProjectId = activeProjectId;
    const initConvId    = activeConvId;

    async function loadInitialData() {
      const [quickResult, projectsResult, projectConvsResult, messagesResult] = await Promise.allSettled([
        fetchQuickConversations(),
        fetchProjects(),
        initProjectId ? fetchConversations(initProjectId) : Promise.resolve([] as Conversation[]),
        initConvId ? fetchMessages(initConvId) : Promise.resolve([] as Message[]),
      ]);

      if (cancelled) return;

      if (quickResult.status === 'fulfilled') setQuickConvs(quickResult.value);
      else showToast('대화 목록을 불러오지 못했습니다.', 'error');

      if (projectsResult.status === 'fulfilled') setProjects(projectsResult.value);
      else showToast('프로젝트 목록을 불러오지 못했습니다.', 'error');

      if (projectConvsResult.status === 'fulfilled') {
        setProjectConvs(projectConvsResult.value);
        if (initProjectId) projectConvsCacheRef.current.set(initProjectId, projectConvsResult.value);
      } else showToast('프로젝트 대화 목록을 불러오지 못했습니다.', 'error');

      if (messagesResult.status === 'fulfilled') {
        setMessages(messagesResult.value);
        if (initConvId) messagesCacheRef.current.set(initConvId, messagesResult.value);
      } else showToast('메시지를 불러오지 못했습니다.', 'error');

      initialLoadDoneRef.current = true;
    }

    loadInitialData();
    return () => { cancelled = true; };
  }, [user]); // eslint-disable-line react-hooks/exhaustive-deps

  // 프로젝트 전환 시 대화 목록 갱신 (초기 로드 제외)
  useEffect(() => {
    if (!activeProjectId || !user) { setProjectConvs([]); return; }
    if (!initialLoadDoneRef.current) return;
    if (MOCK_MODE) {
      const uid = user?.user_id ?? '';
      setProjectConvs(
        (MOCK_PROJECT_CONVS[activeProjectId] ?? []).map(c => ({ ...c, can_write: c.owner_id === uid }))
      );
      return;
    }
    const cached = projectConvsCacheRef.current.get(activeProjectId);
    if (cached) { setProjectConvs(cached); return; }
    setLoadingProjectConvs(true);
    fetchConversations(activeProjectId)
      .then(convs => {
        setProjectConvs(convs);
        projectConvsCacheRef.current.set(activeProjectId, convs);
      })
      .catch(() => showToast('프로젝트 대화 목록을 불러오지 못했습니다.', 'error'))
      .finally(() => setLoadingProjectConvs(false));
  }, [activeProjectId]); // eslint-disable-line react-hooks/exhaustive-deps

  // 대화 전환 시 메시지 갱신 (초기 로드 제외)
  useEffect(() => {
    if (!activeConvId || !user) { setMessages([]); return; }
    if (!initialLoadDoneRef.current) return;
    if (MOCK_MODE) {
      setMessages(MOCK_MESSAGES[activeConvId] ?? []);
      return;
    }
    const cached = messagesCacheRef.current.get(activeConvId);
    if (cached) { setMessages(cached); return; }
    setLoadingMessages(true);
    fetchMessages(activeConvId)
      .then(msgs => {
        setMessages(msgs);
        messagesCacheRef.current.set(activeConvId, msgs);
        setLoadingMessages(false);
      })
      .catch(() => { showToast('메시지를 불러오지 못했습니다.', 'error'); setLoadingMessages(false); });
  }, [activeConvId]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── 대화 핸들러 ─────────────────────────────────────────────
  const handleNeedConv = useCallback(async (): Promise<string> => {
    if (!user) return '';
    if (MOCK_MODE) {
      const conv = createMockConversation(user.user_id, user.name);
      setQuickConvs(prev => [conv, ...prev]);
      setActiveConvId(conv.id);
      activeConvIdRef.current = conv.id;
      return conv.id;
    }
    const conv = await createQuickConversation();
    setQuickConvs(prev => [conv, ...prev]);
    selectConv(conv.id);
    activeConvIdRef.current = conv.id;
    return conv.id;
  }, [user, selectConv]);

  const handleQuickNew = useCallback(async () => {
    if (!user) return;
    if (MOCK_MODE) {
      const conv = createMockConversation(user.user_id, user.name);
      setQuickConvs(prev => [conv, ...prev]);
      selectProject(null);
      selectConv(conv.id);
      setMessages([]);
      return;
    }
    try {
      const conv = await createQuickConversation();
      setQuickConvs(prev => [conv, ...prev]);
      selectProject(null);
      selectConv(conv.id);
      setMessages([]);
    } catch {
      showToast('대화 생성에 실패했습니다.', 'error');
    }
  }, [user, selectProject, selectConv]);

  const handleQuickDelete = useCallback(async (convId: string) => {
    await deleteConversation(convId);
    setQuickConvs(prev => prev.filter(c => c.id !== convId));
    messagesCacheRef.current.delete(convId);
    if (activeConvIdRef.current === convId) { selectConv(null); setMessages([]); }
  }, [selectConv]);

  const handleCreateProject = useCallback(async (req: ProjectCreateRequest) => {
    if (!user) return;
    if (MOCK_MODE) {
      const proj: Project = {
        id: `p-${Date.now()}`,
        ...req,
        work_type: '',
        latitude: 0,
        longitude: 0,
        created_by: user.user_id,
        created_by_name: user.name,
        my_project_role: 'owner',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      setProjects(prev => [proj, ...prev]);
      selectProject(proj.id);
      showToast(`'${proj.name}' 프로젝트가 생성됐습니다.`, 'success');
      return;
    }
    try {
      const proj = await createProject(req);
      setProjects(prev => [proj, ...prev]);
      selectProject(proj.id);
      showToast(`'${proj.name}' 프로젝트가 생성됐습니다.`, 'success');
    } catch {
      showToast('프로젝트 생성에 실패했습니다.', 'error');
    }
  }, [user, selectProject]);

  const handleDeleteProject = useCallback(async (projectId: string) => {
    try {
      await deleteProject(projectId);
      setProjects(prev => prev.filter(p => p.id !== projectId));
      projectConvsCacheRef.current.delete(projectId);
      if (activeProjectId === projectId) {
        selectProject(null);
        setProjectConvs([]);
        if (activeConvIdRef.current) { selectConv(null); setMessages([]); }
      }
      showToast('프로젝트가 삭제됐습니다.', 'success');
    } catch {
      showToast('프로젝트 삭제에 실패했습니다.', 'error');
    }
  }, [activeProjectId, selectProject, selectConv]);

  const handleCreateProjectConv = useCallback(async () => {
    if (!activeProjectId || !user) return;
    if (MOCK_MODE) {
      const conv = createMockConversation(user.user_id, user.name, activeProjectId);
      setProjectConvs(prev => [conv, ...prev]);
      selectConv(conv.id);
      setMessages([]);
      return;
    }
    try {
      const conv = await createConversation(activeProjectId);
      setProjectConvs(prev => {
        const next = [conv, ...prev];
        projectConvsCacheRef.current.set(activeProjectId, next);
        return next;
      });
      selectConv(conv.id);
      setMessages([]);
    } catch {
      showToast('대화 생성에 실패했습니다.', 'error');
    }
  }, [activeProjectId, user, selectConv]);

  const handleGoHome = useCallback(() => {
    selectProject(null);
    selectConv(null);
    setMessages([]);
  }, [selectProject, selectConv]);

  const handleRenameConversation = useCallback(async (convId: string, newTitle: string) => {
    try {
      await renameConversation(convId, newTitle);
      setQuickConvs(prev => prev.map(c => c.id === convId ? { ...c, title: newTitle } : c));
      setProjectConvs(prev => {
        const next = prev.map(c => c.id === convId ? { ...c, title: newTitle } : c);
        if (activeProjectId) projectConvsCacheRef.current.set(activeProjectId, next);
        return next;
      });
    } catch {
      showToast('제목 변경에 실패했습니다.', 'error');
    }
  }, [activeProjectId]);

  const handleDeleteProjectConv = useCallback(async (convId: string) => {
    await deleteConversation(convId);
    setProjectConvs(prev => {
      const next = prev.filter(c => c.id !== convId);
      if (activeProjectId) projectConvsCacheRef.current.set(activeProjectId, next);
      return next;
    });
    if (activeConvIdRef.current === convId) { selectConv(null); setMessages([]); }
  }, [activeProjectId, selectConv]);

  const handleMessagesUpdate = useCallback((newMessages: Message[]) => {
    setMessages(newMessages);
    const cid = activeConvIdRef.current;
    if (cid) messagesCacheRef.current.set(cid, newMessages);
    if (!cid) return;
    const firstUser = newMessages.find(m => m.role === 'user');
    if (!firstUser) return;
    const title = firstUser.content.slice(0, 30) + (firstUser.content.length > 30 ? '...' : '');
    setQuickConvs(prev => prev.map(c => c.id === cid ? { ...c, title } : c));
    setProjectConvs(prev => {
      const next = prev.map(c => c.id === cid ? { ...c, title } : c);
      if (activeProjectId) projectConvsCacheRef.current.set(activeProjectId, next);
      return next;
    });
  }, []);

  const handleSelectConv = useCallback((id: string) => {
    selectConv(id);
  }, [selectConv]);

  const closeSidebar = () => { setSidebarOpen(false); setTimeout(() => setShowOpenBtn(true), 250); };
  const openSidebar  = () => { setShowOpenBtn(false); setSidebarOpen(true); };

  // ── 인증 확인 전 빈 화면 ────────────────────────────────────
  if (!authReady) return <ToastContainer />;

  // ── 비로그인 → 로그인 화면 ──────────────────────────────────
  if (!user) return <><LoginPage onLogin={handleLogin} /><ToastContainer /></>;

  // ── 로그인 후 메인 앱 ───────────────────────────────────────
  const activeConv = [...quickConvs, ...projectConvs].find(c => c.id === activeConvId) ?? null;

  return (
    <div className="app">
      <ToastContainer />
      {showOpenBtn && (
        <button className="sidebar-open-btn" onClick={openSidebar} title="사이드바 열기">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="3" y1="6" x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
          </svg>
        </button>
      )}

      {sidebarOpen && <div className="sidebar-overlay" onClick={closeSidebar} />}
      <Sidebar
        user={user}
        quickConvs={quickConvs}
        projects={projects}
        activeProjectId={activeProjectId}
        projectConvs={projectConvs}
        activeConvId={activeConvId}
        onQuickNew={handleQuickNew}
        onQuickDelete={handleQuickDelete}
        onSelectConversation={handleSelectConv}
        onSelectProject={(id) => selectProject(id === activeProjectId ? null : id)}
        onCreateProject={handleCreateProject}
        onDeleteProject={handleDeleteProject}
        onCreateProjectConv={handleCreateProjectConv}
        onDeleteProjectConv={handleDeleteProjectConv}
        onRenameConversation={handleRenameConversation}
        onClose={closeSidebar}
        onLogout={handleLogout}
        onGoHome={handleGoHome}
        isOpen={sidebarOpen}
        loadingProjectConvs={loadingProjectConvs}
        settings={settings}
        onSettingsChange={handleSettingsChange}
      />

      <ChatArea
        convId={activeConvId}
        canWrite={activeConv?.can_write ?? true}
        messages={messages}
        loadingMessages={loadingMessages}
        onMessagesUpdate={handleMessagesUpdate}
        onNeedConv={handleNeedConv}
        onConvCreated={handleSelectConv}
        settings={settings}
      />
    </div>
  );
}
