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
        dimension: undefined,
        fix_type: undefined,
        target_fields: [],
        segment_index: undefined,
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

  it('normalizes llm_dimensions from review payload', () => {
    const review = normalizeScriptReview({
      overall_score: 78,
      overall_grade: 'B',
      issues: [],
      llm_dimensions: {
        semantic_coherence: { score: 8.0, label: '语义连贯', category: 'content_narrative', comment: '好' },
        dialogue_naturalness: { score: 6.5, label: '对白自然', category: 'character_dialogue', comment: '一般' },
        invalid_dim: 'not-an-object',
      },
    })

    expect(review?.llm_dimensions).toBeDefined()
    expect(review?.llm_dimensions?.semantic_coherence).toEqual({
      score: 8.0,
      label: '语义连贯',
      category: 'content_narrative',
      comment: '好',
    })
    expect(review?.llm_dimensions?.dialogue_naturalness?.score).toBe(6.5)
    // 非对象维度被过滤
    expect(review?.llm_dimensions?.invalid_dim).toBeUndefined()
  })

  it('returns undefined llm_dimensions when absent or invalid', () => {
    const review = normalizeScriptReview({
      overall_score: 80,
      issues: [],
    })
    expect(review?.llm_dimensions).toBeUndefined()

    const review2 = normalizeScriptReview({
      overall_score: 80,
      issues: [],
      llm_dimensions: 'invalid',
    })
    expect(review2?.llm_dimensions).toBeUndefined()
  })

  it('normalizes issue dimension and fix_type fields', () => {
    const review = normalizeScriptReview({
      overall_score: 75,
      issues: [
        {
          severity: 'major',
          category: 'llm_quality',
          description: '对白生硬',
          suggestion: '口语化',
          dimension: 'dialogue_naturalness',
          fix_type: 'llm_rewrite',
          target_fields: ['text', 'performance_notes'],
          segment_index: 3,
        },
      ],
    })

    expect(review?.issues?.[0]).toMatchObject({
      dimension: 'dialogue_naturalness',
      fix_type: 'llm_rewrite',
      target_fields: ['text', 'performance_notes'],
      segment_index: 3,
    })
  })
})
