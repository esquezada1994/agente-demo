import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// En desarrollo, /api va al backend del agente: misma "origin" para la cookie
// de sesión, igual que en producción detrás de nginx.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    port: 5180,
    host: true,
    proxy: { '/api': process.env.AGENT_API_URL ?? 'http://localhost:8100' },
  },
})
