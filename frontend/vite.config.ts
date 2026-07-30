import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const LOCAL_BACKEND_TARGET = 'http://127.0.0.1:8000'

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
