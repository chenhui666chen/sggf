import { describe, expect, it } from 'vitest'

import { parseWorkflowStageContent } from '../workflowStageContent'

describe('workflowStageContent', () => {
  it('空值返回空字符串', () => {
    expect(parseWorkflowStageContent(null)).toBe('')
    expect(parseWorkflowStageContent(undefined)).toBe('')
    expect(parseWorkflowStageContent('')).toBe('')
  })

  it('普通字符串保持原样', () => {
    expect(parseWorkflowStageContent('第1章：开端')).toBe('第1章：开端')
  })

  it('JSON 字符串数组会被格式化为多段文本', () => {
    expect(parseWorkflowStageContent('["甲","乙"]')).toBe('甲\n\n乙')
  })

  it('JSON 字符串对象会被还原为字符串值', () => {
    expect(parseWorkflowStageContent('"世界观设定"')).toBe('世界观设定')
  })

  it('结构化数组会被逐项拼接', () => {
    expect(parseWorkflowStageContent(['甲', { name: '乙' }])).toBe('甲\n\n{\n  "name": "乙"\n}')
  })

  it('对象会被格式化为 JSON 文本', () => {
    expect(parseWorkflowStageContent({ title: '开场' })).toBe('{\n  "title": "开场"\n}')
  })
})
