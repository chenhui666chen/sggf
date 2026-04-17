import type { ReactNode } from 'react'

import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import RefreshIcon from '@mui/icons-material/Refresh'
import { Accordion, AccordionDetails, AccordionSummary, Button, Chip, Stack, Typography } from '@mui/material'

type DreamweaverDiagnosticShotSummaryProps = {
  shotId: string
  desc: string
  duration?: number | null
  hasHeadFrame: boolean
  hasTailFrame: boolean
  hasMidFrame: boolean
  hasVideoClip: boolean
  route?: string | null
  appliedProvider?: string | null
  shadowed?: boolean
  autoQCPass?: boolean | null
  autoQCScore?: number | null
}

export function DreamweaverDiagnosticShotSummary({
  shotId,
  desc,
  duration,
  hasHeadFrame,
  hasTailFrame,
  hasMidFrame,
  hasVideoClip,
  route,
  appliedProvider,
  shadowed,
  autoQCPass,
  autoQCScore,
}: DreamweaverDiagnosticShotSummaryProps) {
  return (
    <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" sx={{ width: '100%' }}>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, fontFamily: 'monospace' }}>
        {shotId || '-'}
      </Typography>
      {desc && (
        <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 520, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {desc}
        </Typography>
      )}
      {typeof duration === 'number' && Number.isFinite(duration) && <Chip size="small" label={`${duration.toFixed(1)}s`} />}
      {hasHeadFrame && <Chip size="small" label="head" color="success" variant="outlined" />}
      {hasTailFrame && <Chip size="small" label="tail" color="success" variant="outlined" />}
      {hasMidFrame && <Chip size="small" label="mid" color="success" variant="outlined" />}
      {hasVideoClip && <Chip size="small" label="clip" color="info" variant="outlined" />}
      {route && <Chip size="small" variant="outlined" color="info" label={`route: ${route}`} />}
      {appliedProvider && <Chip size="small" variant="outlined" label={`applied: ${appliedProvider}`} />}
      {shadowed && <Chip size="small" color="warning" label="shadow" />}
      {autoQCPass != null && (
        <Chip
          size="small"
          label={`AutoQC: ${autoQCPass ? 'pass' : 'fail'}${typeof autoQCScore === 'number' ? ` (${autoQCScore.toFixed(2)})` : ''}`}
          color={autoQCPass ? 'success' : 'warning'}
        />
      )}
    </Stack>
  )
}

type DreamweaverDiagnosticShotActionsProps = {
  onCopy: () => void
  onCopyStoryboard?: (() => void) | null
  uploadActions?: ReactNode
  promptRegenerateActions?: ReactNode
  onRestartVideo?: (() => void) | null
  restartDisabled: boolean
}

export function DreamweaverDiagnosticShotActions({
  onCopy,
  onCopyStoryboard,
  uploadActions,
  promptRegenerateActions,
  onRestartVideo,
  restartDisabled,
}: DreamweaverDiagnosticShotActionsProps) {
  return (
    <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
      <Button size="small" variant="outlined" startIcon={<ContentCopyIcon fontSize="small" />} onClick={onCopy}>
        复制镜头诊断
      </Button>
      {onCopyStoryboard && (
        <Button size="small" variant="text" onClick={onCopyStoryboard}>
          复制分镜
        </Button>
      )}
      {uploadActions ?? null}
      {promptRegenerateActions ?? null}
      {onRestartVideo && (
        <Button
          size="small"
          variant="contained"
          startIcon={<RefreshIcon fontSize="small" />}
          onClick={onRestartVideo}
          disabled={restartDisabled}
        >
          重跑该镜头视频
        </Button>
      )}
    </Stack>
  )
}

type DreamweaverDiagnosticShotProviderTraceSectionProps = {
  reason?: string | null
  requestedProviderMode?: string | null
  recommendedProvider?: string | null
  appliedProvider?: string | null
  selectorMode?: string | null
  metadataText?: string | null
  jsonContent: ReactNode
}

export function DreamweaverDiagnosticShotProviderTraceSection({
  reason,
  requestedProviderMode,
  recommendedProvider,
  appliedProvider,
  selectorMode,
  metadataText,
  jsonContent,
}: DreamweaverDiagnosticShotProviderTraceSectionProps) {
  return (
    <Accordion sx={{ mt: 1 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            Provider 路由
          </Typography>
          {reason && <Chip size="small" variant="outlined" label={`reason: ${reason}`} />}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center" sx={{ mb: 1 }}>
          {requestedProviderMode && <Chip size="small" variant="outlined" label={`requested: ${requestedProviderMode}`} />}
          {recommendedProvider && <Chip size="small" variant="outlined" label={`recommended: ${recommendedProvider}`} />}
          {appliedProvider && <Chip size="small" variant="outlined" label={`applied: ${appliedProvider}`} />}
          {selectorMode && <Chip size="small" variant="outlined" label={`selector: ${selectorMode}`} />}
        </Stack>
        {metadataText && (
          <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1 }}>
            metadata: {metadataText}
          </Typography>
        )}
        {jsonContent}
      </AccordionDetails>
    </Accordion>
  )
}

type DreamweaverDiagnosticShotDetailsProps = {
  storyboardAccordion?: ReactNode
  providerTraceSection?: ReactNode
  autoqcAccordion?: ReactNode
  headFrame?: ReactNode
  tailFrame?: ReactNode
  midFrame?: ReactNode
  videoFrame?: ReactNode
}

export function DreamweaverDiagnosticShotDetails({
  storyboardAccordion,
  providerTraceSection,
  autoqcAccordion,
  headFrame,
  tailFrame,
  midFrame,
  videoFrame,
}: DreamweaverDiagnosticShotDetailsProps) {
  return (
    <>
      {storyboardAccordion ?? null}
      {providerTraceSection ?? null}
      {autoqcAccordion ?? null}
      {headFrame ?? null}
      {tailFrame ?? null}
      {midFrame ?? null}
      {videoFrame ?? null}
    </>
  )
}

type DreamweaverDiagnosticShotAccordionProps = {
  accordionKey: string
  summary: ReactNode
  actions: ReactNode
  details: ReactNode
}

export function DreamweaverDiagnosticShotAccordion({
  accordionKey,
  summary,
  actions,
  details,
}: DreamweaverDiagnosticShotAccordionProps) {
  return (
    <Accordion key={accordionKey} sx={{ mb: 1 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>{summary}</AccordionSummary>
      <AccordionDetails>
        {actions}
        {details}
      </AccordionDetails>
    </Accordion>
  )
}
