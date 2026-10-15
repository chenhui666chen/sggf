import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const LOCAL_BACKEND_TARGET = process.env.VITE_DEV_BACKEND_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [
    react({
      babel: {
        plugins: ['@emotion/babel-plugin'],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
    dedupe: [
      '@mui/icons-material',
      '@mui/material',
      '@mui/system',
      '@mui/styled-engine',
      '@emotion/react',
      '@emotion/styled',
    ],
  },
  server: {
    port: 5173,
    strictPort: true,
    middlewareMode: false,
    // 强制 dev 响应不写入浏览器磁盘缓存。
    // 背景：强杀 vite 时，某个懒加载 chunk 的响应体可能只写了半截，
    // 但 ETag 已经落盘；之后浏览器发条件请求命中 304，就会复用那条
    // 截断的 body，表现为登录后进入 /home 等懒加载页面白屏，
    // 且 Ctrl+Shift+R 无法修复（硬刷新只是不断确认这条坏缓存）。
    // 设为 no-store 后响应永不入缓存，从根上消除该故障模式。
    headers: {
      'Cache-Control': 'no-store, no-cache, must-revalidate, max-age=0',
      Pragma: 'no-cache',
      Expires: '0',
    },
    hmr: {
      protocol: 'ws',
      host: 'localhost',
    },
    fs: {
      cachedChecks: true,
    },
    proxy: {
      '/api/workflow': {
        target: LOCAL_BACKEND_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/workflow/, '/api/v1/workflow'),
        headers: {
          Connection: 'keep-alive',
        },
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            if (req.headers.authorization) {
              proxyReq.setHeader('Authorization', req.headers.authorization)
              console.log(
                'Vite proxy forwarded authorization header (workflow):',
                req.headers.authorization.substring(0, 20) + '...',
              )
            }
          })
        },
      },
      '/api': {
        target: LOCAL_BACKEND_TARGET,
        changeOrigin: true,
        headers: {
          Connection: 'keep-alive',
        },
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            if (req.headers.authorization) {
              proxyReq.setHeader('Authorization', req.headers.authorization)
              console.log(
                'Vite proxy forwarded authorization header:',
                req.headers.authorization.substring(0, 20) + '...',
              )
            }
          })
        },
      },
      '/socket.io': {
        target: LOCAL_BACKEND_TARGET,
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    minify: 'terser',
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom', 'react-router-dom'],
          ui: ['@mui/material', '@mui/icons-material'],
          state: ['@reduxjs/toolkit', 'react-redux'],
          utils: ['axios', 'date-fns', 'clsx'],
        },
      },
    },
  },
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      '@reduxjs/toolkit',
      'react-redux',
      '@emotion/react',
      '@emotion/styled',
      'prop-types',
      'react-is',
      'axios',
    ],
  },
})
