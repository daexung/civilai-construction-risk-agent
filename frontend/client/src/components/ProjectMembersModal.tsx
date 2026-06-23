import React, { useState, useEffect } from 'react';
import { Project, ProjectMember, ProjectRole } from '../types';
import { fetchProjectMembers, addProjectMember, removeProjectMember } from '../api';
import { showToast } from '../toast';
import './ProjectMembersModal.css';

interface Props {
  project: Project;
  currentUserId: string;
  onClose: () => void;
}

const ROLE_LABEL: Record<ProjectRole, string> = {
  owner:  '소유자',
  member: '멤버',
};

export default function ProjectMembersModal({ project, currentUserId, onClose }: Props) {
  const [members,     setMembers]     = useState<ProjectMember[]>([]);
  const [loading,     setLoading]     = useState(true);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole,  setInviteRole]  = useState<ProjectRole>('member');
  const [inviting,    setInviting]    = useState(false);
  const [inviteError, setInviteError] = useState('');
  const [removingId,  setRemovingId]  = useState<string | null>(null);

  const isOwner = project.my_project_role === 'owner';

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  useEffect(() => {
    fetchProjectMembers(project.id)
      .then(setMembers)
      .catch(() => showToast('멤버 목록을 불러오지 못했습니다.', 'error'))
      .finally(() => setLoading(false));
  }, [project.id]);

  const handleInvite = async () => {
    const email = inviteEmail.trim();
    if (!email) return;
    setInviting(true);
    setInviteError('');
    try {
      const newMember = await addProjectMember(project.id, email, inviteRole);
      setMembers(prev => [...prev, newMember]);
      setInviteEmail('');
      showToast(`${newMember.name}님이 초대됐습니다.`, 'success');
    } catch (e: any) {
      setInviteError(e.message ?? '초대에 실패했습니다.');
    } finally {
      setInviting(false);
    }
  };

  const handleRemove = async (member: ProjectMember) => {
    setRemovingId(member.user_id);
    try {
      await removeProjectMember(project.id, member.user_id);
      setMembers(prev => prev.filter(m => m.user_id !== member.user_id));
      showToast(`${member.name}님이 프로젝트에서 제외됐습니다.`, 'info');
    } catch {
      showToast('멤버 제거에 실패했습니다.', 'error');
    } finally {
      setRemovingId(null);
    }
  };

  return (
    <div className="pm-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="pm-modal">

        {/* 헤더 */}
        <div className="pm-header">
          <div className="pm-header-text">
            <h2 className="pm-title">프로젝트 멤버</h2>
            <p className="pm-subtitle">{project.name}</p>
          </div>
          <button className="pm-close" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/>
              <line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        {/* 멤버 목록 */}
        <div className="pm-section">
          <p className="pm-section-label">멤버 {!loading && `(${members.length}명)`}</p>

          {loading ? (
            <div className="pm-loading">불러오는 중...</div>
          ) : members.length === 0 ? (
            <div className="pm-empty">멤버가 없습니다.</div>
          ) : (
            <div className="pm-members-list">
              {members.map(m => (
                <div key={m.user_id} className="pm-member-row">
                  <div className="pm-avatar">{m.name[0]}</div>
                  <div className="pm-member-info">
                    <span className="pm-member-name">
                      {m.name}
                      {m.user_id === currentUserId && <span className="pm-me-tag">나</span>}
                    </span>
                    <span className="pm-member-email">{m.email}</span>
                  </div>
                  <span className={`pm-role-badge ${m.project_role}`}>
                    {ROLE_LABEL[m.project_role]}
                  </span>
                  {isOwner && m.user_id !== currentUserId && (
                    <button
                      className="pm-remove-btn"
                      onClick={() => handleRemove(m)}
                      disabled={removingId === m.user_id}
                      title="멤버 제거"
                    >
                      {removingId === m.user_id ? '…' : (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <line x1="18" y1="6" x2="6" y2="18"/>
                          <line x1="6" y1="6" x2="18" y2="18"/>
                        </svg>
                      )}
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 초대 폼 (소유자만) */}
        {isOwner && (
          <div className="pm-section pm-invite-section">
            <p className="pm-section-label">멤버 초대</p>
            <div className="pm-invite-row">
              <input
                className="pm-email-input"
                type="email"
                placeholder="이메일 주소 입력"
                value={inviteEmail}
                onChange={e => { setInviteEmail(e.target.value); setInviteError(''); }}
                onKeyDown={e => e.key === 'Enter' && handleInvite()}
              />
              <select
                className="pm-role-select"
                value={inviteRole}
                onChange={e => setInviteRole(e.target.value as ProjectRole)}
              >
                <option value="member">멤버</option>
                <option value="owner">소유자</option>
              </select>
              <button
                className="pm-invite-btn"
                onClick={handleInvite}
                disabled={inviting || !inviteEmail.trim()}
              >
                {inviting ? '초대 중…' : '초대'}
              </button>
            </div>
            {inviteError && <p className="pm-invite-error">{inviteError}</p>}
          </div>
        )}

        {/* 푸터 */}
        <div className="pm-footer">
          <button className="pm-footer-close" onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  );
}
