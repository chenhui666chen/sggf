import { describe, expect, it } from 'vitest'

import {
  coerceStoryExpansionResult,
  createStoryExpansionResultView,
  mergeStoryExpansionRepairResult,
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
      completion_status: undefined,
      goal_reached: undefined,
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
      execution_rounds: [
        {
          round: 1,
          before_chapter_count: 2,
          after_chapter_count: 3,
          character: {
            increment_requested: 1,
            post_validation_score: 82,
            cards_response_mode: 'raw_cards',
            cards_retry_used: true,
            recognized_new_character_count: 1,
            recognized_new_character_names: ['顾晚'],
          },
        },
      ],
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
      completionStatus: 'partial',
      goalReached: false,
      chapterBefore: 2,
      chapterAfter: 3,
      chapterTarget: 3,
      remainingChapterCount: 0,
      characterBefore: 4,
      characterAfter: 5,
      characterTarget: 6,
      remainingCharacterCount: 1,
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
    expect(view?.executionRounds[0].character).toMatchObject({
      cards_response_mode: 'raw_cards',
      cards_retry_used: true,
      recognized_new_character_count: 1,
      recognized_new_character_names: ['顾晚'],
    })
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

  it('保留协同校验中的引用人物与建议字段', () => {
    expect(
      coerceStoryExpansionResult({
        validation_before: {
          score: 78,
          coverage_ratio: 0.75,
          referenced_characters: ['顾晚', '沈砚'],
          unreferenced_characters: ['陈昭'],
          suggestions: ['存在未被大纲引用的人物，优先为这些角色补充登场章节或职责。'],
          validation_stage: 'chapter_level',
        },
        validation_after: {
          score: 86,
          coverage_ratio: 1,
          referenced_characters: ['顾晚', '沈砚', '陈昭'],
          unreferenced_characters: [],
          suggestions: ['当前人物与大纲的基础协同正常，适合继续做增量扩展。'],
          validation_stage: 'chapter_level',
        },
      }),
    ).toMatchObject({
      validation_before: {
        score: 78,
        coverage_ratio: 0.75,
        referenced_characters: ['顾晚', '沈砚'],
        unreferenced_characters: ['陈昭'],
        suggestions: ['存在未被大纲引用的人物，优先为这些角色补充登场章节或职责。'],
        validation_stage: 'chapter_level',
      },
      validation_after: {
        score: 86,
        coverage_ratio: 1,
        referenced_characters: ['顾晚', '沈砚', '陈昭'],
        unreferenced_characters: [],
        suggestions: ['当前人物与大纲的基础协同正常，适合继续做增量扩展。'],
        validation_stage: 'chapter_level',
      },
    })
  })
  it('保留阶段性完成与目标达成字段', () => {
    expect(
      coerceStoryExpansionResult({
        completion_status: 'partial',
        goal_reached: false,
        current_chapter_count: 38,
        target_chapter_count: 60,
      }),
    ).toMatchObject({
      completion_status: 'partial',
      goal_reached: false,
      current_chapter_count: 38,
      target_chapter_count: 60,
    })
  })

  it('保留执行轮次中的尾差补章标记', () => {
    const view = createStoryExpansionResultView({
      execution_rounds: [
        {
          round: 3,
          tail_supplement: true,
          before_chapter_count: 58,
          after_chapter_count: 60,
        },
      ],
      current_chapter_count: 60,
      target_chapter_count: 60,
      current_character_count: 12,
      target_character_count: 12,
    })

    expect(view?.executionRounds).toEqual([
      {
        round: 3,
        tail_supplement: true,
        before_chapter_count: 58,
        after_chapter_count: 60,
        stage: undefined,
        strategy: undefined,
        before_character_count: undefined,
        after_character_count: undefined,
        plot: undefined,
        character: undefined,
      },
    ])
  })

  it('自动修复后会同步新评分并保留原有可复用上下文', () => {
    expect(
      mergeStoryExpansionRepairResult(
        {
          expanded_outline: '旧大纲',
          all_characters: '旧人物',
          execution_mode: 'volume_detail',
          execution_rounds: [{ round: 1, after_chapter_count: 32 }],
          outline_ops: [{ action: 'append', generated_count: 4 }],
          new_characters: ['陈昭'],
          story_strategy: 'balanced',
          story_intent: 'balanced',
          story_expansion_mode: 'volume_detail',
          story_preserve_written_mode: 'preserve_written',
          written_chapter_context: {
            applied: true,
            written_chapter_count: 12,
            preserve_written_mode: 'preserve_written',
          },
          expansion_analysis: {
            validation: { score: 71 },
            analysis_summary: '旧摘要',
          },
          validation_before: { score: 88 },
          validation_after: { score: 71 },
        },
        {
          expanded_outline: '修复后大纲',
          all_characters: '旧人物',
          execution_mode: 'repair',
          alignment_repairs: ['已补齐陈昭的出场承接'],
          validation_before: { score: 71 },
          validation_after: { score: 86 },
          coordination_summary: '评分 71 → 86',
        },
      ),
    ).toMatchObject({
      expanded_outline: '修复后大纲',
      execution_mode: 'repair',
      execution_rounds: [{ round: 1, after_chapter_count: 32 }],
      outline_ops: [{ action: 'append', generated_count: 4 }],
      new_characters: ['陈昭'],
      story_strategy: 'balanced',
      story_intent: 'balanced',
      story_expansion_mode: 'volume_detail',
      story_preserve_written_mode: 'preserve_written',
      written_chapter_context: {
        applied: true,
        written_chapter_count: 12,
        preserve_written_mode: 'preserve_written',
      },
      validation_before: { score: 71 },
      validation_after: { score: 86 },
      alignment_repairs: ['已补齐陈昭的出场承接'],
      expansion_analysis: {
        validation: { score: 86 },
        analysis_summary: '旧摘要',
      },
    })
  })
})
