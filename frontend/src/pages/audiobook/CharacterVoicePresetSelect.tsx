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
  onVoiceChange: (characterId: number, voiceId: string) => void
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

  // 验证当前 value 是否在可用选项中,如果不在则使用空字符串(默认值)
  // 这样可以避免 MUI Select 的 "out-of-range value" 警告
  const safeValue = hasNoVoicePresets || voiceLoading
    ? ''
    : currentVoicePresets.some((preset) => preset.id === value)
      ? value
      : ''

  // 如果 value 无效且不是 loading/empty 状态,通知父组件重置为默认值
  if (value && value !== safeValue && !voiceLoading && !hasNoVoicePresets) {
    console.warn(
      `[CharacterVoicePresetSelect] Character ${characterId}: ` +
      `Invalid voice ID "${value}", resetting to default.`
    )
    // 延迟执行,避免在渲染期间调用 setState
    setTimeout(() => onVoiceChange(characterId, ''), 0)
  }

  return (
    <FormControl size="small" fullWidth>
      <InputLabel>角色音</InputLabel>
      <Select
        label="角色音"
        value={safeValue}
        onChange={(event) => onVoiceChange(characterId, event.target.value as string)}
        disabled={voiceLoading && hasNoVoicePresets}
      >
        <MenuItem value="">
          <em>自动（AI 选择）</em>
        </MenuItem>
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
