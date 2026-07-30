import { useMemo, useState } from 'react'

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControlLabel,
  List,
  Switch,
  Typography,
} from '@mui/material'

import CharacterVoiceCard from './CharacterVoiceCard'
import { audiobookButtonSx, audiobookColors } from './audiobookTheme'
import { selectVisibleCharacterVoices } from './characterScopeUtils'
import type { TtsModelOption } from './ttsModels'
import type {
  CharacterVoiceSetting,
  TtsModel,
  VoicePreset,
} from './types'

interface CharacterVoiceConfigPanelProps {
  loadingCharacters: boolean
  characterScopeLoading: boolean
  characterScopeError: string | null
  scopedCharacterIds: number[]
  unresolvedCharacterNames: string[]
  characterVoices: CharacterVoiceSetting[]
  ttsModel: TtsModel
  voiceLoading: boolean
  currentVoicePresets: VoicePreset[]
  voicePresetsByModel: Record<TtsModel, VoicePreset[]>
  ttsModelOptions: readonly TtsModelOption[]
  previewingCharacterId: number | null
  autoAssigningVoices: boolean
  onVoiceChange: (characterId: number, voiceId: string, preset?: VoicePreset) => void
  onTtsModelChangeForCharacter: (characterId: number, nextModel: TtsModel) => void
  onPreviewCharacterVoice: (characterVoice: CharacterVoiceSetting) => void
  onOpenVoiceManagement: (model: TtsModel) => void
  onAutoAssignVoices: () => void
}

const CharacterVoiceConfigPanel = ({
  loadingCharacters,
  characterScopeLoading,
  characterScopeError,
  scopedCharacterIds,
  unresolvedCharacterNames,
  characterVoices,
  ttsModel,
  voiceLoading,
  currentVoicePresets,
  voicePresetsByModel,
  ttsModelOptions,
  previewingCharacterId,
  autoAssigningVoices,
  onVoiceChange,
  onTtsModelChangeForCharacter,
  onPreviewCharacterVoice,
  onOpenVoiceManagement,
  onAutoAssignVoices,
}: CharacterVoiceConfigPanelProps) => {
  const [showAllCharacters, setShowAllCharacters] = useState(false)
  const effectiveShowAll = showAllCharacters || Boolean(characterScopeError)
  const visibleCharacterVoices = useMemo(
    () => selectVisibleCharacterVoices({
      characterVoices,
      scopedCharacterIds,
      showAll: effectiveShowAll,
    }),
    [characterVoices, effectiveShowAll, scopedCharacterIds],
  )
  const projectCharacterCount = characterVoices.filter((voice) => voice.characterId !== 0).length
  const scopedCharacterCount = scopedCharacterIds.length

  return <Box sx={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
    <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
      不修改时使用 AI 默认音色；为角色选择音色后，本次有声书生成将优先使用你的配置。
    </Typography>

    {!loadingCharacters && (
      <Box
        sx={{
          mb: 1.25,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 1.5,
          flexWrap: 'wrap',
        }}
      >
        <Typography variant="body2" sx={{ fontWeight: 700 }}>
          {characterScopeLoading
            ? '正在识别所选章节人物...'
            : `本次人物 ${scopedCharacterCount} 位，项目共 ${projectCharacterCount} 位`}
        </Typography>
        {projectCharacterCount > scopedCharacterCount && !characterScopeError && (
          <FormControlLabel
            sx={{ m: 0 }}
            control={(
              <Switch
                size="small"
                checked={showAllCharacters}
                onChange={(event) => setShowAllCharacters(event.target.checked)}
              />
            )}
            label="显示全部人物"
          />
        )}
      </Box>
    )}

    {characterScopeError && (
      <Alert severity="warning" sx={{ mb: 1.25 }}>
        {characterScopeError}，已回退显示全部人物。
      </Alert>
    )}

    {!characterScopeError && unresolvedCharacterNames.length > 0 && (
      <Alert severity="warning" sx={{ mb: 1.25 }}>
        未关联人物卡：{unresolvedCharacterNames.join('、')}
      </Alert>
    )}

    {(loadingCharacters || characterScopeLoading) && (
      <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
        <CircularProgress size={24} />
      </Box>
    )}

    {!loadingCharacters && !characterScopeLoading && characterVoices.length === 0 && (
      <Box sx={{ py: 2 }}>
        <Typography variant="body2" color="text.secondary">
          当前项目还没有结构化角色档案，可在项目详情的角色管理中添加角色后再配置音色。
        </Typography>
      </Box>
    )}

    {!loadingCharacters && !characterScopeLoading && visibleCharacterVoices.length > 0 && (
      <Box
        sx={{
          flex: { xs: '0 1 auto', lg: '1 1 0' },
          minHeight: { lg: 0 },
          maxHeight: { xs: 430, lg: 'none' },
          overflow: 'auto',
          borderRadius: 1.5,
          border: `1px solid ${audiobookColors.surfaceBorder}`,
          backgroundColor: 'rgba(255,255,255,0.72)',
        }}
      >
        <List disablePadding>
          {visibleCharacterVoices.map((characterVoice) => (
            <CharacterVoiceCard
              key={characterVoice.characterId}
              characterVoice={characterVoice}
              defaultTtsModel={ttsModel}
              voiceLoading={voiceLoading}
              currentVoicePresets={currentVoicePresets}
              voicePresetsByModel={voicePresetsByModel}
              ttsModelOptions={ttsModelOptions}
              isPreviewing={previewingCharacterId === characterVoice.characterId}
              onVoiceChange={onVoiceChange}
              onTtsModelChangeForCharacter={onTtsModelChangeForCharacter}
              onPreviewCharacterVoice={onPreviewCharacterVoice}
              onOpenVoiceManagement={onOpenVoiceManagement}
            />
          ))}
        </List>
      </Box>
    )}

    {!loadingCharacters && !characterScopeLoading && (
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
  </Box>
}

export default CharacterVoiceConfigPanel
