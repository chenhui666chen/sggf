import {
  Box,
  Button,
  CircularProgress,
  List,
  Paper,
  Typography,
} from '@mui/material'
import AudioIcon from '@mui/icons-material/GraphicEq'

import CharacterVoiceCard from './CharacterVoiceCard'
import { audiobookButtonSx } from './audiobookTheme'
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
    <Typography variant="subtitle1" sx={{ mb: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
      <AudioIcon fontSize="small" />
      {supportsTtsTuning ? '角色音与音量配置' : '角色音配置'}
    </Typography>
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
      <Paper
        variant="outlined"
        sx={{
          maxHeight: 400,
          overflow: 'auto',
          p: 1,
        }}
      >
        <List>
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
      </Paper>
    )}

    {!loadingCharacters && (
      <Box sx={{ mt: 2, display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
        <Button
          size="small"
          variant="outlined"
          onClick={onAutoAssignVoices}
          disabled={autoAssigningVoices}
          sx={audiobookButtonSx.brandOutlined}
        >
          {autoAssigningVoices ? '智能推荐中...' : '基于人物卡自动推荐声线'}
        </Button>
      </Box>
    )}
  </>
)

export default CharacterVoiceConfigPanel
