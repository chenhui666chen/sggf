import {
  Box,
  Button,
  Chip,
  CircularProgress,
  ListItem,
  Tooltip,
  Typography,
} from '@mui/material'

import {
  CharacterVoiceModelSelect,
  CharacterVoicePresetSelect,
  CharacterVoiceTraitControls,
  CharacterVoiceTuningControls,
  getCharacterModelChipColor,
} from './CharacterVoiceCardControls'
import { audiobookColors } from './audiobookTheme'
import {
  getTtsModelLabel,
  modelRequiresCustomVoice,
  modelSupportsVoiceTuning,
} from './ttsModels'
import type { TtsModelOption } from './ttsModels'
import type {
  CharacterVoiceSetting,
  TtsModel,
  VoicePreset,
} from './types'

interface CharacterVoiceCardProps {
  characterVoice: CharacterVoiceSetting
  supportsTtsTuning: boolean
  projectTtsModel: TtsModel
  voiceLoading: boolean
  currentVoicePresets: VoicePreset[]
  voicePresetsByModel: Record<TtsModel, VoicePreset[]>
  ttsModelOptions: readonly TtsModelOption[]
  isPreviewing: boolean
  isRecommendingVoiceType: boolean
  onVoiceChange: (characterId: number, voiceId: string) => void
  onTtsModelChangeForCharacter: (characterId: number, nextModel: TtsModel | 'inherit') => void
  onVoiceTypeChange: (characterId: number, voiceType: string) => void
  onPersonalityChange: (characterId: number, personality: string) => void
  onEmotionTendencyChange: (characterId: number, emotionTendency: string) => void
  onRecommendVoiceType: (characterVoice: CharacterVoiceSetting) => void
  onVolumeChange: (characterId: number, volume: number) => void
  onSpeedChange: (characterId: number, speed: number) => void
  onPitchChange: (characterId: number, pitch: number) => void
  onPreviewCharacterVoice: (characterVoice: CharacterVoiceSetting) => void
}

const CharacterVoiceCard = ({
  characterVoice,
  supportsTtsTuning,
  projectTtsModel,
  voiceLoading,
  currentVoicePresets,
  voicePresetsByModel,
  ttsModelOptions,
  isPreviewing,
  isRecommendingVoiceType,
  onVoiceChange,
  onTtsModelChangeForCharacter,
  onVoiceTypeChange,
  onPersonalityChange,
  onEmotionTendencyChange,
  onRecommendVoiceType,
  onVolumeChange,
  onSpeedChange,
  onPitchChange,
  onPreviewCharacterVoice,
}: CharacterVoiceCardProps) => {
  const effectiveTtsModel = characterVoice.ttsModel || projectTtsModel
  const effectiveVoicePresets = voicePresetsByModel[effectiveTtsModel] || currentVoicePresets
  const supportsEffectiveTuning = modelSupportsVoiceTuning(effectiveTtsModel, ttsModelOptions)
  const effectiveModelRequiresCustomVoice = modelRequiresCustomVoice(effectiveTtsModel, ttsModelOptions)

  return (
    <ListItem
      alignItems="flex-start"
      sx={{
        alignItems: 'stretch',
        py: 1.25,
        px: 1.25,
        borderBottom: `1px solid ${audiobookColors.surfaceBorder}`,
        '&:last-of-type': {
          borderBottom: 0,
        },
        '&:hover': {
          backgroundColor: audiobookColors.brandFaint,
        },
      }}
    >
      <Box sx={{ width: '100%' }}>
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 1,
            mb: 1,
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            <Typography
              variant="subtitle2"
              sx={{
                fontWeight: 700,
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {characterVoice.name}
            </Typography>
            {(characterVoice.role || characterVoice.gender) && (
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{
                  display: 'block',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {characterVoice.role || '角色'} · {characterVoice.gender || '性别未设定'}
              </Typography>
            )}
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {characterVoice.ttsModel && characterVoice.ttsModel !== projectTtsModel && (
              <Chip
                label={getTtsModelLabel(characterVoice.ttsModel)}
                size="small"
                color={getCharacterModelChipColor(characterVoice.ttsModel, ttsModelOptions)}
                sx={{ height: 18, fontSize: '0.65rem' }}
              />
            )}
            {characterVoice.voiceId && (
              <Chip
                label="已配置"
                size="small"
                color="success"
                sx={{ height: 18 }}
              />
            )}
          </Box>
        </Box>

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1fr) 180px' }, gap: 1, mb: 1 }}>
          <CharacterVoicePresetSelect
            characterId={characterVoice.characterId}
            value={characterVoice.voiceId}
            requiresCustomVoice={effectiveModelRequiresCustomVoice}
            voiceLoading={voiceLoading}
            currentVoicePresets={effectiveVoicePresets}
            onVoiceChange={onVoiceChange}
          />
          <CharacterVoiceModelSelect
            characterId={characterVoice.characterId}
            value={characterVoice.ttsModel}
            projectTtsModel={projectTtsModel}
            ttsModelOptions={ttsModelOptions}
            onTtsModelChangeForCharacter={onTtsModelChangeForCharacter}
          />
        </Box>

        <CharacterVoiceTraitControls
          characterVoice={characterVoice}
          onVoiceTypeChange={onVoiceTypeChange}
          onPersonalityChange={onPersonalityChange}
          onEmotionTendencyChange={onEmotionTendencyChange}
          onRecommendVoiceType={onRecommendVoiceType}
          isRecommendingVoiceType={isRecommendingVoiceType}
        />

        {(supportsTtsTuning || supportsEffectiveTuning) && (
          <CharacterVoiceTuningControls
            characterVoice={characterVoice}
            onVolumeChange={onVolumeChange}
            onSpeedChange={onSpeedChange}
            onPitchChange={onPitchChange}
          />
        )}

        <Box sx={{ mt: 1, display: 'flex', justifyContent: 'flex-end' }}>
          <Tooltip title="云端精确试听效果，请稍作等待...">
            <span>
              <Button
                size="small"
                variant="outlined"
                onClick={() => onPreviewCharacterVoice(characterVoice)}
                disabled={!characterVoice.voiceId || isPreviewing}
                startIcon={isPreviewing ? <CircularProgress size={16} color="inherit" /> : undefined}
              >
                {isPreviewing ? '试听中...' : '试听'}
              </Button>
            </span>
          </Tooltip>
        </Box>
      </Box>
    </ListItem>
  )
}

export default CharacterVoiceCard
