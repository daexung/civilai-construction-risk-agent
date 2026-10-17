import React, { lazy, Suspense, useEffect, useState } from 'react';
import './App.css';

// Load the local estimate trial before the production chat bundle. Its route must
// not run the chat's auth, usage, conversation, or analytics initialization.
const ChatApp = lazy(() => import('./ChatApp'));
const MultiTradeTrial = lazy(() => import('./components/MultiTradeTrial'));

export function ChatLoadingSkeleton() {
  return <main className="chat-loading" aria-busy="true" aria-label="채팅 화면을 불러오는 중">
    <div className="chat-loading-sidebar" aria-hidden="true">
      <div className="chat-loading-brand" />
      <div className="chat-loading-nav">
        <i /><i /><i />
      </div>
      <div className="chat-loading-sidebar-bottom"><i /><i /></div>
    </div>
    <div className="chat-loading-workspace">
      <header className="chat-loading-header" aria-hidden="true"><span /><span /></header>
      <div className="chat-loading-body" aria-hidden="true">
        <div className="chat-loading-lines"><i /><i /><i /></div>
      </div>
      <div className="chat-loading-composer" aria-hidden="true"><i /><b /></div>
    </div>
    <span className="chat-loading-status" role="status">화면을 여는 중입니다</span>
  </main>;
}

function TrialLoadingFallback() {
  return <main className="route-loading" role="status" aria-busy="true">시험 화면을 여는 중입니다</main>;
}

export default function App() {
  const [pathname, setPathname] = useState(window.location.pathname);
  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  const localTrial = process.env.REACT_APP_MULTI_TRADE_TRIAL === 'on' && pathname === '/estimate-trial';
  return <Suspense fallback={localTrial ? <TrialLoadingFallback /> : <ChatLoadingSkeleton />}>
    {localTrial ? <MultiTradeTrial /> : <ChatApp />}
  </Suspense>;
}
