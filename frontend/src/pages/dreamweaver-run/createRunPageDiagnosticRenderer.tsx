import type { TFunction } from 'i18next'
import {
  DiagnosticFrameAccordion,
  DiagnosticJson,
  TitledDiagnosticJsonAccordion,
  ShotDiagnosticUploadActions,
  ShotDiagnosticPromptRegenerateActions,
  ShotProviderTraceSection,
  DreamweaverDiagnosticCameraDiagnosticsSection,
  DreamweaverDiagnosticPreflightSection,
  DreamweaverDiagnosticProviderTraceSection,
  DreamweaverDiagnosticSmartDispatchSection,
  DreamweaverDiagnosticTelemetrySection,
} from './diagnosticSections'
import {
  DreamweaverRunDiagnosticDialog,
} from './diagnosticDialog'
import {
  DreamweaverDiagnosticShotAccordion,
  DreamweaverDiagnosticShotActions,
  DreamweaverDiagnosticShotDetails,
  DreamweaverDiagnosticShotSummary,
} from './diagnosticShotViews'
import {
  buildDiagnosticDialogProps,
  buildRunDiagnosticPayload as buildRunDiagnosticPayloadHelper,
  buildShotDiagnosticCopyPayload,
  buildCameraDiagnosticPayload as buildCameraDiagnosticPayloadHelper,
  hasCameraDiagnosticsData,
  resolveCameraCounts,
  resolveShotDiagnosticAccordionState,
  resolvePreflightVideoConfig,
  resolveProviderTraceSummaryProps,
  resolveProviderTraceFeatureFlags,
  resolveSmartDispatchTraceDetails,
  resolveSmartDispatchSummaryProps,
  resolveTelemetrySectionProps,
  buildCameraAccordionProps,
} from './runPageHelpers'
import type {
  DreamweaverDiagnosticShot,
  DreamweaverVideoProviderShotTrace,
  DreamweaverRunPreflight,
  DreamweaverVideoProviderTrace,
  DreamweaverSmartDispatchTrace,
  RunResult,
} from '@/types/dreamweaver'
import type { DreamweaverProviderTraceSummary, DreamweaverSmartDispatchTraceSummary } from '@/utils/dreamweaver'
import type { SnapshotCameraDiagnostics } from './runPageDiagnosticHelpers'

type RenderRunAssetPreviewGrid = (title: string, uris: string[], kind: 'image' | 'video') => React.ReactNode

interface CreateRunPageDiagnosticRendererDeps {
  safeJsonStringify: (value: unknown) => string
  copyText: (text: string) => Promise<void>
  renderRunAssetPreviewGrid: RenderRunAssetPreviewGrid
  currentRunId: string | null
  diagnosticOpen: boolean
  closeDiagnosticDialog: () => void
  diagnosticResult: RunResult | null
  diagnosticActionError: string | null
  diagnosticActionLoading: boolean
  diagnosticShots: DreamweaverDiagnosticShot[]
  persistedRunId: string | null
  runSnapshotLoading: boolean
  diagnosticPreflight: DreamweaverRunPreflight | null
  diagnosticProviderTrace: DreamweaverVideoProviderTrace | null
  diagnosticSmartDispatchTrace: DreamweaverSmartDispatchTrace | null
  diagnosticProviderTraceByShotId: Map<string, DreamweaverVideoProviderShotTrace>
  diagnosticProviderTraceSummary: DreamweaverProviderTraceSummary | null
  diagnosticSmartDispatchTraceSummary: DreamweaverSmartDispatchTraceSummary | null
  snapshotRuntimeConfig: Record<string, unknown> | null
  snapshotTelemetrySummary: unknown
  snapshotTelemetryCounters: unknown
  snapshotTelemetry: unknown
  diagnosticCameraDiagnostics: SnapshotCameraDiagnostics
  hasDiagnosticCameraSceneUris: boolean
  diagnosticCameraSceneUris: string[]
  diagnosticUploadDisabled: boolean
  uploadShotAsset: (shotId: string, assetRole: 'head_frame' | 'tail_frame' | 'mid_frame' | 'video_clip', file: File) => void
  promptAndRegenerateKeyframe: (shotId: string, frameType: 'head' | 'tail', prompt: string) => void
  getDiagnosticStoryboardPrompt: (sb: Record<string, unknown> | null, frameRole: 'head_frame' | 'tail_frame') => string
  restartGeneration: (startState: string, shotIds?: string[], cameraIndices?: number[]) => void
  restartActionDisabled: boolean
  loadRunSnapshot: () => void
  taskStatus: string | null
  taskState: string | null
  taskStage: string | null
  hasDiagnosticShots: boolean
  telemetryAbVariant: string | undefined
  t: TFunction
}

export function createRunPageDiagnosticRenderer(deps: CreateRunPageDiagnosticRendererDeps) {
  const {
    safeJsonStringify,
    copyText,
    renderRunAssetPreviewGrid,
    currentRunId,
    diagnosticOpen,
    closeDiagnosticDialog,
    diagnosticResult,
    diagnosticActionError,
    diagnosticActionLoading,
    diagnosticShots,
    persistedRunId,
    runSnapshotLoading,
    diagnosticPreflight,
    diagnosticProviderTrace,
    diagnosticSmartDispatchTrace,
    diagnosticProviderTraceByShotId,
    diagnosticProviderTraceSummary,
    diagnosticSmartDispatchTraceSummary,
    snapshotRuntimeConfig,
    snapshotTelemetrySummary,
    snapshotTelemetryCounters,
    snapshotTelemetry,
    diagnosticCameraDiagnostics,
    hasDiagnosticCameraSceneUris,
    diagnosticCameraSceneUris,
    diagnosticUploadDisabled,
    uploadShotAsset,
    promptAndRegenerateKeyframe,
    getDiagnosticStoryboardPrompt,
    restartGeneration,
    restartActionDisabled,
    loadRunSnapshot,
    taskStatus,
    taskState,
    taskStage,
    hasDiagnosticShots,
    telemetryAbVariant,
    t,
  } = deps

  const renderDiagnosticJson = (value: unknown) => (
    <DiagnosticJson value={value} safeJsonStringify={safeJsonStringify} />
  )

  const renderTitledDiagnosticJsonAccordion = ({
    title,
    value,
    marginTop = 1,
  }: {
    title: string
    value: unknown
    marginTop?: number
  }) => (
    <TitledDiagnosticJsonAccordion title={title} value={value} marginTop={marginTop} safeJsonStringify={safeJsonStringify} />
  )

  const renderDiagnosticFrame = (title: string, frame: unknown, kind: 'image' | 'video' = 'image') => (
    <DiagnosticFrameAccordion
      title={title}
      frame={frame}
      kind={kind}
      renderPreviewGrid={renderRunAssetPreviewGrid}
      renderDiagnosticJson={renderDiagnosticJson}
      copyText={copyText}
      safeJsonStringify={safeJsonStringify}
    />
  )

  const resolveShotDiagnosticAccordionStateLocal = (shot: DreamweaverDiagnosticShot) =>
    resolveShotDiagnosticAccordionState(shot, diagnosticResult, diagnosticProviderTraceByShotId)

  const renderShotDiagnosticUploadActions = (shotId: string) => (
    <ShotDiagnosticUploadActions shotId={shotId} uploadDisabled={diagnosticUploadDisabled} onUpload={uploadShotAsset} />
  )

  const renderShotDiagnosticPromptRegenerateActions = (shotId: string, sb: Record<string, unknown> | null) => (
    <ShotDiagnosticPromptRegenerateActions
      shotId={shotId}
      sb={sb}
      actionDisabled={diagnosticUploadDisabled}
      onPromptAndRegenerateKeyframe={promptAndRegenerateKeyframe}
      getDiagnosticStoryboardPrompt={getDiagnosticStoryboardPrompt}
    />
  )

  const renderShotProviderTraceSection = (shotProviderTrace: DreamweaverVideoProviderShotTrace | null) => (
    <ShotProviderTraceSection shotProviderTrace={shotProviderTrace} safeJsonStringify={safeJsonStringify} renderDiagnosticJson={renderDiagnosticJson} />
  )

  const renderShotDiagnosticAccordion = (shot: DreamweaverDiagnosticShot) => {
    const {
      shotId,
      frames: rawFrames,
      sb,
      desc,
      duration,
      shotAutoQC,
      shotAutoQCPass,
      shotAutoQCScore,
      shotProviderTrace,
      videoClip,
      hasVideoClip,
    } = resolveShotDiagnosticAccordionStateLocal(shot)
    const frames = rawFrames ?? { head: null, tail: null, mid: null }
    const hasHeadFrame = Boolean(frames.head)
    const hasTailFrame = Boolean(frames.tail)
    const hasMidFrame = Boolean(frames.mid)
    const isShadowed = Boolean(shotProviderTrace?.shadowed)
    const shotCopyPayload = buildShotDiagnosticCopyPayload({
      shotId,
      sb,
      frames,
      videoClip,
      shotProviderTrace,
      shotAutoQC,
    })

    return (
      <DreamweaverDiagnosticShotAccordion
        accordionKey={`diag:${shotId}`}
        summary={
          <DreamweaverDiagnosticShotSummary
            shotId={shotId}
            desc={desc}
            duration={duration}
            hasHeadFrame={hasHeadFrame}
            hasTailFrame={hasTailFrame}
            hasMidFrame={hasMidFrame}
            hasVideoClip={hasVideoClip}
            route={shotProviderTrace?.route}
            appliedProvider={shotProviderTrace?.applied_provider}
            shadowed={isShadowed}
            autoQCPass={shotAutoQCPass}
            autoQCScore={shotAutoQCScore}
          />
        }
        actions={
          <DreamweaverDiagnosticShotActions
            onCopy={() => copyText(safeJsonStringify(shotCopyPayload))}
            onCopyStoryboard={sb ? () => copyText(safeJsonStringify(sb)) : null}
            uploadActions={renderShotDiagnosticUploadActions(shotId)}
            promptRegenerateActions={renderShotDiagnosticPromptRegenerateActions(shotId, sb)}
            onRestartVideo={shotId ? () => void restartGeneration('VIDEO', [shotId]) : null}
            restartDisabled={restartActionDisabled}
          />
        }
        details={
          <DreamweaverDiagnosticShotDetails
            storyboardAccordion={renderTitledDiagnosticJsonAccordion({
              title: t('dreamweaverRun.storyboardTitle'),
              value: sb,
              marginTop: 0,
            })}
            providerTraceSection={renderShotProviderTraceSection(shotProviderTrace)}
            autoqcAccordion={renderTitledDiagnosticJsonAccordion({
              title: 'AutoQC',
              value: shotAutoQC,
            })}
            headFrame={renderDiagnosticFrame(t('dreamweaverRun.frameHead'), frames.head, 'image')}
            tailFrame={renderDiagnosticFrame(t('dreamweaverRun.frameTail'), frames.tail, 'image')}
            midFrame={renderDiagnosticFrame(t('dreamweaverRun.frameMid'), frames.mid, 'image')}
            videoFrame={renderDiagnosticFrame(t('dreamweaverRun.frameVideoClip'), videoClip, 'video')}
          />
        }
      />
    )
  }

  const renderDiagnosticPreflightSection = () => {
    if (!diagnosticPreflight) return null

    const videoConfig = resolvePreflightVideoConfig(diagnosticPreflight)
    const preflightErrorCount = diagnosticPreflight.errors.length
    const preflightWarningCount = diagnosticPreflight.warnings.length

    return (
      <DreamweaverDiagnosticPreflightSection
        allowed={diagnosticPreflight.allowed}
        errorCount={preflightErrorCount}
        warningCount={preflightWarningCount}
        {...videoConfig}
        errors={diagnosticPreflight.errors}
        warnings={diagnosticPreflight.warnings}
        onCopy={() => copyText(safeJsonStringify(diagnosticPreflight))}
        jsonAccordion={renderTitledDiagnosticJsonAccordion({ title: 'preflight', value: diagnosticPreflight })}
      />
    )
  }

  const renderDiagnosticProviderTraceSection = () => {
    if (!diagnosticProviderTrace) return null

    const traceSummary = resolveProviderTraceSummaryProps(diagnosticProviderTraceSummary)
    const providerFeatureFlags = resolveProviderTraceFeatureFlags(diagnosticProviderTrace)

    return (
      <DreamweaverDiagnosticProviderTraceSection
        providerMode={diagnosticProviderTrace.provider_mode}
        selectorMode={diagnosticProviderTrace.selector_mode}
        {...traceSummary}
        featureFlags={providerFeatureFlags}
        onCopy={() => copyText(safeJsonStringify(diagnosticProviderTrace))}
        jsonAccordion={renderTitledDiagnosticJsonAccordion({
          title: 'video_provider_trace',
          value: diagnosticProviderTrace,
        })}
      />
    )
  }

  const renderDiagnosticSmartDispatchSection = () => {
    if (!diagnosticSmartDispatchTrace) return null

    const { routing, prompt, attemptedModels } = resolveSmartDispatchTraceDetails(diagnosticSmartDispatchTrace)
    const summaryProps = resolveSmartDispatchSummaryProps(diagnosticSmartDispatchTraceSummary)
    const promptAccordion = prompt
      ? renderTitledDiagnosticJsonAccordion({ title: 'prompt_trace', value: prompt })
      : null
    const routingAccordion = routing
      ? renderTitledDiagnosticJsonAccordion({ title: 'routing_trace', value: routing })
      : null

    return (
      <DreamweaverDiagnosticSmartDispatchSection
        {...summaryProps}
        attemptedModels={attemptedModels}
        onCopy={() => copyText(safeJsonStringify(diagnosticSmartDispatchTrace))}
        promptAccordion={promptAccordion}
        routingAccordion={routingAccordion}
        jsonAccordion={renderTitledDiagnosticJsonAccordion({
          title: 'smart_dispatch_trace',
          value: diagnosticSmartDispatchTrace,
        })}
      />
    )
  }

  const renderDiagnosticTelemetrySection = () => {
    if (!snapshotTelemetrySummary) return null

    const telProps = resolveTelemetrySectionProps({
      summary: snapshotTelemetrySummary as Parameters<typeof resolveTelemetrySectionProps>[0]['summary'],
      abVariant: telemetryAbVariant,
      counters: snapshotTelemetryCounters as Parameters<typeof resolveTelemetrySectionProps>[0]['counters'],
    })

    return (
      <DreamweaverDiagnosticTelemetrySection
        {...telProps}
        jsonAccordion={renderTitledDiagnosticJsonAccordion({
          title: 'Telemetry JSON',
          value: snapshotTelemetry,
        })}
      />
    )
  }

  const buildCameraDiagnosticPayload = () =>
    buildCameraDiagnosticPayloadHelper(diagnosticCameraDiagnostics)

  const renderDiagnosticCameraDiagnosticsSection = () => {
    if (!hasCameraDiagnosticsData(diagnosticCameraDiagnostics)) {
      return null
    }
    const { cameraCount, sceneCount } = resolveCameraCounts(diagnosticCameraDiagnostics)
    const scenePreview = hasDiagnosticCameraSceneUris
      ? renderRunAssetPreviewGrid(
          t('dreamweaverRun.cameraScene'),
          diagnosticCameraSceneUris.slice(0, 12),
          'image',
        )
      : null

    return (
      <DreamweaverDiagnosticCameraDiagnosticsSection
        mode={diagnosticCameraDiagnostics.mode ?? undefined}
        cameraCount={cameraCount}
        sceneCount={sceneCount}
        onCopy={() => copyText(safeJsonStringify(buildCameraDiagnosticPayload()))}
        scenePreview={scenePreview}
        {...buildCameraAccordionProps(diagnosticCameraDiagnostics, (title: string, value: unknown) =>
          renderTitledDiagnosticJsonAccordion({ title, value }),
        )}
      />
    )
  }

  const buildRunDiagnosticPayload = () =>
    buildRunDiagnosticPayloadHelper({
      currentRunId,
      taskStatus,
      taskState,
      taskStage,
      diagnosticPreflight,
      diagnosticProviderTrace,
      diagnosticSmartDispatchTrace,
      snapshotRuntimeConfig,
      cameraDiagnosticsGeneration: diagnosticCameraDiagnostics.generation,
      cameraDiagnosticsCameraTree: diagnosticCameraDiagnostics.cameraTree,
      cameraDiagnosticsCameraStates: diagnosticCameraDiagnostics.cameraStates,
      cameraDiagnosticsCameraScenes: diagnosticCameraDiagnostics.cameraScenes,
      diagnosticResult,
    })

  const copyRunDiagnosticPayload = () => copyText(safeJsonStringify(buildRunDiagnosticPayload()))

  const renderDiagnosticDialog = () => {
    const dialogProps = buildDiagnosticDialogProps({
      currentRunId,
      diagnosticResult,
      diagnosticActionError,
      diagnosticActionLoading,
      diagnosticShots,
      persistedRunId,
      runSnapshotLoading,
      diagnosticPreflight,
      diagnosticProviderTrace,
      diagnosticSmartDispatchTrace,
    }, t)

    const diagnosticShotAccordions = hasDiagnosticShots ? diagnosticShots.map(renderShotDiagnosticAccordion) : null

    return (
      <DreamweaverRunDiagnosticDialog
        open={diagnosticOpen}
        onClose={closeDiagnosticDialog}
        {...dialogProps}
        onRefresh={loadRunSnapshot}
        onCopy={copyRunDiagnosticPayload}
        sections={
          <>
            {renderDiagnosticPreflightSection()}
            {renderDiagnosticProviderTraceSection()}
            {renderDiagnosticSmartDispatchSection()}
            {renderDiagnosticTelemetrySection()}
            {renderDiagnosticCameraDiagnosticsSection()}
          </>
        }
        shotAccordions={diagnosticShotAccordions}
      />
    )
  }

  return {
    renderDiagnosticDialog,
    copyRunDiagnosticPayload,
  }
}
