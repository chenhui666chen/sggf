import {
  Box,
  Button,
  Chip,
  Divider,
  List,
  ListItem,
  ListItemText,
  Tooltip,
  Typography,
} from '@mui/material'

import type { VoicePreset } from './types'

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
  if (customVoicePresets.length === 0) {
    return null
  }

  return (
    <Box sx={{ mt: 1.5 }}>
      <Divider sx={{ mb: 1 }} />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
        已创建自定义音色（可删除）
      </Typography>
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
                    color="error"
                    size="small"
                    disabled={cloneDeletingId === preset.id || deleteDisabled}
                    onClick={() => onRequestDeleteVoice(preset.id, preset.label)}
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
    </Box>
  )
}

export default CosyVoiceCustomVoiceList
