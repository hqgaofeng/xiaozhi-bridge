import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 3000,
    proxy: {
      // V2 #5: /api/* goes to the bridge-api FastAPI process on 8001
      // (the WS bridge on 8000 doesn't serve HTTP routes). /xiaozhi/*
      // stays pointed at 8000 for the WebSocket upgrade.
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
      '/xiaozhi': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
})
