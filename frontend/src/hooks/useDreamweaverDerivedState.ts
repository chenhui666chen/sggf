import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import type { LibraryPayload, DreamweaverRunSnapshot, DreamweaverAssetPlanItem, DreamweaverLibraryPlanItem, RunResult, DreamweaverTaskArtifacts } from '@/types/dreamweaver'
import {
  resolveScriptGenerationLabel,
  buildStreamSnapshots,
  computeActiveStreamKeys,
  extractSnapshotShots,
  computeSafetyBlockedShots,
  buildSnapshotShotById,
  computeSnapshotAssetCount,
  extractSnapshotAssetSummary,
  resolveLibraryPromptReviewMessage,
  computeAssetPlanSummary,
  computeLibraryDisplayItems,
  computeLibrarySummary,
  computeLibraryGroups,
  resolveDiagnosticCameraDiagnostics,
  computeDiagnosticShots,
  resolveTaskStatusLabel,
  resolveTaskStatusColor,
  buildArtifactDerivedState,
} from '@/pages/dreamweaver-run/runPageHelpers'
import { stageToPreviewStep } from '@/utils/dreamweaver'
import type { SnapshotCameraDiagnostics } from '@/pages/dreamweaver-run/runPageHelpers'

export interface UseDreamweaverDerivedStateOptions {
  scriptGeneration: { mode?: string | null; model?: string | null } | null
  streamTextByKey: Record<string, string>
  streamMetaByKey: Record<string, { stage?: string | null; done?: boolean }>
  runSnapshot: DreamweaverRunSnapshot | null
  promptReviewShowAll: boolean
  libraryApproved: boolean
  promptReviewReady: boolean
  promptReviewRequiredSnapshot: boolean
  assetPlanItems: DreamweaverAssetPlanItem[]
  library: LibraryPayload | null
  libraryPlanItems: DreamweaverLibraryPlanItem[]
  libraryPreviews: Record<number, string>
  libraryPreviewAspectRatio: string
  missingRoleSet: Set<string>
  snapshotCameraDiagnostics: SnapshotCameraDiagnostics
  diagnosticResult: RunResult | null
  taskRunId: string | null
  result: RunResult | null
  taskStage: string | null
  taskState: string | null
  taskStatus: string | null
  taskArtifacts: DreamweaverTaskArtifacts | null
  running: boolean
  waitingApproval: boolean
  taskProgress: number
}

export function useDreamweaverDerivedState(options: UseDreamweaverDerivedStateOptions) {
  const {
    scriptGeneration,
    streamTextByKey,
    streamMetaByKey,
    runSnapshot,
    promptReviewShowAll,
    libraryApproved,
    promptReviewReady,
    promptReviewRequiredSnapshot,
    assetPlanItems,
    library,
    libraryPlanItems,
    libraryPreviews,
    libraryPreviewAspectRatio,
    missingRoleSet,
    snapshotCameraDiagnostics,
    diagnosticResult,
    taskRunId,
    result,
    taskStage,
    taskState,
    taskStatus,
    taskArtifacts,
    running,
    waitingApproval,
    taskProgress,
  } = options

  const { t } = useTranslation()

  const scriptGenerationLabel = useMemo(
    () => resolveScriptGenerationLabel(scriptGeneration, t),
    [scriptGeneration?.mode, scriptGeneration?.model, t],
  )

  const streamSnapshots = useMemo(() => buildStreamSnapshots(streamTextByKey), [streamTextByKey])

  const activeStreamKeys = useMemo(() => computeActiveStreamKeys(streamMetaByKey), [streamMetaByKey])

  const { snapshotShots, safetyBlockedShots, snapshotShotById } = useMemo(() => {
    const shots = extractSnapshotShots(runSnapshot)
    return {
      snapshotShots: shots,
      safetyBlockedShots: computeSafetyBlockedShots(shots),
      snapshotShotById: buildSnapshotShotById(shots),
    }
  }, [runSnapshot])

  const promptReviewShots = useMemo(() => {
    return promptReviewShowAll ? snapshotShots : snapshotShots.slice(0, 12)
  }, [promptReviewShowAll, snapshotShots])

  const { snapshotAssetCount, snapshotAssetSummary } = useMemo(() => ({
    snapshotAssetCount: computeSnapshotAssetCount(snapshotShots),
    snapshotAssetSummary: extractSnapshotAssetSummary(snapshotShots),
  }), [snapshotShots])

  const libraryPromptReviewMessage = resolveLibraryPromptReviewMessage(libraryApproved, promptReviewReady, promptReviewRequiredSnapshot, t)

  const { assetPlanSummary, mergedVideoPlan } = useMemo(() => ({
    assetPlanSummary: computeAssetPlanSummary(assetPlanItems),
    mergedVideoPlan: assetPlanItems.find((item) => item.id === 'merged_video') || null,
  }), [assetPlanItems])

  const nonMergedVideoAssets = useMemo(() => assetPlanItems.filter((item) => item.id !== 'merged_video'), [assetPlanItems])
  const hasNonMergedVideoAssets = nonMergedVideoAssets.length > 0
  const hasMergedVideoPlan = Boolean(mergedVideoPlan)

  const libraryPreviewsStringKeys = useMemo(
    () => Object.fromEntries(Object.entries(libraryPreviews)) as Record<string, string>,
    [libraryPreviews],
  )

  const libraryDisplayItems = useMemo(
    () => computeLibraryDisplayItems({ library, libraryPlanItems, libraryPreviews: libraryPreviewsStringKeys, libraryPreviewAspectRatio, missingRoleSet }, t),
    [library?.assets, library?.spec, libraryPlanItems, libraryPreviewsStringKeys, libraryPreviewAspectRatio, missingRoleSet, t],
  )

  const { librarySummary, libraryGroups } = useMemo(() => ({
    librarySummary: computeLibrarySummary(libraryDisplayItems),
    libraryGroups: computeLibraryGroups(libraryDisplayItems, t),
  }), [libraryDisplayItems, t])

  const hasLibraryItems = libraryDisplayItems.length > 0

  const diagnosticCameraDiagnostics = useMemo(
    () => resolveDiagnosticCameraDiagnostics(snapshotCameraDiagnostics, diagnosticResult),
    [diagnosticResult, snapshotCameraDiagnostics],
  )

  const diagnosticCameraSceneUris = diagnosticCameraDiagnostics.sceneUris
  const hasDiagnosticCameraSceneUris = diagnosticCameraSceneUris.length > 0

  const diagnosticShots = useMemo(
    () => computeDiagnosticShots(diagnosticResult),
    [diagnosticResult],
  )

  const { runId, stageLabel, stateLabel } = useMemo(() => ({
    runId: taskRunId || result?.run_id || null,
    stageLabel: taskStage || result?.stage || null,
    stateLabel: taskState || result?.state || null,
  }), [result?.run_id, result?.stage, result?.state, taskRunId, taskStage, taskState])

  const { taskStatusLabel, taskStatusColor } = useMemo(() => ({
    taskStatusLabel: resolveTaskStatusLabel(taskStatus, t),
    taskStatusColor: resolveTaskStatusColor(taskStatus),
  }), [taskStatus, t])

  const { chips: artifactChips, lines: artifactLines } = useMemo(
    () => buildArtifactDerivedState(taskArtifacts),
    [taskArtifacts],
  )
  const hasArtifactLines = artifactLines.length > 0

  const progressLabel = useMemo(() => {
    if (running || waitingApproval) return taskProgress
    if (typeof result?.progress === 'number') return result.progress
    return taskProgress
  }, [result?.progress, running, taskProgress, waitingApproval])

  const progressStep = useMemo(() => stageToPreviewStep(stageLabel), [stageLabel])

  return {
    scriptGenerationLabel,
    streamSnapshots,
    activeStreamKeys,
    snapshotShots,
    safetyBlockedShots,
    snapshotShotById,
    promptReviewShots,
    snapshotAssetCount,
    snapshotAssetSummary,
    libraryPromptReviewMessage,
    assetPlanSummary,
    mergedVideoPlan,
    nonMergedVideoAssets,
    hasNonMergedVideoAssets,
    hasMergedVideoPlan,
    libraryDisplayItems,
    librarySummary,
    libraryGroups,
    hasLibraryItems,
    diagnosticCameraDiagnostics,
    diagnosticCameraSceneUris,
    hasDiagnosticCameraSceneUris,
    diagnosticShots,
    runId,
    stageLabel,
    stateLabel,
    taskStatusLabel,
    taskStatusColor,
    artifactChips,
    artifactLines,
    hasArtifactLines,
    progressLabel,
    progressStep,
  }
}
