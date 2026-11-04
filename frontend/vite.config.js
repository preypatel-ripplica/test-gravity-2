import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      // Beacon dotted CRUDL routes (and /health)
      // edit = editor-screen tracker editor APIs; google = OAuth/GSC helpers
      '^/(auth|user|project|client|channel|video|production|report|social|website|weekly|custom|tracker|edit|google)\\..*': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      // WhatsApp bot API (backend/bot mounted at /bot/api)
      '/bot/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/social_assets': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
