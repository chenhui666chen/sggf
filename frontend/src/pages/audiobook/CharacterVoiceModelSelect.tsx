import {
  Box,
  Chip,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
} from '@mui/material'

import { useTranslation } from 'react-i18next'

import { getTtsModelLabel, type TtsModelOption } from './ttsModels'
import { getTtsModelBadge } from './characterVoiceModelUtils'
import type { TtsModel } from './types'

interface CharacterVoiceModelSelectProps {
  characterId: number
  value: TtsModel
  ttsModelOptions: readonly TtsModelOption[]
  onTtsModelChangeForCharacter: (characterId: number, nextModel: TtsModel) => void
}

const CharacterVoiceModelSelect = ({
  characterId,
  value,
  ttsModelOptions,
  onTtsModelChangeForCharacter,
}: CharacterVoiceModelSelectProps) => {
  const { t } = useTranslation()
  return (
    <FormControl size="small" sx={{ minWidth: 140 }}>
      <InputLabel>{t('audiobook.characterVoiceModelSelect.label')}</InputLabel>
      <Select
        label={t('audiobook.characterVoiceModelSelect.label')}
        value={value}
        onChange={(event) => onTtsModelChangeForCharacter(
          characterId,
          event.target.value as TtsModel,
        )}
      >
        {ttsModelOptions.map((option) => {
          const badge = getTtsModelBadge(option.id, ttsModelOptions)
          return (
            <MenuItem key={option.id} value={option.id}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                <span>{option.name || getTtsModelLabel(option.id)}</span>
                {badge && (
                  <Chip
                    label={t(badge.labelKey)}
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
}

export default CharacterVoiceModelSelect
