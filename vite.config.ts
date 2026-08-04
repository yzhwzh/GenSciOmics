import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const HMR_PORT = 5181

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5180,
    hmr: {
      overlay: false,
      host: '10.243.163.51',
      port: HMR_PORT,
      clientPort: HMR_PORT,
    },
    allowedHosts: ['10.243.163.51', 'localhost', '127.0.0.1'],
    watch: {
      usePolling: false,
      ignored: [
        '**/dist/**',
        '**/.scanner_cache.json',
        '**/*.h5ad',
        '**/GenSci.log',
        '**/milestones.json',
      ],
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:6001',
        changeOrigin: true,
      },
    },
  },
})
