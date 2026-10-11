import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
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

const PRESET_LABEL_KEYS: Record<ReviewPreset, string> = {
  balanced_3: 'project.multiModelReview.presetBalanced3',
  key_chapter_5: 'project.multiModelReview.presetKeyChapter5',
  deep_7: 'project.multiModelReview.presetDeep7',
}

const AUTO_STRATEGY_LABEL_KEYS: Record<keyof ReviewAutoStrategy, string> = {
  regular: 'project.multiModelReview.strategyRegular',
  opening: 'project.multiModelReview.strategyOpening',
  key: 'project.multiModelReview.strategyKey',
  finale: 'project.multiModelReview.strategyFinale',
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
  chief_model: 'deepseek-pro',
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
  const { t } = useTranslation()
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
        setError(await extractApiErrorMessage(err, t('project.multiModelReview.loadFailed')))
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
      setError(await extractApiErrorMessage(err, t('project.multiModelReview.saveFailed')))
    } finally {
      setSaving(false)
    }
  }

  const disabled = loading || saving

  return (
    <Dialog open={open} onClose={saving ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>{t('project.multiModelReview.title')}</DialogTitle>
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
                label={t('project.multiModelReview.enableLabel')}
              />
              {config.enabled ? (
                <Alert severity="warning">
                  {t('project.multiModelReview.costWarning')}
                </Alert>
              ) : null}

              <Box>
                <Typography variant="subtitle2" sx={{ mb: 1 }}>{t('project.multiModelReview.strategyTitle')}</Typography>
                <Box sx={{ display: 'grid', gap: 1.5 }}>
                  {(Object.keys(AUTO_STRATEGY_LABEL_KEYS) as Array<keyof ReviewAutoStrategy>).map((key) => (
                    <FormControl key={key} fullWidth size="small" disabled={disabled}>
                      <InputLabel>{t(AUTO_STRATEGY_LABEL_KEYS[key])}</InputLabel>
                      <Select
                        label={t(AUTO_STRATEGY_LABEL_KEYS[key])}
                        value={config.auto_strategy[key] || ''}
                        onChange={(event) => updateAutoStrategy(
                          key,
                          event.target.value ? event.target.value as ReviewPreset : null,
                        )}
                      >
                        <MenuItem value="">{t('project.multiModelReview.noBoost')}</MenuItem>
                        {availablePresets.map((preset) => (
                          <MenuItem key={preset} value={preset}>{t(PRESET_LABEL_KEYS[preset])}</MenuItem>
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
        <Button onClick={onClose} disabled={saving}>{t('action.cancel')}</Button>
        <Button variant="contained" onClick={handleSave} disabled={loading || saving || !projectId}>
          {saving ? t('project.multiModelReview.saving') : t('common.save')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
