import { describe, expect, it } from 'vitest'

import {
  isSeedSceneVoiceCompatible,
  markSeedSceneIncompatibleVoicePresets,
  SEED_SCENE_INCOMPATIBLE_VOICE_REASON,
} from '../seedSceneVoiceCompatibility'
import type { VoicePreset } from '../types'


const seedNativePreset = (overrides: Partial<VoicePreset> = {}): VoicePreset => ({
  id: 'zh_male_taocheng_uranus_bigtts',
  speaker: 'zh_male_taocheng_uranus_bigtts',
  label: 'Seed 原生男声',
  sourceModel: 'seed-tts-2.0-expressive',
  ...overrides,
})

describe('seed_scene 音色白名单兼容性判定', () => {
  it('接受 Seed-TTS 2.0 原生音色（speaker 直传）', () => {
    expect(isSeedSceneVoiceCompatible(seedNativePreset())).toBe(true)
  })

  it('接受 doubao/ 前缀的 Seed-TTS 模型音色（归一化后兼容）', () => {
    expect(isSeedSceneVoiceCompatible(seedNativePreset({
      sourceModel: 'doubao/seed-tts-2.0-expressive',
    }))).toBe(true)
  })

  it('接受 user_private 音频参考音色（我的复刻/设计）', () => {
    expect(isSeedSceneVoiceCompatible({
      id: 'private:asset_001',
      speaker: 'voice_clone_001',
      label: '我的复刻',
      category: 'custom',
      sourceModel: 'mimo-v2.5-tts-voiceclone',
      referenceSource: 'user_private',
    })).toBe(true)
  })

  it('接受 public_pool 公共音色池音色', () => {
    expect(isSeedSceneVoiceCompatible({
      id: 'public:pub_001',
      speaker: 'voice_pool:pub_001',
      label: '公共音色',
      category: 'public',
      sourceModel: 'seed-tts-2.0-expressive',
      referenceSource: 'public_pool',
    })).toBe(true)
  })

  it('拒绝其他供应商官方音色（qwen3 官方音色）', () => {
    expect(isSeedSceneVoiceCompatible({
      id: 'Cherry',
      speaker: 'Cherry',
      label: 'Qwen Cherry',
      sourceModel: 'qwen3-tts-instruct-flash',
    })).toBe(false)
  })

  it('拒绝 mimo voicedesign 的官方 voice id（无 referenceSource）', () => {
    expect(isSeedSceneVoiceCompatible({
      id: 'mimo_design_001',
      speaker: 'mimo_design_001',
      label: 'MiMo 设计音色',
      sourceModel: 'mimo-v2.5-tts-voicedesign',
    })).toBe(false)
  })
})

describe('markSeedSceneIncompatibleVoicePresets', () => {
  it('为不兼容音色标记 disabled 与提示原因', () => {
    const marked = markSeedSceneIncompatibleVoicePresets([
      seedNativePreset(),
      { id: 'Cherry', speaker: 'Cherry', label: 'Qwen Cherry', sourceModel: 'qwen3-tts-instruct-flash' },
    ])
    expect(marked[0].disabled).toBeUndefined()
    expect(marked[1].disabled).toBe(true)
    expect(marked[1].disabledReason).toBe(SEED_SCENE_INCOMPATIBLE_VOICE_REASON)
  })

  it('保留已存在的 disabledReason，不覆盖更具体的原因', () => {
    const marked = markSeedSceneIncompatibleVoicePresets([
      {
        id: 'private:asset_002',
        speaker: 'voice_002',
        label: '我的复刻',
        category: 'custom',
        referenceSource: 'user_private',
        disabled: true,
        disabledReason: '请先在音色管理中生成标准参考试听',
      },
    ])
    expect(marked[0].disabled).toBe(true)
    expect(marked[0].disabledReason).toBe('请先在音色管理中生成标准参考试听')
  })

  it('保持原数组与未涉及 preset 引用不变（仅替换不兼容项）', () => {
    const presets = [seedNativePreset()]
    const marked = markSeedSceneIncompatibleVoicePresets(presets)
    expect(marked).toEqual(presets)
    expect(marked[0]).toBe(presets[0])
  })
})
