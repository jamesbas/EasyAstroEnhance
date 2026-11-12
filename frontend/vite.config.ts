import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev: run the backend with EASYASTRO_DEV_ORIGINS=http://localhost:5173 so the proxied origin is accepted.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true },
    },
  },
  build: { outDir: 'dist', sourcemap: false },
});
