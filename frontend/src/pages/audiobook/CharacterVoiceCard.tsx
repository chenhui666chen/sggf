import {
  Box,
  Button,
  Chip,
  CircularProgress,
  ListItem,
  Tooltip,
  Typography,
} from '@mui/material'

import { useTranslation } from 'react-i18next'

import {
  CharacterVoiceModelSelect,
  CharacterVoicePresetSelect,
} from './CharacterVoiceCardControls'
import { audiobookColors } from './audiobookTheme'
import { SEED_SCENE_INCOMPATIBLE_VOICE_REASON } from './seedSceneVoiceCompatibility'
import {
  modelRequiresCustomVoice,
} from './ttsModels'
import type { TtsModelOption } from './ttsModels'
import type {
  CharacterVoiceSetting,
  TtsModel,
  VoicePreset,
} from './types'

interface CharacterVoiceCardProps {
  characterVoice: CharacterVoiceSetting
  defaultTtsModel: TtsModel
  voiceLoading: boolean
  currentVoicePresets: VoicePreset[]
  voicePresetsByModel: Record<TtsModel, VoicePreset[]>
  ttsModelOptions: readonly TtsModelOption[]
  isPreviewing: boolean
  onVoiceChange: (characterId: number, voiceId: string, preset?: VoicePreset) => void
  onTtsModelChangeForCharacter: (characterId: number, nextModel: TtsModel) => void
  onPreviewCharacterVoice: (characterVoice: CharacterVoiceSetting) => void
  onOpenVoiceManagement: (model: TtsModel) => void
}

const CharacterVoiceCard = ({
  characterVoice,
  defaultTtsModel,
  voiceLoading,
  currentVoicePresets,
  voicePresetsByModel,
  ttsModelOptions,
  isPreviewing,
  onVoiceChange,
  onTtsModelChangeForCharacter,
  onPreviewCharacterVoice,
  onOpenVoiceManagement,
}: CharacterVoiceCardProps) => {
  const { t } = useTranslation()
  const effectiveTtsModel = characterVoice.ttsModel || defaultTtsModel
  const effectiveVoicePresets = voicePresetsByModel[effectiveTtsModel] || currentVoicePresets
  const effectiveModelRequiresCustomVoice = modelRequiresCustomVoice(effectiveTtsModel, ttsModelOptions)
  const canPreview = Boolean(characterVoice.voiceId.trim())
  // 已配置音色被白名单标记为不兼容（场景生成模式下的其他供应商官方音色）时给出警告
  const currentPreset = effectiveVoicePresets.find((preset) => preset.id === characterVoice.voiceId)
  const voiceIncompatible = Boolean(
    characterVoice.voiceId
    && currentPreset?.disabled
    && currentPreset.disabledReason === SEED_SCENE_INCOMPATIBLE_VOICE_REASON,
  )

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
                {characterVoice.role || t('audiobook.characterVoiceCard.defaultRole')} · {characterVoice.gender || t('audiobook.characterVoiceCard.genderUnset')}
              </Typography>
            )}
          </Box>
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {characterVoice.voiceId && (
              <Chip
                label={voiceIncompatible ? t('audiobook.characterVoiceCard.configuredIncompatible') : t('audiobook.characterVoiceCard.configured')}
                size="small"
                color={voiceIncompatible ? 'warning' : 'success'}
                sx={{ height: 18 }}
              />
            )}
          </Box>
        </Box>

        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '180px minmax(0, 1fr)' }, gap: 1, mb: 1 }}>
          <CharacterVoiceModelSelect
            characterId={characterVoice.characterId}
            value={effectiveTtsModel}
            ttsModelOptions={ttsModelOptions}
            onTtsModelChangeForCharacter={onTtsModelChangeForCharacter}
          />
          <CharacterVoicePresetSelect
            characterId={characterVoice.characterId}
            value={characterVoice.voiceId}
            requiresCustomVoice={effectiveModelRequiresCustomVoice}
            voiceLoading={voiceLoading}
            currentVoicePresets={effectiveVoicePresets}
            onVoiceChange={onVoiceChange}
          />
        </Box>

        <Box sx={{ mt: 1, display: 'flex', justifyContent: 'flex-end', gap: 1, flexWrap: 'wrap' }}>
          <Tooltip title={t('audiobook.characterVoiceCard.manageTooltip')}>
            <Button
              size="small"
              variant="outlined"
              onClick={() => onOpenVoiceManagement(effectiveTtsModel)}
            >
              {t('audiobook.characterVoiceCard.manage')}
            </Button>
          </Tooltip>
          <Tooltip title={t('audiobook.characterVoiceCard.previewTooltip')}>
            <span>
              <Button
                size="small"
                variant="outlined"
                onClick={() => onPreviewCharacterVoice(characterVoice)}
                disabled={!canPreview || isPreviewing}
                startIcon={isPreviewing ? <CircularProgress size={16} color="inherit" /> : undefined}
              >
                {isPreviewing ? t('audiobook.characterVoiceCard.previewing') : t('audiobook.characterVoiceCard.preview')}
              </Button>
            </span>
          </Tooltip>
        </Box>
      </Box>
    </ListItem>
  )
}

export default CharacterVoiceCard
