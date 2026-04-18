import type { ReactNode } from 'react'

import BugReportIcon from '@mui/icons-material/BugReport'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera'
import WarningIcon from '@mui/icons-material/Warning'
import { Alert, Accordion, AccordionDetails, AccordionSummary, Button, Chip, Stack, Typography } from '@mui/material'

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
