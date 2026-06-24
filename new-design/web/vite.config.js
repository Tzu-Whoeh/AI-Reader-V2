import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// base 可配:开发期 /new/,迁顶层时设 VITE_BASE=/ 即可,无需改代码。
// 产物输出到 pipeline/static/,由 server.py 托管。
const BASE = process.env.VITE_BASE || '/new/'

export default defineConfig({
  base: BASE,
  plugins: [react()],
  build: {
    outDir: '../pipeline/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    // 开发期把 API 透传到本地后端(server.py --base-path=/new 起在 8081)
    proxy: {
      '/new/api': {
        target: 'http://127.0.0.1:8081',
        changeOrigin: true,
      },
    },
  },
})
