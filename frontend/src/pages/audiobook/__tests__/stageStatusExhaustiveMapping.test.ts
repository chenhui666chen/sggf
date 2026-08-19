/**
 * StageStatus 穷举映射完备性测试（GUIDE R15/P1-3，验收 81）。
 *
 * 新增 StageStatus 联合类型键后，全部 Record<StageStatus, ...> 映射必须同步
 * 补齐，否则 tsc 编译立即报错；本测试断言映射完备且新状态渲染不崩。
 */
import { describe, expect, it } from 'vitest'

import { STAGE_STATUS_LABELS } from '../constants'
import { coerceStageStatus } from '../utils'
import { audiobookColorRoles } from '../audiobookTheme'
import { STAGE_STATUS_COLORS } from '../TaskStageDetails'
import type { StageStatus } from '../types'

describe('StageStatus 穷举映射完备（R15/P1-3）', () => {
  const allStatuses: StageStatus[] = [
    'pending',
    'running',
    'completed',
    'failed',
    'paused',
    'pause_requested',
    'cancelled',
    'completed_with_partial_failure',
  ]

  it('STAGE_STATUS_LABELS 覆盖全部状态键', () => {
    for (const status of allStatuses) {
      expect(STAGE_STATUS_LABELS[status], `缺少 label: ${status}`).toBeTruthy()
    }
    expect(STAGE_STATUS_LABELS.cancelled).toBe('已取消')
    expect(STAGE_STATUS_LABELS.completed_with_partial_failure).toBe('部分完成')
  })

  it('audiobookTheme.taskStatus 覆盖全部状态键', () => {
    for (const status of allStatuses) {
      const role = audiobookColorRoles.taskStatus[status]
      expect(role, `缺少颜色角色: ${status}`).toBeTruthy()
      expect(role.bg).toBeTruthy()
      expect(role.border).toBeTruthy()
      expect(role.text).toBeTruthy()
    }
  })

  it('TaskStageDetails STAGE_STATUS_COLORS 覆盖全部状态键且不崩', () => {
    for (const status of allStatuses) {
      const colors = STAGE_STATUS_COLORS[status]
      expect(colors, `缺少颜色: ${status}`).toBeTruthy()
      // 渲染不崩：颜色对象可直接消费
      expect(`${colors.bg}|${colors.border}|${colors.text}`).not.toContain('undefined')
    }
  })

  it('coerceStageStatus 识别新状态并保留原值', () => {
    expect(coerceStageStatus('cancelled')).toBe('cancelled')
    expect(coerceStageStatus('completed_with_partial_failure')).toBe('completed_with_partial_failure')
    expect(coerceStageStatus('completed')).toBe('completed')
  })

  it('coerceStageStatus 未知值回退 pending（fail-closed 前向兼容）', () => {
    expect(coerceStageStatus('something_new_unknown')).toBe('pending')
    expect(coerceStageStatus(null)).toBe('pending')
    expect(coerceStageStatus(undefined)).toBe('pending')
  })
})
