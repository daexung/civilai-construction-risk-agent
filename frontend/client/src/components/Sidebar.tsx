import React, { useState, useRef } from 'react';
import { User, Project, Conversation, ProjectCreateRequest } from '../types';
import { Settings } from '../settings';
import ProjectCreateModal from './ProjectCreateModal';
import ProjectMembersModal from './ProjectMembersModal';
import UserMenu from './UserMenu';
import './Sidebar.css';

interface Props {
  user: User;
  quickConvs: Conversation[];
  projects: Project[];
  activeProjectId: string | null;
  projectConvs: Conversation[];
  activeConvId: string | null;
  onQuickNew: () => void;
  onQuickDelete: (id: string) => void;
  onSelectConversation: (id: string) => void;
  onSelectProject: (id: string) => void;
  onCreateProject: (req: ProjectCreateRequest) => void;
  onDeleteProject: (id: string) => void;
  onCreateProjectConv: () => void;
  onDeleteProjectConv: (id: string) => void;
  onRenameConversation: (convId: string, title: string) => void;
  onClose: () => void;
  onLogout: () => void;
  onGoHome: () => void;
  isOpen: boolean;
  loadingProjectConvs: boolean;
  settings: Settings;
  onSettingsChange: (s: Settings) => void;
}


function ConvItem({
  conv, isActive, onSelect, onDelete, onRename, showOwner,
}: {
  conv: Conversation; isActive: boolean;
  onSelect: () => void;
  onDelete: (() => void) | null;
  onRename: ((title: string) => void) | null;
  showOwner?: boolean;
}) {
  const [confirmDel, setConfirmDel] = useState(false);
  const [isRenaming, setIsRenaming]   = useState(false);
  const [renameVal, setRenameVal]     = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const startRename = () => {
    setRenameVal(conv.title);
    setIsRenaming(true);
  };

  const commitRename = () => {
    const t = renameVal.trim();
    if (t && t !== conv.title) onRename?.(t);
    setIsRenaming(false);
  };

  if (isRenaming) {
    return (
      <div className="list-item-row renaming">
        <input
          ref={inputRef}
          className="conv-rename-input"
          value={renameVal}
          onChange={e => setRenameVal(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter')  { e.preventDefault(); commitRename(); }
            if (e.key === 'Escape') setIsRenaming(false);
          }}
          onBlur={commitRename}
          autoFocus
          maxLength={100}
        />
      </div>
    );
  }

  return (
    <div className="list-item-row">
      <button
        className={`conversation-item ${isActive ? 'active' : ''}`}
        onClick={onSelect}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <div className="conv-item-inner">
          <span className="conv-title">{conv.title}</span>
          {showOwner && (
            <span className={`conv-owner ${conv.can_write ? '' : 'readonly'}`}>
              {conv.owner_name}
              {!conv.can_write && ' · 읽기전용'}
            </span>
          )}
        </div>
      </button>

      {onRename && (
        <button className="row-rename-btn" onClick={startRename} title="제목 변경">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
      )}

      {onDelete && (
        confirmDel ? (
          <div className="delete-confirm">
            <button className="del-yes" onClick={() => { onDelete(); setConfirmDel(false); }}>삭제</button>
            <button className="del-no"  onClick={() => setConfirmDel(false)}>취소</button>
          </div>
        ) : (
          <button className="row-delete-btn" onClick={() => setConfirmDel(true)} title="삭제">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polyline points="3 6 5 6 21 6"/>
              <path d="M19 6l-1 14H6L5 6"/>
              <path d="M10 11v6M14 11v6"/>
              <path d="M9 6V4h6v2"/>
            </svg>
          </button>
        )
      )}
    </div>
  );
}

function ConvSkeleton() {
  return (
    <div className="conv-skeleton-list">
      {[1, 2, 3].map(i => (
        <div key={i} className="conv-skeleton-item">
          <div className="conv-skeleton-icon" />
          <div className="conv-skeleton-lines">
            <div className="conv-skeleton-title" style={{ width: `${55 + i * 12}%` }} />
            <div className="conv-skeleton-sub" style={{ width: `${30 + i * 8}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function Sidebar({
  user, quickConvs, projects, activeProjectId, projectConvs, activeConvId,
  onQuickNew, onQuickDelete, onSelectConversation,
  onSelectProject, onCreateProject, onDeleteProject,
  onCreateProjectConv, onDeleteProjectConv,
  onRenameConversation,
  onClose, onLogout, onGoHome, isOpen,
  loadingProjectConvs,
  settings, onSettingsChange,
}: Props) {
  const [projectsOpen, setProjectsOpen]       = useState(true);
  const [quickOpen, setQuickOpen]             = useState(true);
  const [showNewProject, setShowNewProject]   = useState(false);
  const [delProjId, setDelProjId]             = useState<string | null>(null);
  const [membersProjId, setMembersProjId]     = useState<string | null>(null);
  const [searchQuery, setSearchQuery]         = useState('');
  const isAdmin = user.role === 'admin';

  const q = searchQuery.trim().toLowerCase();
  const filteredQuickConvs  = q ? quickConvs.filter(c => c.title.toLowerCase().includes(q))   : quickConvs;
  const filteredProjectConvs = q ? projectConvs.filter(c => c.title.toLowerCase().includes(q)) : projectConvs;
  const filteredProjects     = q ? projects.filter(p =>
    p.name.toLowerCase().includes(q) || p.site_name.toLowerCase().includes(q)
  ) : projects;

  const handleCreateProject = (req: ProjectCreateRequest) => {
    onCreateProject(req);
    setShowNewProject(false);
    setProjectsOpen(true);
  };

  return (
    <>
    {showNewProject && (
      <ProjectCreateModal
        onConfirm={handleCreateProject}
        onClose={() => setShowNewProject(false)}
      />
    )}
    {membersProjId && (() => {
      const proj = projects.find(p => p.id === membersProjId);
      return proj ? (
        <ProjectMembersModal
          project={proj}
          currentUserId={user.user_id}
          onClose={() => setMembersProjId(null)}
        />
      ) : null;
    })()}
    <aside className={`sidebar ${isOpen ? 'open' : 'closed'}`}>
      {/* ── 헤더 ── */}
      <div className="sidebar-header">
        <div className="logo-row">
          <button className="logo-btn" onClick={onGoHome} title="홈으로">
            Civil<span className="logo-ai">.AI</span>
          </button>
          <button className="close-btn" onClick={onClose} title="사이드바 닫기">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
              <rect x="3" y="3" width="18" height="18" rx="2"/>
              <line x1="9" y1="3" x2="9" y2="21"/>
            </svg>
          </button>
        </div>
        <button className="new-chat-btn" onClick={onQuickNew}>
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5"  y1="12" x2="19" y2="12"/>
          </svg>
          새 대화
        </button>

        <div className="sidebar-search-wrap">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="sidebar-search-icon">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input
            className="sidebar-search"
            type="text"
            placeholder="대화 검색"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button className="sidebar-search-clear" onClick={() => setSearchQuery('')}>
              <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* ── 프로젝트 섹션 ── */}
      <div className="project-section">
        <div className="project-section-header">
          <button className="project-toggle-btn" onClick={() => setProjectsOpen(v => !v)}>
            <svg
              width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5"
              style={{ transform: projectsOpen ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}
            >
              <polyline points="9 18 15 12 9 6"/>
            </svg>
            <span>프로젝트</span>
            {projects.length > 0 && <span className="proj-count">{projects.length}</span>}
          </button>

          {isAdmin && (
            <button
              className="icon-btn"
              onClick={() => { setShowNewProject(v => !v); setProjectsOpen(true); }}
              title="새 프로젝트 (관리자)"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="12" y1="5" x2="12" y2="19"/>
                <line x1="5"  y1="12" x2="19" y2="12"/>
              </svg>
            </button>
          )}
        </div>

        {projectsOpen && (
          <div className="project-body">

            {filteredProjects.length === 0 && !showNewProject && (
              <p className="empty-hint">
                {q ? '검색 결과가 없습니다' : isAdmin ? '+ 버튼으로 프로젝트를 만드세요' : '참여 중인 프로젝트가 없습니다'}
              </p>
            )}

            {/* 프로젝트 목록 */}
            {filteredProjects.map(proj => (
              <div key={proj.id}>
                <div className="list-item-row">
                  <button
                    className={`conversation-item project-item ${activeProjectId === proj.id ? 'active' : ''}`}
                    onClick={() => onSelectProject(proj.id)}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
                    </svg>
                    <div className="conv-item-inner">
                      <span className="conv-title">{proj.name}</span>
                      <span className="conv-owner">{proj.site_name || proj.work_type}</span>
                    </div>
                  </button>

                  {/* 멤버 버튼 — 전체 공개, hover 시 표시 */}
                  <button
                    className="row-members-btn"
                    onClick={() => setMembersProjId(proj.id)}
                    title="멤버 관리"
                  >
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                      <circle cx="9" cy="7" r="4"/>
                      <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                      <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                    </svg>
                  </button>

                  {proj.my_project_role === 'owner' && (
                    delProjId === proj.id ? (
                      <div className="delete-confirm">
                        <button className="del-yes" onClick={() => { onDeleteProject(proj.id); setDelProjId(null); }}>삭제</button>
                        <button className="del-no"  onClick={() => setDelProjId(null)}>취소</button>
                      </div>
                    ) : (
                      <button className="row-delete-btn" onClick={() => setDelProjId(proj.id)} title="삭제">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <polyline points="3 6 5 6 21 6"/>
                          <path d="M19 6l-1 14H6L5 6"/>
                          <path d="M10 11v6M14 11v6"/>
                          <path d="M9 6V4h6v2"/>
                        </svg>
                      </button>
                    )
                  )}
                </div>

                {activeProjectId === proj.id && (
                  <div className="project-convs">
                    <button className="new-proj-conv-btn" onClick={onCreateProjectConv}>
                      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <line x1="12" y1="5" x2="12" y2="19"/>
                        <line x1="5"  y1="12" x2="19" y2="12"/>
                      </svg>
                      새 대화
                    </button>
                    {loadingProjectConvs ? (
                      <ConvSkeleton />
                    ) : (
                      <>
                        {filteredProjectConvs.map(conv => (
                          <ConvItem
                            key={conv.id}
                            conv={conv}
                            isActive={activeConvId === conv.id}
                            onSelect={() => onSelectConversation(conv.id)}
                            onDelete={conv.can_write ? () => onDeleteProjectConv(conv.id) : null}
                            onRename={conv.can_write ? (t) => onRenameConversation(conv.id, t) : null}
                            showOwner
                          />
                        ))}
                        {filteredProjectConvs.length === 0 && (
                          <p className="empty-hint" style={{ paddingLeft: 8 }}>
                            {q ? '검색 결과가 없습니다' : '대화가 없습니다'}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── 내 대화 섹션 ── */}
      <div className="quick-section">
        <div className="project-section-header">
          <button className="project-toggle-btn" onClick={() => setQuickOpen(v => !v)}>
            <svg
              width="12" height="12" viewBox="0 0 24 24" fill="none"
              stroke="currentColor" strokeWidth="2.5"
              style={{ transform: quickOpen ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s' }}
            >
              <polyline points="9 18 15 12 9 6"/>
            </svg>
            <span>내 대화</span>
            {quickConvs.length > 0 && <span className="proj-count">{quickConvs.length}</span>}
          </button>

        </div>

        {quickOpen && (
          <div className="conversation-list">
            {filteredQuickConvs.length === 0 && (
              <p className="empty-hint">
                {q ? '검색 결과가 없습니다' : '새 대화 버튼으로 시작하세요'}
              </p>
            )}
            {filteredQuickConvs.map(conv => (
              <ConvItem
                key={conv.id}
                conv={conv}
                isActive={activeConvId === conv.id}
                onSelect={() => onSelectConversation(conv.id)}
                onDelete={() => onQuickDelete(conv.id)}
                onRename={(t) => onRenameConversation(conv.id, t)}
              />
            ))}
          </div>
        )}
      </div>

      {/* ── 푸터: 유저 메뉴 ── */}
      <UserMenu user={user} onLogout={onLogout} settings={settings} onSettingsChange={onSettingsChange} />
    </aside>
    </>
  );
}
