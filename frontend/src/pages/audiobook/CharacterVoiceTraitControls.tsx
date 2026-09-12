import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

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
  labelKey?: string
}

const VOICE_TYPE_OPTIONS: readonly SelectOption[] = [
  { value: 'majestic', label: '威严', labelKey: 'audiobook.characterVoiceTraits.majestic' },
  { value: 'gentle', label: '温柔', labelKey: 'audiobook.characterVoiceTraits.gentle' },
  { value: 'lively', label: '活泼', labelKey: 'audiobook.characterVoiceTraits.lively' },
  { value: 'weathered', label: '沧桑', labelKey: 'audiobook.characterVoiceTraits.weathered' },
  { value: 'warm', label: '温暖', labelKey: 'audiobook.characterVoiceTraits.warm' },
  { value: 'mysterious', label: '神秘', labelKey: 'audiobook.characterVoiceTraits.mysterious' },
  { value: 'powerful', label: '力量', labelKey: 'audiobook.characterVoiceTraits.powerful' },
  { value: 'scholarly', label: '书卷气', labelKey: 'audiobook.characterVoiceTraits.scholarly' },
  { value: 'playful', label: '俏皮', labelKey: 'audiobook.characterVoiceTraits.playful' },
  { value: 'cold', label: '清冷', labelKey: 'audiobook.characterVoiceTraits.cold' },
]

const PERSONALITY_OPTIONS: readonly SelectOption[] = [
  { value: 'introvert', label: '内向', labelKey: 'audiobook.characterVoiceTraits.introvert' },
  { value: 'extrovert', label: '外向', labelKey: 'audiobook.characterVoiceTraits.extrovert' },
  { value: 'ambitious', label: '野心', labelKey: 'audiobook.characterVoiceTraits.ambitious' },
  { value: 'calm', label: '冷静', labelKey: 'audiobook.characterVoiceTraits.calm' },
  { value: 'emotional', label: '感性', labelKey: 'audiobook.characterVoiceTraits.emotional' },
  { value: 'rational', label: '理性', labelKey: 'audiobook.characterVoiceTraits.rational' },
  { value: 'rebel', label: '叛逆', labelKey: 'audiobook.characterVoiceTraits.rebel' },
  { value: 'loyal', label: '忠诚', labelKey: 'audiobook.characterVoiceTraits.loyal' },
]

const EMOTION_TENDENCY_OPTIONS: readonly SelectOption[] = [
  { value: 'positive', label: '积极', labelKey: 'audiobook.characterVoiceTraits.positive' },
  { value: 'negative', label: '消极', labelKey: 'audiobook.characterVoiceTraits.negative' },
  { value: 'neutral', label: '中性', labelKey: 'audiobook.characterVoiceTraits.neutral' },
  { value: 'variable', label: '多变', labelKey: 'audiobook.characterVoiceTraits.variable' },
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
}: CharacterTraitSelectProps) => {
  const { t } = useTranslation()
  return (
    <FormControl size="small" sx={{ minWidth: 100 }}>
      <InputLabel>{label}</InputLabel>
      <Select
        label={label}
        value={value}
        onChange={(event) => onChange(event.target.value as string)}
      >
        <MenuItem value="">
          <em>{t('audiobook.characterVoiceTraits.auto')}</em>
        </MenuItem>
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {option.labelKey ? t(option.labelKey) : option.label}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  )
}

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
  const { t } = useTranslation()
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
        label={t('audiobook.characterVoiceTraits.voiceTypeLabel')}
        value={characterVoice.voiceType || ''}
        options={voiceTypeOptions}
        onChange={(value) => onVoiceTypeChange(characterId, value)}
      />
      <CharacterTraitSelect
        label={t('audiobook.characterVoiceTraits.personalityLabel')}
        value={characterVoice.personality || ''}
        options={PERSONALITY_OPTIONS}
        onChange={(value) => onPersonalityChange(characterId, value)}
      />
      <CharacterTraitSelect
        label={t('audiobook.characterVoiceTraits.emotionTendencyLabel')}
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
        {isRecommendingVoiceType
          ? t('audiobook.characterVoiceTraits.recommending')
          : t('audiobook.characterVoiceTraits.recommend')}
      </Button>
    </Box>
  )
}

export default CharacterVoiceTraitControls
