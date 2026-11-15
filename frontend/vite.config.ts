import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Backend runs on :8000 (uv run uvicorn app.main:app --port 8000). Proxying keeps
// the browser on one origin, so SSE and fetch need no CORS. Open http://localhost:5173
// (localhost, not 127.0.0.1: the Matterport SDK key only allows localhost).
const backend = process.env.ROUNDS_BACKEND ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: 'localhost',
    port: 5173,
    proxy: { '/api': backend, '/agent': backend, '/health': backend },
  },
})
