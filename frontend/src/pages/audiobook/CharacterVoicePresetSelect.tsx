import {
  Box,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Tooltip,
  Typography,
} from '@mui/material'

import { useTranslation } from 'react-i18next'

import type { VoicePreset } from './types'

interface CharacterVoicePresetSelectProps {
  characterId: number
  value: string
  requiresCustomVoice: boolean
  voiceLoading: boolean
  currentVoicePresets: VoicePreset[]
  onVoiceChange: (characterId: number, voiceId: string, preset?: VoicePreset) => void
}

const CharacterVoicePresetSelect = ({
  characterId,
  value,
  requiresCustomVoice,
  voiceLoading,
  currentVoicePresets,
  onVoiceChange,
}: CharacterVoicePresetSelectProps) => {
  const { t } = useTranslation()
  const hasNoVoicePresets = currentVoicePresets.length === 0
  const isValueInPresets = currentVoicePresets.some((preset) => preset.id === value)

  // 始终保留并展示已配置的音色：即使它暂时不在当前目录中（跨模型音色、目录未加载完成、
  // 自定义音色等），也不能在渲染期静默重置为空。重置会触发自动保存，把空配置回写后端，
  // 永久覆盖用户已保存的音色（固定化失效）。这里仅补充一个占位选项避免 MUI out-of-range 警告。
  const safeValue = value

  return (
    <FormControl size="small" fullWidth>
      <InputLabel>{t('audiobook.characterVoicePresetSelect.label')}</InputLabel>
      <Select
        label={t('audiobook.characterVoicePresetSelect.label')}
        value={safeValue}
        onChange={(event) => {
          const voiceId = event.target.value as string
          onVoiceChange(
            characterId,
            voiceId,
            currentVoicePresets.find((preset) => preset.id === voiceId),
          )
        }}
        disabled={voiceLoading && hasNoVoicePresets}
      >
        <MenuItem value="">
          <em>{t('audiobook.characterVoicePresetSelect.auto')}</em>
        </MenuItem>
        {value && !isValueInPresets && (
          <MenuItem value={value}>
            <em>
              {value}
              {voiceLoading || hasNoVoicePresets ? '' : t('audiobook.characterVoicePresetSelect.notInCurrentLibrary')}
            </em>
          </MenuItem>
        )}
        {voiceLoading && hasNoVoicePresets && (
          <MenuItem disabled value="__loading">
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <CircularProgress size={14} />
              <Typography variant="caption">{t('audiobook.characterVoicePresetSelect.syncing')}</Typography>
            </Box>
          </MenuItem>
        )}
        {!voiceLoading && hasNoVoicePresets && (
          <MenuItem disabled value="__empty">
            {requiresCustomVoice
              ? t('audiobook.characterVoicePresetSelect.emptyCustom')
              : t('audiobook.characterVoicePresetSelect.emptyOfficial')}
          </MenuItem>
        )}
        {currentVoicePresets.map((preset) => (
          <MenuItem key={preset.id} value={preset.id} disabled={Boolean(preset.disabled)}>
            <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 0.25 }}>
              <Typography variant="body2" fontWeight={600}>
                {preset.label || preset.id}
              </Typography>
              {preset.description && (
                <Typography variant="caption" color="text.secondary">
                  {preset.description}
                </Typography>
              )}
              {preset.disabledReason && (
                <Typography variant="caption" color="warning.main">
                  {preset.disabledReason}
                </Typography>
              )}
              <Typography variant="caption" color="text.secondary">
                {(preset.languages?.join('/') || t('audiobook.characterVoicePresetSelect.defaultLanguages'))} · {preset.style || t('audiobook.characterVoicePresetSelect.defaultStyle')}
              </Typography>
            </Box>
            {preset.supportsInstruct && (
              <Tooltip title={t('audiobook.characterVoicePresetSelect.supportsInstructTooltip')}>
                <Chip
                  label="Instruct"
                  size="small"
                  color="primary"
                  sx={{ height: 18, fontSize: '0.65rem', ml: 1 }}
                />
              </Tooltip>
            )}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  )
}

export default CharacterVoicePresetSelect
