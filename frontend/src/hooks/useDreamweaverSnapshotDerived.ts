import { useMemo } from 'react'

import {
  asObject,
  computeSnapshotCameraDiagnostics,
  computeTelemetryCounters,
  computeTelemetrySummary,
  extractAudioMarkers,
  extractCharacterProfiles,
  extractScriptGeneration,
  extractSnapshotPlanText,
  extractSnapshotScriptApproved,
  extractSnapshotScriptText,
  toDreamweaverScriptEntities,
  toDreamweaverVideoClipJobs,
} from '@/pages/dreamweaver-run/runPageHelpers'
import type { DreamweaverVideoClipJob, ScriptGeneration } from '@/types/dreamweaver'

export interface UseDreamweaverSnapshotDerivedParams {
  snapshotRuntimeConfig: Record<string, unknown>
  snapshotContract: unknown
}

export interface UseDreamweaverSnapshotDerivedReturn {
  snapshotCameraDiagnostics: ReturnType<typeof computeSnapshotCameraDiagnostics>
  snapshotTelemetry: Record<string, unknown> | null
  snapshotTelemetrySummary: ReturnType<typeof computeTelemetrySummary>
  snapshotTelemetryCounters: ReturnType<typeof computeTelemetryCounters>
  snapshotPlanText: string
  snapshotScriptText: string
  snapshotScriptApproved: boolean
  snapshotScriptEntities: ReturnType<typeof toDreamweaverScriptEntities>
  snapshotScriptGeneration: ScriptGeneration | null
  snapshotCharacterProfiles: unknown[]
  snapshotAudioMarkers: unknown[]
  snapshotMergedVideo: unknown
  videoClipJobs: DreamweaverVideoClipJob[]
  promptReviewRequiredSnapshot: boolean
  promptReviewApproved: boolean
}

function extractMergedVideoFromContract(contract: unknown): unknown {
  const obj = asObject(contract)
  if (!obj) return null
  const mergedVideo = asObject(obj.merged_video)
  if (!mergedVideo) return null
  return mergedVideo
}

export function useDreamweaverSnapshotDerived(
  params: UseDreamweaverSnapshotDerivedParams,
): UseDreamweaverSnapshotDerivedReturn {
  const { snapshotRuntimeConfig, snapshotContract } = params

  const snapshotCameraDiagnostics = useMemo(
    () => computeSnapshotCameraDiagnostics(snapshotRuntimeConfig),
    [snapshotRuntimeConfig],
  )

  const snapshotTelemetry = useMemo(() => asObject(snapshotRuntimeConfig?.telemetry), [snapshotRuntimeConfig])

  const snapshotTelemetrySummary = useMemo(
    () => computeTelemetrySummary(snapshotTelemetry),
    [snapshotTelemetry],
  )

  const snapshotTelemetryCounters = useMemo(
    () => computeTelemetryCounters(snapshotTelemetry),
    [snapshotTelemetry],
  )

  const snapshotPlanText = useMemo(
    () => extractSnapshotPlanText(snapshotRuntimeConfig),
    [snapshotRuntimeConfig],
  )

  const snapshotScriptText = useMemo(
    () => extractSnapshotScriptText(snapshotRuntimeConfig),
    [snapshotRuntimeConfig],
  )

  const snapshotScriptApproved = useMemo(
    () => extractSnapshotScriptApproved(snapshotRuntimeConfig),
    [snapshotRuntimeConfig],
  )

  const snapshotScriptEntities = useMemo(() => {
    return toDreamweaverScriptEntities(snapshotRuntimeConfig?.script_entities)
  }, [snapshotRuntimeConfig])

  const snapshotScriptGeneration = useMemo(
    () => extractScriptGeneration(snapshotRuntimeConfig) as ScriptGeneration | null,
    [snapshotRuntimeConfig],
  )

  const snapshotCharacterProfiles = useMemo(
    () => extractCharacterProfiles(snapshotRuntimeConfig),
    [snapshotRuntimeConfig],
  )

  const snapshotAudioMarkers = useMemo(
    () => extractAudioMarkers(snapshotRuntimeConfig),
    [snapshotRuntimeConfig],
  )

  const snapshotMergedVideo = useMemo(() => {
    return snapshotContract ? extractMergedVideoFromContract(snapshotContract) : null
  }, [snapshotContract])

  const videoClipJobs = useMemo(() => {
    return toDreamweaverVideoClipJobs(snapshotRuntimeConfig.video_clip_jobs)
  }, [snapshotRuntimeConfig.video_clip_jobs])

  const promptReviewRequiredSnapshot = Boolean(snapshotRuntimeConfig?.prompt_review_required)
  const promptReviewApproved = Boolean(
    (snapshotRuntimeConfig.prompt_review as Record<string, unknown> | null | undefined)?.approved,
  )

  return {
    snapshotCameraDiagnostics,
    snapshotTelemetry,
    snapshotTelemetrySummary,
    snapshotTelemetryCounters,
    snapshotPlanText,
    snapshotScriptText,
    snapshotScriptApproved,
    snapshotScriptEntities,
    snapshotScriptGeneration,
    snapshotCharacterProfiles,
    snapshotAudioMarkers,
    snapshotMergedVideo,
    videoClipJobs,
    promptReviewRequiredSnapshot,
    promptReviewApproved,
  }
}
