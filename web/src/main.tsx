import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

// StrictMode double-mounts effects in dev, which clashes with the camera/mic lifecycle
// (start → stop → start crashes the MediaStream). Omitted intentionally.
createRoot(document.getElementById('root')!).render(<App />);
