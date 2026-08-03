import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // DEV_PROXY_TARGET is server-only (not VITE_-prefixed, never reaches the
  // browser bundle) — lets Docker point the proxy at the backend container
  // without affecting VITE_API_BASE, which chat-client.js bakes into fetch
  // URLs on the client and must stay blank for same-origin dev proxying.
  const apiBase = env.DEV_PROXY_TARGET || env.VITE_API_BASE || 'http://localhost:8000'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/api': {
          target: apiBase,
          changeOrigin: true,
        },
      },
    },
  }
})
