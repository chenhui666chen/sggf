export interface CircuitBreakerPause {
  paused: boolean
  reason?: string
  paused_at_chapter?: number | null
}

interface GenerateNextChapterResponse {
  status?: number
  data?: {
    detail?: unknown
  } | null
}

/**
 * 从"生成下一章"的响应中提取熔断暂停信息。
 *
 * 后端只在自动推进被熔断时返回 409 + detail.circuit_breaker；
 * 生成锁占用的 409 其 detail 是纯字符串，必须返回 null 走普通提示，
 * 否则会把"任务进行中"误报成需要人工确认的熔断。
 */
export function extractCircuitBreakerPause(
  response: GenerateNextChapterResponse | null | undefined,
): CircuitBreakerPause | null {
  if (response?.status !== 409) {
    return null
  }

  const detail = response.data?.detail
  if (typeof detail !== 'object' || detail === null) {
    return null
  }

  const breaker = (detail as { circuit_breaker?: unknown }).circuit_breaker
  if (typeof breaker !== 'object' || breaker === null) {
    return null
  }

  const pause = breaker as CircuitBreakerPause
  return pause.paused === true ? pause : null
}
