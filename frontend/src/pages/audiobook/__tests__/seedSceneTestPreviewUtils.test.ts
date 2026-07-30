import { describe, expect, it } from 'vitest'

import type { SeedSceneTestPreviewResponse } from '@/services/api'
import { normalizeSeedSceneTestPreviewResponse } from '../seedSceneTestPreviewUtils'

const legacyResponse = {
  model: 'seed-audio-1.0',
  case_id: 'multi_character_pressure',
  variant: 'described_voices',
  blind_label: '样本 A',
  prompt: '测试 Prompt',
  expected_texts: ['不要啊！'],
  audio_data_base64: 'SUQz',
  audio_format: 'mp3',
  audio_mime_type: 'audio/mpeg',
  audio_size_bytes: 3,
  duration: 19.032,
  request_id: 'request-legacy-1',
  generation_status: 'passed',
  fallback_reason: null,
  quality_report: { passed: true },
  references: [],
  cached: true,
} as unknown as SeedSceneTestPreviewResponse

describe('Seed scene preview response compatibility', () => {
  it('normalizes an older backend response without crashing the review page', () => {
    const normalized = normalizeSeedSceneTestPreviewResponse(legacyResponse, 2)

    expect(normalized.sample_index).toBe(2)
    expect(normalized.sample_id).toBe(
      'legacy:multi_character_pressure:described_voices:r2:request-legacy-1',
    )
    expect(normalized.billing).toEqual({})
    expect(normalized.generation_latency_s).toBeNull()
  })

  it('preserves metrics returned by the current backend', () => {
    const normalized = normalizeSeedSceneTestPreviewResponse({
      ...legacyResponse,
      sample_index: 3,
      sample_id: 'seed-sample-current',
      generation_latency_s: 21.5,
      billing: { actual_cost_yuan: 0.3167 },
    }, 1)

    expect(normalized.sample_index).toBe(3)
    expect(normalized.sample_id).toBe('seed-sample-current')
    expect(normalized.generation_latency_s).toBe(21.5)
    expect(normalized.billing.actual_cost_yuan).toBe(0.3167)
  })
})
