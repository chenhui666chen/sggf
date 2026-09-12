import { describe, expect, it, vi } from 'vitest'
import { extractApiErrorMessage } from '../api'

// api.ts 顶层 new ApiClient() 需要 axios.create 桩，同 apiRefresh.test.ts
vi.mock('axios', () => ({
  default: {
    create: () => ({
      interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
      defaults: {},
    }),
    isAxiosError: (err: unknown) =>
      Boolean(err && typeof err === 'object' && (err as { isAxiosError?: boolean }).isAxiosError === true),
  },
}))

function makeAuthError(detail: string): Error {
  const err = new Error('http 401') as Error & {
    isAxiosError?: boolean
    response?: { status: number; data: unknown }
  }
  err.isAxiosError = true
  err.response = { status: 401, data: { detail } }
  return err
}

describe('extractApiErrorMessage 本地化', () => {
  it('把后端英文鉴权 detail 翻译为中文，避免英文原文直出 UI', async () => {
    expect(await extractApiErrorMessage(makeAuthError('Not authenticated'), '登录状态已失效')).toBe(
      '登录状态已失效，请重新登录',
    )
  })

  it('把 Could not validate credentials 翻译为中文', async () => {
    expect(await extractApiErrorMessage(makeAuthError('Could not validate credentials'), '登录状态已失效')).toBe(
      '登录凭证校验失败，请重新登录',
    )
  })

  it('未登记的英文 detail 保持原样，不做猜测翻译', async () => {
    expect(await extractApiErrorMessage(makeAuthError('Some unknown error'), '请求失败')).toBe('Some unknown error')
  })
})
