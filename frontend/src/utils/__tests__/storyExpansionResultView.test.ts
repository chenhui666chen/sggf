import { describe, expect, it } from 'vitest'

import { createStoryExpansionResultView } from '../storyExpansionResultModel'
import {
  createStoryExpansionResultDisplayView,
  formatCountDelta,
  getExecutionRoundTitle,
  getOutlineOperationLabel,
} from '../storyExpansionResultView'

describe('storyExpansionResultView', () => {
  it('统一结果页展示文案与快速跳转', () => {
    const view = createStoryExpansionResultView({
      expanded_outline: '更新后大纲',
      all_characters: '更新后人物',
      outline_delta: '章节增量',
      character_delta: '人物增量',
      character_relationships: '关系补丁',
      execution_mode_reason: '按人物与情节交替推进',
      execution_rounds: [
        {
          round: 2,
          stage: 'volume_detail',
          strategy: 'balanced',
          before_chapter_count: 10,
          after_chapter_count: 12,
          before_character_count: 4,
          after_character_count: 5,
          plot: { increment_requested: 2 },
          character: {
            increment_requested: 1,
            post_validation_score: 91,
          },
        },
      ],
      outline_ops: [
        {
          action: 'insert_after',
          after_chapter: 12,
          requested_count: 2,
          generated_count: 1,
          goal: '补足主线冲突',
          generated_titles: ['第13章', '  '],
        },
      ],
      new_characters: ['沈策'],
      alignment_repairs: ['修复主角关系'],
      alignment_warnings: ['仍需检查配角承接'],
      stop_reasons: ['达到本轮扩展目标'],
      validation_before: { chapter_count: 10, character_count: 4, score: 80 },
      validation_after: { score: 91 },
      current_chapter_count: 12,
      target_chapter_count: 14,
      current_character_count: 5,
      target_character_count: 6,
    })

    const display = createStoryExpansionResultDisplayView({
      view,
      summaryLabel: '协同摘要',
      writtenContextLabel: '提取后续写',
      repairedMessages: ['修复主角关系'],
      advisoryMessages: ['仍需检查配角承接'],
    })

    expect(display).toMatchObject({
      completionStatusLabel: '阶段性完成',
      completionStatusTone: 'warning',
      completionStatusDescription: '本次协同已完成当前可确认增量，仍差 2 章 / 1 人。',
      remainingGoalChipLabel: '仍差 2 章 / 1 人',
      canAutoImprove: false,
      autoImproveActionLabel: null,
      autoImproveHint: null,
      executionModeReasonText: '按人物与情节交替推进',
      chapterMetricValue: '10 → 12 / 目标 14',
      characterMetricValue: '4 → 5 / 目标 6',
      scoreMetricValue: '80 → 91',
      scoreMetricHelperText: '本轮评分保持或提升。',
      roundsMetricValue: '1 轮',
      roundsMetricHelperText: '正文处理策略：提取后续写',
      addedChapterCount: 2,
      addedCharacterCount: 1,
      addedChapterChipLabel: '本轮新增 2个细化章节',
      addedCharacterChipLabel: '本轮新增人物 1 人',
      executionRoundsChipLabel: '共执行 1 轮',
      alignmentRepairsChipLabel: '已自动修复 1 处人物承接',
      alignmentWarningsChipLabel: '存在 1 条协同提醒',
      hasChangesSection: true,
      hasDeltaSection: true,
      quickJumpItems: [
        { key: 'summary', label: '协同摘要' },
        { key: 'changes', label: '本轮变更' },
        { key: 'rounds', label: '协同轮次' },
        { key: 'delta', label: '增量内容' },
        { key: 'outline', label: '更新后大纲' },
        { key: 'characters', label: '更新后人物' },
      ],
    })

    expect(display.changeCardViews).toEqual([
      {
        key: 'repairs',
        title: '自动修复',
        kind: 'messages',
        tone: 'success',
        messages: ['修复主角关系'],
        chips: [],
        outlineOperations: [],
      },
      {
        key: 'advisories',
        title: '协同提醒',
        kind: 'messages',
        tone: 'warning',
        messages: ['仍需检查配角承接'],
        chips: [],
        outlineOperations: [],
      },
      {
        key: 'new-characters',
        title: '本轮新增角色',
        kind: 'chips',
        tone: 'default',
        messages: [],
        chips: ['沈策'],
        outlineOperations: [],
      },
      {
        key: 'stop-reasons',
        title: '停止原因',
        kind: 'messages',
        tone: 'default',
        messages: ['达到本轮扩展目标'],
        chips: [],
        outlineOperations: [],
      },
      {
        key: 'outline-operations',
        title: '本轮细化章节操作',
        kind: 'outline_operations',
        tone: 'default',
        messages: [],
        chips: [],
        outlineOperations: [
          {
            key: 'insert_after-0',
            title: '插入到第 12 章后',
            requestedLabel: '计划 2个细化章节',
            generatedLabel: '实际 1个细化章节',
            goal: '补足主线冲突',
            generatedTitles: ['第13章'],
          },
        ],
      },
    ])

    expect(display.deltaSectionViews).toEqual([
      {
        key: 'outline-delta',
        title: '细化章节增量',
        content: '章节增量',
        contentKind: 'delta',
        copyMessage: '已复制细化章节增量',
      },
      {
        key: 'character-delta',
        title: '人物增量',
        content: '人物增量',
        contentKind: 'character',
        copyMessage: '已复制人物增量',
      },
      {
        key: 'relationship-delta',
        title: '关系补丁',
        content: '关系补丁',
        contentKind: 'relationship',
        copyMessage: '已复制关系补丁',
      },
    ])

    expect(display.finalSectionViews).toEqual([
      {
        key: 'outline',
        title: '更新后大纲',
        content: '更新后大纲',
        contentKind: 'outline',
        copyMessage: '已复制更新后大纲',
        lg: 7,
      },
      {
        key: 'characters',
        title: '更新后人物',
        content: '更新后人物',
        contentKind: 'character',
        copyMessage: '已复制更新后人物',
        lg: 5,
      },
    ])

    expect(display.outlineOperationViews).toEqual([
      {
        key: 'insert_after-0',
        title: '插入到第 12 章后',
        requestedLabel: '计划 2个细化章节',
        generatedLabel: '实际 1个细化章节',
        goal: '补足主线冲突',
        generatedTitles: ['第13章'],
      },
    ])

    expect(display.executionRoundViews).toEqual([
      {
        key: '2-0',
        title: '第 2 轮协同',
        strategyLabel: '策略：balanced',
        chapterRangeText: '细化章节：10 → 12',
        characterRangeText: '人物：4 → 5',
        plotIncrementText: '本轮新增目标：2个细化章节',
        characterIncrementText: '本轮新增人物目标：1',
        postValidationScoreText: '人物匹配评分：91',
      },
    ])
  })

  it('评分下降时展示明确原因与可执行修复建议', () => {
    const view = createStoryExpansionResultView({
      expanded_outline: '修复前后大纲',
      all_characters: '顾晚\n沈砚\n陈昭',
      validation_before: {
        chapter_count: 12,
        character_count: 3,
        score: 88,
        coverage_ratio: 1,
        referenced_characters: ['顾晚', '沈砚', '陈昭'],
      },
      validation_after: {
        chapter_count: 15,
        character_count: 3,
        score: 71,
        coverage_ratio: 0.667,
        referenced_characters: ['顾晚', '沈砚'],
        unreferenced_characters: ['陈昭'],
        suggestions: [
          '存在未被大纲引用的人物，优先为这些角色补充登场章节或职责。',
          '人物与章节覆盖率偏低，新增章节时需要明确写出涉及人物与关系推进。',
        ],
      },
      current_chapter_count: 15,
      current_character_count: 3,
    })

    const display = createStoryExpansionResultDisplayView({
      view,
      repairedMessages: [],
      advisoryMessages: [],
    })

    expect(display.scoreMetricValue).toBe('88 → 71')
    expect(display.scoreMetricHelperText).toBe('下降 17 分。仍有未被章节正式承接的人物：陈昭。')
    expect(display.canAutoImprove).toBe(true)
    expect(display.autoImproveActionLabel).toBe('一键自动改进')
    expect(display.autoImproveHint).toBe('系统会根据当前协同结果自动补齐人物承接与章节挂接，不会开启下一轮协同。')
    expect(display.hasChangesSection).toBe(true)
    expect(display.changeCardViews).toEqual([
      {
        key: 'score-regression-reasons',
        title: '评分下降原因',
        kind: 'messages',
        tone: 'warning',
        messages: [
          '仍有未被章节正式承接的人物：陈昭。',
          '人物覆盖率从 100% 降到 67%，新增内容对人物挂接不足。',
          '章节数增加了，但被正式挂接的人物没有同步增加，说明本轮偏向扩剧情、弱化了人物承接。',
        ],
        chips: [],
        outlineOperations: [],
      },
      {
        key: 'score-improvements',
        title: '建议优先修复',
        kind: 'messages',
        tone: 'default',
        messages: [
          '优先把 陈昭 补进对应章节的“涉及人物”字段，并明确这些角色在该章承担的剧情职责。',
          '存在未被大纲引用的人物，优先为这些角色补充登场章节或职责。',
          '人物与章节覆盖率偏低，新增章节时需要明确写出涉及人物与关系推进。',
          '先修复当前章节的人物承接，再决定是否继续追加新章节或新角色。',
        ],
        chips: [],
        outlineOperations: [],
      },
    ])
  })

  it('在缺省结果下提供稳定的默认展示', () => {
    const view = createStoryExpansionResultView({
      current_chapter_count: 3,
      current_character_count: 2,
    })

    const display = createStoryExpansionResultDisplayView({
      view,
      repairedMessages: [],
      advisoryMessages: [],
    })

    expect(display).toMatchObject({
      completionStatusLabel: '已达目标',
      completionStatusTone: 'success',
      completionStatusDescription: '本次协同已达到当前设定的章节与人物目标。',
      remainingGoalChipLabel: null,
      canAutoImprove: false,
      autoImproveActionLabel: null,
      autoImproveHint: null,
      executionModeReasonText: '本次结果已按可扫描的摘要、增量和最终内容分区展示。',
      chapterMetricValue: '0 → 3 / 目标 3',
      characterMetricValue: '0 → 2 / 目标 2',
      scoreMetricValue: '0 → 0',
      roundsMetricValue: '1 轮',
      roundsMetricHelperText: '未额外覆盖正文处理策略。',
      hasChangesSection: false,
      hasDeltaSection: false,
      quickJumpItems: [],
      outlineOperationViews: [],
      executionRoundViews: [],
      changeCardViews: [],
      deltaSectionViews: [],
      finalSectionViews: [
        {
          key: 'outline',
          title: '更新后大纲',
          content: '',
          contentKind: 'outline',
          copyMessage: '已复制更新后大纲',
          lg: 7,
        },
        {
          key: 'characters',
          title: '更新后人物',
          content: '',
          contentKind: 'character',
          copyMessage: '已复制更新后人物',
          lg: 5,
        },
      ],
    })
  })

  it('定向修复结果显示为修复完成而不是下一轮协同', () => {
    const view = createStoryExpansionResultView({
      execution_mode: 'repair',
      current_chapter_count: 60,
      target_chapter_count: 60,
      current_character_count: 20,
      target_character_count: 20,
    })

    const display = createStoryExpansionResultDisplayView({
      view,
      repairedMessages: ['修复人物承接'],
      advisoryMessages: [],
    })

    expect(display.completionStatusLabel).toBe('修复完成')
    expect(display.completionStatusTone).toBe('success')
    expect(display.completionStatusDescription).toBe('当前结果来自定向修复，不会自动开启下一轮协同扩展。')
    expect(display.remainingGoalChipLabel).toBeNull()
    expect(display.canAutoImprove).toBe(false)
    expect(display.autoImproveActionLabel).toBeNull()
    expect(display.autoImproveHint).toBeNull()
  })

  it('顶部提醒统计与协同提醒卡片使用统一口径', () => {
    const view = createStoryExpansionResultView({
      current_chapter_count: 8,
      current_character_count: 3,
    })

    const display = createStoryExpansionResultDisplayView({
      view,
      repairedMessages: [],
      advisoryMessages: ['补查卷间承接', '检查配角动机'],
    })

    expect(display.alignmentWarningsChipLabel).toBe('存在 2 条协同提醒')
    expect(display.hasChangesSection).toBe(true)
    expect(display.changeCardViews).toEqual([
      {
        key: 'advisories',
        title: '协同提醒',
        kind: 'messages',
        tone: 'warning',
        messages: ['补查卷间承接', '检查配角动机'],
        chips: [],
        outlineOperations: [],
      },
    ])
  })

  it('长篇框架阶段人物计划会展示为独立结果卡片', () => {
    const view = createStoryExpansionResultView({
      current_chapter_count: 120,
      target_chapter_count: 900,
      current_character_count: 34,
      target_character_count: 34,
      expansion_analysis: {
        auto_supplement: {
          character_plan: {
            recommended_range_text: '113-180',
            stage_label: '框架阶段',
            suggested_increment: 24,
            stage_target_characters: 34,
            task_target_characters: 58,
            task_target_increment: 48,
            remaining_to_recommended_min: 79,
            follow_up_phase: '后续卷级细化或后续协同',
          },
        },
      },
    })

    const display = createStoryExpansionResultDisplayView({
      view,
      repairedMessages: [],
      advisoryMessages: [],
    })

    expect(display.hasChangesSection).toBe(true)
    expect(display.changeCardViews).toEqual([
      {
        key: 'character-phase-plan',
        title: '阶段人物计划',
        kind: 'messages',
        tone: 'default',
        messages: [
          '全书建议规模约为 113-180 人，框架阶段先补到 34 人（本次新增 24 人）。',
          '点击一次开始后，系统会自动连续执行多轮；首轮人物数只是起点，不是整次任务上限。',
          '本次自动协同预计补到 58 人（约新增 48 人）。',
          '距离建议下限还差约 79 人，会在后续卷级细化或后续协同继续补齐。',
        ],
        chips: [],
        outlineOperations: [],
      },
    ])
  })

  it('暴露稳定的标题与计数格式化规则', () => {
    expect(getOutlineOperationLabel({ action: 'append' })).toBe('追加到大纲末尾')
    expect(getOutlineOperationLabel({ action: 'insert_after', after_chapter: 8 })).toBe('插入到第 8 章后')

    expect(getExecutionRoundTitle({ round: 3 }, 0)).toBe('第 3 轮协同')
    expect(getExecutionRoundTitle({ stage: 'volume_detail' }, 1)).toBe('单卷细化 2')
    expect(getExecutionRoundTitle({}, 2)).toBe('执行轮次 3')

    expect(formatCountDelta(4, 7, 10)).toBe('4 → 7 / 目标 10')
    expect(formatCountDelta(4, 7, 0)).toBe('4 → 7')
  })
})
