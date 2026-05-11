import { useCallback, useEffect, useState } from 'react'

import {
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  List,
  ListItem,
  ListItemText,
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
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
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
        <List dense>
          {customVoicePresets.map((preset) => {
            const isDesign = preset.customType === 'design'
            return (
              <ListItem
                key={preset.id}
                secondaryAction={
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Tooltip title={isDesign ? '音色设计：通过文字描述生成新的声线' : '音色克隆：基于音频样本创建的专属音色'}>
                      <Chip
                        label={isDesign ? '设计' : '克隆'}
                        size="small"
                        color={isDesign ? 'warning' : 'success'}
                        sx={{ height: 18, fontSize: '0.65rem' }}
                      />
                    </Tooltip>
                    <Button
                      variant="outlined"
                      size="small"
                      disabled={cloneDeletingId === preset.id || deleteDisabled}
                      onClick={() => onRequestDeleteVoice(preset.id, preset.label)}
                      sx={audiobookButtonSx.dangerOutlined}
                    >
                      {cloneDeletingId === preset.id ? '删除中...' : '删除'}
                    </Button>
                  </Box>
                }
              >
                <ListItemText
                  primary={preset.label || preset.id}
                  secondary={preset.description || preset.id}
                />
              </ListItem>
            )
          })}
        </List>
      ) : (
        <>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
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
              <List dense>
                {details.map((clone) => (
                  <ListItem
                    key={clone.voice_id}
                    secondaryAction={
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                        <Chip
                          label={clone.custom_type === 'design' ? '设计' : '克隆'}
                          size="small"
                          color={clone.custom_type === 'design' ? 'warning' : 'success'}
                          sx={{ height: 18, fontSize: '0.65rem' }}
                        />
                        <Chip
                          label={clone.status}
                          size="small"
                          variant="outlined"
                          sx={{ height: 18, fontSize: '0.65rem' }}
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
                    }
                  >
                    <ListItemText
                      primary={clone.display_name || clone.voice_id}
                      secondary={
                        <>
                          <Typography variant="caption" component="span" color="text.secondary">
                            创建：{clone.gmt_create ? new Date(clone.gmt_create).toLocaleString() : '—'}
                          </Typography>
                          {clone.voice_prompt && (
                            <Typography variant="caption" component="div" color="text.secondary" noWrap>
                              提示词：{clone.voice_prompt}
                            </Typography>
                          )}
                        </>
                      }
                    />
                  </ListItem>
                ))}
              </List>
            )}
          </Collapse>
        </>
      )}
    </Box>
  )
}

export default CosyVoiceCustomVoiceList
