import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Switch,
  Typography,
} from '@mui/material'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import type {
  MultiModelReviewConfig,
  ReviewAutoStrategy,
  ReviewConfigResponse,
  ReviewPreset,
  ReviewStrategyPreset,
} from '@/types/project'

const PRESET_LABELS: Record<ReviewPreset, string> = {
  balanced_3: '普通增强（3 评审）',
  key_chapter_5: '重点章节（5 评审）',
  deep_7: '深度人工（7 评审）',
}

const AUTO_STRATEGY_LABELS: Record<keyof ReviewAutoStrategy, string> = {
  regular: '普通章节',
  opening: '开篇章节',
  key: '重点章节',
  finale: '完结章节',
}

const DEFAULT_AUTO_STRATEGY: ReviewAutoStrategy = {
  regular: null,
  opening: 'key_chapter_5',
  key: 'key_chapter_5',
  finale: 'deep_7',
}

const DEFAULT_CONFIG: MultiModelReviewConfig = {
  enabled: false,
  preset: 'balanced_3',
  auto_scenarios: [],
  manual_depth: 'balanced_3',
  key_chapter_depth: 'key_chapter_5',
  auto_strategy: DEFAULT_AUTO_STRATEGY,
  chief_model: 'deepseek-v4-pro',
  custom_panel: null,
}

interface MultiModelReviewSettingsDialogProps {
  open: boolean
  projectId: number | null
  projectTitle?: string
  onClose: () => void
  onSaved?: () => void
}

function normalizeConfig(response?: ReviewConfigResponse | null): MultiModelReviewConfig {
  const multiModelReview: Partial<MultiModelReviewConfig> = response?.multi_model_review || {}
  return {
    ...DEFAULT_CONFIG,
    ...multiModelReview,
    auto_scenarios: multiModelReview.auto_scenarios || [],
    auto_strategy: {
      ...DEFAULT_AUTO_STRATEGY,
      ...(multiModelReview.auto_strategy || {}),
    },
  }
}

export default function MultiModelReviewSettingsDialog({
  open,
  projectId,
  projectTitle,
  onClose,
  onSaved,
}: MultiModelReviewSettingsDialogProps) {
  const [config, setConfig] = useState<MultiModelReviewConfig>(DEFAULT_CONFIG)
  const [availablePresets, setAvailablePresets] = useState<ReviewPreset[]>(['balanced_3', 'key_chapter_5', 'deep_7'])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open || !projectId) return

    let active = true
    setLoading(true)
    setError('')
    apiClient.getProjectReviewConfig(projectId)
      .then((response) => {
        if (!active) return
        setConfig(normalizeConfig(response.data))
        setAvailablePresets(response.data.available_presets.length ? response.data.available_presets : ['balanced_3'])
      })
      .catch(async (err) => {
        if (!active) return
        setConfig(DEFAULT_CONFIG)
        setError(await extractApiErrorMessage(err, '加载评审设置失败'))
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [open, projectId])

  const updateConfig = (patch: Partial<MultiModelReviewConfig>) => {
    setConfig((current) => ({ ...current, ...patch }))
  }

  const updateAutoStrategy = (
    key: keyof ReviewAutoStrategy,
    preset: ReviewStrategyPreset,
  ) => {
    setConfig((current) => {
      return {
        ...current,
        auto_strategy: {
          ...current.auto_strategy,
          [key]: preset,
        },
      }
    })
  }

  const handleSave = async () => {
    if (!projectId) return
    setSaving(true)
    setError('')
    try {
      const response = await apiClient.updateProjectReviewConfig(projectId, {
        multi_model_review: config,
      })
      setConfig(normalizeConfig(response.data))
      onSaved?.()
      onClose()
    } catch (err) {
      setError(await extractApiErrorMessage(err, '保存评审设置失败'))
    } finally {
      setSaving(false)
    }
  }

  const disabled = loading || saving

  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>多模型评审设置</DialogTitle>
      <DialogContent dividers>
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.25 }}>
          {projectTitle ? (
            <Typography variant="body2" sx={{ color: 'text.secondary' }}>
              {projectTitle}
            </Typography>
          ) : null}

          {loading ? (
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', py: 5 }}>
              <CircularProgress size={28} />
            </Box>
          ) : (
            <>
              {error ? <Alert severity="error">{error}</Alert> : null}
              <FormControlLabel
                control={
                  <Switch
                    checked={config.enabled}
                    disabled={loading || saving}
                    onChange={(event) => updateConfig({ enabled: event.target.checked })}
                  />
                }
                label="启用多模型质量评审"
              />

              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>自动多模型评审策略</Typography>
                <Box sx={{ display: 'grid', gap: 1.5 }}>
                  {(Object.keys(AUTO_STRATEGY_LABELS) as Array<keyof ReviewAutoStrategy>).map((key) => (
                    <FormControl key={key} fullWidth size="small" disabled={disabled}>
                      <InputLabel>{AUTO_STRATEGY_LABELS[key]}</InputLabel>
                      <Select
                        label={AUTO_STRATEGY_LABELS[key]}
                        value={config.auto_strategy[key] || ''}
                        onChange={(event) => updateAutoStrategy(
                          key,
                          event.target.value ? event.target.value as ReviewPreset : null,
                        )}
                      >
                        <MenuItem value="">不增强（单模型）</MenuItem>
                        {availablePresets.map((preset) => (
                          <MenuItem key={preset} value={preset}>{PRESET_LABELS[preset]}</MenuItem>
                        ))}
                      </Select>
                    </FormControl>
                  ))}
                </Box>
              </Box>
            </>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>取消</Button>
        <Button variant="contained" onClick={handleSave} disabled={loading || saving || !projectId}>
          {saving ? '保存中...' : '保存'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
