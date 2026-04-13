import { describe, expect, it } from 'vitest'

import {
  extractSystemCollectionsCreatedNames,
  getStoryExpansionResultFromTaskComplete,
  isStoryExpansionTaskError,
  isStoryExpansionTaskId,
  isStoryExpansionTaskProgress,
} from '../storyExpansionEvents'

describe('storyExpansionEvents', () => {
  it('只识别协同扩展任务 ID', () => {
    expect(isStoryExpansionTaskId('expand-story-123')).toBe(true)
    expect(isStoryExpansionTaskId('expand-outline-123')).toBe(false)
    expect(isStoryExpansionTaskId(null)).toBe(false)
  })

  it('从完成事件中提取并规范化协同扩展结果', () => {
    expect(
      getStoryExpansionResultFromTaskComplete({
        project_id: 1,
        task_id: 'expand-story-123',
        status: 'completed',
        result: {
          current_chapter_count: 12,
          alignment_repairs: ['顾晚'],
        },
      }),
    ).toMatchObject({
      expanded_outline: '',
      all_characters: '',
      outline_delta: '',
      character_delta: '',
      character_relationships: '',
      outline_ops: [],
      execution_rounds: [],
      new_characters: [],
      current_chapter_count: 12,
      alignment_repairs: ['顾晚'],
      alignment_warnings: [],
      stop_reasons: [],
      volume_index: null,
      volume_chapter_range: null,
      epic_total_volumes: null,
      epic_chapter_range: null,
    })
  })

  it('非协同扩展任务不会被识别成协同结果', () => {
    expect(
      getStoryExpansionResultFromTaskComplete({
        project_id: 1,
        task_id: 'expand-outline-123',
        status: 'completed',
        result: {
          expanded_outline: '第1章：开场',
        },
      }),
    ).toBeNull()
  })

  it('识别协同扩展进度与错误事件', () => {
    expect(
      isStoryExpansionTaskProgress({
        project_id: 1,
        task_id: 'expand-story-123',
        progress: 40,
        message: '进行中',
      }),
    ).toBe(true)
    expect(
      isStoryExpansionTaskError({
        project_id: 1,
        task_id: 'expand-story-123',
        status: 'failed',
        error: '任务失败',
      }),
    ).toBe(true)
  })

  it('提取系统自动创建通知里的集合名称', () => {
    expect(
      extractSystemCollectionsCreatedNames({
        project_id: 1,
        message: '已创建',
        type: 'system_collections_created',
        data: {
          collections: [
            { name: '人物体系' },
            { name: '势力体系' },
            { name: ' ' },
          ],
        },
      }),
    ).toEqual(['人物体系', '势力体系'])
  })
})
