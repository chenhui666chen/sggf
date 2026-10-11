import { describe, expect, it } from 'vitest'

import { extractCircuitBreakerPause } from '../workflowCircuitBreaker'

describe('workflowCircuitBreaker', () => {
  it('从 409 熔断响应中提取暂停信息供确认弹窗渲染', () => {
    const response = {
      status: 409,
      data: {
        detail: {
          message: '项目自动推进已暂停，请确认暂停原因后再继续生成',
          circuit_breaker: { paused: true, reason: '章节内容为空', paused_at_chapter: 3 },
        },
      },
    }

    expect(extractCircuitBreakerPause(response)).toEqual({
      paused: true,
      reason: '章节内容为空',
      paused_at_chapter: 3,
    })
  })

  it('普通 409（生成锁占用，detail 为字符串）不触发熔断弹窗', () => {
    expect(
      extractCircuitBreakerPause({ status: 409, data: { detail: '该项目正在生成章节中，请稍后重试' } }),
    ).toBeNull()
  })

  it('未暂停或结构缺失时返回 null', () => {
    expect(
      extractCircuitBreakerPause({ status: 409, data: { detail: { circuit_breaker: { paused: false } } } }),
    ).toBeNull()
    expect(extractCircuitBreakerPause({ status: 409, data: { detail: {} } })).toBeNull()
    expect(extractCircuitBreakerPause({ status: 409, data: {} })).toBeNull()
    expect(extractCircuitBreakerPause({ status: 409 })).toBeNull()
    expect(extractCircuitBreakerPause(undefined)).toBeNull()
  })

  it('仅 409 才视为熔断暂停，其他状态码交回原有错误提示', () => {
    expect(
      extractCircuitBreakerPause({
        status: 429,
        data: { detail: { circuit_breaker: { paused: true, reason: '章节内容为空' } } },
      }),
    ).toBeNull()
  })
})
