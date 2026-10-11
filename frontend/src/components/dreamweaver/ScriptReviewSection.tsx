import { useMemo } from 'react'
import {
  Alert,
  Box,
  Chip,
  Divider,
  Grid,
  IconButton,
  LinearProgress,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import { getStageDisplayName } from '@/utils/timeEstimate'
import { PREVIEW_STEPS_LABELS, stageToPreviewStep } from '@/constants/dreamweaver'
import type { RunResult, DreamweaverAssetPlanItem } from '@/types/dreamweaver'
import { useTranslation } from 'react-i18next'

interface ScriptReviewSectionProps {
  result: RunResult | null
  scriptText: string
  scriptSavedText: string
  scriptApproved: boolean
  scriptRequiresReview: boolean
  scriptEntities: Record<string, unknown> | null
  scriptGeneration: { mode?: string; model?: string | null; error?: string | null } | null
  scriptLoading: boolean
  scriptError: string | null
  promptReviewLoading: boolean
  promptReviewError: string | null
  promptReviewShowAll: boolean
  shotPromptExpanded: Record<string, boolean>
  promptEditOpen: boolean
  promptEditShot: unknown | null
  promptEditHead: string
  promptEditTail: string
  promptEditVideo: string
  promptEditSaving: boolean
  promptEditError: string | null
  characterAssetPlanItems: DreamweaverAssetPlanItem[]
  sceneAssetPlanItems: DreamweaverAssetPlanItem[]
  propAssetPlanItems: DreamweaverAssetPlanItem[]
  onScriptTextChange: (text: string) => void
  onSaveScript: () => void
  onApproveScript: () => void
  onTogglePromptExpand: (shotId: string) => void
  onOpenPromptEdit: (shot: unknown) => void
  onClosePromptEdit: () => void
  onPromptEditFieldChange: (field: 'head' | 'tail' | 'video', value: string) => void
  onSavePromptEdit: () => void
  onToggleShowAll: () => void
}

export function ScriptReviewSection({
  result,
  scriptText,
  scriptSavedText,
  scriptApproved,
  scriptRequiresReview: _scriptRequiresReview,
  scriptEntities: _scriptEntities,
  scriptGeneration: _scriptGeneration,
  scriptLoading,
  scriptError,
  promptReviewLoading: _promptReviewLoading,
  promptReviewError: _promptReviewError,
  promptReviewShowAll,
  shotPromptExpanded: _shotPromptExpanded,
  promptEditOpen: _promptEditOpen,
  promptEditShot: _promptEditShot,
  promptEditHead: _promptEditHead,
  promptEditTail: _promptEditTail,
  promptEditVideo: _promptEditVideo,
  promptEditSaving: _promptEditSaving,
  promptEditError: _promptEditError,
  characterAssetPlanItems,
  sceneAssetPlanItems,
  propAssetPlanItems,
  onScriptTextChange: _onScriptTextChange,
  onSaveScript: _onSaveScript,
  onApproveScript: _onApproveScript,
  onTogglePromptExpand: _onTogglePromptExpand,
  onOpenPromptEdit: _onOpenPromptEdit,
  onClosePromptEdit: _onClosePromptEdit,
  onPromptEditFieldChange: _onPromptEditFieldChange,
  onSavePromptEdit: _onSavePromptEdit,
  onToggleShowAll,
}: ScriptReviewSectionProps) {
  const { t } = useTranslation()
  const scriptDirty = useMemo(() => scriptText !== scriptSavedText, [scriptText, scriptSavedText])

  const previewStep = useMemo(() => stageToPreviewStep(result?.stage), [result?.stage])

  const renderScriptBlock = () => {
    if (scriptLoading) {
      return (
        <Box sx={{ p: 2 }}>
          <LinearProgress />
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {t('dreamweaverScriptReview.loadingScript')}
          </Typography>
        </Box>
      )
    }

    if (scriptError) {
      return (
        <Alert severity="error" sx={{ mb: 2 }}>
          {scriptError}
        </Alert>
      )
    }

    if (!scriptText) {
      return (
        <Typography variant="body2" color="text.secondary">
          {t('dreamweaverScriptReview.noScriptInfo')}
        </Typography>
      )
    }

    return (
      <Box>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
          <Typography variant="subtitle2">{t('dreamweaverScriptReview.scriptContentTitle')}</Typography>
          <Stack direction="row" spacing={1}>
            <Tooltip title={t('dreamweaverScriptReview.copyScript')}>
              <IconButton size="small" onClick={() => navigator.clipboard.writeText(scriptText)}>
                <ContentCopyIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          </Stack>
        </Box>
        <Paper variant="outlined" sx={{ p: 2, maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
          {scriptText}
        </Paper>
      </Box>
    )
  }

  const renderAssetPlanGrid = (title: string, items: DreamweaverAssetPlanItem[]) => {
    if (!items.length) return null

    return (
      <Box>
        <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>
          {title} ({items.length})
        </Typography>
        <Grid container spacing={1}>
          {items.slice(0, promptReviewShowAll ? undefined : 6).map((item) => (
            <Grid item xs={12} sm={6} md={4} key={item.id}>
              <Paper variant="outlined" sx={{ p: 1 }}>
                <Typography variant="caption" noWrap>
                  {item.label || item.role}
                </Typography>
                <Chip
                  size="small"
                  label={item.status === 'done' ? t('dreamweaverScriptReview.statusDone') : item.status === 'processing' ? t('dreamweaverScriptReview.statusProcessing') : t('dreamweaverScriptReview.statusPending')}
                  color={item.status === 'done' ? 'success' : 'default'}
                  sx={{ ml: 1 }}
                />
              </Paper>
            </Grid>
          ))}
        </Grid>
        {items.length > 6 && !promptReviewShowAll && (
          <Chip
            size="small"
            label={t('dreamweaverScriptReview.showAll', { count: items.length })}
            onClick={onToggleShowAll}
            sx={{ mt: 1, cursor: 'pointer' }}
          />
        )}
      </Box>
    )
  }

  return (
    <Box>
      <Paper sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" spacing={2} alignItems="center" mb={2}>
          <Typography variant="h6">{t('dreamweaverScriptReview.scriptReviewTitle')}</Typography>
          {scriptApproved && <Chip size="small" label={t('dreamweaverScriptReview.approved')} color="success" />}
          {scriptDirty && <Chip size="small" label={t('dreamweaverPending.unsaved')} color="warning" />}
        </Stack>

        {renderScriptBlock()}

        <Divider sx={{ my: 2 }} />

        <Stack direction="row" spacing={1}>
          <Chip
            size="small"
            label={`${t('dreamweaverScriptReview.stageLabel')}: ${getStageDisplayName(result?.stage || '', t)}`}
            variant="outlined"
          />
          <Chip
            size="small"
            label={`${t('dreamweaverScriptReview.previewStepLabel')}: ${t(PREVIEW_STEPS_LABELS[previewStep])}`}
            variant="outlined"
          />
        </Stack>
      </Paper>

      {renderAssetPlanGrid(t('dreamweaverScriptReview.rolePortrait'), characterAssetPlanItems)}
      {renderAssetPlanGrid(t('dreamweaverScriptReview.sceneCard'), sceneAssetPlanItems)}
      {renderAssetPlanGrid(t('dreamweaverScriptReview.propCard'), propAssetPlanItems)}
    </Box>
  )
}
