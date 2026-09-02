import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // ADR-0015 one-port collapse: the app calls the API at same-origin paths
  // (see src/api.ts). In `vite dev` those paths are served by this dev
  // server, so proxy the backend's route prefixes through to uvicorn on
  // :8000. Keep this list in sync with the routers in backend/app/.
  server: {
    proxy: {
      '^/(cases|budget|observability|evaluation|config|health|webhooks)(/|$)': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
