import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf-8',
)

describe('Workflow multi-model review settings source guards', () => {
  it('keeps the only review-settings entry on the quality review step label', () => {
    const workflowSource = readSource('../WorkflowControlPage.tsx')
    const dashboardSource = readSource('../DashboardPage.tsx')
    const openSettingsEntrances = workflowSource.match(/setShowReviewSettingsDialog\(true\)/g) || []

    expect(openSettingsEntrances).toHaveLength(1)

    const stepperStart = workflowSource.indexOf('<Stepper')
    const stepperEnd = workflowSource.indexOf('</Stepper>', stepperStart)
    const opener = workflowSource.indexOf('setShowReviewSettingsDialog(true)')

    expect(stepperStart).toBeGreaterThan(-1)
    expect(stepperEnd).toBeGreaterThan(stepperStart)
    expect(opener).toBeGreaterThan(stepperStart)
    expect(opener).toBeLessThan(stepperEnd)

    const openerContext = workflowSource.slice(Math.max(0, opener - 700), opener + 700)
    expect(openerContext).toContain("stage === 'review'")
    expect(openerContext).toContain('event.stopPropagation()')

    expect(dashboardSource).not.toContain('MultiModelReviewSettingsDialog')
    expect(dashboardSource).not.toContain('reviewSettingsProjectId')
    expect(dashboardSource).not.toContain('handleOpenReviewSettings')
  })

  it('keeps review settings focused on automatic chapter-position strategy', () => {
    const dialogSource = readSource('../../components/project/MultiModelReviewSettingsDialog.tsx')

    expect(dialogSource).toContain('自动多模型评审策略')
    expect(dialogSource).toContain('普通章节')
    expect(dialogSource).toContain('开篇章节')
    expect(dialogSource).toContain('重点章节')
    expect(dialogSource).toContain('完结章节')

    expect(dialogSource).not.toContain('默认评审深度')
    expect(dialogSource).not.toContain('手动触发深度')
    expect(dialogSource).not.toContain('自动触发场景')
    expect(dialogSource).not.toContain('auto_scenarios.includes')
  })

  it('warns users that multi-model review increases latency and cost', () => {
    const dialogSource = readSource('../../components/project/MultiModelReviewSettingsDialog.tsx')

    expect(dialogSource).toContain('会增加评审耗时与模型调用成本')
    expect(dialogSource).toContain('severity="warning"')
  })
})
