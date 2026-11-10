import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

const BOT_BASE = '/bot/'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Installable bot app (same idea as bot.ripplica.com). Scoped to /bot/ so
    // home-screen installs open the Ripplica inbox, not the whole Plug site.
    VitePWA({
      registerType: 'autoUpdate',
      // SW file stays at /sw.js ( /bot/* is SPA-only), but claim only /bot so
      // Chrome's installability check lines up with the manifest scope.
      scope: BOT_BASE,
      includeAssets: [
        'bot-assets/apple-touch-icon.png',
        'bot-assets/favicon.png',
        'bot-assets/pwa-192x192.png',
        'bot-assets/pwa-512x512.png',
        'bot-assets/pwa-maskable-512x512.png',
      ],
      devOptions: { enabled: true, type: 'module' },
      workbox: {
        navigateFallback: '/index.html',
        navigateFallbackAllowlist: [/^\/bot/],
        // Keep desktop-only / spreadsheet chunks out of the precache so phone
        // installs stay small; fetch them on demand instead.
        globIgnores: [
          '**/xlsx-*.js',
          '**/LeadsGrid-*.js',
          '**/Broadcasts-*.js',
          '**/Templates-*.js',
          '**/Contacts-*.js',
          '**/Calls-*.js',
          '**/SendTemplateModal-*.js',
        ],
        runtimeCaching: [
          {
            urlPattern: /\/assets\/.*\.(js|css)$/,
            handler: 'StaleWhileRevalidate',
            options: {
              cacheName: 'assets-on-demand',
              expiration: { maxEntries: 40, maxAgeSeconds: 60 * 60 * 24 * 30 },
            },
          },
          {
            // Icons + apple-touch must never stick as grayscale/stale copies on
            // a phone that installed before the RGB re-encode.
            urlPattern: /\/bot-assets\/.*\.png$/,
            handler: 'NetworkFirst',
            options: {
              cacheName: 'bot-icons',
              expiration: { maxEntries: 12, maxAgeSeconds: 60 * 60 * 24 * 7 },
            },
          },
        ],
      },
      manifest: {
        id: BOT_BASE,
        name: 'Ripplica',
        short_name: 'Ripplica',
        description: 'Ripplica inbox',
        start_url: BOT_BASE,
        scope: BOT_BASE,
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#f6f7f9',
        theme_color: '#f6f7f9',
        // Same dark-scheme paint as bot.ripplica.com so Android status bar
        // matches when the phone itself is in dark mode.
        user_preferences: {
          color_scheme_dark: {
            theme_color: '#0b0e14',
            background_color: '#0b0e14',
          },
        },
        icons: [
          { src: '/bot-assets/pwa-192x192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/bot-assets/pwa-512x512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          {
            src: '/bot-assets/pwa-maskable-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      // Beacon dotted CRUDL routes (and /health)
      // edit = editor-screen tracker editor APIs; google = OAuth/GSC helpers
      '^/(auth|user|project|client|channel|video|production|report|social|website|weekly|custom|tracker|edit|google)\\..*': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        timeout: 3_600_000,
        proxyTimeout: 3_600_000,
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
