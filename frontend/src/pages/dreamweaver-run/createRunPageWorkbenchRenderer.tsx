import React from 'react'
import type { TFunction } from 'i18next'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import BugReportIcon from '@mui/icons-material/BugReport'
import HistoryIcon from '@mui/icons-material/History'
import RefreshIcon from '@mui/icons-material/Refresh'
import { TaskHeader } from '@/components/dreamweaver/TaskHeader'
import {
  DreamweaverWorkbenchCard,
  DreamweaverWorkbenchStatusScaffold,
} from './workbenchStatusPanel'
import {
  buildWorkbenchActionItems,
} from './runPagePropsBuilders'
import {
  buildRestartMenuItems,
  isRestartDisabled,
} from './runPageConfigHelpers'
import {
  parsePromptedIds,
  parsePromptedCameraIndices,
} from './runPageCore'

interface CreateRunPageWorkbenchRendererDeps {
  runId: string | null
  progressLabel: number | null
  stateLabel: string | null
  stageLabel: string | null
  taskStatusLabel: string | null
  taskQueue: string | null
  taskStatusColor: 'default' | 'primary' | 'secondary' | 'error' | 'info' | 'success' | 'warning'
  currentRunId: string | null
  running: boolean
  restartLoading: boolean
  manualPreviewStep: boolean
  previewStep: number
  progressStep: number
  selectedProjectId: number | null
  taskStage: string | null
  taskState: string | null
  taskProgress: number | null
  taskStatus: string | null
  waitingApproval: boolean
  result: unknown
  restartAnchorEl: HTMLElement | null
  setRestartAnchorEl: (el: HTMLElement | null) => void
  copyDebugInfo: () => Promise<void>
  openDiagnosticDialog: () => void
  openHistoryDialog: (projectId: number) => void
  openConfigDialog: () => void
  restartGeneration: (startState: string, shotIds?: string[], camIdxs?: number[]) => Promise<void>
  followProgressStep: () => void
  handleClickStep: (step: number) => void
  setError: (v: string | null) => void
  renderPendingView: () => React.ReactNode
  renderResultView: () => React.ReactNode
  renderWorkbenchDialogs: () => React.ReactNode
  stepLabels: readonly string[]
  t: TFunction
}

export function createRunPageWorkbenchRenderer(deps: CreateRunPageWorkbenchRendererDeps) {
  const {
    runId,
    progressLabel,
    stateLabel,
    stageLabel,
    taskStatusLabel,
    taskQueue,
    taskStatusColor,
    currentRunId,
    running,
    restartLoading,
    manualPreviewStep,
    previewStep,
    progressStep,
    taskStage,
    taskState,
    taskProgress,
    taskStatus,
    waitingApproval,
    result,
    restartAnchorEl,
    setRestartAnchorEl,
    copyDebugInfo,
    openDiagnosticDialog,
    openHistoryDialog,
    openConfigDialog,
    restartGeneration,
    followProgressStep,
    handleClickStep,
    setError,
    renderPendingView,
    renderResultView,
    renderWorkbenchDialogs,
    stepLabels,
    t,
  } = deps

  const closeRestartMenu = () => setRestartAnchorEl(null)

  const triggerRestartFromStage = (startState: string) => {
    closeRestartMenu()
    void restartGeneration(startState)
  }

  const requestRestartVideoShots = () => {
    closeRestartMenu()
    const raw = window.prompt(t('dreamweaverRun.promptShotIds'), '')
    const ids = parsePromptedIds(raw)
    if (ids.length === 0) {
      setError(t('dreamweaverRun.errorInvalidShotId'))
      return
    }
    void restartGeneration('VIDEO', ids)
  }

  const requestRestartKeyframeCameras = () => {
    closeRestartMenu()
    const raw = window.prompt(t('dreamweaverRun.promptCamIdxs'), '')
    const unique = parsePromptedCameraIndices(raw)
    if (unique.length === 0) {
      setError(t('dreamweaverRun.errorInvalidCamIdx'))
      return
    }
    void restartGeneration('KEYFRAMES', undefined, unique)
  }

  const openRestartMenu = (e: React.MouseEvent<HTMLElement>) => setRestartAnchorEl(e.currentTarget)

  const copyDebugIcon = <ContentCopyIcon fontSize="small" />
  const diagnosticsIcon = <BugReportIcon fontSize="small" />
  const historyIcon = <HistoryIcon fontSize="small" />
  const restartIcon = <RefreshIcon fontSize="small" />

  const restartActionLabel = restartLoading ? t('dreamweaverRun.restarting') : t('dreamweaverRun.restart')
  const restartActionDisabled = isRestartDisabled(currentRunId, running, restartLoading)
  const restartOpen = !!restartAnchorEl
  const followStepVisible = manualPreviewStep && previewStep !== progressStep

  const renderWorkbenchStatusPanel = () => (
    <DreamweaverWorkbenchStatusScaffold
      runId={runId}
      progressLabel={progressLabel ?? 0}
      stateLabel={stateLabel}
      stageLabel={stageLabel}
      taskStatusLabel={taskStatusLabel}
      taskQueue={taskQueue}
      taskStatusColor={taskStatusColor}
      actionItems={buildWorkbenchActionItems({
        copyDebugInfo,
        openDiagnosticDialog,
        currentRunId,
        openHistoryDialog,
        selectedProjectId: deps.selectedProjectId,
        openConfigDialog,
        copyDebugIcon,
        diagnosticsIcon,
        historyIcon,
      }, t)}
      restartActionLabel={restartActionLabel}
      restartActionDisabled={restartActionDisabled}
      restartActionStartIcon={restartIcon}
      onOpenRestartMenu={openRestartMenu}
      restartAnchorEl={restartAnchorEl}
      restartOpen={restartOpen}
      onCloseRestartMenu={closeRestartMenu}
      restartMenuItems={buildRestartMenuItems({
        currentRunId,
        running,
        restartLoading,
        requestRestartVideoShots,
        requestRestartKeyframeCameras,
        triggerRestartFromStage,
      }, t)}
      followVisible={followStepVisible}
      onFollow={followProgressStep}
      stepLabels={stepLabels}
      activeStep={previewStep}
      progressStep={progressStep}
      onStepClick={handleClickStep}
    />
  )

  const renderWorkbenchTaskHeader = () => (
    <TaskHeader
      runId={runId}
      taskStage={taskStage}
      taskState={taskState}
      taskProgress={taskProgress}
      taskStatus={taskStatus}
      waitingApproval={waitingApproval}
    />
  )

  const renderWorkbenchMainContent = () => (!result ? renderPendingView() : renderResultView())

  const renderWorkbenchCard = () => (
    <DreamweaverWorkbenchCard
      running={running}
      taskProgress={taskProgress ?? 0}
      statusPanel={renderWorkbenchStatusPanel()}
      taskHeader={renderWorkbenchTaskHeader()}
      mainContent={renderWorkbenchMainContent()}
      dialogs={renderWorkbenchDialogs()}
    />
  )

  return {
    renderWorkbenchCard,
  }
}
