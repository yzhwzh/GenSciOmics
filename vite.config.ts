import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const HMR_PORT = 5181

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5180,
    // 端口被占时直接报错退出，而不是静默顺延到 5182/5183/5184。
    // 2026-10-19 清出过 3 个这样的僵尸实例：反复 npm run dev 后各自漂到
    // 相邻端口，ps 里看起来都"启动成功"，实际只有第一个在服务，
    // 其余既没客户端连接、HMR 也抢不到 5181（hmr.port 是写死的）。
    strictPort: true,
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
