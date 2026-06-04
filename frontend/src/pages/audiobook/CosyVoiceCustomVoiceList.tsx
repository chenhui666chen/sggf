import { useCallback, useEffect, useState } from 'react'

import {
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  Tooltip,
  Typography,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { audiobookButtonSx } from './audiobookTheme'
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
  onRequestDeleteVoice: (voiceId: string, label?: string) => void
}

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
  gap: 1,
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
  onRequestDeleteVoice,
}: CosyVoiceCustomVoiceListProps) => {
  const [details, setDetails] = useState<CloneDetail[]>([])
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [detailsError, setDetailsError] = useState<string | null>(null)
  const [showDetails, setShowDetails] = useState(false)

  const fetchDetails = useCallback(async () => {
    setDetailsLoading(true)
    setDetailsError(null)
    try {
      const res = await apiClient.listCosyVoiceClones()
      setDetails(res.data.voices || [])
    } catch (err: unknown) {
      setDetailsError(await extractApiErrorMessage(err, '获取音色列表失败'))
    } finally {
      setDetailsLoading(false)
    }
  }, [])

  useEffect(() => {
    if (showDetails && details.length === 0 && !detailsLoading && !detailsError) {
      void fetchDetails()
    }
  }, [showDetails, details.length, detailsLoading, detailsError, fetchDetails])

  if (customVoicePresets.length === 0) {
    return null
  }

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
          {customVoicePresets.map((preset) => {
            const isDesign = preset.customType === 'design'
            const description = preset.description || preset.id
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
                  <Button
                    variant="outlined"
                    size="small"
                    disabled={cloneDeletingId === preset.id || deleteDisabled}
                    onClick={() => onRequestDeleteVoice(preset.id, preset.label)}
                    sx={{ ...audiobookButtonSx.dangerOutlined, flexShrink: 0 }}
                  >
                    {cloneDeletingId === preset.id ? '删除中...' : '删除'}
                  </Button>
                </Box>
              </Box>
            )
          })}
        </Box>
      ) : (
        <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1 }}>
            <Button
              size="small"
              variant="outlined"
              startIcon={<RefreshIcon />}
              onClick={fetchDetails}
              disabled={detailsLoading}
              sx={{ fontSize: '0.7rem' }}
            >
              {detailsLoading ? '加载中...' : '刷新列表'}
            </Button>
            {detailsError && (
              <Typography variant="caption" color="error">{detailsError}</Typography>
            )}
          </Box>
          <Collapse in={details.length > 0 || detailsLoading}>
            {detailsLoading && details.length === 0 ? (
              <Typography variant="caption" color="text.secondary">加载中...</Typography>
            ) : (
              <Box>
                {details.map((clone) => {
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
                        <Button
                          variant="outlined"
                          size="small"
                          disabled={cloneDeletingId === clone.voice_id || deleteDisabled}
                          onClick={() => onRequestDeleteVoice(clone.voice_id, clone.display_name)}
                          sx={audiobookButtonSx.dangerOutlined}
                        >
                          {cloneDeletingId === clone.voice_id ? '删除中...' : '删除'}
                        </Button>
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
