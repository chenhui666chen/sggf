import {
  Box,
  Button,
  Chip,
  CircularProgress,
  ListItem,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'

import {
  CharacterVoiceModelSelect,
  CharacterVoicePresetSelect,
  getCharacterModelChipColor,
} from './CharacterVoiceCardControls'
import { audiobookColors } from './audiobookTheme'
import {
  getTtsStyleControlLabels,
  getTtsModelLabel,
  modelUsesInlineCustomVoiceInput,
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
  projectTtsModel: TtsModel
  voiceLoading: boolean
  currentVoicePresets: VoicePreset[]
  voicePresetsByModel: Record<TtsModel, VoicePreset[]>
  ttsModelOptions: readonly TtsModelOption[]
  isPreviewing: boolean
  onVoiceChange: (characterId: number, voiceId: string) => void
  onTtsModelChangeForCharacter: (characterId: number, nextModel: TtsModel | 'inherit') => void
  onVoiceCloneDataUrlChange: (characterId: number, voiceCloneDataUrl: string) => void
  onPreviewCharacterVoice: (characterVoice: CharacterVoiceSetting) => void
}

const CharacterVoiceCard = ({
  characterVoice,
  projectTtsModel,
  voiceLoading,
  currentVoicePresets,
  voicePresetsByModel,
  ttsModelOptions,
  isPreviewing,
  onVoiceChange,
  onTtsModelChangeForCharacter,
  onVoiceCloneDataUrlChange,
  onPreviewCharacterVoice,
}: CharacterVoiceCardProps) => {
  const effectiveTtsModel = characterVoice.ttsModel || projectTtsModel
  const effectiveVoicePresets = voicePresetsByModel[effectiveTtsModel] || currentVoicePresets
  const effectiveModelRequiresCustomVoice = modelRequiresCustomVoice(effectiveTtsModel, ttsModelOptions)
  const usesInlineCustomVoiceInput = modelUsesInlineCustomVoiceInput(effectiveTtsModel, ttsModelOptions)
  const styleControlLabels = getTtsStyleControlLabels(effectiveTtsModel, ttsModelOptions)
  const hasInlineCustomVoiceInput = Boolean(characterVoice.voiceCloneDataUrl?.trim())
  const hasReusableMimoVoiceAsset = Boolean(characterVoice.mimoVoiceAssetId?.trim())
  const hasReusableStepAudioVoiceAsset = Boolean(characterVoice.stepaudioVoiceAssetId?.trim())
  const canPreview = Boolean(
    characterVoice.voiceId
    || hasInlineCustomVoiceInput
    || hasReusableMimoVoiceAsset
    || hasReusableStepAudioVoiceAsset,
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
            {(characterVoice.voiceId || hasInlineCustomVoiceInput || hasReusableMimoVoiceAsset || hasReusableStepAudioVoiceAsset) && (
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
          {usesInlineCustomVoiceInput ? (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              <CharacterVoicePresetSelect
                characterId={characterVoice.characterId}
                value={characterVoice.voiceId}
                requiresCustomVoice={effectiveModelRequiresCustomVoice}
                voiceLoading={voiceLoading}
                currentVoicePresets={effectiveVoicePresets}
                onVoiceChange={onVoiceChange}
              />
              {effectiveTtsModel === 'mimo-v2.5-tts-voiceclone' && (
                <TextField
                  label="audio.voice 样本"
                  value={characterVoice.voiceCloneDataUrl || ''}
                  onChange={(event) => onVoiceCloneDataUrlChange(characterVoice.characterId, event.target.value)}
                  placeholder="data:audio/mpeg;base64,... 或 data:audio/wav;base64,..."
                  size="small"
                  fullWidth
                  multiline
                  minRows={2}
                />
              )}
            </Box>
          ) : (
            <CharacterVoicePresetSelect
              characterId={characterVoice.characterId}
              value={characterVoice.voiceId}
              requiresCustomVoice={effectiveModelRequiresCustomVoice}
              voiceLoading={voiceLoading}
              currentVoicePresets={effectiveVoicePresets}
              onVoiceChange={onVoiceChange}
            />
          )}
          <CharacterVoiceModelSelect
            characterId={characterVoice.characterId}
            value={characterVoice.ttsModel}
            projectTtsModel={projectTtsModel}
            ttsModelOptions={ttsModelOptions}
            onTtsModelChangeForCharacter={onTtsModelChangeForCharacter}
          />
        </Box>

        {styleControlLabels.length > 0 && (
          <Box
            sx={{
              mb: 1,
              display: 'flex',
              alignItems: 'center',
              gap: 0.75,
              flexWrap: 'wrap',
            }}
          >
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              控制方式
            </Typography>
            {styleControlLabels.map((label) => (
              <Chip
                key={label}
                label={label}
                size="small"
                variant="outlined"
                sx={{
                  height: 20,
                  fontSize: '0.68rem',
                  borderColor: audiobookColors.surfaceBorder,
                  backgroundColor: 'rgba(255,255,255,0.72)',
                }}
              />
            ))}
          </Box>
        )}

        <Box sx={{ mt: 1, display: 'flex', justifyContent: 'flex-end' }}>
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
