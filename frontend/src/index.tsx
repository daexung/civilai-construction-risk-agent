import React from 'react';
import { createRoot, hydrateRoot } from 'react-dom/client';
import './index.css';
import App from './App';
import Landing from './landing/Landing';
import OwnerDashboard from './OwnerDashboard';
import { trackPage } from './analytics';

const container = document.getElementById('root') as HTMLElement;
const prerenderedHome = container.dataset.prerendered === 'homepage' && window.location.pathname === '/';
const ownerDashboard = window.location.pathname === '/admin' || window.location.pathname === '/admin/';
if (prerenderedHome) {
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
      <OwnerDashboard />
    </React.StrictMode>
  );
} else {
  createRoot(container).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
