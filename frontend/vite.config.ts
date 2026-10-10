import path from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const backendTarget = process.env.VITE_PROXY_TARGET ?? 'http://localhost:8081';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          firebase: ['firebase/app', 'firebase/auth'],
          markdown: ['react-markdown', 'remark-gfm'],
          vendor: ['react', 'react-dom', 'react-router-dom', '@tanstack/react-query', 'axios'],
        },
      },
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
    proxy: {
      // Same-origin in dev, like nginx: the API, the MCP OAuth endpoints and their discovery
      // documents all go to the local backend, so the consent flow works end to end.
      '/api': { target: backendTarget, changeOrigin: true },
      '/mcp-server': { target: backendTarget, changeOrigin: true },
      '/.well-known': { target: backendTarget, changeOrigin: true },
    },
  },
});
