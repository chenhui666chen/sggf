import {
  Box,
  Button,
  CircularProgress,
  List,
  Typography,
} from '@mui/material'

import CharacterVoiceCard from './CharacterVoiceCard'
import { audiobookButtonSx, audiobookColors } from './audiobookTheme'
import type { TtsModelOption } from './ttsModels'
import type {
  CharacterVoiceSetting,
  TtsModel,
  VoicePreset,
} from './types'

interface CharacterVoiceConfigPanelProps {
  supportsTtsTuning: boolean
  loadingCharacters: boolean
  characterVoices: CharacterVoiceSetting[]
  ttsModel: TtsModel
  voiceLoading: boolean
  currentVoicePresets: VoicePreset[]
  voicePresetsByModel: Record<TtsModel, VoicePreset[]>
  ttsModelOptions: readonly TtsModelOption[]
  previewingCharacterId: number | null
  recommendingVoiceTypeId: number | null
  autoAssigningVoices: boolean
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
  onAutoAssignVoices: () => void
}

const CharacterVoiceConfigPanel = ({
  supportsTtsTuning,
  loadingCharacters,
  characterVoices,
  ttsModel,
  voiceLoading,
  currentVoicePresets,
  voicePresetsByModel,
  ttsModelOptions,
  previewingCharacterId,
  recommendingVoiceTypeId,
  autoAssigningVoices,
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
  onAutoAssignVoices,
}: CharacterVoiceConfigPanelProps) => (
  <>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
      {supportsTtsTuning
        ? '不修改时使用 AI 默认音色；为角色选择音色或调整音量、语速、音高后，本次有声书生成将优先使用你的配置。'
        : '不修改时使用 AI 默认音色；为角色选择音色后，本次有声书生成将优先使用你的配置。'}
    </Typography>

    {loadingCharacters && (
      <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress size={24} />
      </Box>
    )}

    {!loadingCharacters && characterVoices.length === 0 && (
      <Box sx={{ py: 2 }}>
        <Typography variant="body2" color="text.secondary">
          当前项目还没有结构化角色档案，可在项目详情的角色管理中添加角色后再配置音色。
        </Typography>
      </Box>
    )}

    {!loadingCharacters && characterVoices.length > 0 && (
      <Box
        sx={{
          maxHeight: { xs: 430, lg: 560 },
          overflow: 'auto',
          borderRadius: 1.5,
          border: `1px solid ${audiobookColors.surfaceBorder}`,
          backgroundColor: 'rgba(255,255,255,0.72)',
        }}
      >
        <List disablePadding>
          {characterVoices.map((characterVoice) => (
            <CharacterVoiceCard
              key={characterVoice.characterId}
              characterVoice={characterVoice}
              supportsTtsTuning={supportsTtsTuning}
              projectTtsModel={ttsModel}
              voiceLoading={voiceLoading}
              currentVoicePresets={currentVoicePresets}
              voicePresetsByModel={voicePresetsByModel}
              ttsModelOptions={ttsModelOptions}
              isPreviewing={previewingCharacterId === characterVoice.characterId}
              isRecommendingVoiceType={recommendingVoiceTypeId === characterVoice.characterId}
              onVoiceChange={onVoiceChange}
              onTtsModelChangeForCharacter={onTtsModelChangeForCharacter}
              onVoiceTypeChange={onVoiceTypeChange}
              onPersonalityChange={onPersonalityChange}
              onEmotionTendencyChange={onEmotionTendencyChange}
              onRecommendVoiceType={onRecommendVoiceType}
              onVolumeChange={onVolumeChange}
              onSpeedChange={onSpeedChange}
              onPitchChange={onPitchChange}
              onPreviewCharacterVoice={onPreviewCharacterVoice}
            />
          ))}
        </List>
      </Box>
    )}

    {!loadingCharacters && (
      <Box sx={{ mt: 1.5, display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        <Button
          size="small"
          variant="outlined"
          onClick={onAutoAssignVoices}
          disabled={autoAssigningVoices}
          startIcon={autoAssigningVoices ? <CircularProgress size={16} color="inherit" /> : undefined}
          sx={audiobookButtonSx.brandOutlined}
        >
          {autoAssigningVoices ? '智能推荐中...' : '基于人物卡自动推荐声线'}
        </Button>
      </Box>
    )}
  </>
)

export default CharacterVoiceConfigPanel
