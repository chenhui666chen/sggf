import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  FormGroup,
  InputLabel,
  MenuItem,
  Select,
  Switch,
  Typography,
} from '@mui/material'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import type {
  AutoReviewScenario,
  MultiModelReviewConfig,
  ReviewConfigResponse,
  ReviewPreset,
} from '@/types/project'

const PRESET_LABELS: Record<ReviewPreset, string> = {
  balanced_3: '普通增强（3 评审）',
  key_chapter_5: '重点章节（5 评审）',
  deep_7: '深度人工（7 评审）',
}

const DEFAULT_CONFIG: MultiModelReviewConfig = {
  enabled: false,
  preset: 'balanced_3',
  auto_scenarios: [],
  manual_depth: 'balanced_3',
  key_chapter_depth: 'key_chapter_5',
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
  return {
    ...DEFAULT_CONFIG,
    ...(response?.multi_model_review || {}),
    auto_scenarios: response?.multi_model_review?.auto_scenarios || [],
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
  const [systemEnabled, setSystemEnabled] = useState(false)
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
        setSystemEnabled(response.data.system_enabled)
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

  const toggleScenario = (scenario: AutoReviewScenario, checked: boolean) => {
    setConfig((current) => {
      const scenarios = new Set(current.auto_scenarios)
      if (checked) {
        scenarios.add(scenario)
      } else {
        scenarios.delete(scenario)
      }
      return { ...current, auto_scenarios: Array.from(scenarios) as AutoReviewScenario[] }
    })
  }

  const handleSave = async () => {
    if (!projectId) return
    setSaving(true)
    setError('')
    try {
      const payloadConfig: MultiModelReviewConfig = {
        ...config,
        enabled: systemEnabled ? config.enabled : false,
      }
      const response = await apiClient.updateProjectReviewConfig(projectId, {
        multi_model_review: payloadConfig,
      })
      setConfig(normalizeConfig(response.data))
      setSystemEnabled(response.data.system_enabled)
      onSaved?.()
      onClose()
    } catch (err) {
      setError(await extractApiErrorMessage(err, '保存评审设置失败'))
    } finally {
      setSaving(false)
    }
  }

  const disabled = loading || saving || !systemEnabled

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
              {!systemEnabled ? (
                <Alert severity="warning">系统级多模型评审开关未开启，项目暂不能启用该能力。</Alert>
              ) : null}

              <FormControlLabel
                control={
                  <Switch
                    checked={config.enabled && systemEnabled}
                    disabled={loading || saving || !systemEnabled}
                    onChange={(event) => updateConfig({ enabled: event.target.checked })}
                  />
                }
                label="启用多模型质量评审"
              />

              <FormControl fullWidth size="small" disabled={disabled}>
                <InputLabel>默认评审深度</InputLabel>
                <Select
                  label="默认评审深度"
                  value={config.preset}
                  onChange={(event) => updateConfig({ preset: event.target.value as ReviewPreset })}
                >
                  {availablePresets.map((preset) => (
                    <MenuItem key={preset} value={preset}>{PRESET_LABELS[preset]}</MenuItem>
                  ))}
                </Select>
              </FormControl>

              <FormControl fullWidth size="small" disabled={disabled}>
                <InputLabel>手动触发深度</InputLabel>
                <Select
                  label="手动触发深度"
                  value={config.manual_depth}
                  onChange={(event) => updateConfig({ manual_depth: event.target.value as ReviewPreset })}
                >
                  {availablePresets.map((preset) => (
                    <MenuItem key={preset} value={preset}>{PRESET_LABELS[preset]}</MenuItem>
                  ))}
                </Select>
              </FormControl>

              <FormControl fullWidth size="small" disabled={disabled}>
                <InputLabel>重点章节深度</InputLabel>
                <Select
                  label="重点章节深度"
                  value={config.key_chapter_depth}
                  onChange={(event) => updateConfig({ key_chapter_depth: event.target.value as 'key_chapter_5' | 'deep_7' })}
                >
                  <MenuItem value="key_chapter_5">{PRESET_LABELS.key_chapter_5}</MenuItem>
                  <MenuItem value="deep_7">{PRESET_LABELS.deep_7}</MenuItem>
                </Select>
              </FormControl>

              <Box>
                <Typography variant="subtitle2" sx={{ mb: 0.75 }}>自动触发场景</Typography>
                <FormGroup row>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={config.auto_scenarios.includes('first_chapter')}
                        disabled={disabled}
                        onChange={(event) => toggleScenario('first_chapter', event.target.checked)}
                      />
                    }
                    label="第一章"
                  />
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={config.auto_scenarios.includes('key_chapter')}
                        disabled={disabled}
                        onChange={(event) => toggleScenario('key_chapter', event.target.checked)}
                      />
                    }
                    label="重点章节"
                  />
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={config.auto_scenarios.includes('final_chapter')}
                        disabled={disabled}
                        onChange={(event) => toggleScenario('final_chapter', event.target.checked)}
                      />
                    }
                    label="完结章"
                  />
                </FormGroup>
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
