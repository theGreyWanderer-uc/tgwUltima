import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import { useWorldState } from './store';
import './styles.css';

// Expose the Zustand store on globalThis so Playwright tests can inject flags
// and read engine state via page.evaluate().
if (typeof globalThis !== 'undefined') {
  (globalThis as any).useWorldState = useWorldState;
}

const root = document.getElementById('root');
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>
  );
}
