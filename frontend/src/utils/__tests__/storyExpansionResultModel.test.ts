import { describe, expect, it } from 'vitest'

import {
  coerceStoryExpansionResult,
  createStoryExpansionResultView,
} from '../storyExpansionResultModel'

describe('storyExpansionResultModel', () => {
  it('将当前 schema 规范化为稳定的前端结果结构', () => {
    expect(
      coerceStoryExpansionResult({
        expanded_outline: '新大纲',
        all_characters: '新人物',
        outline_delta: '章节增量',
        character_delta: '人物增量',
        new_characters: ['顾晚', '顾晚', '沈策'],
        coordination_summary: '本轮协同完成',
        story_strategy: 'balanced',
        story_intent: 'character_led',
        story_expansion_mode: 'volume_detail',
        story_preserve_written_mode: 'extract_extend',
        target_chapter_count: 24,
        target_character_count: 8,
      }),
    ).toEqual({
      expanded_outline: '新大纲',
      all_characters: '新人物',
      outline_delta: '章节增量',
      character_delta: '人物增量',
      character_relationships: '',
      outline_ops: [],
      execution_mode: undefined,
      execution_mode_reason: undefined,
      execution_rounds: [],
      new_characters: ['顾晚', '沈策'],
      alignment_repairs: [],
      story_strategy: 'balanced',
      story_intent: 'character_led',
      story_expansion_mode: 'volume_detail',
      story_preserve_written_mode: 'extract_extend',
      written_chapter_context: undefined,
      volume_index: null,
      volume_chapter_range: null,
      coordination_summary: '本轮协同完成',
      current_chapter_count: undefined,
      target_chapter_count: 24,
      current_character_count: undefined,
      target_character_count: 8,
      validation_before: undefined,
      validation_after: undefined,
      alignment_warnings: [],
      character_sync: undefined,
      stop_reasons: [],
      expansion_analysis: undefined,
      epic_total_volumes: null,
      epic_chapter_range: null,
      message: undefined,
    })
  })

  it('为结果页生成稳定的展示视图', () => {
    const view = createStoryExpansionResultView({
      expanded_outline: '总纲',
      all_characters: '角色',
      outline_delta: '新增第3章',
      character_delta: '新增顾晚',
      character_relationships: '林舟 -> 顾晚',
      execution_rounds: [{ round: 1, before_chapter_count: 2, after_chapter_count: 3 }],
      outline_ops: [{ action: 'append', requested_count: 1, generated_count: 1 }],
      new_characters: ['顾晚'],
      alignment_repairs: ['修复人物承接'],
      alignment_warnings: ['仍需补入陈昭'],
      stop_reasons: ['达到目标后停止'],
      validation_before: { chapter_count: 2, character_count: 4, score: 82 },
      validation_after: { score: 89 },
      current_chapter_count: 3,
      target_chapter_count: 3,
      current_character_count: 5,
      target_character_count: 6,
    })

    expect(view).toMatchObject({
      chapterBefore: 2,
      chapterAfter: 3,
      chapterTarget: 3,
      characterBefore: 4,
      characterAfter: 5,
      characterTarget: 6,
      scoreBefore: 82,
      scoreAfter: 89,
      addedChapterCount: 1,
      addedCharacterCount: 1,
      outlineDelta: '新增第3章',
      characterDelta: '新增顾晚',
      characterRelationships: '林舟 -> 顾晚',
      expandedOutline: '总纲',
      allCharacters: '角色',
    })
    expect(view?.executionRounds).toHaveLength(1)
    expect(view?.outlineOps).toHaveLength(1)
    expect(view?.newCharacters).toEqual(['顾晚'])
  })

  it('保留阶段人物计划等扩展分析字段', () => {
    expect(
      coerceStoryExpansionResult({
        current_character_count: 34,
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
      }),
    ).toMatchObject({
      current_character_count: 34,
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
    })
  })
})
