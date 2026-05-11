import { describe, expect, it } from 'vitest'

import {
  formatOneDecimal,
  formatTenScale,
  normalizeScriptReview,
} from '../utils'

describe('audiobook script review utils', () => {
  it('normalizes missing script review payloads', () => {
    expect(normalizeScriptReview(null)).toBeNull()
    expect(normalizeScriptReview('invalid')).toBeNull()
  })

  it('normalizes review issue counts and suggestion arrays', () => {
    const review = normalizeScriptReview({
      overall_score: 8.5,
      overall_grade: 'A',
      issues: [{ severity: 'minor', category: 'script', description: '节奏可更自然' }],
      revision_suggestions: 'not-array',
    })

    expect(review).toMatchObject({
      overall_score: 8.5,
      overall_grade: 'A',
      issues_count: 1,
      revision_suggestions: [],
    })
    expect(review?.issues).toHaveLength(1)
  })

  it('keeps only typed script review metric fields', () => {
    const review = normalizeScriptReview({
      overall_score: 9,
      script_quality: {
        naturalness_score: 8.7,
        clarity_score: 'invalid',
        total_segments: 24,
      },
      audio_balance: {
        sound_effects: '适中',
        total_effects: 12,
        effects_per_minute: Number.NaN,
      },
      pacing: {
        estimated_duration: '12分钟',
        pacing_issues: ['开头略慢', 123],
        total_segments: 24,
      },
      issues: [
        { severity: 'minor', category: 'pacing', description: '开头可更紧凑' },
        'invalid',
      ],
      revision_suggestions: ['压缩开场环境描写', false],
    })

    expect(review).toMatchObject({
      overall_score: 9,
      script_quality: {
        naturalness_score: 8.7,
        clarity_score: undefined,
        total_segments: 24,
      },
      audio_balance: {
        sound_effects: '适中',
        total_effects: 12,
        effects_per_minute: undefined,
      },
      pacing: {
        estimated_duration: '12分钟',
        pacing_issues: ['开头略慢'],
        total_segments: 24,
      },
      revision_suggestions: ['压缩开场环境描写'],
    })
    expect(review?.issues).toEqual([
      {
        location: undefined,
        severity: 'minor',
        category: 'pacing',
        description: '开头可更紧凑',
        suggestion: undefined,
      },
    ])
  })

  it('normalizes unresolved sound effect asset warnings for display', () => {
    const review = normalizeScriptReview({
      overall_score: 8,
      audio_balance: {
        unresolved_effect_count: 2,
        placeholder_effect_count: 1,
        missing_effect_file_count: 1,
      },
      audio_warnings: [
        {
          code: 'unresolved_sound_effect_assets',
          level: 'warning',
          message: '有 2 个音效未找到真实素材，已在混音时跳过。',
        },
        'invalid',
      ],
      issues: [],
      revision_suggestions: [],
    })

    expect(review?.audio_balance).toMatchObject({
      unresolved_effect_count: 2,
      placeholder_effect_count: 1,
      missing_effect_file_count: 1,
    })
    expect(review?.audio_warnings).toEqual([
      {
        code: 'unresolved_sound_effect_assets',
        level: 'warning',
        message: '有 2 个音效未找到真实素材，已在混音时跳过。',
      },
    ])
  })

  it('formats numeric metrics safely', () => {
    expect(formatTenScale(7)).toBe('7.0')
    expect(formatOneDecimal(12.34)).toBe('12.3')
    expect(formatTenScale(Number.NaN)).toBe('—')
    expect(formatOneDecimal(undefined)).toBe('—')
  })
})
