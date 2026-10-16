import React, { lazy, Suspense, useEffect, useState } from 'react';

// Load the local estimate trial before the production chat bundle. Its route must
// not run the chat's auth, usage, conversation, or analytics initialization.
const ChatApp = lazy(() => import('./ChatApp'));
const MultiTradeTrial = lazy(() => import('./components/MultiTradeTrial'));

export default function App() {
  const [pathname, setPathname] = useState(window.location.pathname);
  useEffect(() => {
    const onPopState = () => setPathname(window.location.pathname);
    window.addEventListener('popstate', onPopState);
    return () => window.removeEventListener('popstate', onPopState);
  }, []);
  const localTrial = process.env.REACT_APP_MULTI_TRADE_TRIAL === 'on' && pathname === '/estimate-trial';
  return <Suspense fallback={<main role="status" className="route-loading">화면을 여는 중입니다</main>}>
    {localTrial ? <MultiTradeTrial /> : <ChatApp />}
  </Suspense>;
}
