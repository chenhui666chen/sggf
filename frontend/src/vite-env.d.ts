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


// 提供 vitest 的最小类型声明，避免 tsc 报错
declare module 'vitest' {
  export const describe: (...args: any[]) => void
  export const it: (...args: any[]) => void
  export const expect: (...args: any[]) => any
}
