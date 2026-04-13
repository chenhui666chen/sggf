import { describe, expect, it } from 'vitest'
import {
  estimateRemainingTime,
  formatEstimatedTime,
  getStageDisplayName,
} from '../timeEstimate'

describe('estimateRemainingTime', () => {
  it('应返回null当stage为空时', () => {
    expect(estimateRemainingTime(null, 0)).toBeNull()
    expect(estimateRemainingTime('', 0)).toBeNull()
    expect(estimateRemainingTime(undefined, 0)).toBeNull()
  })

  it('应返回null当stage不存在于配置中时', () => {
    expect(estimateRemainingTime('unknown_stage', 0)).toBeNull()
  })

  it('应返回正确的预估时间', () => {
    const result = estimateRemainingTime('script', 0)
    expect(result).not.toBeNull()
    expect(typeof result?.estimatedMinutes).toBe('number')
  })

  it('应根据进度调整预估时间', () => {
    const result0 = estimateRemainingTime('script', 0)
    const result50 = estimateRemainingTime('script', 50)
    expect(result0?.estimatedMinutes).toBeGreaterThan(result50?.estimatedMinutes ?? 0)
  })
})

describe('formatEstimatedTime', () => {
  it('应正确处理小于1分钟的情况', () => {
    expect(formatEstimatedTime(0.5)).toBe('不到1分钟')
  })

  it('应正确格式化分钟数', () => {
    expect(formatEstimatedTime(5)).toBe('约5分钟')
    expect(formatEstimatedTime(60)).toBe('约1小时')
    expect(formatEstimatedTime(61)).toBe('约1小时1分钟')
  })
})

describe('getStageDisplayName', () => {
  it('应返回默认值当stage为空时', () => {
    expect(getStageDisplayName('')).toBe('未知阶段')
  })

  it('应返回正确的显示名称', () => {
    expect(getStageDisplayName('script')).toBe('剧本生成')
    expect(getStageDisplayName('storyboard')).toBe('分镜生成')
  })
})
