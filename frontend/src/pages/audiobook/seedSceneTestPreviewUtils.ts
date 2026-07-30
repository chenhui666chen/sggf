import type { SeedSceneTestPreviewResponse } from '@/services/api'

type SeedSceneTestPreviewCompatInput = Omit<
  SeedSceneTestPreviewResponse,
  'billing' | 'generation_latency_s' | 'sample_id' | 'sample_index'
> & Partial<Pick<
  SeedSceneTestPreviewResponse,
  'billing' | 'generation_latency_s' | 'sample_id' | 'sample_index'
>>

export const normalizeSeedSceneTestPreviewResponse = (
  response: SeedSceneTestPreviewCompatInput,
  requestedSampleIndex: number,
): SeedSceneTestPreviewResponse => {
  const sampleIndex = Number.isInteger(response.sample_index)
    ? Number(response.sample_index)
    : requestedSampleIndex
  const requestIdentity = String(
    response.request_id || response.duration || response.audio_size_bytes || 'unknown',
  )

  return {
    ...response,
    sample_index: sampleIndex,
    sample_id: String(response.sample_id || (
      `legacy:${response.case_id}:${response.variant}:r${sampleIndex}:${requestIdentity}`
    )),
    generation_latency_s: response.generation_latency_s ?? null,
    billing: response.billing ?? {},
  }
}
