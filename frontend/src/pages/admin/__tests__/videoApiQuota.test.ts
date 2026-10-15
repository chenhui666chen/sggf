import { describe, expect, it } from 'vitest'
import { parseVideoApiQuota } from '../videoApiQuota'

describe('video API quota', () => {
  it('returns numeric values for valid quota', () => {
    expect(parseVideoApiQuota({ rate_limit_per_second: '20', burst_capacity: '100', max_active_jobs: '100', max_parallel_attempts: '2', lifetime_task_limit: '500' })).toEqual({
      rate_limit_per_second: 20, burst_capacity: 100, max_active_jobs: 100, max_parallel_attempts: 2, lifetime_task_limit: 500,
    })
  })
  it.each(['', '0', '-1', '1.5', 'NaN', '10001'])('rejects invalid rate %s', (value) => {
    expect(() => parseVideoApiQuota({ rate_limit_per_second: value, burst_capacity: '5', max_active_jobs: '5', max_parallel_attempts: '2', lifetime_task_limit: '100' })).toThrow()
  })
  it('rejects an excessive number of parallel attempts', () => {
    expect(() => parseVideoApiQuota({ rate_limit_per_second: '1', burst_capacity: '5', max_active_jobs: '5', max_parallel_attempts: '17', lifetime_task_limit: '100' })).toThrow()
  })
  it.each(['0', '-1', '1.5', '100000001'])('rejects invalid cumulative quota %s', (value) => {
    expect(() => parseVideoApiQuota({ rate_limit_per_second: '1', burst_capacity: '5', max_active_jobs: '5', max_parallel_attempts: '2', lifetime_task_limit: value })).toThrow()
  })
})
