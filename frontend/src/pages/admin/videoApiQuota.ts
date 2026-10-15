export type VideoApiQuota = {
  rate_limit_per_second: number
  burst_capacity: number
  max_active_jobs: number
  max_parallel_attempts: number
  lifetime_task_limit: number
}

export function parseVideoApiQuota(values: Record<keyof VideoApiQuota, string>): VideoApiQuota {
  const limits: VideoApiQuota = {
    rate_limit_per_second: 10000,
    burst_capacity: 100000,
    max_active_jobs: 100000,
    max_parallel_attempts: 16,
    lifetime_task_limit: 100000000,
  }
  const result = {} as VideoApiQuota
  for (const field of Object.keys(limits) as Array<keyof VideoApiQuota>) {
    const value = Number(values[field])
    if (!values[field].trim() || !Number.isInteger(value) || value < 1 || value > limits[field]) {
      throw new Error('配额必须为有效的正整数；请求速率最多 10000，突发与活动任务最多 100000，并行尝试最多 16，累计任务最多 100000000。')
    }
    result[field] = value
  }
  return result
}
