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
} from './CharacterVoiceCardControls'
import { audiobookColors } from './audiobookTheme'
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
  onVoiceChange: (characterId: number, voiceId: string) => void
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
  const effectiveTtsModel = characterVoice.ttsModel || defaultTtsModel
  const effectiveVoicePresets = voicePresetsByModel[effectiveTtsModel] || currentVoicePresets
  const effectiveModelRequiresCustomVoice = modelRequiresCustomVoice(effectiveTtsModel, ttsModelOptions)
  const canPreview = Boolean(characterVoice.voiceId.trim())

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
          <Tooltip title="创建、试听和管理克隆/设计音色">
            <Button
              size="small"
              variant="outlined"
              onClick={() => onOpenVoiceManagement(effectiveTtsModel)}
            >
              音色管理
            </Button>
          </Tooltip>
          <Tooltip title="云端精确试听效果，请稍作等待...">
            <span>
              <Button
                size="small"
                variant="outlined"
                onClick={() => onPreviewCharacterVoice(characterVoice)}
                disabled={!canPreview || isPreviewing}
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
