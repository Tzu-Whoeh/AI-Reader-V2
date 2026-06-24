import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 合并后端单端口:开发期 /new/api 全部透传到 :8080。产物输出到 app/server/static/。
const BASE = process.env.VITE_BASE || '/new/'

export default defineConfig({
  base: BASE,
  plugins: [react()],
  build: { outDir: '../server/static', emptyOutDir: true },
  server: {
    port: 5173,
    proxy: { '/new/api': { target: 'http://127.0.0.1:8080', changeOrigin: true } },
  },
})
