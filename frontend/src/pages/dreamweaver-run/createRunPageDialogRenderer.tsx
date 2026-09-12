import React from 'react'
import type { TFunction } from 'i18next'
import type { AppLanguage } from '@/i18n'
import type { DreamweaverShotSnapshot, BulkDeleteProgress, BulkDeleteResult } from '@/types/dreamweaver'
import type { DreamweaverHistoryRunListItem } from './historyDialog'
import type { HistoryRunItem } from './runPageHistoryHelpers'
import type { TaskPointsPrecheckErrorDetail } from '@/services/api'
import type { DreamweaverModelOption } from './runPageAccessors'
import { DreamweaverPromptEditDialog, DreamweaverRegenerateDialog } from './promptDialogs'
import { DreamweaverHistoryDialog } from './historyDialog'
import { DreamweaverBulkDeleteDialog, DreamweaverDeleteRunDialog } from './deleteDialogs'
import { DreamweaverRunConfigDialog } from './configDialog'
import { RunPageAlertsSection } from './RunPageAlertsSection'
import {
  resolveRegenerateDialogLabels,
  resolveRegenerateSubmitDisabled,
} from './runPageHelpers'
import {
  mapHistoryRunsToItems,
  buildHistoryFilterItems,
} from './runPageHistoryHelpers'
import {
  buildModelFieldProps,
  buildToggleFieldProps,
  buildVisualFieldProps,
  buildStrategyFields,
} from './runPagePropsBuilders'
import { getShotId, getShotDesc } from './runPageAccessors'
import {
  STYLE_PRESET_OPTIONS,
  IMAGE_RATIO_OPTIONS,
  IMAGE_RESOLUTION_OPTIONS,
} from './runPageCore'

interface ChapterLike {
  id: number
  chapter_number: string | number
  title?: string | null
  content?: string | null
}

export interface CreateRunPageDialogRendererDeps {
  /** 当前界面语言。本文件不是组件也不是 hook，只能由调用方把它递进来。 */
  language: AppLanguage
  promptEditOpen: boolean
  closePromptEditDialog: () => void
  promptEditShot: DreamweaverShotSnapshot | null
  promptEditGenerated: string | null
  promptEditHead: string
  promptEditTail: string
  promptEditVideo: string
  promptEditSaving: boolean
  promptEditError: string | null
  setPromptEditHead: (v: string) => void
  setPromptEditTail: (v: string) => void
  setPromptEditVideo: (v: string) => void
  savePromptEdit: () => void
  regenOpen: boolean
  closeRegenDialog: () => void
  regenTitle: string | null
  regenRole: string | null
  regenSuggesting: boolean
  regenSubmitting: boolean
  regenForceImageEdit: boolean
  regenImageEditActive: boolean
  regenHasImageBase: boolean
  regenAlertBaseLabel: string
  regenAlertReadyReferenceLabel: string
  regenAlertReadyReferenceCount: number
  regenAlertMissingReferenceLabel: string | null
  regenSuggestError: string | null
  regenImageEditAutoCleared: boolean
  regenPromptInputLabel: string
  regenPrompt: string
  regenPromptInitial: string
  regenError: string | null
  submitRegenerateDialog: () => void
  toggleRegenImageEditPreference: () => void
  requestSmartRegeneratePrompt: (opts?: { role?: string; source?: 'auto' | 'manual' }) => void
  setRegenPrompt: (v: string) => void
  setRegenPromptDirty: (v: boolean) => void
  historyOpen: boolean
  closeHistoryDialog: () => void
  selectedProjectTitle: string | null | undefined
  historyError: string | null
  historyLoading: boolean
  historyRunCount: number
  historyStatusFilters: string[]
  historyStatusCounts: Record<string, number>
  clearHistoryStatusFilters: () => void
  toggleHistoryStatusFilter: (status: string) => void
  refreshHistory: () => void
  historyRefreshDisabled: boolean
  openBulkDeleteDialog: () => void
  historyBulkDeleteDisabled: boolean
  bulkDeleteTargetCount: number
  filteredHistoryRuns: HistoryRunItem[]
  handleViewHistoryRun: (runId: string) => void
  openDeleteRunDialog: (runId: string) => void
  historyEmpty: boolean
  historyFilterEmpty: boolean
  bulkDeleteDialogOpen: boolean
  closeBulkDeleteDialog: () => void
  bulkDeleteSkippedCount: number
  bulkDeleteProgress: BulkDeleteProgress | null
  bulkDeleteError: string | null
  bulkDeleteResult: BulkDeleteResult | null
  bulkDeleteSubmitting: boolean
  confirmBulkDeleteRuns: () => void
  deleteDialogOpen: boolean
  closeDeleteRunDialog: () => void
  deleteRunId: string | null
  deleteDialogError: string | null
  deleteSubmitting: boolean
  confirmDeleteCurrentRun: () => void
  configDialogOpen: boolean
  closeConfigDialog: () => void
  configDialogFullScreen: boolean
  configSubtitle: string
  configDialogErrorNotice: React.ReactNode
  lockedProjectId: number | null
  onOpenProjectList: () => void
  selectedChapterIds: number[]
  chapters: ChapterLike[]
  loadingChapters: boolean
  running: boolean
  handleSelectAll: () => void
  onRefreshChapters: () => void
  chapterRefreshDisabled: boolean
  handleToggleChapter: (chapterId: number) => void
  highQuality: boolean
  setHighQuality: (v: boolean) => void
  smartTuning: boolean
  setSmartTuning: (v: boolean) => void
  videoRequireConfirmation: boolean
  setVideoRequireConfirmation: (v: boolean) => void
  promptReviewRequired: boolean
  setPromptReviewRequired: (v: boolean) => void
  qcAllowFail: boolean
  setQcAllowFail: (v: boolean) => void
  abVariant: string
  setAbVariant: (v: string) => void
  lockedGenerationConfigError: string | null
  generationConfigLocked: boolean
  lockedGenerationConfigSourceRunId: string | null | undefined
  stylePreset: string
  setStylePreset: (v: string) => void
  imageRatio: string
  setImageRatio: (v: string) => void
  imageResolution: string
  setImageResolution: (v: string) => void
  visualFieldsDisabled: boolean
  imageModel: string
  setImageModel: (v: string) => void
  dreamweaverImageModelOptions: DreamweaverModelOption[]
  videoModel: string
  setVideoModel: (v: string) => void
  dreamweaverVideoModelOptions: DreamweaverModelOption[]
  videoEditModel: string
  setVideoEditModel: (v: string) => void
  dreamweaverVideoEditModelOptions: DreamweaverModelOption[]
  visionModel: string
  setVisionModel: (v: string) => void
  dreamweaverVisionModelOptions: DreamweaverModelOption[]
  enableVideoEdit: boolean
  setEnableVideoEdit: (v: boolean) => void
  enableVisionReview: boolean
  setEnableVisionReview: (v: boolean) => void
  enableSafetyAudit: boolean
  setEnableSafetyAudit: (v: boolean) => void
  safetyFailPolicy: string
  setSafetyFailPolicy: (v: 'warn' | 'block') => void
  SAFETY_FAIL_POLICY_OPTIONS: DreamweaverModelOption[]
  onRunFromConfigDialog: () => void
  configRunDisabled: boolean
  renderDiagnosticDialog: () => React.ReactNode
  taskPointsPrecheckError: TaskPointsPrecheckErrorDetail | null
  onClearTaskPointsPrecheckError: () => void
  safetyAuditAlertState: {
    show: boolean
    summary: string
    categories: string[]
    canApprove: boolean
  }
  safetyAuditApproveLoading: boolean
  safetyAuditApproveError: string | null
  onApproveSafetyAudit: () => void
  error: string | null
  hasQcWarning: boolean
  diagnosticPreflight: {
    allowed: boolean
    warnings: { length: number }
    errors: { length: number }
  } | null
  t: TFunction
}

export function createRunPageDialogRenderer(deps: CreateRunPageDialogRendererDeps) {
  const {
    language,
    promptEditOpen,
    closePromptEditDialog,
    promptEditShot,
    promptEditGenerated,
    promptEditHead,
    promptEditTail,
    promptEditVideo,
    promptEditSaving,
    promptEditError,
    setPromptEditHead,
    setPromptEditTail,
    setPromptEditVideo,
    savePromptEdit,
    regenOpen,
    closeRegenDialog,
    regenTitle,
    regenRole,
    regenSuggesting,
    regenSubmitting,
    regenForceImageEdit,
    regenImageEditActive,
    regenHasImageBase,
    regenAlertBaseLabel,
    regenAlertReadyReferenceLabel,
    regenAlertReadyReferenceCount,
    regenAlertMissingReferenceLabel,
    regenSuggestError,
    regenImageEditAutoCleared,
    regenPromptInputLabel,
    regenPrompt,
    regenPromptInitial,
    regenError,
    submitRegenerateDialog,
    toggleRegenImageEditPreference,
    requestSmartRegeneratePrompt,
    setRegenPrompt,
    setRegenPromptDirty,
    historyOpen,
    closeHistoryDialog,
    selectedProjectTitle,
    historyError,
    historyLoading,
    historyRunCount,
    historyStatusFilters,
    historyStatusCounts,
    clearHistoryStatusFilters,
    toggleHistoryStatusFilter,
    refreshHistory,
    historyRefreshDisabled,
    openBulkDeleteDialog,
    historyBulkDeleteDisabled,
    bulkDeleteTargetCount,
    filteredHistoryRuns,
    handleViewHistoryRun,
    openDeleteRunDialog,
    historyEmpty,
    historyFilterEmpty,
    bulkDeleteDialogOpen,
    closeBulkDeleteDialog,
    bulkDeleteSkippedCount,
    bulkDeleteProgress,
    bulkDeleteError,
    bulkDeleteResult,
    bulkDeleteSubmitting,
    confirmBulkDeleteRuns,
    deleteDialogOpen,
    closeDeleteRunDialog,
    deleteRunId,
    deleteDialogError,
    deleteSubmitting,
    confirmDeleteCurrentRun,
    configDialogOpen,
    closeConfigDialog,
    configDialogFullScreen,
    configSubtitle,
    configDialogErrorNotice,
    lockedProjectId,
    onOpenProjectList,
    selectedChapterIds,
    chapters,
    loadingChapters,
    running,
    handleSelectAll,
    onRefreshChapters,
    chapterRefreshDisabled,
    handleToggleChapter,
    highQuality,
    setHighQuality,
    smartTuning,
    setSmartTuning,
    videoRequireConfirmation,
    setVideoRequireConfirmation,
    promptReviewRequired,
    setPromptReviewRequired,
    qcAllowFail,
    setQcAllowFail,
    abVariant,
    setAbVariant,
    lockedGenerationConfigError,
    generationConfigLocked,
    lockedGenerationConfigSourceRunId,
    stylePreset,
    setStylePreset,
    imageRatio,
    setImageRatio,
    imageResolution,
    setImageResolution,
    visualFieldsDisabled,
    imageModel,
    setImageModel,
    dreamweaverImageModelOptions,
    videoModel,
    setVideoModel,
    dreamweaverVideoModelOptions,
    videoEditModel,
    setVideoEditModel,
    dreamweaverVideoEditModelOptions,
    visionModel,
    setVisionModel,
    dreamweaverVisionModelOptions,
    enableVideoEdit,
    setEnableVideoEdit,
    enableVisionReview,
    setEnableVisionReview,
    enableSafetyAudit,
    setEnableSafetyAudit,
    safetyFailPolicy,
    setSafetyFailPolicy,
    SAFETY_FAIL_POLICY_OPTIONS,
    onRunFromConfigDialog,
    configRunDisabled,
    renderDiagnosticDialog,
    taskPointsPrecheckError,
    onClearTaskPointsPrecheckError,
    safetyAuditAlertState,
    safetyAuditApproveLoading,
    safetyAuditApproveError,
    onApproveSafetyAudit,
    error,
    hasQcWarning,
    diagnosticPreflight,
    t,
  } = deps

  const promptEditShotTitle = getShotId(promptEditShot) || t('dreamweaverRun.notSelected')
  const promptEditShotDesc = promptEditShot ? getShotDesc(promptEditShot) : null
  const promptEditGeneratedText = promptEditGenerated || t('dreamweaverRun.noAutoPrompt')

  const renderPromptEditDialog = () => (
    <DreamweaverPromptEditDialog
      open={promptEditOpen}
      onClose={closePromptEditDialog}
      shotTitle={promptEditShotTitle}
      shotDescription={promptEditShotDesc}
      headPrompt={promptEditHead}
      tailPrompt={promptEditTail}
      generatedPrompt={promptEditGeneratedText}
      videoPrompt={promptEditVideo}
      saving={promptEditSaving}
      error={promptEditError}
      onChangeHead={setPromptEditHead}
      onChangeTail={setPromptEditTail}
      onChangeVideo={setPromptEditVideo}
      onSave={savePromptEdit}
    />
  )

  const handleRegenPromptChange = (value: string) => {
    setRegenPrompt(value)
    setRegenPromptDirty(value.trim() !== regenPromptInitial.trim())
  }

  const hasRegenRole = Boolean(regenRole)
  const regenMissingRefLabel = regenAlertMissingReferenceLabel || ''
  const regenDialogTitle = regenTitle || regenRole
  const requestSmartRegeneratePromptManual = () => requestSmartRegeneratePrompt({ source: 'manual' })

  const renderRegenerateDialog = () => {
    const labels = resolveRegenerateDialogLabels({
      imageEditActive: regenImageEditActive,
      imageEditAutoCleared: regenImageEditAutoCleared,
      submitting: regenSubmitting,
    }, t)

    return (
      <DreamweaverRegenerateDialog
        open={regenOpen}
        onClose={closeRegenDialog}
        title={t('dreamweaverRun.regenerateAsset', { title: regenDialogTitle })}
        modeHint={labels.modeHint}
        suggesting={regenSuggesting}
        submitting={regenSubmitting}
        hasRole={hasRegenRole}
        forceImageEdit={regenForceImageEdit}
        imageEditActive={regenImageEditActive}
        hasImageBase={regenHasImageBase}
        alertBaseLabel={regenAlertBaseLabel}
        alertReadyReferenceLabel={regenAlertReadyReferenceLabel}
        alertReadyReferenceCount={regenAlertReadyReferenceCount}
        alertMissingReferenceLabel={regenMissingRefLabel}
        suggestError={regenSuggestError}
        imageEditAutoCleared={regenImageEditAutoCleared}
        promptInputLabel={regenPromptInputLabel}
        prompt={regenPrompt}
        promptPlaceholder={labels.promptPlaceholder}
        error={regenError}
        submitLabel={labels.submitLabel}
        submitDisabled={resolveRegenerateSubmitDisabled({
          submitting: regenSubmitting,
          suggesting: regenSuggesting,
          hasRole: hasRegenRole,
          forceImageEdit: regenForceImageEdit,
          hasImageBase: regenHasImageBase,
        })}
        onSmartGenerate={requestSmartRegeneratePromptManual}
        onToggleImageEdit={toggleRegenImageEditPreference}
        onChangePrompt={handleRegenPromptChange}
        onSubmit={submitRegenerateDialog}
      />
    )
  }

  const historyRunItems = mapHistoryRunsToItems(filteredHistoryRuns, language, t).map((item) => ({
    ...item,
    onView: () => handleViewHistoryRun(item.runId),
    onDelete: () => openDeleteRunDialog(item.runId),
  })) as DreamweaverHistoryRunListItem[]

  const renderHistoryDialog = () => (
    <DreamweaverHistoryDialog
      open={historyOpen}
      onClose={closeHistoryDialog}
      projectTitle={selectedProjectTitle}
      error={historyError}
      loading={historyLoading}
      filterItems={buildHistoryFilterItems({
        totalRuns: historyRunCount,
        statusFilters: historyStatusFilters,
        statusCounts: historyStatusCounts,
        onClearFilters: clearHistoryStatusFilters,
        onToggleFilter: toggleHistoryStatusFilter,
      }, t)}
      onRefresh={refreshHistory}
      refreshDisabled={historyRefreshDisabled}
      onBulkDelete={openBulkDeleteDialog}
      bulkDeleteDisabled={historyBulkDeleteDisabled}
      bulkDeleteLabel={t('dreamweaverRun.bulkDeleteFiltered', { count: bulkDeleteTargetCount })}
      runs={historyRunItems}
      showEmptyHistory={historyEmpty}
      showEmptyFilter={historyFilterEmpty}
    />
  )

  const renderBulkDeleteDialog = () => (
    <DreamweaverBulkDeleteDialog
      open={bulkDeleteDialogOpen}
      onClose={closeBulkDeleteDialog}
      targetCount={bulkDeleteTargetCount}
      skippedCount={bulkDeleteSkippedCount}
      progress={bulkDeleteProgress}
      error={bulkDeleteError}
      result={bulkDeleteResult}
      submitting={bulkDeleteSubmitting}
      onConfirm={confirmBulkDeleteRuns}
    />
  )

  const renderDeleteRunDialog = () => (
    <DreamweaverDeleteRunDialog
      open={deleteDialogOpen}
      onClose={closeDeleteRunDialog}
      runId={deleteRunId}
      error={deleteDialogError}
      submitting={deleteSubmitting}
      onConfirm={confirmDeleteCurrentRun}
    />
  )

  const renderConfigDialog = () => (
    <DreamweaverRunConfigDialog
      open={configDialogOpen}
      onClose={closeConfigDialog}
      fullScreen={configDialogFullScreen}
      subtitle={configSubtitle}
      errorNotice={configDialogErrorNotice}
      lockedProjectId={lockedProjectId}
      projectTitle={selectedProjectTitle}
      onOpenProjectList={onOpenProjectList}
      selectedChapterIds={selectedChapterIds}
      chapters={chapters}
      loadingChapters={loadingChapters}
      running={running}
      onToggleAll={handleSelectAll}
      onRefreshChapters={onRefreshChapters}
      refreshDisabled={chapterRefreshDisabled}
      onToggleChapter={handleToggleChapter}
      strategyFields={buildStrategyFields({
        highQuality,
        setHighQuality,
        smartTuning,
        setSmartTuning,
        videoRequireConfirmation,
        setVideoRequireConfirmation,
        promptReviewRequired,
        setPromptReviewRequired,
        qcAllowFail,
        setQcAllowFail,
      }, t)}
      abVariant={abVariant}
      onChangeAbVariant={setAbVariant}
      lockedGenerationConfigError={lockedGenerationConfigError}
      generationConfigLocked={generationConfigLocked}
      lockedGenerationConfigSourceRunId={lockedGenerationConfigSourceRunId}
      {...buildVisualFieldProps({
        stylePreset, setStylePreset, stylePresetOptions: STYLE_PRESET_OPTIONS,
        imageRatio, setImageRatio, imageRatioOptions: IMAGE_RATIO_OPTIONS,
        imageResolution, setImageResolution, imageResolutionOptions: IMAGE_RESOLUTION_OPTIONS,
      })}
      visualFieldsDisabled={visualFieldsDisabled}
      {...buildModelFieldProps({
        imageModel, setImageModel, imageModelOptions: dreamweaverImageModelOptions,
        videoModel, setVideoModel, videoModelOptions: dreamweaverVideoModelOptions,
        videoEditModel, setVideoEditModel, videoEditModelOptions: dreamweaverVideoEditModelOptions,
        visionModel, setVisionModel, visionModelOptions: dreamweaverVisionModelOptions,
      })}
      {...buildToggleFieldProps({
        enableVideoEdit, setEnableVideoEdit,
        enableVisionReview, setEnableVisionReview,
        enableSafetyAudit, setEnableSafetyAudit,
        safetyFailPolicy, setSafetyFailPolicy,
        safetyFailPolicyOptions: SAFETY_FAIL_POLICY_OPTIONS,
      })}
      onRun={onRunFromConfigDialog}
      runDisabled={configRunDisabled}
    />
  )

  const renderWorkbenchDialogs = () => (
    <>
      {renderDiagnosticDialog()}
      {renderRegenerateDialog()}
      {renderPromptEditDialog()}
      {renderHistoryDialog()}
      {renderBulkDeleteDialog()}
      {renderDeleteRunDialog()}
    </>
  )

  const renderRunPageAlerts = () => (
    <RunPageAlertsSection
      taskPointsPrecheckError={taskPointsPrecheckError}
      onClearTaskPointsPrecheckError={onClearTaskPointsPrecheckError}
      safetyAuditAlertState={safetyAuditAlertState}
      safetyAuditApproveLoading={safetyAuditApproveLoading}
      safetyAuditApproveError={safetyAuditApproveError}
      onApproveSafetyAudit={onApproveSafetyAudit}
      error={error}
      qcWarning={hasQcWarning}
      diagnosticPreflight={diagnosticPreflight}
    />
  )

  return {
    renderPromptEditDialog,
    renderRegenerateDialog,
    renderHistoryDialog,
    renderBulkDeleteDialog,
    renderDeleteRunDialog,
    renderConfigDialog,
    renderWorkbenchDialogs,
    renderRunPageAlerts,
  }
}
