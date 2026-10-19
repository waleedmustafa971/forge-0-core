import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import './styles.css';

const saved = (() => {
  try {
    return localStorage.getItem('forge0-theme');
  } catch {
    return null;
  }
})();
document.documentElement.dataset.theme = saved === 'light' ? 'light' : 'dark';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
