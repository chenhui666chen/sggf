import { useEffect, useMemo } from 'react'

import type { QualityMode } from '@/types/dreamweaver'
import { writePersistedDreamWeaverRun } from '@/utils/dreamweaver'
import type { UseDreamweaverRunConfigReturn } from './useDreamweaverRunConfig'

export interface UseDreamweaverRunPersistenceParams {
  selectedProjectId: number | null
  taskRunId: string | null
  resultRunId?: string | null
  taskId: string | null
  taskStatus: string | null
  config: UseDreamweaverRunConfigReturn
  selectedChapterIds: number[]
}

export interface UseDreamweaverRunPersistenceReturn {
  persistedRunId: string | null
  currentRunId: string | null
}

export function useDreamweaverRunPersistence({
  selectedProjectId,
  taskRunId,
  resultRunId,
  taskId,
  taskStatus,
  config,
  selectedChapterIds,
}: UseDreamweaverRunPersistenceParams): UseDreamweaverRunPersistenceReturn {
  const {
    highQuality,
    qcAllowFail,
    smartTuning,
    videoRequireConfirmation,
    promptReviewRequired,
    stylePreset,
    imageRatio,
    imageResolution,
    imageModel,
    videoModel,
    videoEditModel,
    visionModel,
    enableVideoEdit,
    enableVisionReview,
    enableSafetyAudit,
    safetyFailPolicy,
  } = config

  const qualityMode: QualityMode = highQuality ? 'quality' : 'cost'

  const persistedRunId = useMemo(() => {
    return taskRunId || resultRunId || null
  }, [resultRunId, taskRunId])

  const currentRunId = persistedRunId

  useEffect(() => {
    if (!selectedProjectId || !currentRunId) return

    writePersistedDreamWeaverRun(selectedProjectId, {
      run_id: currentRunId,
      task_id: taskId,
      status: taskStatus,
      quality_mode: qualityMode,
      qc_allow_fail: qcAllowFail,
      smart_tuning: smartTuning,
      video_require_confirmation: videoRequireConfirmation,
      prompt_review_required: promptReviewRequired,
      style_preset: stylePreset,
      image_ratio: imageRatio,
      image_resolution: imageResolution,
      image_model: imageModel,
      video_model: videoModel,
      video_edit_model: videoEditModel,
      vision_model: visionModel,
      enable_video_edit: enableVideoEdit,
      enable_vision_review: enableVisionReview,
      enable_safety_audit: enableSafetyAudit,
      safety_fail_policy: safetyFailPolicy,
      selected_chapter_ids: selectedChapterIds,
    })
  }, [
    currentRunId,
    enableVideoEdit,
    enableVisionReview,
    enableSafetyAudit,
    imageModel,
    imageRatio,
    imageResolution,
    promptReviewRequired,
    qcAllowFail,
    qualityMode,
    selectedChapterIds,
    selectedProjectId,
    smartTuning,
    stylePreset,
    safetyFailPolicy,
    taskId,
    taskStatus,
    videoEditModel,
    videoModel,
    videoRequireConfirmation,
    visionModel,
  ])

  return {
    persistedRunId,
    currentRunId,
  }
}
