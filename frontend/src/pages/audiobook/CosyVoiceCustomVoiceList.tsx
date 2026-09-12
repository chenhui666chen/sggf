import { useCallback, useEffect, useState } from 'react'

import {
  Box,
  Button,
  Chip,
  Collapse,
  CircularProgress,
  Divider,
  IconButton,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'

import { useTranslation } from 'react-i18next'

import { useFormats } from '../../i18n'
import { apiClient, extractApiErrorMessage } from '../../services/api'
import type { TranslateFn } from './audioLibraryDisplay'
import type { VoicePreset } from './types'

interface CloneDetail {
  voice_id: string
  status: string
  gmt_create: string
  gmt_modified: string
  custom_type: string
  voice_prompt: string
  preview_text: string
  preview_audio: string
  display_name: string
}

interface CosyVoiceCustomVoiceListProps {
  customVoicePresets: VoicePreset[]
  cloneDeletingId: string | null
  deleteDisabled: boolean
  previewingVoiceId: string | null
  onPreviewCustomVoice: (voice: VoicePreset) => void
  onRequestDeleteVoice: (voiceId: string, label?: string) => void
}

const VISIBLE_CUSTOM_VOICE_LIMIT = 3

const voiceItemSx = {
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1fr) auto' },
  gap: 1,
  alignItems: { xs: 'stretch', sm: 'center' },
  p: 1,
  borderRadius: 1.5,
  border: '1px solid',
  borderColor: 'divider',
  backgroundColor: 'background.paper',
  '& + &': { mt: 1 },
} as const

const actionSx = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: { xs: 'space-between', sm: 'flex-end' },
  gap: 0.5,
  minWidth: { xs: 0, sm: 132 },
} as const

const singleLineTextSx = {
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
} as const

const doubleLineTextSx = {
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
} as const

const getVoiceKindLabel = (type: string | undefined, t: TranslateFn) => (
  type === 'design'
    ? t('audiobook.cosyVoiceCustomVoiceList.kindDesign')
    : t('audiobook.cosyVoiceCustomVoiceList.kindClone')
)

const getVoiceKindColor = (type?: string): 'warning' | 'success' => (
  type === 'design' ? 'warning' : 'success'
)

const CosyVoiceCustomVoiceList = ({
  customVoicePresets,
  cloneDeletingId,
  deleteDisabled,
  previewingVoiceId,
  onPreviewCustomVoice,
  onRequestDeleteVoice,
}: CosyVoiceCustomVoiceListProps) => {
  const { t } = useTranslation()
  const { formatDateTime } = useFormats()
  const [details, setDetails] = useState<CloneDetail[]>([])
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [detailsLoaded, setDetailsLoaded] = useState(false)
  const [detailsError, setDetailsError] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState(customVoicePresets.length === 0)
  const [showAllPresets, setShowAllPresets] = useState(false)
  const visiblePresets = showAllPresets
    ? customVoicePresets
    : customVoicePresets.slice(0, VISIBLE_CUSTOM_VOICE_LIMIT)
  const hiddenPresetCount = customVoicePresets.length - visiblePresets.length

  // 原本在模块级，依赖当前语言之后只能待进组件内。无效日期时保留后端给的
  // 原始串而不是空串——那串东西至少能让人看出后端返回了什么，这个语义刻意不变。
  const formatCreatedAt = (value?: string) => {
    if (!value) return '—'
    return formatDateTime(value) || value
  }

  const fetchDetails = useCallback(async () => {
    setDetailsLoading(true)
    setDetailsError(null)
    try {
      const res = await apiClient.listCosyVoiceClones()
      setDetails(res.data.voices || [])
      setDetailsLoaded(true)
    } catch (err: unknown) {
      setDetailsError(await extractApiErrorMessage(err, t('audiobook.cosyVoiceCustomVoiceList.fetchFailed')))
    } finally {
      setDetailsLoading(false)
    }
  }, [t])

  useEffect(() => {
    if (customVoicePresets.length === 0 && !showDetails) {
      setShowDetails(true)
    }
  }, [customVoicePresets.length, showDetails])

  useEffect(() => {
    if (showDetails && !detailsLoaded && !detailsLoading && !detailsError) {
      void fetchDetails()
    }
  }, [showDetails, detailsLoaded, detailsLoading, detailsError, fetchDetails])

  return (
    <Box sx={{ mt: 1.5 }}>
      <Divider sx={{ mb: 1 }} />
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1,
          mb: 1,
        }}
      >
        <Typography variant="caption" color="text.secondary">
          {t('audiobook.cosyVoiceCustomVoiceList.sectionTitle')}
        </Typography>
        <Button
          size="small"
          variant="text"
          onClick={() => setShowDetails(!showDetails)}
          sx={{ fontSize: '0.7rem', minWidth: 0 }}
        >
          {showDetails
            ? t('audiobook.cosyVoiceCustomVoiceList.compactView')
            : t('audiobook.cosyVoiceCustomVoiceList.detailView')}
        </Button>
      </Box>

      {!showDetails ? (
        <Box>
          {visiblePresets.map((preset) => {
            const isDesign = preset.customType === 'design'
            const description = preset.description || preset.id
            const isDeleting = cloneDeletingId === preset.id
            const isPreviewing = previewingVoiceId === preset.id
            return (
              <Box key={preset.id} sx={voiceItemSx}>
                <Box sx={{ minWidth: 0 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700, ...singleLineTextSx }}>
                    {preset.label || preset.id}
                  </Typography>
                  <Tooltip title={description}>
                    <Typography
                      variant="caption"
                      color="text.secondary"
                      sx={{ display: 'block', mt: 0.25, ...singleLineTextSx }}
                    >
                      {description}
                    </Typography>
                  </Tooltip>
                </Box>
                <Box sx={actionSx}>
                  <Tooltip
                    title={
                      isDesign
                        ? t('audiobook.cosyVoiceCustomVoiceList.designTooltip')
                        : t('audiobook.cosyVoiceCustomVoiceList.cloneTooltip')
                    }
                  >
                    <Chip
                      label={getVoiceKindLabel(preset.customType, t)}
                      size="small"
                      color={getVoiceKindColor(preset.customType)}
                      sx={{ height: 22, fontSize: '0.7rem', flexShrink: 0 }}
                    />
                  </Tooltip>
                  <Tooltip title={t('audiobook.cosyVoiceCustomVoiceList.preview')}>
                    <span>
                      <IconButton
                        size="small"
                        onClick={() => onPreviewCustomVoice(preset)}
                        disabled={Boolean(previewingVoiceId) || isDeleting}
                        sx={{ flexShrink: 0 }}
                        aria-label={t('audiobook.cosyVoiceCustomVoiceList.previewWithLabel', { label: preset.label || preset.id })}
                      >
                        {isPreviewing ? <CircularProgress size={18} /> : <PlayArrowIcon fontSize="small" />}
                      </IconButton>
                    </span>
                  </Tooltip>
                  <Tooltip
                    title={
                      isDeleting
                        ? t('audiobook.cosyVoiceCustomVoiceList.deleting')
                        : t('audiobook.cosyVoiceCustomVoiceList.delete')
                    }
                  >
                    <span>
                      <IconButton
                        size="small"
                        color="error"
                        disabled={isDeleting || deleteDisabled}
                        onClick={() => onRequestDeleteVoice(preset.id, preset.label)}
                        sx={{ flexShrink: 0 }}
                        aria-label={t('audiobook.cosyVoiceCustomVoiceList.deleteWithLabel', { label: preset.label || preset.id })}
                      >
                        {isDeleting ? <CircularProgress size={18} /> : <DeleteOutlineIcon fontSize="small" />}
                      </IconButton>
                    </span>
                  </Tooltip>
                </Box>
              </Box>
            )
          })}
          {customVoicePresets.length > VISIBLE_CUSTOM_VOICE_LIMIT && (
            <Button
              size="small"
              variant="text"
              endIcon={showAllPresets ? <ExpandLessIcon /> : <ExpandMoreIcon />}
              onClick={() => setShowAllPresets((current) => !current)}
              sx={{ mt: 1, fontSize: '0.75rem', minWidth: 0 }}
            >
              {showAllPresets
                ? t('audiobook.cosyVoiceCustomVoiceList.collapse')
                : t('audiobook.cosyVoiceCustomVoiceList.expandMore', { total: hiddenPresetCount })}
            </Button>
          )}
        </Box>
      ) : (
        <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
            <Button
              size="small"
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={() => void fetchDetails()}
              disabled={detailsLoading}
              sx={{ fontSize: '0.7rem' }}
            >
              {detailsLoading
                ? t('audiobook.cosyVoiceCustomVoiceList.loading')
                : t('audiobook.cosyVoiceCustomVoiceList.refreshList')}
            </Button>
            {detailsError && (
              <Typography variant="caption" color="error">{detailsError}</Typography>
            )}
          </Box>
          <Collapse in={details.length > 0 || detailsLoading || detailsLoaded}>
            {detailsLoading && details.length === 0 ? (
              <Typography variant="caption" color="text.secondary">{t('audiobook.cosyVoiceCustomVoiceList.loading')}</Typography>
            ) : detailsLoaded && details.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                {t('audiobook.cosyVoiceCustomVoiceList.emptyList')}
              </Typography>
            ) : (
              <Box>
                {details.map((clone) => {
                  const detailPreset: VoicePreset = {
                    id: clone.voice_id,
                    speaker: clone.voice_id,
                    label: clone.display_name || clone.voice_id,
                    customType: clone.custom_type === 'design' ? 'design' : 'clone',
                    category: 'custom',
                    description: clone.voice_prompt || clone.voice_id,
                  }
                  const isDeleting = cloneDeletingId === clone.voice_id
                  const isPreviewing = previewingVoiceId === clone.voice_id
                  return (
                    <Box key={clone.voice_id} sx={voiceItemSx}>
                      <Box sx={{ minWidth: 0 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
                          <Typography variant="body2" sx={{ fontWeight: 700, ...singleLineTextSx }}>
                            {clone.display_name || clone.voice_id}
                          </Typography>
                          <Chip
                            label={clone.status || '—'}
                            size="small"
                            variant="outlined"
                            sx={{ height: 20, fontSize: '0.65rem', flexShrink: 0 }}
                          />
                        </Box>
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
                          {t('audiobook.cosyVoiceCustomVoiceList.createdAtPrefix', { time: formatCreatedAt(clone.gmt_create) })}
                        </Typography>
                        {clone.voice_prompt && (
                          <Tooltip title={clone.voice_prompt}>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              sx={{ mt: 0.25, ...doubleLineTextSx }}
                            >
                              {t('audiobook.cosyVoiceCustomVoiceList.descriptionPrefix', { value: clone.voice_prompt })}
                            </Typography>
                          </Tooltip>
                        )}
                      </Box>
                      <Box sx={actionSx}>
                        <Chip
                          label={getVoiceKindLabel(clone.custom_type, t)}
                          size="small"
                          color={getVoiceKindColor(clone.custom_type)}
                          sx={{ height: 22, fontSize: '0.7rem', flexShrink: 0 }}
                        />
                        <Tooltip title={t('audiobook.cosyVoiceCustomVoiceList.preview')}>
                          <span>
                            <IconButton
                              size="small"
                              onClick={() => onPreviewCustomVoice(detailPreset)}
                              disabled={Boolean(previewingVoiceId) || isDeleting}
                              aria-label={t('audiobook.cosyVoiceCustomVoiceList.previewWithLabel', { label: clone.display_name || clone.voice_id })}
                            >
                              {isPreviewing ? <CircularProgress size={18} /> : <PlayArrowIcon fontSize="small" />}
                            </IconButton>
                          </span>
                        </Tooltip>
                        <Tooltip
                          title={
                            isDeleting
                              ? t('audiobook.cosyVoiceCustomVoiceList.deleting')
                              : t('audiobook.cosyVoiceCustomVoiceList.delete')
                          }
                        >
                          <span>
                            <IconButton
                              size="small"
                              color="error"
                              disabled={isDeleting || deleteDisabled}
                              onClick={() => onRequestDeleteVoice(clone.voice_id, clone.display_name)}
                              aria-label={t('audiobook.cosyVoiceCustomVoiceList.deleteWithLabel', { label: clone.display_name || clone.voice_id })}
                            >
                              {isDeleting ? <CircularProgress size={18} /> : <DeleteOutlineIcon fontSize="small" />}
                            </IconButton>
                          </span>
                        </Tooltip>
                      </Box>
                    </Box>
                  )
                })}
              </Box>
            )}
          </Collapse>
        </>
      )}
    </Box>
  )
}

export default CosyVoiceCustomVoiceList
