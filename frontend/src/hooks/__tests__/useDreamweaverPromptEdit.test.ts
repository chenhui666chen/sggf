import { describe, expect, it } from 'vitest'

function getShotFramePrompt(frame: unknown): string {
  if (!frame || typeof frame !== 'object' || Array.isArray(frame)) return ''
  const rec = frame as Record<string, unknown>
  return String(rec.prompt ?? rec.suggested_prompt ?? '')
}

function getShotVideoPromptOverride(shot: Record<string, unknown>): string {
  if (!shot || typeof shot !== 'object') return ''
  const meta = shot.meta
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return ''
  return String((meta as Record<string, unknown>).video_prompt_override ?? '')
}

function getShotId(shot: Record<string, unknown>): string {
  if (!shot || typeof shot !== 'object') return ''
  return String(shot.shot_id ?? '')
}

function getShotVideoPromptGenerated(shot: Record<string, unknown> | null): string | null {
  if (!shot || typeof shot !== 'object') return null
  const meta = shot.meta
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return null
  return (meta as Record<string, unknown>).video_prompt_generated as string | null ?? null
}

describe('getShotFramePrompt', () => {
  it('应从 frame 中提取 prompt', () => {
    expect(getShotFramePrompt({ prompt: '一个女孩站在海边' })).toBe('一个女孩站在海边')
  })

  it('应回退到 suggested_prompt', () => {
    expect(getShotFramePrompt({ suggested_prompt: '建议提示词' })).toBe('建议提示词')
  })

  it('prompt 优先于 suggested_prompt', () => {
    expect(getShotFramePrompt({ prompt: '优先', suggested_prompt: '回退' })).toBe('优先')
  })

  it('null 输入应返回空字符串', () => {
    expect(getShotFramePrompt(null)).toBe('')
  })

  it('undefined 输入应返回空字符串', () => {
    expect(getShotFramePrompt(undefined)).toBe('')
  })

  it('数组输入应返回空字符串', () => {
    expect(getShotFramePrompt([1, 2, 3])).toBe('')
  })

  it('无匹配字段应返回空字符串', () => {
    expect(getShotFramePrompt({ other: 'value' })).toBe('')
  })
})

describe('getShotVideoPromptOverride', () => {
  it('应从 shot.meta 中提取 video_prompt_override', () => {
    const shot = { meta: { video_prompt_override: '自定义视频提示词' } }
    expect(getShotVideoPromptOverride(shot)).toBe('自定义视频提示词')
  })

  it('无 meta 应返回空字符串', () => {
    expect(getShotVideoPromptOverride({})).toBe('')
  })

  it('meta 为数组应返回空字符串', () => {
    expect(getShotVideoPromptOverride({ meta: [1, 2] })).toBe('')
  })

  it('无 video_prompt_override 应返回空字符串', () => {
    expect(getShotVideoPromptOverride({ meta: {} })).toBe('')
  })
})

describe('getShotId', () => {
  it('应提取 shot_id', () => {
    expect(getShotId({ shot_id: 'shot_001' })).toBe('shot_001')
  })

  it('无 shot_id 应返回空字符串', () => {
    expect(getShotId({})).toBe('')
  })
})

describe('getShotVideoPromptGenerated', () => {
  it('应提取 video_prompt_generated', () => {
    const shot = { meta: { video_prompt_generated: '生成的视频提示词' } }
    expect(getShotVideoPromptGenerated(shot)).toBe('生成的视频提示词')
  })

  it('null 输入应返回 null', () => {
    expect(getShotVideoPromptGenerated(null)).toBeNull()
  })

  it('无 meta 应返回 null', () => {
    expect(getShotVideoPromptGenerated({})).toBeNull()
  })

  it('无 video_prompt_generated 应返回 null', () => {
    expect(getShotVideoPromptGenerated({ meta: {} })).toBeNull()
  })
})
