import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import axios from 'axios'
import {
  REFRESH_RETRY_DELAY_MS,
  REFRESH_RETRY_JITTER_MS,
  __resetRefreshInFlightForTest,
  refreshAccessToken,
} from '../api'

// api.ts 顶层 new ApiClient() 需要 axios.create + 拦截器桩；
// refresh 请求用 axios.post，测试可控。
vi.mock('axios', () => {
  const post = vi.fn()
  const create = vi.fn(() => ({
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: {},
  }))
  return {
    default: {
      post,
      create,
      isAxiosError: (err: unknown) =>
        Boolean(err && typeof err === 'object' && (err as { isAxiosError?: boolean }).isAxiosError === true),
    },
  }
})

function makeErrorResponse(status: number): Error {
  const err = new Error(`http ${status}`) as Error & {
    isAxiosError?: boolean
    response?: { status: number; data: unknown }
  }
  err.isAxiosError = true
  err.response = { status, data: {} }
  return err
}

describe('api refreshAccessToken（P2-4.5 收尾：纯 cookie 语义）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    __resetRefreshInFlightForTest()
  })

  afterEach(() => {
    vi.useRealTimers()
    __resetRefreshInFlightForTest()
    vi.mocked(axios.post).mockReset()
    vi.mocked(axios.create).mockClear()
  })

  it('refresh 返回 200 即视为成功（新令牌由后端 Set-Cookie 下发，body 不再返回）', async () => {
    vi.mocked(axios.post).mockResolvedValueOnce({ status: 200, data: { message: '刷新成功' } })

    expect(await refreshAccessToken()).toBe(true)
    expect(vi.mocked(axios.post)).toHaveBeenCalledWith(expect.stringContaining('/api/v1/auth/refresh'), {}, expect.anything())
  })

  it('429（后端并发刷新锁）后重试一次成功', async () => {
    vi.mocked(axios.post)
      .mockRejectedValueOnce(makeErrorResponse(429))
      .mockResolvedValueOnce({ status: 200, data: {} })

    const promise = refreshAccessToken()
    // 重试等待 = 后端锁 TTL（5s）+ 抖动上限，推进到上限确保定时器触发
    await vi.advanceTimersByTimeAsync(REFRESH_RETRY_DELAY_MS + REFRESH_RETRY_JITTER_MS)
    expect(await promise).toBe(true)
    expect(vi.mocked(axios.post)).toHaveBeenCalledTimes(2)
  })

  it('非 429 失败（401）返回 false 且不重试', async () => {
    vi.mocked(axios.post).mockRejectedValueOnce(makeErrorResponse(401))

    expect(await refreshAccessToken()).toBe(false)
    expect(vi.mocked(axios.post)).toHaveBeenCalledTimes(1)
  })

  it('429 等待期间仍只重试一次（无 storage 接管逻辑）', async () => {
    vi.mocked(axios.post)
      .mockRejectedValueOnce(makeErrorResponse(429))
      .mockRejectedValueOnce(makeErrorResponse(429))

    const promise = refreshAccessToken()
    await vi.advanceTimersByTimeAsync(REFRESH_RETRY_DELAY_MS + REFRESH_RETRY_JITTER_MS)
    expect(await promise).toBe(false)
    expect(vi.mocked(axios.post)).toHaveBeenCalledTimes(2)
  })
})
