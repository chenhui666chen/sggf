import type { ReactNode } from 'react'

import BugReportIcon from '@mui/icons-material/BugReport'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera'
import WarningIcon from '@mui/icons-material/Warning'
import { Alert, Accordion, AccordionDetails, AccordionSummary, Box, Button, Chip, Stack, Typography } from '@mui/material'
import { DreamweaverDiagnosticShotProviderTraceSection } from './diagnosticShotViews'

type DreamweaverDiagnosticIssue = {
  code: string
  message: string
}

type DreamweaverDiagnosticRouteFeatureFlags = {
  allowKlingOmni?: boolean | null
  enableKlingVideoProvider?: boolean | null
  allowSubjectBridge?: boolean | null
}

type DreamweaverDiagnosticChipItem = {
  key: string
  label: string
}

function DreamweaverDiagnosticRouteFeatureChips({
  allowKlingOmni,
  enableKlingVideoProvider,
  allowSubjectBridge,
}: DreamweaverDiagnosticRouteFeatureFlags) {
  return (
    <>
      {typeof allowKlingOmni === 'boolean' && (
        <Chip size="small" variant="outlined" label={`allow_kling_omni: ${allowKlingOmni ? 'on' : 'off'}`} />
      )}
      {typeof enableKlingVideoProvider === 'boolean' && (
        <Chip size="small" variant="outlined" label={`kling_executor: ${enableKlingVideoProvider ? 'on' : 'off'}`} />
      )}
      {typeof allowSubjectBridge === 'boolean' && (
        <Chip size="small" variant="outlined" label={`subject_bridge: ${allowSubjectBridge ? 'on' : 'off'}`} />
      )}
    </>
  )
}

function DreamweaverDiagnosticIssueAlerts({
  issues,
  severity,
  keyPrefix,
}: {
  issues: DreamweaverDiagnosticIssue[]
  severity: 'error' | 'warning'
  keyPrefix: string
}) {
  return (
    <>
      {issues.map((issue) => (
        <Alert key={`${keyPrefix}:${issue.code}`} severity={severity} sx={{ mb: 1 }}>
          {issue.code}: {issue.message}
        </Alert>
      ))}
    </>
  )
}

function DreamweaverDiagnosticOutlinedChipStack({
  items,
  marginTop = 0,
}: {
  items: DreamweaverDiagnosticChipItem[]
  marginTop?: number
}) {
  if (items.length === 0) return null

  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={marginTop > 0 ? { mt: marginTop } : undefined}>
      {items.map((item) => (
        <Chip key={item.key} size="small" variant="outlined" label={item.label} />
      ))}
    </Stack>
  )
}

type DreamweaverDiagnosticPreflightSectionProps = {
  allowed: boolean
  errorCount: number
  warningCount: number
  providerMode?: string | null
  selectorMode?: string | null
  featureFlags?: DreamweaverDiagnosticRouteFeatureFlags
  errors: DreamweaverDiagnosticIssue[]
  warnings: DreamweaverDiagnosticIssue[]
  onCopy: () => void
  jsonAccordion?: ReactNode
}

export function DreamweaverDiagnosticPreflightSection({
  allowed,
  errorCount,
  warningCount,
  providerMode,
  selectorMode,
  featureFlags,
  errors,
  warnings,
  onCopy,
  jsonAccordion,
}: DreamweaverDiagnosticPreflightSectionProps) {
  return (
    <Accordion defaultExpanded={!allowed} sx={{ mb: 1 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <WarningIcon color={allowed ? 'warning' : 'error'} fontSize="small" />
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            运行预检
          </Typography>
          <Chip size="small" color={allowed ? 'success' : 'error'} label={allowed ? 'allowed' : 'blocked'} />
          <Chip size="small" label={`errors: ${errorCount}`} />
          <Chip size="small" label={`warnings: ${warningCount}`} />
          {providerMode && <Chip size="small" variant="outlined" label={`provider: ${providerMode}`} />}
          {selectorMode && <Chip size="small" variant="outlined" label={`selector: ${selectorMode}`} />}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
          <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={onCopy}>
            复制 Preflight
          </Button>
          <DreamweaverDiagnosticRouteFeatureChips {...featureFlags} />
        </Stack>

        <DreamweaverDiagnosticIssueAlerts issues={errors} severity="error" keyPrefix="preflight:error" />
        <DreamweaverDiagnosticIssueAlerts issues={warnings} severity="warning" keyPrefix="preflight:warning" />
        {jsonAccordion ?? null}
      </AccordionDetails>
    </Accordion>
  )
}

type DreamweaverDiagnosticProviderTraceSectionProps = {
  providerMode?: string | null
  selectorMode?: string | null
  totalShots?: number | null
  recommendedKling?: number | null
  appliedKling?: number | null
  shadowed?: number | null
  featureFlags?: DreamweaverDiagnosticRouteFeatureFlags
  onCopy: () => void
  jsonAccordion?: ReactNode
}

export function DreamweaverDiagnosticProviderTraceSection({
  providerMode,
  selectorMode,
  totalShots,
  recommendedKling,
  appliedKling,
  shadowed,
  featureFlags,
  onCopy,
  jsonAccordion,
}: DreamweaverDiagnosticProviderTraceSectionProps) {
  return (
    <Accordion defaultExpanded sx={{ mb: 1 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <BugReportIcon color="primary" fontSize="small" />
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            Provider 路由
          </Typography>
          {providerMode && <Chip size="small" variant="outlined" label={`provider_mode: ${providerMode}`} />}
          {selectorMode && <Chip size="small" variant="outlined" label={`selector_mode: ${selectorMode}`} />}
          {typeof totalShots === 'number' && <Chip size="small" label={`shots: ${totalShots}`} />}
          {typeof recommendedKling === 'number' && <Chip size="small" label={`recommend_kling: ${recommendedKling}`} />}
          {typeof appliedKling === 'number' && <Chip size="small" label={`apply_kling: ${appliedKling}`} />}
          {typeof shadowed === 'number' && shadowed > 0 && <Chip size="small" color="warning" label={`shadow: ${shadowed}`} />}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
          <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={onCopy}>
            复制 Provider Trace
          </Button>
          <DreamweaverDiagnosticRouteFeatureChips {...featureFlags} />
        </Stack>
        {jsonAccordion ?? null}
      </AccordionDetails>
    </Accordion>
  )
}

type DreamweaverDiagnosticSmartDispatchSectionProps = {
  stage?: string | null
  strategy?: string | null
  intentModality?: string | null
  intentConfidence?: number | null
  parseErrorCount?: number | null
  selectedModel?: string | null
  resolvedModel?: string | null
  fallbackCount?: number | null
  candidateCount?: number | null
  attemptedCount?: number | null
  promptChanged?: boolean | null
  timedOut?: boolean | null
  attemptedModels?: string[]
  phaseCount?: number | null
  phaseStages?: string[]
  onCopy: () => void
  jsonAccordion?: ReactNode
  promptAccordion?: ReactNode
  routingAccordion?: ReactNode
}

export function DreamweaverDiagnosticSmartDispatchSection({
  stage,
  strategy,
  intentModality,
  intentConfidence,
  parseErrorCount,
  selectedModel,
  resolvedModel,
  fallbackCount,
  candidateCount,
  attemptedCount,
  promptChanged,
  timedOut,
  attemptedModels,
  phaseCount,
  phaseStages,
  onCopy,
  jsonAccordion,
  promptAccordion,
  routingAccordion,
}: DreamweaverDiagnosticSmartDispatchSectionProps) {
  const attemptedChips = Array.isArray(attemptedModels)
    ? attemptedModels
        .map((item) => String(item || '').trim())
        .filter(Boolean)
        .slice(0, 8)
        .map((item) => ({ key: `attempt:${item}`, label: `attempt: ${item}` }))
    : []
  const phaseChips = Array.isArray(phaseStages)
    ? phaseStages
        .map((item) => String(item || '').trim())
        .filter(Boolean)
        .slice(0, 8)
        .map((item) => ({ key: `phase:${item}`, label: `phase: ${item}` }))
    : []

  return (
    <Accordion defaultExpanded sx={{ mb: 1 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <BugReportIcon color="primary" fontSize="small" />
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            智能调度
          </Typography>
          {stage && <Chip size="small" variant="outlined" label={`stage: ${stage}`} />}
          {strategy && <Chip size="small" variant="outlined" label={`strategy: ${strategy}`} />}
          {intentModality && <Chip size="small" variant="outlined" label={`modality: ${intentModality}`} />}
          {typeof intentConfidence === 'number' && <Chip size="small" label={`confidence: ${intentConfidence.toFixed(2)}`} />}
          {typeof parseErrorCount === 'number' && <Chip size="small" label={`parse_errors: ${parseErrorCount}`} color={parseErrorCount > 0 ? 'warning' : 'default'} />}
          {selectedModel && <Chip size="small" label={`selected: ${selectedModel}`} />}
          {resolvedModel && <Chip size="small" label={`resolved: ${resolvedModel}`} color="success" />}
          {typeof fallbackCount === 'number' && <Chip size="small" label={`fallbacks: ${fallbackCount}`} />}
          {typeof candidateCount === 'number' && <Chip size="small" label={`candidates: ${candidateCount}`} />}
          {typeof attemptedCount === 'number' && <Chip size="small" label={`attempts: ${attemptedCount}`} />}
          {typeof phaseCount === 'number' && phaseCount > 0 && <Chip size="small" label={`phases: ${phaseCount}`} />}
          {typeof promptChanged === 'boolean' && (
            <Chip size="small" color={promptChanged ? 'warning' : 'default'} label={`prompt: ${promptChanged ? 'changed' : 'same'}`} />
          )}
          {typeof timedOut === 'boolean' && timedOut && <Chip size="small" color="error" label="timed_out" />}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
          <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={onCopy}>
            复制调度 Trace
          </Button>
        </Stack>
        <DreamweaverDiagnosticOutlinedChipStack items={attemptedChips} />
        <DreamweaverDiagnosticOutlinedChipStack items={phaseChips} marginTop={attemptedChips.length > 0 ? 1 : 0} />
        {promptAccordion ?? null}
        {routingAccordion ?? null}
        {jsonAccordion ?? null}
      </AccordionDetails>
    </Accordion>
  )
}

type DreamweaverDiagnosticTelemetrySectionProps = {
  totalSeconds?: number | null
  terminalState?: string | null
  reworkCount?: number | null
  abVariant?: string | null
  stageEntries: DreamweaverDiagnosticChipItem[]
  reworkChips: DreamweaverDiagnosticChipItem[]
  counterChips: DreamweaverDiagnosticChipItem[]
  jsonAccordion?: ReactNode
}

export function DreamweaverDiagnosticTelemetrySection({
  totalSeconds,
  terminalState,
  reworkCount,
  abVariant,
  stageEntries,
  reworkChips,
  counterChips,
  jsonAccordion,
}: DreamweaverDiagnosticTelemetrySectionProps) {
  return (
    <Accordion defaultExpanded sx={{ mb: 1 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          运行耗时（Telemetry）
        </Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
          {typeof totalSeconds === 'number' && <Chip size="small" label={`总耗时: ${totalSeconds.toFixed(1)}s`} />}
          {terminalState && <Chip size="small" label={`terminal: ${terminalState}`} variant="outlined" />}
          {typeof reworkCount === 'number' && <Chip size="small" label={`返工: ${reworkCount}`} variant="outlined" />}
          {abVariant && <Chip size="small" label={`variant: ${abVariant}`} variant="outlined" />}
        </Stack>

        <DreamweaverDiagnosticOutlinedChipStack items={stageEntries} />
        <DreamweaverDiagnosticOutlinedChipStack items={reworkChips} marginTop={1} />
        <DreamweaverDiagnosticOutlinedChipStack items={counterChips} marginTop={1} />
        {jsonAccordion ?? null}
      </AccordionDetails>
    </Accordion>
  )
}

type DreamweaverDiagnosticCameraDiagnosticsSectionProps = {
  mode?: string | null
  cameraCount?: number | null
  sceneCount?: number | null
  onCopy: () => void
  scenePreview?: ReactNode
  generationAccordion?: ReactNode
  cameraTreeAccordion?: ReactNode
  cameraStatesAccordion?: ReactNode
  cameraScenesAccordion?: ReactNode
}

export function DreamweaverDiagnosticCameraDiagnosticsSection({
  mode,
  cameraCount,
  sceneCount,
  onCopy,
  scenePreview,
  generationAccordion,
  cameraTreeAccordion,
  cameraStatesAccordion,
  cameraScenesAccordion,
}: DreamweaverDiagnosticCameraDiagnosticsSectionProps) {
  return (
    <Accordion sx={{ mb: 1 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <PhotoCameraIcon color="primary" fontSize="small" />
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            相机依赖（Camera Tree）
          </Typography>
          {mode && <Chip size="small" label={`mode: ${mode}`} variant="outlined" />}
          {typeof cameraCount === 'number' && <Chip size="small" label={`cameras: ${cameraCount}`} />}
          {typeof sceneCount === 'number' && <Chip size="small" label={`scenes: ${sceneCount}`} />}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
          <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={onCopy}>
            复制 Camera 诊断
          </Button>
        </Stack>
        {scenePreview ?? null}
        {generationAccordion ?? null}
        {cameraTreeAccordion ?? null}
        {cameraStatesAccordion ?? null}
        {cameraScenesAccordion ?? null}
      </AccordionDetails>
    </Accordion>
  )
}

export interface DiagnosticFrameAccordionProps {
  title: string
  frame: unknown
  kind?: 'image' | 'video'
  renderPreviewGrid: (title: string, uris: string[], kind: 'image' | 'video') => ReactNode
  renderDiagnosticJson: (value: unknown) => ReactNode
  copyText: (text: string) => void
  safeJsonStringify: (value: unknown) => string
}

export function DiagnosticFrameAccordion({
  title,
  frame,
  kind = 'image',
  renderPreviewGrid,
  renderDiagnosticJson,
  copyText,
  safeJsonStringify,
}: DiagnosticFrameAccordionProps) {
  if (!frame || typeof frame !== 'object') return null
  const frameRecord = frame as Record<string, unknown>
  const uri = String(frameRecord.path || '').trim()
  if (!uri) return null
  const meta =
    frameRecord.meta && typeof frameRecord.meta === 'object' && !Array.isArray(frameRecord.meta)
      ? (frameRecord.meta as Record<string, unknown>)
      : {}
  const decision =
    meta.decision && typeof meta.decision === 'object' && !Array.isArray(meta.decision)
      ? (meta.decision as Record<string, unknown>)
      : null
  const via = typeof meta.via === 'string' ? meta.via : ''
  const mode = decision && typeof decision.mode === 'string' ? String(decision.mode) : ''
  const reason = decision && typeof decision.reason === 'string' ? String(decision.reason) : ''
  const selector = typeof meta.selector === 'string' ? meta.selector : ''
  const candidateCount = typeof meta.candidate_count === 'number' ? meta.candidate_count : null
  const selected = typeof meta.selected === 'number' ? meta.selected : null
  const selectedSeed = typeof meta.selected_seed === 'number' ? meta.selected_seed : null
  const candidates = Array.isArray(meta.candidates) ? meta.candidates : []
  const hasCandidates = candidates.some((c) => typeof c === 'string' && String(c).trim())

  return (
    <Accordion sx={{ mt: 1 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ width: '100%' }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
            {title}
          </Typography>
          {via && <Chip size="small" label={`via: ${via}`} />}
          {mode && <Chip size="small" label={`mode: ${mode}`} />}
          {reason && (
            <Chip size="small" label={`reason: ${reason}`} variant="outlined" sx={{ maxWidth: 420 }} />
          )}
          {selector && <Chip size="small" label={`selector: ${selector}`} />}
          {candidateCount != null && <Chip size="small" label={`cands: ${candidateCount}`} />}
          {selected != null && <Chip size="small" label={`selected: ${selected}`} color="primary" />}
          {selectedSeed != null && <Chip size="small" label={`seed: ${selectedSeed}`} />}
          {hasCandidates && <Chip size="small" label="keep_candidates" color="success" variant="outlined" />}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
          <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={() => copyText(safeJsonStringify(meta))}>
            复制 meta
          </Button>
          <Button size="small" variant="text" onClick={() => copyText(uri)}>
            复制路径
          </Button>
        </Stack>

        {renderPreviewGrid('预览', [uri], kind)}

        {hasCandidates &&
          renderPreviewGrid(
            '候选图（keep_candidates）',
            candidates
              .map((c) => (typeof c === 'string' ? c.trim() : ''))
              .filter(Boolean)
              .slice(0, 12),
            'image',
          )}

        <Typography variant="subtitle2" sx={{ fontWeight: 600, mt: 1, mb: 0.5 }}>
          meta
        </Typography>
        {renderDiagnosticJson(meta)}
      </AccordionDetails>
    </Accordion>
  )
}

export function DebugJsonBox({ value, maxHeight, safeJsonStringify }: { value: unknown; maxHeight?: number; safeJsonStringify: (v: unknown) => string }) {
  return (
    <Box
      sx={{
        whiteSpace: 'pre-wrap',
        fontFamily: 'monospace',
        fontSize: 12,
        bgcolor: '#fafafa',
        border: '1px solid #eee',
        borderRadius: 2,
        p: 1.5,
        ...(typeof maxHeight === 'number'
          ? {
              maxHeight,
              overflow: 'auto',
            }
          : {}),
      }}
    >
      {safeJsonStringify(value)}
    </Box>
  )
}

export function DiagnosticJson({ value, safeJsonStringify }: { value: unknown; safeJsonStringify: (v: unknown) => string }) {
  return <DebugJsonBox value={value} maxHeight={320} safeJsonStringify={safeJsonStringify} />
}

export function TitledDiagnosticJsonAccordion({
  title,
  value,
  marginTop = 1,
  safeJsonStringify,
}: {
  title: string
  value: unknown
  marginTop?: number
  safeJsonStringify: (v: unknown) => string
}) {
  if (!value) return null
  return (
    <Accordion sx={marginTop > 0 ? { mt: marginTop } : undefined}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      </AccordionSummary>
      <AccordionDetails><DiagnosticJson value={value} safeJsonStringify={safeJsonStringify} /></AccordionDetails>
    </Accordion>
  )
}

export interface DiagnosticUploadButtonProps {
  label: string
  accept: string
  shotId: string
  assetRole: 'head_frame' | 'tail_frame' | 'mid_frame' | 'video_clip'
  disabled: boolean
  onUpload: (shotId: string, assetRole: 'head_frame' | 'tail_frame' | 'mid_frame' | 'video_clip', file: File) => void
}

export function DiagnosticUploadButton({
  label,
  accept,
  shotId,
  assetRole,
  disabled,
  onUpload,
}: DiagnosticUploadButtonProps) {
  return (
    <Button
      size="small"
      variant="outlined"
      component="label"
      disabled={disabled}
    >
      {label}
      <input
        hidden
        type="file"
        accept={accept}
        onChange={(e) => {
          const f = e.target.files && e.target.files[0]
          e.target.value = ''
          if (!f) return
          onUpload(shotId, assetRole, f)
        }}
      />
    </Button>
  )
}

export interface ShotDiagnosticUploadActionsProps {
  shotId: string
  uploadDisabled: boolean
  onUpload: (shotId: string, assetRole: 'head_frame' | 'tail_frame' | 'mid_frame' | 'video_clip', file: File) => void
}

export function ShotDiagnosticUploadActions({ shotId, uploadDisabled, onUpload }: ShotDiagnosticUploadActionsProps) {
  if (!shotId) return null
  return (
    <>
      <DiagnosticUploadButton label="上传首帧" accept="image/png" shotId={shotId} assetRole="head_frame" disabled={uploadDisabled} onUpload={onUpload} />
      <DiagnosticUploadButton label="上传尾帧" accept="image/png" shotId={shotId} assetRole="tail_frame" disabled={uploadDisabled} onUpload={onUpload} />
      <DiagnosticUploadButton label="上传中间帧" accept="image/png" shotId={shotId} assetRole="mid_frame" disabled={uploadDisabled} onUpload={onUpload} />
      <DiagnosticUploadButton label="上传镜头视频" accept="video/mp4" shotId={shotId} assetRole="video_clip" disabled={uploadDisabled} onUpload={onUpload} />
    </>
  )
}

export interface ShotDiagnosticPromptRegenerateActionsProps {
  shotId: string
  sb: Record<string, unknown> | null
  actionDisabled: boolean
  onPromptAndRegenerateKeyframe: (shotId: string, frameType: 'head' | 'tail', prompt: string) => void
  getDiagnosticStoryboardPrompt: (sb: Record<string, unknown> | null, frameRole: 'head_frame' | 'tail_frame') => string
}

export function ShotDiagnosticPromptRegenerateActions({
  shotId,
  sb,
  actionDisabled,
  onPromptAndRegenerateKeyframe,
  getDiagnosticStoryboardPrompt,
}: ShotDiagnosticPromptRegenerateActionsProps) {
  if (!shotId) return null
  return (
    <>
      <Button
        size="small"
        variant="contained"
        onClick={() => void onPromptAndRegenerateKeyframe(shotId, 'head', getDiagnosticStoryboardPrompt(sb, 'head_frame'))}
        disabled={actionDisabled}
      >
        改首帧提示词并重跑
      </Button>
      <Button
        size="small"
        variant="contained"
        onClick={() => void onPromptAndRegenerateKeyframe(shotId, 'tail', getDiagnosticStoryboardPrompt(sb, 'tail_frame'))}
        disabled={actionDisabled}
      >
        改尾帧提示词并重跑
      </Button>
    </>
  )
}

export interface ShotProviderTraceSectionProps {
  shotProviderTrace: {
    reason?: string | null
    requested_provider_mode?: string | null
    recommended_provider?: string | null
    applied_provider?: string | null
    selector_mode?: string | null
    metadata?: unknown
  } | null
  safeJsonStringify: (v: unknown) => string
  renderDiagnosticJson: (value: unknown) => ReactNode
}

export function ShotProviderTraceSection({
  shotProviderTrace,
  safeJsonStringify,
  renderDiagnosticJson,
}: ShotProviderTraceSectionProps) {
  if (!shotProviderTrace) return null
  return (
    <DreamweaverDiagnosticShotProviderTraceSection
      reason={shotProviderTrace.reason}
      requestedProviderMode={shotProviderTrace.requested_provider_mode}
      recommendedProvider={shotProviderTrace.recommended_provider}
      appliedProvider={shotProviderTrace.applied_provider}
      selectorMode={shotProviderTrace.selector_mode}
      metadataText={shotProviderTrace.metadata ? safeJsonStringify(shotProviderTrace.metadata) : null}
      jsonContent={renderDiagnosticJson(shotProviderTrace)}
    />
  )
}

export interface SafetyBlockedShotItem {
  shotId: string
  shotIndex?: number
  roles: string[]
  errorSample: string
}

export interface SafetyBlockedAlertProps {
  shots: SafetyBlockedShotItem[]
  onOpenShot: (shotId: string) => void
}

export function SafetyBlockedAlert({ shots, onOpenShot }: SafetyBlockedAlertProps) {
  if (!shots.length) return null
  return (
    <Alert severity="warning" sx={{ mb: 1 }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
        检测到内容安全拦截：部分镜头产物被安全过滤
      </Typography>
      <Typography variant="body2" color="text.secondary">
        请点击下方镜头编号查看/修改提示词后重试生成。
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" sx={{ mt: 1 }}>
        {shots.map((item) => {
          const label = item.shotIndex != null ? `#${item.shotIndex} ${item.shotId}` : item.shotId
          return (
            <Button key={item.shotId} size="small" variant="outlined" onClick={() => onOpenShot(item.shotId)}>
              {label}
            </Button>
          )
        })}
      </Stack>
      {shots[0]?.errorSample && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          示例错误：{shots[0].errorSample}
        </Typography>
      )}
    </Alert>
  )
}

export interface DebugAccordionProps {
  title: string
  value: unknown
  marginTop?: number
  marginBottom?: number
  safeJsonStringify: (v: unknown) => string
}

export function DebugAccordion({ title, value, marginTop = 0, marginBottom = 0, safeJsonStringify }: DebugAccordionProps) {
  return (
    <Accordion
      sx={{
        ...(marginTop > 0 ? { mt: marginTop } : {}),
        ...(marginBottom > 0 ? { mb: marginBottom } : {}),
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      </AccordionSummary>
      <AccordionDetails>
        <DebugJsonBox value={value} safeJsonStringify={safeJsonStringify} />
      </AccordionDetails>
    </Accordion>
  )
}
