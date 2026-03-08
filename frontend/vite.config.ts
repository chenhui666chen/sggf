import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [
    react({
      jsxImportSource: '@emotion/react',
      babel: {
        plugins: ['@emotion/babel-plugin'],
      },
    }),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,  // 统一使用 Vite 默认端口
    strictPort: true,  // 强制使用指定端口，避免自动切换
    // 优化开发服务器性能
    middlewareMode: false,
    hmr: {
      protocol: 'ws',
      host: 'localhost',
      port: 5173,
    },
    // 启用缓存
    fs: {
      cachedChecks: true,
    },
    proxy: {
      // 特殊处理 /api/workflow 路径，重写为 /api/v1/workflow
      '/api/workflow': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api\/workflow/, '/api/v1/workflow'),
        headers: {
          'Connection': 'keep-alive',
        },
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            // 确保Authorization头被传递
            if (req.headers.authorization) {
              proxyReq.setHeader('Authorization', req.headers.authorization)
              console.log('🔑 Vite代理传递Authorization头 (workflow):', req.headers.authorization.substring(0, 20) + '...')
            }
          })
        },
      },
      // 其他 /api 请求保持不变
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // 保留所有请求头，包括Authorization
        headers: {
          'Connection': 'keep-alive',
        },
        // 不重写请求头
        configure: (proxy, _options) => {
          proxy.on('proxyReq', (proxyReq, req, _res) => {
            // 确保Authorization头被传递
            if (req.headers.authorization) {
              proxyReq.setHeader('Authorization', req.headers.authorization)
              console.log('🔑 Vite代理传递Authorization头:', req.headers.authorization.substring(0, 20) + '...')
            }
          })
        },
      },
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    minify: 'terser',
    // 优化 chunk 分割
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor': ['react', 'react-dom', 'react-router-dom'],
          'ui': ['@mui/material', '@mui/icons-material'],
          'state': ['@reduxjs/toolkit', 'react-redux'],
          'utils': ['axios', 'date-fns', 'clsx'],
        }
      }
    }
  },
  // 优化依赖预构建
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      '@reduxjs/toolkit',
      'react-redux',
      '@mui/material',
      '@mui/icons-material',
      '@emotion/react',
      '@emotion/styled',
      'axios',
    ],
  },
})
