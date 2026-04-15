import { describe, expect, it } from 'vitest'

import {
  getStoryExpansionTaskMeta,
  getStoryExpansionWaitHint,
} from '../storyExpansionTiming'

describe('storyExpansionTiming', () => {
  it('为分轮补人场景生成等待提示', () => {
    expect(getStoryExpansionWaitHint({
      estimated_rounds: 8,
      auto_supplement: {
        chapter_delta: 6,
        character_plan: {
          stage_label: '首轮',
          stage_target_characters: 18,
          task_target_characters: 38,
        },
      },
    })).toBe('当前按分轮协同推进：首轮先补到 18 人，本次任务预计补到 38 人，自动补足 6 个承接章节，预计执行 8 轮。')
  })

  it('合并耗时区间与等待提示为任务元数据', () => {
    expect(getStoryExpansionTaskMeta({
      estimated_duration_minutes_min: 45,
      estimated_duration_minutes_max: 80,
      estimated_rounds: 8,
      auto_supplement: {
        chapter_delta: 6,
        character_plan: {
          stage_label: '首轮',
          stage_target_characters: 18,
          task_target_characters: 38,
        },
      },
    })).toEqual({
      estimated_duration_minutes_min: 45,
      estimated_duration_minutes_max: 80,
      wait_hint: '当前按分轮协同推进：首轮先补到 18 人，本次任务预计补到 38 人，自动补足 6 个承接章节，预计执行 8 轮。',
    })
  })

  it('没有耗时区间时也能保留等待提示', () => {
    expect(getStoryExpansionTaskMeta({
      estimated_rounds: 5,
      auto_supplement: {
        character_plan: {
          stage_label: '首轮',
          stage_target_characters: 15,
          task_target_characters: 35,
        },
      },
    })).toEqual({
      wait_hint: '当前按分轮协同推进：首轮先补到 15 人，本次任务预计补到 35 人，预计执行 5 轮。',
    })
  })
})
