import { describe, expect, it } from 'vitest'

import {
  getStoryExpansionStorageKeys,
  parseStoredStoryExpansionResult,
} from '../storyExpansionStorage'

describe('storyExpansionStorage', () => {
  it('为当前协同扩展状态生成统一的缓存 key', () => {
    expect(getStoryExpansionStorageKeys(12)).toEqual({
      taskState: 'expanding_story_12',
      taskStartedAt: 'expanding_story_start_12',
      taskId: 'expanding_story_task_12',
      result: 'story_expand_result_12',
    })
  })

  it('安全恢复当前 schema 的协同扩展缓存结果', () => {
    const raw = JSON.stringify({
      current_character_count: 12,
      alignment_repairs: ['顾晚'],
      alignment_warnings: ['陈昭尚未在大纲中出场'],
      expansion_analysis: {
        warnings: ['建议复查卷末钩子'],
        auto_supplement: {
          character_plan: {
            recommended_range_text: '113-180',
            stage_label: '框架阶段',
            stage_target_characters: 34,
            remaining_to_recommended_min: 79,
            follow_up_phase: '后续卷级细化或后续协同',
          },
        },
      },
    })

    expect(parseStoredStoryExpansionResult(raw)).toEqual({
      expanded_outline: '',
      all_characters: '',
      outline_delta: '',
      character_delta: '',
      character_relationships: '',
      outline_ops: [],
      execution_mode: undefined,
      execution_mode_reason: undefined,
      execution_rounds: [],
      new_characters: [],
      alignment_repairs: ['顾晚'],
      story_strategy: undefined,
      story_intent: undefined,
      story_expansion_mode: undefined,
      story_preserve_written_mode: undefined,
      written_chapter_context: undefined,
      volume_index: null,
      volume_chapter_range: null,
      coordination_summary: undefined,
      current_chapter_count: undefined,
      target_chapter_count: undefined,
      current_character_count: 12,
      target_character_count: undefined,
      validation_before: undefined,
      validation_after: undefined,
      alignment_warnings: ['陈昭尚未在大纲中出场'],
      character_sync: undefined,
      stop_reasons: [],
      expansion_analysis: {
        warnings: ['建议复查卷末钩子'],
        auto_supplement: {
          character_plan: {
            recommended_range_text: '113-180',
            stage_label: '框架阶段',
            stage_target_characters: 34,
            remaining_to_recommended_min: 79,
            follow_up_phase: '后续卷级细化或后续协同',
          },
        },
      },
      epic_total_volumes: null,
      epic_chapter_range: null,
      message: undefined,
    })
  })

  it('包含历史冗余字段但具备当前 schema 锚点时仍按当前结果恢复', () => {
    const raw = JSON.stringify({
      expanded_outline: '新大纲',
      all_characters: '新人物',
      outline_delta_text: '新增章节',
      character_delta_text: '新增角色',
      new_character_names: ['顾晚'],
      summary: '已完成协同',
      target_chapters: 18,
      target_count: 7,
    })

    expect(parseStoredStoryExpansionResult(raw)).toEqual({
      expanded_outline: '新大纲',
      all_characters: '新人物',
      outline_delta: '',
      character_delta: '',
      character_relationships: '',
      outline_ops: [],
      execution_mode: undefined,
      execution_mode_reason: undefined,
      execution_rounds: [],
      new_characters: [],
      alignment_repairs: [],
      story_strategy: undefined,
      story_intent: undefined,
      story_expansion_mode: undefined,
      story_preserve_written_mode: undefined,
      written_chapter_context: undefined,
      volume_index: null,
      volume_chapter_range: null,
      coordination_summary: undefined,
      current_chapter_count: undefined,
      target_chapter_count: undefined,
      current_character_count: undefined,
      target_character_count: undefined,
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

  it('遇到不含当前 schema 锚点的对象时返回 null', () => {
    const raw = JSON.stringify({
      foo: 'bar',
      count: 3,
    })

    expect(parseStoredStoryExpansionResult(raw)).toBeNull()
  })

  it('遇到损坏 JSON 时返回 null', () => {
    expect(parseStoredStoryExpansionResult('{bad json')).toBeNull()
  })

  it('遇到非对象 JSON 时返回 null', () => {
    expect(parseStoredStoryExpansionResult('"plain text"')).toBeNull()
    expect(parseStoredStoryExpansionResult('[1,2,3]')).toBeNull()
  })
})
