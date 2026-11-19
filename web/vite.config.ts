import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';

// We proxy every backend path so the frontend + backend share a single origin.
// That lets us tunnel the whole app through one HTTPS URL for iPhone Safari.
const BACKEND = 'http://127.0.0.1:8000';

export default defineConfig({
  plugins: [react(), basicSsl()],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true,
  },
  server: {
    host: true,
    port: 5173,
    allowedHosts: true,
    proxy: {
      '/ws/live':  { target: BACKEND, ws: true, changeOrigin: true },
      '/ws/sweep': { target: BACKEND, ws: true, changeOrigin: true },
      '/agent':    { target: BACKEND, changeOrigin: true },
      '/stt':      { target: BACKEND, changeOrigin: true },
      '/sweeps':   { target: BACKEND, changeOrigin: true },
      '/health':   { target: BACKEND, changeOrigin: true },
    },
  },
});
