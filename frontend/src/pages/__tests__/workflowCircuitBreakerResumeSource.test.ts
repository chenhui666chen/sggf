import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf-8',
)

// 熔断暂停过去只有后端半截实现：409 要求客户端携带 resume_after_confirmation，
// 但前端既不发送也没有任何展示入口，项目一旦熔断就在界面上永久卡死。
describe('circuit breaker resume wiring', () => {
  it('创作流程页把熔断 409 转成确认弹窗而不是普通报错', () => {
    const source = readSource('../WorkflowControlPage.tsx')

    expect(source).toContain('extractCircuitBreakerPause(response)')
    expect(source).toContain('setBreakerPause(')
    expect(source).toContain('Boolean(breakerPause)')
    // 确认按钮必须携带恢复标记，并沿用用户暂停前选择的档位
    expect(source).toContain('handleGenerateNextChapter(breakerPause.tier, true)')
    expect(source).toContain('workflow.breakerDialog.confirm')
  })

  it('api 层把确认标记映射为 snake_case 请求字段', () => {
    const source = readSource('../../services/api.ts')

    expect(source).toContain('resumeAfterConfirmation?: boolean')
    expect(source).toContain('resume_after_confirmation')
  })

  it('仪表盘页遇熔断时引导用户到创作流程页确认', () => {
    const source = readSource('../DashboardPage.tsx')

    expect(source).toContain('extractCircuitBreakerPause(response)')
    expect(source).toContain('dashboard.breakerPaused')
  })

  it('中英两套文案都齐备', () => {
    const zh = readSource('../../i18n/resources/zh-CN/common.json')
    const en = readSource('../../i18n/resources/en-US/common.json')

    for (const source of [zh, en]) {
      const json = JSON.parse(source)
      expect(json.workflow.breakerDialog.title).toBeTruthy()
      expect(json.workflow.breakerDialog.desc).toContain('{{chapter}}')
      expect(json.workflow.breakerDialog.reasonLabel).toBeTruthy()
      expect(json.workflow.breakerDialog.confirm).toBeTruthy()
      expect(json.workflow.breakerDialog.cancel).toBeTruthy()
      expect(json.dashboard.breakerPaused).toBeTruthy()
    }
  })
})
