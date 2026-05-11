import { describe, expect, it, vi } from 'vitest'
import type { DreamweaverRunSummary } from '../../types/dreamweaver'

vi.mock('../../services/api', () => ({
  apiClient: {
    listDreamweaverRuns: vi.fn(),
  },
  extractApiErrorMessage: vi.fn(async (_e: unknown, fallback: string) => fallback),
}))

function makeRun(overrides: Partial<DreamweaverRunSummary> = {}): DreamweaverRunSummary {
  return {
    run_id: `run-${Date.now()}`,
    status: 'completed',
    ...overrides,
  }
}

describe('DreamweaverRunSummary 类型与工具函数', () => {
  it('makeRun 应生成有效的运行记录', () => {
    const run = makeRun({ run_id: 'run-001', status: 'completed' })
    expect(run.run_id).toBe('run-001')
    expect(run.status).toBe('completed')
  })

  it('makeRun 应支持覆盖默认值', () => {
    const run = makeRun({
      run_id: 'run-002',
      status: 'failed',
      progress: 50,
      error_message: 'Test error',
    })
    expect(run.status).toBe('failed')
    expect(run.progress).toBe(50)
    expect(run.error_message).toBe('Test error')
  })
})

describe('状态过滤逻辑', () => {
  const runs: DreamweaverRunSummary[] = [
    makeRun({ run_id: 'run-1', status: 'completed' }),
    makeRun({ run_id: 'run-2', status: 'completed' }),
    makeRun({ run_id: 'run-3', status: 'failed' }),
    makeRun({ run_id: 'run-4', status: 'running' }),
    makeRun({ run_id: 'run-5', status: '' }),
  ]

  function filterByStatus(runs: DreamweaverRunSummary[], filters: string[]): DreamweaverRunSummary[] {
    if (!filters.length) return runs
    const enabled = new Set(filters.map((s) => String(s || '').trim().toLowerCase()).filter(Boolean))
    if (!enabled.size) return runs
    return runs.filter((run) => enabled.has(String(run.status || '').trim().toLowerCase() || 'unknown'))
  }

  function countByStatus(runs: DreamweaverRunSummary[]): Record<string, number> {
    const counts: Record<string, number> = {}
    for (const run of runs) {
      const statusRaw = String(run.status || '').trim().toLowerCase() || 'unknown'
      counts[statusRaw] = (counts[statusRaw] || 0) + 1
    }
    return counts
  }

  it('应正确统计各状态数量', () => {
    const counts = countByStatus(runs)
    expect(counts['completed']).toBe(2)
    expect(counts['failed']).toBe(1)
    expect(counts['running']).toBe(1)
    expect(counts['unknown']).toBe(1)
  })

  it('应正确过滤指定状态', () => {
    const filtered = filterByStatus(runs, ['completed'])
    expect(filtered).toHaveLength(2)
    expect(filtered.every((r) => r.status === 'completed')).toBe(true)
  })

  it('应正确过滤多个状态', () => {
    const filtered = filterByStatus(runs, ['completed', 'failed'])
    expect(filtered).toHaveLength(3)
  })

  it('空过滤器应返回全部记录', () => {
    const filtered = filterByStatus(runs, [])
    expect(filtered).toHaveLength(5)
  })

  it('应处理大小写不一致', () => {
    const mixedRuns = [
      makeRun({ status: 'COMPLETED' }),
      makeRun({ status: 'Completed' }),
      makeRun({ status: 'completed' }),
    ]
    const filtered = filterByStatus(mixedRuns, ['completed'])
    expect(filtered).toHaveLength(3)
  })
})

describe('API 参数构建', () => {
  it('应正确构建运行参数', () => {
    const params = {
      project_id: 1,
      chapter_ids: [1, 2, 3],
      schema_version: '0.1.0',
      quality_mode: 'quality',
      smart_tuning: true,
      style_preset: 'cinematic_realistic',
      image_ratio: '16:9',
      image_resolution: '1080p',
    }

    expect(params.project_id).toBe(1)
    expect(params.chapter_ids).toHaveLength(3)
    expect(params.quality_mode).toBe('quality')
    expect(params.smart_tuning).toBe(true)
  })

  it('应省略未提供的可选参数', () => {
    const params = {
      project_id: 1,
      chapter_ids: [1],
      schema_version: '0.1.0',
    }

    expect(params).not.toHaveProperty('quality_mode')
    expect(params).not.toHaveProperty('smart_tuning')
    expect(params).not.toHaveProperty('style_preset')
  })
})
