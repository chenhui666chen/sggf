import { useEffect, useState } from 'react'

import {
  Box,
  Button,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
} from '@mui/material'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'

import { apiClient } from '../../services/api'
import type { CharacterVoiceSetting } from './types'

interface SelectOption {
  value: string
  label: string
}

const VOICE_TYPE_OPTIONS: readonly SelectOption[] = [
  { value: 'majestic', label: '威严' },
  { value: 'gentle', label: '温柔' },
  { value: 'lively', label: '活泼' },
  { value: 'weathered', label: '沧桑' },
  { value: 'warm', label: '温暖' },
  { value: 'mysterious', label: '神秘' },
  { value: 'powerful', label: '力量' },
  { value: 'scholarly', label: '书卷气' },
  { value: 'playful', label: '俏皮' },
  { value: 'cold', label: '清冷' },
]

const PERSONALITY_OPTIONS: readonly SelectOption[] = [
  { value: 'introvert', label: '内向' },
  { value: 'extrovert', label: '外向' },
  { value: 'ambitious', label: '野心' },
  { value: 'calm', label: '冷静' },
  { value: 'emotional', label: '感性' },
  { value: 'rational', label: '理性' },
  { value: 'rebel', label: '叛逆' },
  { value: 'loyal', label: '忠诚' },
]

const EMOTION_TENDENCY_OPTIONS: readonly SelectOption[] = [
  { value: 'positive', label: '积极' },
  { value: 'negative', label: '消极' },
  { value: 'neutral', label: '中性' },
  { value: 'variable', label: '多变' },
]

let cachedVoiceTypeOptions: readonly SelectOption[] | null = null
let voiceTypeOptionsRequest: Promise<readonly SelectOption[]> | null = null

const normalizeVoiceTypeOptions = (raw: unknown): readonly SelectOption[] => {
  if (!Array.isArray(raw)) {
    return VOICE_TYPE_OPTIONS
  }

  const options = raw.flatMap((item): SelectOption[] => {
    if (!item || typeof item !== 'object') {
      return []
    }
    const data = item as Record<string, unknown>
    const value = typeof data.voice_type === 'string' ? data.voice_type.trim() : ''
    if (!value) {
      return []
    }
    const label = typeof data.name === 'string' && data.name.trim() ? data.name.trim() : value
    return [{ value, label }]
  })

  return options.length ? options : VOICE_TYPE_OPTIONS
}

const loadVoiceTypeOptions = (): Promise<readonly SelectOption[]> => {
  if (cachedVoiceTypeOptions) {
    return Promise.resolve(cachedVoiceTypeOptions)
  }
  if (!voiceTypeOptionsRequest) {
    voiceTypeOptionsRequest = apiClient.getVoiceTypes()
      .then((response) => {
        cachedVoiceTypeOptions = normalizeVoiceTypeOptions(response.data)
        return cachedVoiceTypeOptions
      })
      .catch(() => {
        cachedVoiceTypeOptions = VOICE_TYPE_OPTIONS
        return cachedVoiceTypeOptions
      })
  }
  return voiceTypeOptionsRequest
}

interface CharacterTraitSelectProps {
  label: string
  value: string
  options: readonly SelectOption[]
  onChange: (value: string) => void
}

const CharacterTraitSelect = ({
  label,
  value,
  options,
  onChange,
}: CharacterTraitSelectProps) => (
  <FormControl size="small" sx={{ minWidth: 100 }}>
    <InputLabel>{label}</InputLabel>
    <Select
      label={label}
      value={value}
      onChange={(event) => onChange(event.target.value as string)}
    >
      <MenuItem value="">
        <em>自动</em>
      </MenuItem>
      {options.map((option) => (
        <MenuItem key={option.value} value={option.value}>
          {option.label}
        </MenuItem>
      ))}
    </Select>
  </FormControl>
)

interface CharacterVoiceTraitControlsProps {
  characterVoice: CharacterVoiceSetting
  onVoiceTypeChange: (characterId: number, voiceType: string) => void
  onPersonalityChange: (characterId: number, personality: string) => void
  onEmotionTendencyChange: (characterId: number, emotionTendency: string) => void
  onRecommendVoiceType: (characterVoice: CharacterVoiceSetting) => void
  isRecommendingVoiceType: boolean
}

const CharacterVoiceTraitControls = ({
  characterVoice,
  onVoiceTypeChange,
  onPersonalityChange,
  onEmotionTendencyChange,
  onRecommendVoiceType,
  isRecommendingVoiceType,
}: CharacterVoiceTraitControlsProps) => {
  const characterId = characterVoice.characterId
  const [voiceTypeOptions, setVoiceTypeOptions] = useState<readonly SelectOption[]>(
    cachedVoiceTypeOptions || VOICE_TYPE_OPTIONS,
  )

  useEffect(() => {
    let active = true
    loadVoiceTypeOptions().then((options) => {
      if (active) {
        setVoiceTypeOptions(options)
      }
    })
    return () => {
      active = false
    }
  }, [])

  return (
    <Box sx={{ display: 'flex', gap: 1, mb: 1, flexWrap: 'wrap' }}>
      <CharacterTraitSelect
        label="声音类型"
        value={characterVoice.voiceType || ''}
        options={voiceTypeOptions}
        onChange={(value) => onVoiceTypeChange(characterId, value)}
      />
      <CharacterTraitSelect
        label="性格"
        value={characterVoice.personality || ''}
        options={PERSONALITY_OPTIONS}
        onChange={(value) => onPersonalityChange(characterId, value)}
      />
      <CharacterTraitSelect
        label="情感倾向"
        value={characterVoice.emotionTendency || ''}
        options={EMOTION_TENDENCY_OPTIONS}
        onChange={(value) => onEmotionTendencyChange(characterId, value)}
      />
      <Button
        size="small"
        variant="outlined"
        onClick={() => onRecommendVoiceType(characterVoice)}
        disabled={isRecommendingVoiceType}
        startIcon={isRecommendingVoiceType
          ? <CircularProgress size={14} />
          : <AutoFixHighIcon fontSize="small" />}
        sx={{ minWidth: 88 }}
      >
        {isRecommendingVoiceType ? '推荐中' : '推荐'}
      </Button>
    </Box>
  )
}

export default CharacterVoiceTraitControls
