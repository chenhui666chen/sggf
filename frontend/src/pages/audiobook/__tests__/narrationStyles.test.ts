import { describe, expect, it } from 'vitest'

import {
  DEFAULT_NARRATION_STYLE,
  NARRATION_STYLE_OPTIONS,
  normalizeNarrationStyleOptions,
  normalizeNarrationStyleValue,
} from '../narrationStyles'
import { TTS_MODELS } from '../ttsModels'

describe('audiobook narrationStyles', () => {
  it('normalizes legacy narration style ids', () => {
    expect(normalizeNarrationStyleValue('relaxed')).toBe('relaxing')
    expect(normalizeNarrationStyleValue('vivid')).toBe('expressive')
  })

  it('normalizes supported and backend-provided ids and falls back for invalid values', () => {
    expect(normalizeNarrationStyleValue('dramatic')).toBe('dramatic')
    expect(normalizeNarrationStyleValue('custom')).toBe('custom')
    expect(normalizeNarrationStyleValue('  EXPRESSIVE  ')).toBe('expressive')
    expect(normalizeNarrationStyleValue('Cinematic_Story')).toBe('cinematic_story')
    expect(normalizeNarrationStyleValue('../bad')).toBe(DEFAULT_NARRATION_STYLE)
    expect(normalizeNarrationStyleValue('')).toBe(DEFAULT_NARRATION_STYLE)
    expect(normalizeNarrationStyleValue(null)).toBe(DEFAULT_NARRATION_STYLE)
  })

  it('defines a complete selectable preset list', () => {
    expect(NARRATION_STYLE_OPTIONS.map((style) => style.id)).toEqual([
      'professional',
      'dramatic',
      'relaxing',
      'expressive',
      'custom',
    ])
    expect(NARRATION_STYLE_OPTIONS.every((style) => style.name && style.description && style.color)).toBe(true)
  })

  it('keeps supported model hints aligned with the TTS registry', () => {
    const supportedModels = new Set(TTS_MODELS)

    for (const style of NARRATION_STYLE_OPTIONS) {
      expect(style.supported_models?.every((model) => supportedModels.has(model))).toBe(true)
    }

    expect(NARRATION_STYLE_OPTIONS.find((style) => style.id === 'professional')?.supported_models).toEqual(TTS_MODELS)
    expect(NARRATION_STYLE_OPTIONS.find((style) => style.id === 'dramatic')?.supported_models).not.toContain(
      'qwen3-tts-instruct-flash',
    )
  })

  it('normalizes backend narration style catalog payloads with local fallback data', () => {
    const normalized = normalizeNarrationStyleOptions([
      {
        id: 'professional',
        name: '后端专业播报',
        description: '后端描述',
        supported_models: ['qwen3-tts-instruct-flash', 'unknown-model'],
      },
      {
        id: 'custom',
        name: '',
        description: '',
        supported_models: TTS_MODELS,
      },
      {
        id: 'cinematic_story',
        name: '电影叙事',
        description: '镜头感强',
        color: '#123456',
        supported_models: ['new-provider-tts'],
      },
      {
        id: '../bad',
        name: '不应进入',
      },
    ])

    expect(normalized.map((style) => style.id)).toEqual(['professional', 'custom', 'cinematic_story'])
    expect(normalized[0]).toMatchObject({
      name: '后端专业播报',
      description: '后端描述',
      supported_models: ['qwen3-tts-instruct-flash', 'unknown-model'],
    })
    expect(normalized[1]).toMatchObject({
      name: '自定义',
      description: '使用自定义提示词控制旁白语气',
    })
    expect(normalized[2]).toMatchObject({
      id: 'cinematic_story',
      name: '电影叙事',
      description: '镜头感强',
      color: '#123456',
      supported_models: ['new-provider-tts'],
    })
    expect(normalizeNarrationStyleOptions(null)).toBe(NARRATION_STYLE_OPTIONS)
  })

  it('keeps backend styles with minimal safe payloads using neutral fallback metadata', () => {
    const normalized = normalizeNarrationStyleOptions([
      {
        id: 'documentary',
      },
    ])

    expect(normalized).toHaveLength(1)
    expect(normalized[0]).toMatchObject({
      id: 'documentary',
      name: 'documentary',
      description: '后端叙事风格',
    })
  })
})
