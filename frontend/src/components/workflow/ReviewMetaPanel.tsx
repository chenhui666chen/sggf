import { Alert, Box, Chip, Divider, Stack, Typography } from '@mui/material'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import GavelIcon from '@mui/icons-material/Gavel'
import SourceIcon from '@mui/icons-material/Source'
import { useTranslation } from 'react-i18next'

export interface ReviewMetaReport {
  requested_model_id?: string
  resolved_model_id?: string
  model_id?: string
  profile?: string
  status?: string
  input_was_clipped?: boolean
  cost?: number | string | null
  usage_metadata?: Record<string, unknown>
}

export interface ReviewStructuredSummary {
  consensus?: string[]
  divergence?: string[]
  final_suggestions?: string[]
  conclusion?: string
  source_models?: string[]
}

export interface ReviewMeta {
  multi_model?: boolean
  preset?: string | null
  chief_model?: string | null
  chief_model_reused_as_reviewer?: boolean
  reviewer_models?: string[]
  reviewer_profiles?: string[]
  per_model_reports?: ReviewMetaReport[]
  fallback_required?: boolean
  fallback_reason?: string | null
  structured_summary?: ReviewStructuredSummary
}

interface ReviewMetaPanelProps {
  reviewMeta?: ReviewMeta | null
  reviewText?: string
}

const PRESET_LABEL_KEYS: Record<string, string> = {
  balanced_3: 'workflow.reviewMeta.presetBalanced3',
  key_chapter_5: 'workflow.reviewMeta.presetKeyChapter5',
  deep_7: 'workflow.reviewMeta.presetDeep7',
}

function uniqueValues(values: Array<string | null | undefined>): string[] {
  return Array.from(
    new Set(
      values
        .map((value) => String(value || '').trim())
        .filter(Boolean),
    ),
  )
}

function getReportModelLabel(report: ReviewMetaReport): string {
  const requested = String(report.requested_model_id || report.model_id || '').trim()
  const resolved = String(report.resolved_model_id || report.model_id || requested).trim()
  if (requested && resolved && requested !== resolved) {
    return `${requested} -> ${resolved}`
  }
  return resolved || requested
}

export function extractSourceModels(reviewText: string = ''): string[] {
  const matches = Array.from(reviewText.matchAll(/source_models:\s*([^\]\n]+)/gi))
  return uniqueValues(
    matches.flatMap((match) => (
      match[1]
        .split(/[、,，/|]/)
        .map((item) => item.trim())
    )),
  )
}

export default function ReviewMetaPanel({ reviewMeta, reviewText = '' }: ReviewMetaPanelProps) {
  const { t } = useTranslation()
  const reports = reviewMeta?.per_model_reports || []
  const reviewerModels = uniqueValues([
    ...(reviewMeta?.reviewer_models || []),
    ...reports.map(getReportModelLabel),
  ])
  const reviewerProfiles = uniqueValues([
    ...(reviewMeta?.reviewer_profiles || []),
    ...reports.map((report) => report.profile),
  ])
  const sourceModels = uniqueValues(
    reviewMeta?.structured_summary?.source_models?.length
      ? reviewMeta.structured_summary.source_models
      : extractSourceModels(reviewText),
  )
  const hasConsensusSection = Boolean(
    reviewMeta?.structured_summary?.consensus?.length || /一致意见/.test(reviewText),
  )
  const hasDivergenceSection = Boolean(
    reviewMeta?.structured_summary?.divergence?.length || /分歧意见/.test(reviewText),
  )
  const shouldRender = Boolean(
    reviewMeta?.multi_model
    || reviewMeta?.fallback_required
    || reviewerModels.length
    || sourceModels.length,
  )

  if (!shouldRender) {
    return null
  }

  return (
    <Box
      sx={{
        mb: 1.5,
        p: 1.25,
        border: '1px solid',
        borderColor: 'divider',
        borderRadius: 1,
        bgcolor: 'background.paper',
      }}
    >
      <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ alignItems: 'center' }}>
        <Chip
          icon={<AccountTreeIcon />}
          label={reviewMeta?.multi_model ? t('workflow.reviewMeta.multiModel') : t('workflow.reviewMeta.singleFallback')}
          color={reviewMeta?.multi_model ? 'primary' : 'warning'}
          variant="outlined"
          size="small"
        />
        {reviewMeta?.preset ? (
          <Chip
            label={PRESET_LABEL_KEYS[reviewMeta.preset] ? t(PRESET_LABEL_KEYS[reviewMeta.preset]) : reviewMeta.preset}
            size="small"
            variant="outlined"
          />
        ) : null}
        {reviewMeta?.chief_model ? (
          <Chip icon={<GavelIcon />} label={t('workflow.reviewMeta.chiefModel', { model: reviewMeta.chief_model })} size="small" variant="outlined" />
        ) : null}
        {reviewMeta?.chief_model_reused_as_reviewer ? (
          <Chip label={t('workflow.reviewMeta.chiefReused')} color="warning" size="small" variant="outlined" />
        ) : null}
        {hasConsensusSection ? <Chip label={t('workflow.reviewMeta.consensus')} color="success" size="small" variant="outlined" /> : null}
        {hasDivergenceSection ? <Chip label={t('workflow.reviewMeta.divergence')} color="info" size="small" variant="outlined" /> : null}
      </Stack>

      {reviewMeta?.fallback_required || reviewMeta?.fallback_reason ? (
        <Alert severity="warning" sx={{ mt: 1 }}>
          {reviewMeta.fallback_reason || t('workflow.reviewMeta.fallbackDefaultReason')}
        </Alert>
      ) : null}

      {reviewerModels.length ? (
        <>
          <Divider sx={{ my: 1 }} />
          <Typography variant="caption" sx={{ display: 'block', mb: 0.75, color: 'text.secondary' }}>
            {t('workflow.reviewMeta.participantModels')}
          </Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
            {reviewerModels.map((model) => (
              <Chip key={model} label={model} size="small" />
            ))}
          </Stack>
        </>
      ) : null}

      {reviewerProfiles.length ? (
        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
          {reviewerProfiles.map((profile) => (
            <Chip key={profile} label={profile} size="small" variant="outlined" />
          ))}
        </Stack>
      ) : null}

      {sourceModels.length ? (
        <>
          <Divider sx={{ my: 1 }} />
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ alignItems: 'center' }}>
            <Chip icon={<SourceIcon />} label={t('workflow.reviewMeta.sourceModels')} size="small" variant="outlined" />
            {sourceModels.map((model) => (
              <Chip key={model} label={model} size="small" />
            ))}
          </Stack>
        </>
      ) : null}
    </Box>
  )
}
