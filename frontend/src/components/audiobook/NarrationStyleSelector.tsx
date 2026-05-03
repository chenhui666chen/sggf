import {
  Box,
  Chip,
  FormControl,
  InputLabel,
  ListItemText,
  MenuItem,
  Select,
  TextField,
  Typography,
} from '@mui/material'
import type { SelectChangeEvent } from '@mui/material/Select'

export interface NarrationStylePreset {
  id: string
  name: string
  description: string
  emotion_profile?: Record<string, unknown>
  speed_range?: Record<string, unknown>
  pitch_range?: Record<string, unknown>
  pause_multiplier?: number
  color?: string
  supported_models?: readonly string[]
}

interface NarrationStyleSelectorProps {
  styles: readonly NarrationStylePreset[]
  selectedStyle: string
  customPrompt?: string
  onStyleChange: (styleId: string) => void
  onPromptChange?: (prompt: string) => void
  disabled?: boolean
  formatModelLabel?: (modelId: string) => string
  currentModel?: string
}

const NarrationStyleSelector = ({
  styles,
  selectedStyle,
  customPrompt,
  onStyleChange,
  onPromptChange,
  disabled = false,
  formatModelLabel,
  currentModel,
}: NarrationStyleSelectorProps) => {
  const selectedStyleData = styles.find((s) => s.id === selectedStyle)
  const selectedColor = selectedStyleData?.color
  const selectedDescription = selectedStyleData?.description
  const supportedModelText = selectedStyleData?.supported_models?.length
    ? selectedStyleData.supported_models.map((modelId) => formatModelLabel?.(modelId) || modelId).join(', ')
    : '全部模型'
  const isStyleSupported = (style: NarrationStylePreset) =>
    !currentModel
    || !style.supported_models?.length
    || style.supported_models.includes(currentModel)
  const selectedStyleSupported = selectedStyleData ? isStyleSupported(selectedStyleData) : true

  const handleStyleChange = (event: SelectChangeEvent<string>) => {
    const nextStyle = event.target.value
    const nextStyleData = styles.find((style) => style.id === nextStyle)
    if (!nextStyleData || !isStyleSupported(nextStyleData)) {
      return
    }
    onStyleChange(nextStyle)
  }

  return (
    <Box>
      {styles.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          暂无可用叙事风格
        </Typography>
      ) : (
        <FormControl fullWidth size="small" disabled={disabled}>
          <InputLabel id="narration-style-label">叙事风格</InputLabel>
          <Select
            labelId="narration-style-label"
            label="叙事风格"
            value={selectedStyleData ? selectedStyle : ''}
            onChange={handleStyleChange}
            renderValue={() => selectedStyleData?.name || '选择叙事风格'}
            MenuProps={{
              PaperProps: {
                sx: { maxWidth: 420 },
              },
            }}
          >
            {styles.map((style) => {
              const styleSupported = isStyleSupported(style)
              const supportText = styleSupported
                ? style.description
                : `当前模型不支持 · ${style.description}`

              return (
                <MenuItem key={style.id} value={style.id} disabled={!styleSupported}>
                  <ListItemText
                    primary={style.name}
                    secondary={supportText}
                    primaryTypographyProps={{
                      sx: {
                        color: selectedStyle === style.id && style.color ? style.color : undefined,
                        fontWeight: selectedStyle === style.id ? 700 : 500,
                      },
                    }}
                    secondaryTypographyProps={{ sx: { whiteSpace: 'normal' } }}
                  />
                </MenuItem>
              )
            })}
          </Select>
        </FormControl>
      )}

      {selectedStyle === 'custom' && onPromptChange && (
        <Box sx={{ mt: 1.5 }}>
          <TextField
            fullWidth
            multiline
            rows={3}
            label="自定义叙事风格提示词"
            placeholder="例如：温柔、克制，情绪递进时放慢语速并保留长停顿"
            value={customPrompt ?? ''}
            onChange={(e) => onPromptChange(e.target.value)}
            size="small"
            disabled={disabled}
          />
        </Box>
      )}

      {selectedStyleData && (
        <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Chip
            label={`已选择：${selectedStyleData.name}`}
            size="small"
            color={selectedStyleSupported ? 'primary' : 'warning'}
            variant="outlined"
            sx={
              selectedStyleSupported && selectedColor
                ? { alignSelf: 'flex-start', borderColor: selectedColor, color: selectedColor }
                : { alignSelf: 'flex-start' }
            }
          />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            支持模型：{supportedModelText}
          </Typography>
          {selectedDescription && selectedStyle !== 'custom' && (
            <Typography variant="caption" color="text.secondary">
              {selectedDescription}
            </Typography>
          )}
        </Box>
      )}
    </Box>
  )
}

export default NarrationStyleSelector
