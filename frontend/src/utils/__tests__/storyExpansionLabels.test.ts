import { describe, expect, it } from 'vitest'

import {
  getStoryExpansionExecutionModeLabel,
  getStoryExpansionResultLabels,
} from '../storyExpansionLabels'

describe('storyExpansionLabels', () => {
  it('执行模式标签优先使用共享映射', () => {
    expect(getStoryExpansionExecutionModeLabel('iterative')).toBe('分轮协同')
    expect(getStoryExpansionExecutionModeLabel('delta')).toBe('单轮增量')
    expect(getStoryExpansionExecutionModeLabel('volume_detail')).toBe('单卷细化')
  })

  it('未知执行模式会回退到原值或默认值', () => {
    expect(getStoryExpansionExecutionModeLabel('custom_mode')).toBe('custom_mode')
    expect(getStoryExpansionExecutionModeLabel(undefined)).toBe('自动协同')
    expect(getStoryExpansionExecutionModeLabel(undefined, '未提供')).toBe('未提供')
  })

  it('结果标签会解析正文处理模式和已写上下文', () => {
    expect(
      getStoryExpansionResultLabels({
        story_expansion_mode: 'epic_framework',
        story_strategy: 'balanced',
        story_intent: 'outline_led',
        story_preserve_written_mode: 'preserve_written',
        written_chapter_context: {
          applied: true,
          preserve_written_mode: 'extract_extend',
        },
      }),
    ).toEqual({
      expansionModeLabel: '长篇框架协同',
      strategyLabel: '均衡推进',
      intentLabel: '大纲主导',
      preserveWrittenModeLabel: '仅保护正文',
      writtenContextLabel: '提取后扩展',
    })
  })
})
