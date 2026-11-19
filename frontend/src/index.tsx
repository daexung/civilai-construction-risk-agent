import React, { Suspense, lazy } from 'react';
import { createRoot, hydrateRoot } from 'react-dom/client';
import './index.css';
import App from './App';
import Landing from './landing/Landing';
import HelpPage from './help/HelpPages';
import { trackPage } from './analytics';

const OwnerDashboard = lazy(() => import('./OwnerDashboard'));

const container = document.getElementById('root') as HTMLElement;
const prerenderedHome = container.dataset.prerendered === 'homepage' && window.location.pathname === '/';
const ownerDashboard = window.location.pathname === '/admin' || window.location.pathname === '/admin/';
const publicPage = window.location.pathname.replace(/\/$/, '');
if ((publicPage === '/guide' || publicPage === '/examples') && container.dataset.prerendered === publicPage.slice(1)) {
  hydrateRoot(container, <React.StrictMode><HelpPage page={publicPage === '/guide' ? 'guide' : 'examples'} /></React.StrictMode>);
} else if (prerenderedHome) {
  trackPage('/');
  hydrateRoot(container,
    <React.StrictMode>
      <Landing
        onStart={() => window.location.assign('/chat')}
        onExample={question => window.location.assign(`/chat?q=${encodeURIComponent(question)}`)}
      />
    </React.StrictMode>
  );
} else if (ownerDashboard) {
  createRoot(container).render(
    <React.StrictMode>
      <Suspense fallback={<main role="status">운영자 화면을 여는 중입니다</main>}>
        <OwnerDashboard />
      </Suspense>
    </React.StrictMode>
  );
} else {
  createRoot(container).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
