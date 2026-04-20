/**
 * 叙事风格选择器组件
 * 
 * 用于在有声书生成配置中选择叙事风格预设
 */
import {
  Box,
  Typography,
  TextField,
  Tooltip,
  Chip,
} from '@mui/material'
import { styled } from '@mui/material/styles'

const StyleCard = styled(Box)(({ theme }) => ({
  padding: theme.spacing(1.5),
  borderRadius: theme.shape.borderRadius,
  border: `1px solid ${theme.palette.divider}`,
  cursor: 'pointer',
  transition: 'all 0.2s',
  '&:hover': {
    borderColor: theme.palette.primary.main,
    backgroundColor: theme.palette.action.hover,
  },
  '&.selected': {
    borderColor: theme.palette.primary.main,
    backgroundColor: theme.palette.primary.light + '20',
    borderWidth: 2,
  },
}))

interface NarrationStyleSelectorProps {
  styles: any[]
  selectedStyle: string
  customPrompt: string
  onStyleChange: (styleId: string) => void
  onPromptChange: (prompt: string) => void
}

const NarrationStyleSelector: React.FC<NarrationStyleSelectorProps> = ({
  styles,
  selectedStyle,
  customPrompt,
  onStyleChange,
  onPromptChange,
}) => {
  const selectedStyleData = styles.find((s) => s.id === selectedStyle)

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 1.5, fontWeight: 600 }}>
        叙事风格
      </Typography>

      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
        {styles.map((style) => (
          <Tooltip key={style.id} title={style.description} arrow>
            <StyleCard
              className={selectedStyle === style.id ? 'selected' : ''}
              onClick={() => onStyleChange(style.id)}
              sx={{ flex: '1 1 140px', minWidth: 140 }}
            >
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {style.name}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                {style.description}
              </Typography>
            </StyleCard>
          </Tooltip>
        ))}
      </Box>

      {selectedStyle === 'custom' && (
        <TextField
          fullWidth
          multiline
          rows={3}
          label="自定义叙事风格提示词"
          placeholder="例如：请以温柔、富有感情的语气朗读，适当加入停顿以增强情感..."
          value={customPrompt}
          onChange={(e) => onPromptChange(e.target.value)}
          sx={{ mt: 1 }}
          size="small"
        />
      )}

      {selectedStyleData && selectedStyle !== 'custom' && (
        <Box sx={{ mt: 1 }}>
          <Chip
            label={`已选择: ${selectedStyleData.name}`}
            size="small"
            color="primary"
            variant="outlined"
          />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            支持模型: {selectedStyleData.supported_models?.join(', ') || '全部'}
          </Typography>
        </Box>
      )}
    </Box>
  )
}

export default NarrationStyleSelector
