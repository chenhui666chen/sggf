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

import { apiClient, extractApiErrorMessage } from '../../services/api'
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

const getVoiceKindLabel = (type?: string) => type === 'design' ? '设计' : '克隆'

const getVoiceKindColor = (type?: string): 'warning' | 'success' => (
  type === 'design' ? 'warning' : 'success'
)

const formatCreatedAt = (value?: string) => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

const CosyVoiceCustomVoiceList = ({
  customVoicePresets,
  cloneDeletingId,
  deleteDisabled,
  previewingVoiceId,
  onPreviewCustomVoice,
  onRequestDeleteVoice,
}: CosyVoiceCustomVoiceListProps) => {
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

  const fetchDetails = useCallback(async () => {
    setDetailsLoading(true)
    setDetailsError(null)
    try {
      const res = await apiClient.listCosyVoiceClones()
      setDetails(res.data.voices || [])
      setDetailsLoaded(true)
    } catch (err: unknown) {
      setDetailsError(await extractApiErrorMessage(err, '获取音色列表失败'))
    } finally {
      setDetailsLoading(false)
    }
  }, [])

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
          已创建自定义音色（可删除）
        </Typography>
        <Button
          size="small"
          variant="text"
          onClick={() => setShowDetails(!showDetails)}
          sx={{ fontSize: '0.7rem', minWidth: 0 }}
        >
          {showDetails ? '精简视图' : '详细信息'}
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
                  <Tooltip title={isDesign ? '音色设计：通过文字描述生成新的声线' : '音色克隆：基于音频样本创建的专属音色'}>
                    <Chip
                      label={getVoiceKindLabel(preset.customType)}
                      size="small"
                      color={getVoiceKindColor(preset.customType)}
                      sx={{ height: 22, fontSize: '0.7rem', flexShrink: 0 }}
                    />
                  </Tooltip>
                  <Tooltip title="试听">
                    <span>
                      <IconButton
                        size="small"
                        onClick={() => onPreviewCustomVoice(preset)}
                        disabled={Boolean(previewingVoiceId) || isDeleting}
                        sx={{ flexShrink: 0 }}
                        aria-label={`试听 ${preset.label || preset.id}`}
                      >
                        {isPreviewing ? <CircularProgress size={18} /> : <PlayArrowIcon fontSize="small" />}
                      </IconButton>
                    </span>
                  </Tooltip>
                  <Tooltip title={isDeleting ? '删除中' : '删除'}>
                    <span>
                      <IconButton
                        size="small"
                        color="error"
                        disabled={isDeleting || deleteDisabled}
                        onClick={() => onRequestDeleteVoice(preset.id, preset.label)}
                        sx={{ flexShrink: 0 }}
                        aria-label={`删除 ${preset.label || preset.id}`}
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
              {showAllPresets ? '收起' : `展开 ${hiddenPresetCount} 个`}
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
              {detailsLoading ? '加载中...' : '刷新列表'}
            </Button>
            {detailsError && (
              <Typography variant="caption" color="error">{detailsError}</Typography>
            )}
          </Box>
          <Collapse in={details.length > 0 || detailsLoading || detailsLoaded}>
            {detailsLoading && details.length === 0 ? (
              <Typography variant="caption" color="text.secondary">加载中...</Typography>
            ) : detailsLoaded && details.length === 0 ? (
              <Typography variant="caption" color="text.secondary">
                暂无已创建的 CosyVoice 自定义音色。
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
                          创建：{formatCreatedAt(clone.gmt_create)}
                        </Typography>
                        {clone.voice_prompt && (
                          <Tooltip title={clone.voice_prompt}>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                              sx={{ mt: 0.25, ...doubleLineTextSx }}
                            >
                              描述：{clone.voice_prompt}
                            </Typography>
                          </Tooltip>
                        )}
                      </Box>
                      <Box sx={actionSx}>
                        <Chip
                          label={getVoiceKindLabel(clone.custom_type)}
                          size="small"
                          color={getVoiceKindColor(clone.custom_type)}
                          sx={{ height: 22, fontSize: '0.7rem', flexShrink: 0 }}
                        />
                        <Tooltip title="试听">
                          <span>
                            <IconButton
                              size="small"
                              onClick={() => onPreviewCustomVoice(detailPreset)}
                              disabled={Boolean(previewingVoiceId) || isDeleting}
                              aria-label={`试听 ${clone.display_name || clone.voice_id}`}
                            >
                              {isPreviewing ? <CircularProgress size={18} /> : <PlayArrowIcon fontSize="small" />}
                            </IconButton>
                          </span>
                        </Tooltip>
                        <Tooltip title={isDeleting ? '删除中' : '删除'}>
                          <span>
                            <IconButton
                              size="small"
                              color="error"
                              disabled={isDeleting || deleteDisabled}
                              onClick={() => onRequestDeleteVoice(clone.voice_id, clone.display_name)}
                              aria-label={`删除 ${clone.display_name || clone.voice_id}`}
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
