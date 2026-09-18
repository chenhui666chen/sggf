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

  it('maps generate-next-chapter options from camelCase to snake_case', async () => {
    const postMock = vi.spyOn((apiClient as any).client, 'post').mockResolvedValue({ status: 200, data: {} })

    await apiClient.generateNextWorkflowChapter(7, {
      workflowGenerationModel: 'deepseek-v4-pro',
      generationTier: 'standard',
    })

    expect(postMock).toHaveBeenCalledWith(
      '/api/v1/workflow/7/generate-next-chapter',
      {
        workflow_generation_model: 'deepseek-v4-pro',
        generation_tier: 'standard',
      },
      expect.any(Object),
    )
  })

  it('sends only generation_tier for free tier requests', async () => {
    const postMock = vi.spyOn((apiClient as any).client, 'post').mockResolvedValue({ status: 200, data: {} })

    await apiClient.generateNextWorkflowChapter(7, { generationTier: 'free' })

    expect(postMock).toHaveBeenCalledWith(
      '/api/v1/workflow/7/generate-next-chapter',
      { generation_tier: 'free' },
      expect.any(Object),
    )
  })

  it('sends empty payload when options are omitted (standard tier default)', async () => {
    const postMock = vi.spyOn((apiClient as any).client, 'post').mockResolvedValue({ status: 200, data: {} })

    await apiClient.generateNextWorkflowChapter(7)

    expect(postMock).toHaveBeenCalledWith(
      '/api/v1/workflow/7/generate-next-chapter',
      {},
      expect.any(Object),
    )
  })

  it('sends resume_after_confirmation only after explicit user confirmation', async () => {
    const postMock = vi.spyOn((apiClient as any).client, 'post').mockResolvedValue({ status: 200, data: {} })

    await apiClient.generateNextWorkflowChapter(7, {
      generationTier: 'standard',
      resumeAfterConfirmation: true,
    })

    expect(postMock).toHaveBeenCalledWith(
      '/api/v1/workflow/7/generate-next-chapter',
      { generation_tier: 'standard', resume_after_confirmation: true },
      expect.any(Object),
    )

    // 未显式确认时不得静默携带恢复标记，否则会绕过熔断的人工确认语义
    await apiClient.generateNextWorkflowChapter(7, { generationTier: 'standard' })

    expect(postMock).toHaveBeenLastCalledWith(
      '/api/v1/workflow/7/generate-next-chapter',
      { generation_tier: 'standard' },
      expect.any(Object),
    )
  })

  it('loads the authenticated user free generation quota', async () => {
    const getMock = vi.spyOn((apiClient as any).client, 'get').mockResolvedValue({ status: 200, data: {} })

    await apiClient.getFreeGenerationQuota()

    expect(getMock).toHaveBeenCalledWith('/api/v1/workflow/free-generation/quota', {
      validateStatus: expect.any(Function),
    })
  })
})
