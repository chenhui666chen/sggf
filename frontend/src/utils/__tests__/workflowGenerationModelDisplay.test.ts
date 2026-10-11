import { describe, expect, it } from 'vitest'

import {
  formatWorkflowGenerationModelOptionLabel,
  formatWorkflowGenerationModelTooltip,
} from '../workflowGenerationModelDisplay'

describe('workflowGenerationModelDisplay', () => {
  it('shows the model name with its relative cost label', () => {
    expect(
      formatWorkflowGenerationModelOptionLabel({
        id: 'minimax-m',
        name: 'MiniMax M3',
        cost_label: '5.4×',
      }),
    ).toBe('MiniMax M3 · 约 5.4×')
  })

  it('falls back to the model id and unknown cost when metadata is missing', () => {
    expect(
      formatWorkflowGenerationModelOptionLabel({
        id: 'mimo-flash',
        name: '',
        cost_label: null,
      }),
    ).toBe('mimo-flash · 成本未知')
  })

  it('builds a hover summary with feature, speed, and relative cost', () => {
    expect(
      formatWorkflowGenerationModelTooltip({
        id: 'glm',
        name: 'GLM 5.2',
        cost_label: '9.3×',
        relative_cost_basis_label: '按 7:1 输入/输出比估算',
      }),
    ).toBe('GLM 5.2\n特点：综合推理和结构控制较强，适合质量优先的重要章节。\n速度：很慢，首包可能超过 1 分钟。\n价格：约 9.3×（按 7:1 输入/输出比估算）。')
  })

  it('falls back to a generic hover summary for unknown model metadata', () => {
    expect(
      formatWorkflowGenerationModelTooltip({
        id: 'custom-model',
        name: '',
        cost_label: null,
      }),
    ).toBe('custom-model\n特点：可用于工作流章节创作，具体表现需以实际生成结果为准。\n速度：暂无实测速度。\n价格：成本未知。')
  })
})
