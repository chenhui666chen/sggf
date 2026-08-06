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
  const hasNoVoicePresets = currentVoicePresets.length === 0
  const isValueInPresets = currentVoicePresets.some((preset) => preset.id === value)

  // 始终保留并展示已配置的音色：即使它暂时不在当前目录中（跨模型音色、目录未加载完成、
  // 自定义音色等），也不能在渲染期静默重置为空。重置会触发自动保存，把空配置回写后端，
  // 永久覆盖用户已保存的音色（固定化失效）。这里仅补充一个占位选项避免 MUI out-of-range 警告。
  const safeValue = value

  return (
    <FormControl size="small" fullWidth>
      <InputLabel>音色</InputLabel>
      <Select
        label="音色"
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
          <em>自动（AI 选择）</em>
        </MenuItem>
        {value && !isValueInPresets && (
          <MenuItem value={value}>
            <em>
              {value}
              {voiceLoading || hasNoVoicePresets ? '' : '（不在当前音色库）'}
            </em>
          </MenuItem>
        )}
        {voiceLoading && hasNoVoicePresets && (
          <MenuItem disabled value="__loading">
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              <CircularProgress size={14} />
              <Typography variant="caption">同步官方音色...</Typography>
            </Box>
          </MenuItem>
        )}
        {!voiceLoading && hasNoVoicePresets && (
          <MenuItem disabled value="__empty">
            {requiresCustomVoice
              ? '暂无可用自定义音色，请先创建'
              : '暂无官方音色，请稍后重试'}
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
                {(preset.languages?.join('/') || '中英')} · {preset.style || '通用'}
              </Typography>
            </Box>
            {preset.supportsInstruct && (
              <Tooltip title="该音色支持 instruction/SSML，情绪和语气可通过 Instruct 参数控制。">
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
