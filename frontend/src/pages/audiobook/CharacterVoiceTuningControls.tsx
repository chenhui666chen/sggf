import {
  Box,
  Slider,
  Typography,
} from '@mui/material'

import { useTranslation } from 'react-i18next'

import type { CharacterVoiceSetting } from './types'

interface TuningSliderProps {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (value: number) => void
}

const TuningSlider = ({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: TuningSliderProps) => (
  <Box sx={{ mt: 1 }}>
    <Typography variant="caption" color="text.secondary">
      {label}：{value}
    </Typography>
    <Slider
      size="small"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(_, nextValue) => onChange(nextValue as number)}
      sx={{ mt: 0.5 }}
    />
  </Box>
)

interface CharacterVoiceTuningControlsProps {
  characterVoice: CharacterVoiceSetting
  onVolumeChange: (characterId: number, volume: number) => void
  onSpeedChange: (characterId: number, speed: number) => void
}

const CharacterVoiceTuningControls = ({
  characterVoice,
  onVolumeChange,
  onSpeedChange,
}: CharacterVoiceTuningControlsProps) => {
  const { t } = useTranslation()
  const characterId = characterVoice.characterId

  return (
    <>
      <TuningSlider
        label={t('audiobook.characterVoiceTuningControls.volume')}
        value={characterVoice.volume}
        min={0}
        max={100}
        step={5}
        onChange={(value) => onVolumeChange(characterId, value)}
      />
      <TuningSlider
        label={t('audiobook.characterVoiceTuningControls.speed')}
        value={characterVoice.speed ?? 1.0}
        min={0.5}
        max={2.0}
        step={0.1}
        onChange={(value) => onSpeedChange(characterId, value)}
      />
    </>
  )
}

export default CharacterVoiceTuningControls
