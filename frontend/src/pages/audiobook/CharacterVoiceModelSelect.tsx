import {
  Box,
  Chip,
  Divider,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
} from '@mui/material'

import { getTtsModelLabel, type TtsModelOption } from './ttsModels'
import { getTtsModelBadge } from './characterVoiceModelUtils'
import type { TtsModel } from './types'

interface CharacterVoiceModelSelectProps {
  characterId: number
  value?: TtsModel
  projectTtsModel: TtsModel
  ttsModelOptions: readonly TtsModelOption[]
  onTtsModelChangeForCharacter: (characterId: number, nextModel: TtsModel | 'inherit') => void
}

const CharacterVoiceModelSelect = ({
  characterId,
  value,
  projectTtsModel,
  ttsModelOptions,
  onTtsModelChangeForCharacter,
}: CharacterVoiceModelSelectProps) => (
  <FormControl size="small" sx={{ minWidth: 140 }}>
    <InputLabel>模型</InputLabel>
    <Select
      label="模型"
      value={value || 'inherit'}
      onChange={(event) => onTtsModelChangeForCharacter(
        characterId,
        event.target.value as TtsModel | 'inherit',
      )}
    >
      <MenuItem value="inherit">
        <em>跟随项目 ({getTtsModelLabel(projectTtsModel)})</em>
      </MenuItem>
      <Divider sx={{ my: 0.5 }} />
      {ttsModelOptions.map((option) => {
        const badge = getTtsModelBadge(option.id, ttsModelOptions)
        return (
          <MenuItem key={option.id} value={option.id}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <span>{option.name || getTtsModelLabel(option.id)}</span>
              {badge && (
                <Chip
                  label={badge.label}
                  size="small"
                  color={badge.color}
                  sx={{ height: 16, fontSize: '0.6rem' }}
                />
              )}
            </Box>
          </MenuItem>
        )
      })}
    </Select>
  </FormControl>
)

export default CharacterVoiceModelSelect
