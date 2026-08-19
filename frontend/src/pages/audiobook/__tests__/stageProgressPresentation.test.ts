import { describe, expect, it } from 'vitest'

import { buildChapterScriptMetadata } from '../ChapterScriptResults'
import { formatStageStatusText } from '../TaskStageDetails'
import { getStageConfigForTask } from '../utils'

// 端到端验收（2026-08-16 场景生成第一章）暴露的三个问题：
// 1. running 阶段长期 0% 显示误导（评审阶段 LLM 调用阻塞，无中间进度）
// 2. seed_scene script_only 任务显示分轨 10 阶段模板（后 4 阶段永远等待中）
// 3. 片段统计遗漏 monologue（48 片段 ≠ 14 对白 + 32 旁白）

describe('stage status text for long-running stages', () => {
  it('hides the misleading 0% while a stage is running without progress', () => {
    expect(formatStageStatusText({ status: 'running', progress: 0 })).toBe('进行中')
  })

  it('keeps percentage once a running stage reports progress', () => {
    expect(formatStageStatusText({ status: 'running', progress: 0.5 })).toBe('进行中 50%')
  })

  it('keeps terminal stage labels unchanged', () => {
    expect(formatStageStatusText({ status: 'completed', progress: 1 })).toBe('已完成')
    expect(formatStageStatusText({ status: 'failed', progress: 0 })).toBe('失败')
    expect(formatStageStatusText({ status: 'pending', progress: 0 })).toBe('等待中')
  })
})

describe('stage template by engine mode', () => {
  it('uses script stages plus scene rendering for seed_scene script-only tasks', () => {
    const keys = getStageConfigForTask({ task_type: 'script_only' }, 'seed_scene')
      .map((stage) => stage.key)

    expect(keys).toEqual([
      'strategy',
      'script_adaptation',
      'voice_design',
      'sound_design',
      'music_composition',
      'quality_review',
      'audio_prompt_review',
      'scene_rendering',
    ])
  })

  it('keeps the split-track ten-stage template for legacy engine tasks', () => {
    const keys = getStageConfigForTask({ task_type: 'script_only' }, 'legacy_stems')
      .map((stage) => stage.key)

    expect(keys).toContain('tts_synthesis')
    expect(keys).toContain('final_audio_review')
    expect(keys).not.toContain('scene_rendering')
  })

  it('falls back to progress-based detection when engine mode is unknown', () => {
    const keys = getStageConfigForTask({ task_type: 'script_only' })
      .map((stage) => stage.key)

    expect(keys).toContain('tts_synthesis')
    expect(keys).not.toContain('scene_rendering')
  })
})

describe('chapter script metadata includes monologue segments', () => {
  it('shows monologue count when segments exceed dialogue plus narration', () => {
    const metadata = buildChapterScriptMetadata({
      segment_count: 48,
      dialogue_count: 14,
      narration_count: 32,
      character_count: 6,
    })

    expect(metadata).toEqual([
      '48 个片段',
      '14 段对白',
      '32 段旁白',
      '2 段独白',
      '6 个角色',
    ])
  })

  it('omits monologue when counts already add up', () => {
    const metadata = buildChapterScriptMetadata({
      segment_count: 46,
      dialogue_count: 14,
      narration_count: 32,
      character_count: 0,
    })

    expect(metadata).toEqual(['46 个片段', '14 段对白', '32 段旁白'])
  })

  it('tolerates missing or malformed counts', () => {
    const metadata = buildChapterScriptMetadata({
      segment_count: null,
      dialogue_count: undefined,
      narration_count: Number.NaN,
      character_count: null,
    })

    expect(metadata).toEqual(['0 个片段', '0 段对白', '0 段旁白'])
  })
})
