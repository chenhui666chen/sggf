import React from 'react'
import type { DreamweaverShotSnapshot, DreamweaverVideoClipJob, DreamweaverScriptEntities } from '@/types/dreamweaver'
import type { ArtifactChipItem, ArtifactLineItem } from './runPagePropsBuilders'
import {
  resolvePendingPromptReviewShotState,
  resolvePendingPromptReviewState,
  resolvePendingRunningState,
  resolvePendingScriptApprovalState,
  resolvePendingVideoConfirmationJobState,
  resolvePendingVideoConfirmationState,
  resolvePendingViewMode,
} from './pendingViewState'
import { PendingPromptReviewShotItem, PendingVideoConfirmationJobItem } from './pendingListItems'
import {
  PendingEmptyState,
  PendingArtifactDetails,
  PendingPromptReviewView,
  PendingRunningArtifactsSummary,
  PendingRunningShell,
  PendingRunningStageHint,
  PendingScriptApprovalEditor,
  PendingScriptApprovalShell,
  PendingVideoConfirmationView,
} from './pendingViews'
import {
  getShotDesc,
  getShotFramePrompt,
  getShotId,
  getShotVideoPromptOverride,
} from './runPageAccessors'
import { summarizeScriptEntities } from './runPageDataTransforms'
import { PENDING_STAGE_HINTS } from './runPageCore'

interface CreateRunPagePendingRendererDeps {
  taskStatus: string | null
  taskQueue: string | null
  previewStep: number
  previewStepLabel: string
  running: boolean
  currentRunId: string | null
  persistedRunId: string | null
  runSnapshotLoading: boolean
  scriptText: string
  scriptLoading: boolean
  scriptError: string | null
  scriptRequiresReview: boolean
  scriptApproved: boolean
  scriptDirty: boolean
  canResumeFromScript: boolean
  resumeLoading: boolean
  scriptGenerationLabel: string | null
  scriptGeneration: { mode?: string | null; error?: string | null } | null
  scriptEntities: DreamweaverScriptEntities | null
  videoClipJobs: DreamweaverVideoClipJob[]
  videoJobConfirmingShotId: string | null
  videoJobActionError: string | null
  promptReviewApproved: boolean
  promptReviewLoading: boolean
  promptReviewError: string | null
  promptReviewShots: DreamweaverShotSnapshot[]
  promptReviewShowAll: boolean
  promptReviewRequiredSnapshot: boolean
  libraryApproved: boolean
  canResumeFromLibrary: boolean
  snapshotShots: DreamweaverShotSnapshot[]
  snapshotShotById: Map<string, DreamweaverShotSnapshot>
  artifactLines: ArtifactLineItem[]
  hasArtifactLines: boolean
  artifactChips: ArtifactChipItem[]
  waitingScriptApproval: boolean
  waitingVideoConfirmation: boolean
  loadScriptWrapper: () => Promise<void>
  saveScriptWrapper: () => Promise<void>
  approveScriptWrapper: (approved: boolean) => Promise<void>
  resumeGeneration: () => Promise<void>
  confirmVideoJob: (shotId: string) => Promise<void>
  openPromptEditDialog: (shot: DreamweaverShotSnapshot) => void
  approvePromptReview: (approved: boolean) => Promise<void>
  loadRunSnapshot: () => void
  rebuildVideoJobs: () => void
  setScriptText: (text: string) => void
  setPromptReviewShowAll: (fn: (prev: boolean) => boolean) => void
  renderArtifactsDebugPanel: () => React.ReactNode
  renderRunSnapshotPreviewPane: (opts: {
    shotEmptyText: string
    includeStreamingPreview?: boolean
    includeWsError?: boolean
  }) => React.ReactNode
  copyDebugInfo: () => Promise<void>
  openDiagnosticDialog: () => void
  renderPendingLibraryReviewView: () => React.ReactNode
  renderPendingLibraryReadyView: () => React.ReactNode
}

export function createRunPagePendingRenderer(deps: CreateRunPagePendingRendererDeps) {
  const {
    taskStatus,
    taskQueue,
    previewStep,
    previewStepLabel,
    running,
    currentRunId,
    persistedRunId,
    runSnapshotLoading,
    scriptText,
    scriptLoading,
    scriptError,
    scriptRequiresReview,
    scriptApproved,
    scriptDirty,
    canResumeFromScript,
    resumeLoading,
    scriptGenerationLabel,
    scriptGeneration,
    scriptEntities,
    videoClipJobs,
    videoJobConfirmingShotId,
    videoJobActionError,
    promptReviewApproved,
    promptReviewLoading,
    promptReviewError,
    promptReviewShots,
    promptReviewShowAll,
    promptReviewRequiredSnapshot,
    libraryApproved,
    canResumeFromLibrary,
    snapshotShots,
    snapshotShotById,
    artifactLines,
    hasArtifactLines,
    artifactChips,
    waitingScriptApproval,
    waitingVideoConfirmation,
    loadScriptWrapper,
    saveScriptWrapper,
    approveScriptWrapper,
    resumeGeneration,
    confirmVideoJob,
    openPromptEditDialog,
    approvePromptReview,
    loadRunSnapshot,
    rebuildVideoJobs,
    setScriptText,
    setPromptReviewShowAll,
    renderArtifactsDebugPanel,
    renderRunSnapshotPreviewPane,
    copyDebugInfo,
    openDiagnosticDialog,
    renderPendingLibraryReviewView,
    renderPendingLibraryReadyView,
  } = deps

  const renderPendingRunningView = () => {
    const state = resolvePendingRunningState({
      taskStatus,
      taskQueue,
    })
    const stageHint = PENDING_STAGE_HINTS[previewStep] || ''
    const stageHintElement = stageHint ? <PendingRunningStageHint message={stageHint} /> : null
    const artifactDetails = hasArtifactLines ? <PendingArtifactDetails lines={artifactLines} /> : null

    return (
      <PendingRunningShell
        state={state}
        stageHint={stageHintElement}
        snapshotPreview={renderRunSnapshotPreviewPane({
          shotEmptyText: state.snapshotShotEmptyText,
          includeStreamingPreview: true,
          includeWsError: true,
        })}
        artifactsSummary={
          <PendingRunningArtifactsSummary
            chips={artifactChips}
            onCopyDebug={copyDebugInfo}
            onOpenDiagnostic={openDiagnosticDialog}
            diagnosticDisabled={!currentRunId}
          />
        }
        artifactDetails={artifactDetails}
        debugPanel={renderArtifactsDebugPanel()}
      />
    )
  }

  const scriptEntitySummary = scriptEntities ? summarizeScriptEntities(scriptEntities) : ''

  const confirmScriptApproval = () => approveScriptWrapper(true)
  const revokeScriptApproval = () => approveScriptWrapper(false)

  const scriptGenMode = scriptGeneration?.mode
  const scriptGenError = scriptGeneration?.error

  const scriptGenLabel = scriptGenerationLabel || ''

  const scriptEditorDisabled = scriptLoading

  const renderPendingScriptApprovalView = () => {
    const state = resolvePendingScriptApprovalState({
      scriptText,
      scriptGenerationLabel: scriptGenLabel,
      scriptGenerationMode: scriptGenMode,
      scriptGenerationError: scriptGenError,
      scriptRequiresReview,
      scriptApproved,
      scriptDirty,
      currentRunId,
      scriptLoading,
      canResumeFromScript,
      resumeLoading,
      scriptError,
      entitySummary: scriptEntitySummary,
    })

    return (
      <PendingScriptApprovalShell
        state={state}
        onLoadScript={loadScriptWrapper}
        onSaveScript={saveScriptWrapper}
        onApproveScript={confirmScriptApproval}
        onRevokeScript={revokeScriptApproval}
        onResume={resumeGeneration}
        editor={<PendingScriptApprovalEditor value={scriptText} onChange={setScriptText} disabled={scriptEditorDisabled} />}
        debugPanel={renderArtifactsDebugPanel()}
      />
    )
  }

  const shotFramePromptGetter = getShotFramePrompt as (frame: unknown) => string
  const shotVideoPromptOverrideGetter = getShotVideoPromptOverride as (shot: unknown) => string

  const renderPendingVideoConfirmationJobItem = (job: DreamweaverVideoClipJob, idx: number) => {
    const sid = String(job.shot_id || '').trim()
    const shot = sid ? snapshotShotById.get(sid) ?? null : null
    const state = resolvePendingVideoConfirmationJobState({
      job,
      shot,
      running,
      videoJobConfirmingShotId,
      getShotFramePrompt: shotFramePromptGetter,
      getShotVideoPromptOverride: shotVideoPromptOverrideGetter,
      snapshotShotById,
    })

    return (
      <PendingVideoConfirmationJobItem
        itemKey={sid || String(idx)}
        shot={shot}
        state={state}
        onConfirm={confirmVideoJob}
        onEditPrompt={openPromptEditDialog}
      />
    )
  }

  const renderPendingPromptReviewShotItem = (shot: DreamweaverShotSnapshot, idx: number) => {
    const shotId = getShotId(shot)
    const shotDesc = getShotDesc(shot)
    const headPrompt = getShotFramePrompt(shot.head_frame)
    const tailPrompt = getShotFramePrompt(shot.tail_frame)
    const overridePrompt = getShotVideoPromptOverride(shot)
    const state = resolvePendingPromptReviewShotState({
      shotId,
      title: shotDesc,
      shotIndex: shot.shot_index ?? idx + 1,
      headPrompt,
      tailPrompt,
      overridePrompt,
    })

    return (
      <PendingPromptReviewShotItem
        itemKey={shotId || String(idx)}
        shot={shot}
        state={state}
        onEditPrompt={openPromptEditDialog}
      />
    )
  }

  const videoClipJobCount = videoClipJobs.length

  const renderPendingVideoConfirmationView = () => {
    const state = resolvePendingVideoConfirmationState({
      videoJobActionError,
      persistedRunId,
      runSnapshotLoading,
      videoClipJobCount,
    })

    return (
      <PendingVideoConfirmationView
        state={state}
        jobItems={videoClipJobs.map(renderPendingVideoConfirmationJobItem)}
        onRefresh={rebuildVideoJobs}
      />
    )
  }

  const confirmPromptReview = () => approvePromptReview(true)
  const revokePromptReview = () => approvePromptReview(false)
  const togglePromptReviewShowAll = () => setPromptReviewShowAll((prev) => !prev)

  const promptReviewShotCount = promptReviewShots.length

  const renderPendingPromptReviewView = () => {
    const state = resolvePendingPromptReviewState({
      promptReviewApproved,
      libraryApproved,
      persistedRunId,
      runSnapshotLoading,
      currentRunId,
      promptReviewLoading,
      canResumeFromLibrary,
      resumeLoading,
      promptReviewError,
      promptReviewShotCount,
      snapshotShotCount: snapshotShots.length,
      promptReviewShowAll,
    })

    return (
      <PendingPromptReviewView
        state={state}
        shotItems={promptReviewShots.map(renderPendingPromptReviewShotItem)}
        revokeLabel="撤销确认"
        onRefresh={loadRunSnapshot}
        onApprove={confirmPromptReview}
        onRevoke={revokePromptReview}
        onResume={resumeGeneration}
        onToggleShowAll={togglePromptReviewShowAll}
      />
    )
  }

  const renderPendingEmptyState = () => (
    <PendingEmptyState description={`点击"开始生成"后，这里会展示「${previewStepLabel}」相关产物与进度。`} />
  )

  const renderPendingView = () => {
    const mode = resolvePendingViewMode({
      running,
      waitingScriptApproval,
      waitingVideoConfirmation,
      promptReviewRequiredSnapshot,
      previewStep,
      currentRunId,
    })

    switch (mode) {
      case 'running':
        return renderPendingRunningView()
      case 'script_approval':
        return renderPendingScriptApprovalView()
      case 'video_confirmation':
        return renderPendingVideoConfirmationView()
      case 'prompt_review':
        return renderPendingPromptReviewView()
      case 'library_review':
        return renderPendingLibraryReviewView()
      case 'library_ready':
        return renderPendingLibraryReadyView()
      case 'empty':
      default:
        return renderPendingEmptyState()
    }
  }

  return { renderPendingView }
}
