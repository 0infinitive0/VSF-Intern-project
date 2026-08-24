import { resolve } from 'node:path'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Vite's dev server only history-API-falls-back to the DEFAULT index.html.
// admin.html is a second, non-default entry, so a request for
// /admin/orders (the admin SPA's own client-side route, not a real file)
// 404s from the dev server unless something rewrites it first. Mirrors
// nginx.conf's `location /admin { try_files ... /admin.html; }` for prod.
function adminHistoryFallback(): Plugin {
  return {
    name: 'admin-history-fallback',
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        const url = req.url ?? ''
        const isAdminRoute = url === '/admin' || url.startsWith('/admin/')
        const isRealFile = /\.[a-zA-Z0-9]+($|\?)/.test(url)
        if (isAdminRoute && !isRealFile) req.url = '/admin.html'
        next()
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // DEV_PROXY_TARGET is server-only (not VITE_-prefixed, never reaches the
  // browser bundle) — lets Docker point the proxy at the backend container
  // without affecting VITE_API_BASE, which chat-client.js bakes into fetch
  // URLs on the client and must stay blank for same-origin dev proxying.
  const apiBase = env.DEV_PROXY_TARGET || env.VITE_API_BASE || 'http://localhost:8000'

  return {
    plugins: [react(), tailwindcss(), adminHistoryFallback()],
    build: {
      rollupOptions: {
        input: {
          main: resolve(__dirname, 'index.html'),
          admin: resolve(__dirname, 'admin.html'),
        },
      },
    },
    server: {
      proxy: {
        '/api': {
          target: apiBase,
          changeOrigin: true,
        },
      },
    },
    test: {
      setupFiles: ['./src/test-setup.ts'],
    },
  }
})
