import { describe, expect, it } from 'vitest'

import {
  buildStoryExpansionCompletionMessage,
  getStoryExpansionSignalCounts,
  getStoryExpansionSignals,
  getStoryExpansionSummary,
} from '../storyExpansionFeedback'

describe('storyExpansionFeedback', () => {
  it('只有自动修复时返回协同修复摘要', () => {
    const result = {
      alignment_repairs: ['顾晚', '沈策'],
    }

    expect(getStoryExpansionSummary(result)).toEqual({
      label: '协同修复',
      text: '顾晚；沈策',
    })
  })

  it('统计自动修复和提醒数量', () => {
    const result = {
      alignment_repairs: ['顾晚', '顾晚', '沈策'],
      alignment_warnings: ['仍需补入陈昭承接'],
      expansion_analysis: {
        warnings: ['仍需补入陈昭承接', '建议复查卷末钩子'],
      },
    }

    expect(getStoryExpansionSignalCounts(result)).toEqual({
      repairCount: 2,
      advisoryCount: 2,
    })
  })

  it('归一化结果页需要的修复与提醒列表', () => {
    const result = {
      alignment_repairs: ['顾晚', '顾晚'],
      alignment_warnings: ['仍需补入陈昭承接'],
      expansion_analysis: {
        warnings: ['仍需补入陈昭承接', '建议复查卷末钩子'],
      },
    }

    expect(getStoryExpansionSignals(result)).toEqual({
      repairedMessages: ['顾晚'],
      advisoryMessages: ['仍需补入陈昭承接', '建议复查卷末钩子'],
    })
  })

  it('优先展示当前 schema 的协同摘要', () => {
    const result = {
      coordination_summary: '本次协同已完成章节细化，并同步补齐关键人物承接。',
      expansion_analysis: {
        analysis_summary: '这条摘要不应覆盖 coordination_summary。',
      },
    }

    expect(getStoryExpansionSummary(result)).toEqual({
      label: '协同摘要',
      text: '本次协同已完成章节细化，并同步补齐关键人物承接。',
    })
  })

  it('完成消息包含自动修复、提醒和摘要', () => {
    const result = {
      coordination_summary: '本次协同已完成章节细化，并同步补齐关键人物承接。',
      alignment_repairs: ['顾晚'],
      alignment_warnings: ['仍需补入陈昭承接'],
    }

    const message = buildStoryExpansionCompletionMessage('协同扩展完成', result)

    expect(message).toContain('协同扩展完成')
    expect(message).toContain('已自动修复 1 处人物承接')
    expect(message).toContain('仍有 1 条协同提醒')
    expect(message).toContain('协同摘要：')
  })

  it('没有协同摘要时会回退到阶段人物计划', () => {
    const result = {
      expansion_analysis: {
        auto_supplement: {
          character_plan: {
            recommended_range_text: '113-180',
            stage_label: '框架阶段',
            stage_target_characters: 34,
            task_target_characters: 58,
            task_target_increment: 48,
            remaining_to_recommended_min: 79,
            follow_up_phase: '后续卷级细化或后续协同',
          },
        },
      },
    }

    expect(getStoryExpansionSummary(result)).toEqual({
      label: '人物计划',
      text: '全书建议规模约为 113-180 人，框架阶段先补到 34 人；点击一次开始后，系统会自动连续执行多轮，首轮人物数不是整次任务上限；本次自动协同预计补到 58 人（约新增 48 人）；剩余约 79 人会在后续卷级细化或后续协同继续补齐',
    })

    const message = buildStoryExpansionCompletionMessage('协同扩展完成', result)
    expect(message).toContain('协同扩展完成')
    expect(message).toContain('人物计划：')
    expect(message.match(/人物计划：/g)?.length).toBe(1)
  })
})
