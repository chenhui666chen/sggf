import { describe, expect, it } from 'vitest'

import {
  describeTaskPointsPrecheckErrorDetail,
  extractTaskPointsPrecheckErrorDetail,
  extractTaskPointsPrecheckErrorMessage,
  type TaskPointsPrecheckErrorDetail,
} from '../api'

function buildAxiosLikeError(detail: Record<string, unknown>) {
  return {
    isAxiosError: true,
    message: 'Request failed with status code 400',
    response: {
      data: {
        detail,
      },
    },
  }
}

describe('task points precheck helpers', () => {
  it('为短剧积分不足生成带镜头和差额提示的友好文案', () => {
    const detail: TaskPointsPrecheckErrorDetail = {
      message: '短剧积分不足',
      module_key: 'dreamweaver',
      module_label: '短剧',
      failure_code: 'insufficient_available_points',
      effective_available_points: 8,
      additional_frozen_points: 20,
      estimated_shot_count: 12,
    }

    expect(describeTaskPointsPrecheckErrorDetail(detail)).toBe(
      '短剧积分不足 当前按约 12 个镜头估算，还差 12.00 积分，可减少章节范围、切换成本模式，或先补充积分后再试。',
    )
  })

  it('为有声书负毛利阻断生成定价策略提示', () => {
    const detail: TaskPointsPrecheckErrorDetail = {
      message: '有声书当前任务不满足定价策略',
      module_key: 'audiobook',
      module_label: '有声书',
      failure_code: 'negative_margin_blocked',
    }

    expect(describeTaskPointsPrecheckErrorDetail(detail)).toBe(
      '有声书当前任务不满足定价策略 可尝试减少生成章节、先仅生成剧本，或联系管理员调整积分定价策略。',
    )
  })

  it('能从 axios 风格错误对象中提取结构化积分预检详情并裁剪模型报错', async () => {
    const longModelError = 'x'.repeat(300)
    const error = buildAxiosLikeError({
      message: '有声书积分不足',
      model_error: longModelError,
      module_key: 'audiobook',
      module_label: '有声书',
      failure_code: 'insufficient_available_points',
      effective_available_points: '18.5',
      additional_frozen_points: '25',
      existing_frozen_points: '4',
      operating_snapshot: {
        margin_status: 'negative',
        negative_margin_blocked: true,
        platform_gross_profit_yuan: '-3.2',
      },
    })

    const detail = await extractTaskPointsPrecheckErrorDetail(error)

    expect(detail).toMatchObject({
      module_key: 'audiobook',
      module_label: '有声书',
      failure_code: 'insufficient_available_points',
      effective_available_points: 18.5,
      additional_frozen_points: 25,
      existing_frozen_points: 4,
      operating_snapshot: {
        margin_status: 'negative',
        negative_margin_blocked: true,
        platform_gross_profit_yuan: -3.2,
      },
    })
    expect(detail?.message).toContain('有声书积分不足（详情：')
    expect(detail?.message).toContain('...')
    expect(detail?.message?.length).toBeLessThan(280)
  })

  it('能把结构化预检错误转成最终对用户展示的文案', async () => {
    const error = buildAxiosLikeError({
      message: '有声书积分不足',
      module_key: 'audiobook',
      module_label: '有声书',
      failure_code: 'insufficient_available_points',
      effective_available_points: 15,
      additional_frozen_points: 22,
      existing_frozen_points: 6,
    })

    await expect(extractTaskPointsPrecheckErrorMessage(error, '请求失败')).resolves.toBe(
      '有声书积分不足 还差 7.00 积分，可减少本次生成章节，或先补充积分后再试。 当前已有 6.00 积分处于正式冻结状态。'
    )
  })
})
