import { describe, expect, it } from 'vitest'

import {
  getWorkflowPreviewEmptyMessage,
  getWorkflowPreviewLoadingLabel,
} from '../workflowPreviewMessages'

describe('workflowPreviewMessages', () => {
  it('在生成下一章的迭代阶段显示专用加载文案', () => {
    expect(getWorkflowPreviewLoadingLabel('iteration', true)).toBe('迭代优化中...')
    expect(getWorkflowPreviewEmptyMessage('iteration', '', true)).toBe(
      '正在内部改稿和复评，最终版本确认后会展示正文，请等待...'
    )
  })

  it('优先显示后端推送的进度消息', () => {
    expect(
      getWorkflowPreviewEmptyMessage('iteration', '步骤 4/4: 正在迭代中，请等待...', true),
    ).toBe('步骤 4/4: 正在迭代中，请等待...')
  })

  it('非迭代场景仍保留通用生成文案', () => {
    expect(getWorkflowPreviewLoadingLabel('content', true)).toBe('正在生成...')
    expect(getWorkflowPreviewEmptyMessage('content', '', true)).toBe('等待内容生成...')
  })
})
