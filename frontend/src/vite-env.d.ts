/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  readonly DEV: boolean
  readonly PROD: boolean
  readonly MODE: string
  // 在此添加更多环境变量类型...
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
