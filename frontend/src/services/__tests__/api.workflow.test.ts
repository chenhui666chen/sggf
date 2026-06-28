import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from '../api'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('workflow API client', () => {
  it('serializes manual multi-model review flag for async stage execution', async () => {
    const postMock = vi.spyOn((apiClient as any).client, 'post').mockResolvedValue({ status: 200, data: {} })

    await apiClient.postWorkflowStageAsync({
      projectId: 7,
      stage: 'review',
      manualMultiModelReview: true,
    })

    expect(postMock).toHaveBeenCalledWith(
      '/api/v1/workflow/execute-stage-async',
      expect.objectContaining({
        project_id: 7,
        stage: 'review',
        manual_multi_model_review: true,
      }),
      expect.any(Object),
    )
  })

  it('serializes one-shot manual multi-model review preset for async stage execution', async () => {
    const postMock = vi.spyOn((apiClient as any).client, 'post').mockResolvedValue({ status: 200, data: {} })

    await apiClient.postWorkflowStageAsync({
      projectId: 7,
      stage: 'review',
      manualMultiModelReview: true,
      manualMultiModelReviewPreset: 'deep_7',
    })

    expect(postMock).toHaveBeenCalledWith(
      '/api/v1/workflow/execute-stage-async',
      expect.objectContaining({
        project_id: 7,
        stage: 'review',
        manual_multi_model_review: true,
        manual_multi_model_review_preset: 'deep_7',
      }),
      expect.any(Object),
    )
  })
})
