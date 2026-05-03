import type { ChangeEvent, MouseEvent } from 'react'

import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Typography,
} from '@mui/material'
import VoiceIcon from '@mui/icons-material/RecordVoiceOver'

import CharacterVoiceConfigPanel from './CharacterVoiceConfigPanel'
import ChapterSelectionPanel from './ChapterSelectionPanel'
import NarrationAudioConfigPanel from './NarrationAudioConfigPanel'
import VoiceCatalogStatusPanel from './VoiceCatalogStatusPanel'
import type { NarrationStyleId } from './narrationStyles'
import type { TtsModelOption } from './ttsModels'
import type {
  AudioFxConfig,
  AudioOutputFormat,
  Chapter,
  CharacterVoiceSetting,
  TtsModel,
  VoiceCatalogMeta,
  VoicePreset,
} from './types'

interface AudiobookSetupStepProps {
  selectedChapterCount: number
  chapterCount: number
  scriptOnlyMode: boolean
  onScriptOnlyModeChange: (value: boolean) => void
  forceRegenerateScript: boolean
  onForceRegenerateScriptChange: (value: boolean) => void
  ttsModel: TtsModel
  ttsModelOptions: readonly TtsModelOption[]
  voiceCatalogMeta: VoiceCatalogMeta | null
  voiceCatalogSummary: string
  voiceCatalogNotice: string
  voiceCatalogNoticeSeverity: 'success' | 'warning' | 'info'
  showCustomVoiceWorkbench: boolean
  voiceError: string | null
  voiceLoading: boolean
  cloneName: string
  cloneUrl: string
  cloneLoading: boolean
  cloneUploading: boolean
  cloneRecording: boolean
  cloneDeletingId: string | null
  cloneError: string | null
  cloneSuccess: string | null
  cloneRecordDialogOpen: boolean
  designName: string
  designPrompt: string
  designPreviewText: string
  designLoading: boolean
  designError: string | null
  designSuccess: string | null
  customVoicePresets: VoicePreset[]
  narrationStyle: NarrationStyleId
  narrationStylePrompt: string
  outputFormat: AudioOutputFormat
  generateSubtitle: boolean
  audioFxConfig: AudioFxConfig
  chapters: Chapter[]
  selectedChapters: number[]
  supportsTtsTuning: boolean
  loadingCharacters: boolean
  characterVoices: CharacterVoiceSetting[]
  currentVoicePresets: VoicePreset[]
  voicePresetsByModel: Record<TtsModel, VoicePreset[]>
  previewingCharacterId: number | null
  recommendingVoiceTypeId: number | null
  autoAssigningVoices: boolean
  generateDisabled: boolean
  onFetchVoiceCatalog: () => void
  onCloneNameChange: (value: string) => void
  onCloneUrlChange: (value: string) => void
  onCreateCloneVoice: () => void
  onOpenCloneRecordDialog: () => void
  onUploadCloneAudio: (event: ChangeEvent<HTMLInputElement>) => void
  onDesignNameChange: (value: string) => void
  onDesignPromptChange: (value: string) => void
  onDesignPreviewTextChange: (value: string) => void
  onCreateDesignVoice: () => void
  onDeleteCustomVoice: (voiceId: string, label?: string) => void
  onCloseCloneRecordDialog: () => void
  onStartCloneRecording: () => void
  onStopCloneRecording: () => void
  onNarrationStyleChange: (value: NarrationStyleId) => void
  onNarrationStylePromptChange: (value: string) => void
  onOutputFormatChange: (value: AudioOutputFormat) => void
  onGenerateSubtitleChange: (value: boolean) => void
  onAudioFxConfigChange: (value: AudioFxConfig) => void
  onTtsModelChange: (value: TtsModel) => void
  onToggleAllChapters: () => void
  onToggleChapter: (chapterId: number) => void
  onOpenChapterMenu: (event: MouseEvent<HTMLButtonElement>, chapter: Chapter) => void
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
  onGenerate: () => void
}

const AudiobookSetupStep = ({
  selectedChapterCount,
  chapterCount,
  scriptOnlyMode,
  onScriptOnlyModeChange,
  forceRegenerateScript,
  onForceRegenerateScriptChange,
  ttsModel,
  ttsModelOptions,
  voiceCatalogMeta,
  voiceCatalogSummary,
  voiceCatalogNotice,
  voiceCatalogNoticeSeverity,
  showCustomVoiceWorkbench,
  voiceError,
  voiceLoading,
  cloneName,
  cloneUrl,
  cloneLoading,
  cloneUploading,
  cloneRecording,
  cloneDeletingId,
  cloneError,
  cloneSuccess,
  cloneRecordDialogOpen,
  designName,
  designPrompt,
  designPreviewText,
  designLoading,
  designError,
  designSuccess,
  customVoicePresets,
  narrationStyle,
  narrationStylePrompt,
  outputFormat,
  generateSubtitle,
  audioFxConfig,
  chapters,
  selectedChapters,
  supportsTtsTuning,
  loadingCharacters,
  characterVoices,
  currentVoicePresets,
  voicePresetsByModel,
  previewingCharacterId,
  recommendingVoiceTypeId,
  autoAssigningVoices,
  generateDisabled,
  onFetchVoiceCatalog,
  onCloneNameChange,
  onCloneUrlChange,
  onCreateCloneVoice,
  onOpenCloneRecordDialog,
  onUploadCloneAudio,
  onDesignNameChange,
  onDesignPromptChange,
  onDesignPreviewTextChange,
  onCreateDesignVoice,
  onDeleteCustomVoice,
  onCloseCloneRecordDialog,
  onStartCloneRecording,
  onStopCloneRecording,
  onNarrationStyleChange,
  onNarrationStylePromptChange,
  onOutputFormatChange,
  onGenerateSubtitleChange,
  onAudioFxConfigChange,
  onTtsModelChange,
  onToggleAllChapters,
  onToggleChapter,
  onOpenChapterMenu,
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
  onGenerate,
}: AudiobookSetupStepProps) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
    <Box component="section" sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
        <VoiceIcon sx={{ color: 'primary.main' }} />
        配置章节与角色音
      </Typography>

      <Alert severity="info">
        已选择 {selectedChapterCount}/{chapterCount} 个章节。未配置的角色将由 AI 自动分配音色和音量。
      </Alert>
    </Box>

    <Box component="section" sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        项目默认
      </Typography>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
        <FormControl size="small" sx={{ minWidth: { xs: '100%', sm: 280 } }}>
          <InputLabel>项目默认 TTS 模型</InputLabel>
          <Select
            label="项目默认 TTS 模型"
            value={ttsModel}
            onChange={(event) => onTtsModelChange(event.target.value as TtsModel)}
          >
            {ttsModelOptions.map((option) => (
              <MenuItem key={option.id} value={option.id}>
                <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                  <span>{option.name}</span>
                  {(option.voiceCount !== undefined || option.description) && (
                    <Typography variant="caption" color="text.secondary">
                      {option.voiceCount !== undefined ? `${option.voiceCount} 个音色` : ''}
                      {option.voiceCount !== undefined && option.description ? ' · ' : ''}
                      {option.description || ''}
                    </Typography>
                  )}
                </Box>
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        <FormControlLabel
          control={
            <Checkbox
              checked={scriptOnlyMode}
              onChange={(_, checked) => onScriptOnlyModeChange(checked)}
              color="primary"
            />
          }
          label="仅生成剧本和评审（稍后再生成音频）"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={forceRegenerateScript}
              onChange={(_, checked) => onForceRegenerateScriptChange(checked)}
              color="primary"
            />
          }
          label="重新生成剧本（不复用旧剧本）"
        />
      </Box>

      <VoiceCatalogStatusPanel
        voiceCatalogMeta={voiceCatalogMeta}
        voiceCatalogSummary={voiceCatalogSummary}
        voiceCatalogNotice={voiceCatalogNotice}
        voiceCatalogNoticeSeverity={voiceCatalogNoticeSeverity}
        showCustomVoiceWorkbench={showCustomVoiceWorkbench}
        voiceError={voiceError}
        voiceLoading={voiceLoading}
        cloneName={cloneName}
        cloneUrl={cloneUrl}
        cloneLoading={cloneLoading}
        cloneUploading={cloneUploading}
        cloneRecording={cloneRecording}
        cloneDeletingId={cloneDeletingId}
        cloneError={cloneError}
        cloneSuccess={cloneSuccess}
        cloneRecordDialogOpen={cloneRecordDialogOpen}
        designName={designName}
        designPrompt={designPrompt}
        designPreviewText={designPreviewText}
        designLoading={designLoading}
        designError={designError}
        designSuccess={designSuccess}
        customVoicePresets={customVoicePresets}
        onFetchVoiceCatalog={onFetchVoiceCatalog}
        onCloneNameChange={onCloneNameChange}
        onCloneUrlChange={onCloneUrlChange}
        onCreateCloneVoice={onCreateCloneVoice}
        onOpenCloneRecordDialog={onOpenCloneRecordDialog}
        onUploadCloneAudio={onUploadCloneAudio}
        onDesignNameChange={onDesignNameChange}
        onDesignPromptChange={onDesignPromptChange}
        onDesignPreviewTextChange={onDesignPreviewTextChange}
        onCreateDesignVoice={onCreateDesignVoice}
        onDeleteCustomVoice={onDeleteCustomVoice}
        onCloseCloneRecordDialog={onCloseCloneRecordDialog}
        onStartCloneRecording={onStartCloneRecording}
        onStopCloneRecording={onStopCloneRecording}
      />
    </Box>

    <Box component="section" sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        音频与导出
      </Typography>
      <NarrationAudioConfigPanel
        narrationStyle={narrationStyle}
        narrationStylePrompt={narrationStylePrompt}
        ttsModel={ttsModel}
        outputFormat={outputFormat}
        generateSubtitle={generateSubtitle}
        audioFxConfig={audioFxConfig}
        onNarrationStyleChange={onNarrationStyleChange}
        onNarrationStylePromptChange={onNarrationStylePromptChange}
        onOutputFormatChange={onOutputFormatChange}
        onGenerateSubtitleChange={onGenerateSubtitleChange}
        onAudioFxConfigChange={onAudioFxConfigChange}
      />
    </Box>

    <Box component="section" sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
        章节与角色音
      </Typography>

      <Grid container spacing={3}>
        <Grid item xs={12} md={6}>
          <ChapterSelectionPanel
            chapters={chapters}
            selectedChapters={selectedChapters}
            onToggleAll={onToggleAllChapters}
            onToggleChapter={onToggleChapter}
            onOpenChapterMenu={onOpenChapterMenu}
          />
        </Grid>

        <Grid item xs={12} md={6}>
          <CharacterVoiceConfigPanel
            supportsTtsTuning={supportsTtsTuning}
            loadingCharacters={loadingCharacters}
            characterVoices={characterVoices}
            ttsModel={ttsModel}
            voiceLoading={voiceLoading}
            currentVoicePresets={currentVoicePresets}
            voicePresetsByModel={voicePresetsByModel}
            ttsModelOptions={ttsModelOptions}
            previewingCharacterId={previewingCharacterId}
            recommendingVoiceTypeId={recommendingVoiceTypeId}
            autoAssigningVoices={autoAssigningVoices}
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
            onAutoAssignVoices={onAutoAssignVoices}
          />
        </Grid>
      </Grid>
    </Box>

    <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
      <Button
        variant="contained"
        onClick={onGenerate}
        disabled={generateDisabled}
        color="primary"
      >
        开始生成 ({selectedChapterCount}章)
      </Button>
    </Box>
  </Box>
)

export default AudiobookSetupStep
