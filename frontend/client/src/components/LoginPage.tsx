import React, { useState } from 'react';
import { AuthResponse } from '../types';
import { MOCK_MODE, mockLogin } from '../mockData';
import { login as apiLogin } from '../api';
import './LoginPage.css';

interface Props {
  onLogin: (user: Omit<AuthResponse, 'token'>, token: string) => void;
}

export default function LoginPage({ onLogin }: Props) {
  const [email, setEmail]       = useState('');
  const [password, setPassword] = useState('');
  const [error, setError]       = useState('');
  const [loading, setLoading]   = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email || !password) { setError('이메일과 비밀번호를 입력해주세요.'); return; }
    setError('');
    setLoading(true);

    try {
      if (MOCK_MODE) {
        await new Promise(r => setTimeout(r, 600));
        const result = mockLogin(email, password);
        if (!result) { setError('이메일 또는 비밀번호가 올바르지 않습니다.'); return; }
        const { token, ...user } = result;
        onLogin(user, token);
      } else {
        const result = await apiLogin(email, password);
        const { token, ...user } = result;
        onLogin(user, token);
      }
    } catch {
      setError('로그인에 실패했습니다. 다시 시도해주세요.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-logo-text">
          Civil<span>.AI</span>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="login-field">
            <label htmlFor="email">이메일</label>
            <input
              id="email"
              type="email"
              placeholder="이메일을 입력하세요"
              value={email}
              onChange={e => setEmail(e.target.value)}
              disabled={loading}
              autoComplete="email"
            />
          </div>
          <div className="login-field">
            <label htmlFor="password">비밀번호</label>
            <input
              id="password"
              type="password"
              placeholder="비밀번호를 입력하세요"
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
              autoComplete="current-password"
            />
          </div>

          {error && <p className="login-error">{error}</p>}

          <button className="login-btn" type="submit" disabled={loading}>
            {loading ? '로그인 중...' : '로그인'}
          </button>
        </form>

        {MOCK_MODE && (
          <div className="login-mock-hint">
            <p>테스트 계정</p>
            <span>admin@example.com / 1234 (관리자)</span>
            <span>user@example.com / 1234 (일반사원)</span>
          </div>
        )}
      </div>
    </div>
  );
}
