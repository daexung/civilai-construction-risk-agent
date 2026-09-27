import React, { useState, useEffect } from 'react';
import { ProjectCreateRequest } from '../types';
import './ProjectCreateModal.css';

interface Props {
  onConfirm: (req: ProjectCreateRequest) => void;
  onClose: () => void;
}

const EMPTY: ProjectCreateRequest = {
  name: '', site_name: '', address: '',
  start_date: '', end_date: '', description: '',
};

export default function ProjectCreateModal({ onConfirm, onClose }: Props) {
  const [form, setForm] = useState<ProjectCreateRequest>(EMPTY);

  const set = (field: keyof ProjectCreateRequest, value: string | number) =>
    setForm(prev => ({ ...prev, [field]: value }));

  const dateError =
    form.start_date && form.end_date && form.end_date < form.start_date
      ? '준공일은 착공일 이후여야 합니다.'
      : '';

  const canSubmit = !!form.name.trim() && !!form.site_name.trim() && !dateError;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) return;
    onConfirm({ ...form, name: form.name.trim(), site_name: form.site_name.trim() });
  };

  return (
    <div className="modal-overlay" onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal-card">
        <div className="modal-header">
          <h2 className="modal-title">새 프로젝트</h2>
          <button className="modal-close" onClick={onClose}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>
            </svg>
          </button>
        </div>

        <form className="modal-form" onSubmit={handleSubmit}>
          <div className="modal-section-label">기본 정보</div>

          <div className="modal-field">
            <label>공사명 <span className="required">*</span></label>
            <input placeholder="예: 마포구 오피스텔 신축공사" value={form.name}
              onChange={e => set('name', e.target.value)} autoFocus/>
          </div>

          <div className="modal-field">
            <label>현장명 <span className="required">*</span></label>
            <input placeholder="예: 마포 현장" value={form.site_name}
              onChange={e => set('site_name', e.target.value)}/>
          </div>

          <div className="modal-field">
            <label>현장 주소</label>
            <input placeholder="예: 서울특별시 마포구 공덕동 105-3" value={form.address}
              onChange={e => set('address', e.target.value)}/>
          </div>

          <div className="modal-section-label" style={{ marginTop: 8 }}>공사 기간</div>

          <div className="modal-row-2">
            <div className="modal-field">
              <label>착공일</label>
              <input type="date" value={form.start_date}
                onChange={e => set('start_date', e.target.value)}/>
            </div>
            <div className="modal-field">
              <label>준공일</label>
              <input type="date" value={form.end_date}
                onChange={e => set('end_date', e.target.value)}/>
            </div>
          </div>
          {dateError && <p className="modal-field-error">{dateError}</p>}

          <div className="modal-field">
            <label>설명</label>
            <textarea placeholder="현장 특이사항, 주요 공종 등을 입력하세요" rows={3}
              value={form.description} onChange={e => set('description', e.target.value)}/>
          </div>

          <div className="modal-footer">
            <button type="button" className="modal-btn-cancel" onClick={onClose}>취소</button>
            <button type="submit" className="modal-btn-confirm" disabled={!canSubmit}>
              프로젝트 만들기
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
