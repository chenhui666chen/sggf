import { describe, expect, it } from 'vitest'

import { formatScore } from '../promptEvolutionScore'


describe('formatScore', () => {
  it('formats numeric scores with one decimal', () => {
    expect(formatScore(99)).toBe('99.0')
    expect(formatScore(0)).toBe('0.0')
    expect(formatScore(47.75)).toBe('47.8')
  })

  it('renders placeholder for missing scores instead of crashing', () => {
    // 篇幅守门拦截的失败样本 original/rewritten 得分为 null，
    // 直接 .toFixed 会抛 TypeError 导致整页白屏（0.0 分版本详情复现）
    expect(formatScore(null)).toBe('-')
    expect(formatScore(undefined)).toBe('-')
  })
})
