import { useMemo, useState, type MouseEvent, type ReactNode } from 'react'

import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import LibraryMusicIcon from '@mui/icons-material/LibraryMusic'
import PlaylistAddCheckIcon from '@mui/icons-material/PlaylistAddCheck'
import VoiceIcon from '@mui/icons-material/RecordVoiceOver'

import CharacterVoiceConfigPanel from './CharacterVoiceConfigPanel'
import ChapterSelectionPanel from './ChapterSelectionPanel'
import NarrationAudioConfigPanel from './NarrationAudioConfigPanel'
import VoiceCatalogStatusPanel from './VoiceCatalogStatusPanel'
import {
  audiobookButtonRowSx,
  audiobookColors,
  audiobookPanelHeaderSx,
  audiobookPanelSx,
} from './audiobookTheme'
import type { CosyVoiceWorkbench } from './CosyVoiceVoiceWorkbench'
import {
  findTtsModelOption,
  getTtsModelLabel,
  modelRequiresCustomVoice,
  modelSupportsCustomVoiceWorkbench,
  type TtsModelOption,
} from './ttsModels'
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
  ttsModel: TtsModel
  ttsModelOptions: readonly TtsModelOption[]
  voiceError: string | null
  voiceLoading: boolean
  cosyVoiceWorkbench: CosyVoiceWorkbench
  outputFormat: AudioOutputFormat
  generateSubtitle: boolean
  audioFxConfig: AudioFxConfig
  chapters: Chapter[]
  selectedChapters: number[]
  generatedChapterIds: ReadonlySet<number>
  loadingCharacters: boolean
  characterScopeLoading: boolean
  characterScopeError: string | null
  scopedCharacterIds: number[]
  unresolvedCharacterNames: string[]
  characterVoices: CharacterVoiceSetting[]
  currentVoicePresets: VoicePreset[]
  voicePresetsByModel: Record<TtsModel, VoicePreset[]>
  voiceCatalogMetaByModel: Record<TtsModel, VoiceCatalogMeta | null>
  previewingCharacterId: number | null
  customVoicePreviewingId: string | null
  autoAssigningVoices: boolean
  generateDisabled: boolean
  generateDisabledReason: string
  onFetchVoiceCatalog: (model: TtsModel) => void
  onOutputFormatChange: (value: AudioOutputFormat) => void
  onGenerateSubtitleChange: (value: boolean) => void
  onAudioFxConfigChange: (value: AudioFxConfig) => void
  onToggleChapter: (chapterId: number) => void
  onOpenChapterMenu: (event: MouseEvent<HTMLButtonElement>, chapter: Chapter) => void
  onVoiceChange: (characterId: number, voiceId: string) => void
  onTtsModelChangeForCharacter: (characterId: number, nextModel: TtsModel) => void
  onPreviewCustomVoice: (voice: VoicePreset, model?: TtsModel) => void
  onPreviewCharacterVoice: (characterVoice: CharacterVoiceSetting) => void
  onAutoAssignVoices: () => void
  onGenerate: () => void
}

interface SetupPanelProps {
  icon: ReactNode
  title: string
  subtitle?: string
  action?: ReactNode
  children: ReactNode
  sx?: object
}

const SetupPanel = ({
  icon,
  title,
  subtitle,
  action,
  children,
  sx,
}: SetupPanelProps) => (
  <Paper
    component="section"
    variant="outlined"
    sx={{
      ...audiobookPanelSx,
      p: { xs: 2, md: 2.5 },
      ...sx,
    }}
  >
    <Box sx={audiobookPanelHeaderSx}>
      <Box sx={{ minWidth: 0, display: 'flex', alignItems: 'center', gap: 1.25 }}>
        <Box
          sx={{
            width: 34,
            height: 34,
            borderRadius: 1.5,
            display: 'grid',
            placeItems: 'center',
            flexShrink: 0,
            color: audiobookColors.brand,
            backgroundColor: audiobookColors.brandSoft,
          }}
        >
          {icon}
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 700, lineHeight: 1.25 }}>
            {title}
          </Typography>
          {subtitle && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.25 }}>
              {subtitle}
            </Typography>
          )}
        </Box>
      </Box>
      {action && <Box sx={{ flexShrink: 0 }}>{action}</Box>}
    </Box>
    {children}
  </Paper>
)

const AudiobookSetupStep = ({
  selectedChapterCount,
  ttsModel,
  ttsModelOptions,
  voiceError,
  voiceLoading,
  cosyVoiceWorkbench,
  outputFormat,
  generateSubtitle,
  audioFxConfig,
  chapters,
  selectedChapters,
  generatedChapterIds,
  loadingCharacters,
  characterScopeLoading,
  characterScopeError,
  scopedCharacterIds,
  unresolvedCharacterNames,
  characterVoices,
  currentVoicePresets,
  voicePresetsByModel,
  voiceCatalogMetaByModel,
  previewingCharacterId,
  customVoicePreviewingId,
  autoAssigningVoices,
  generateDisabled,
  generateDisabledReason,
  onFetchVoiceCatalog,
  onOutputFormatChange,
  onGenerateSubtitleChange,
  onAudioFxConfigChange,
  onToggleChapter,
  onOpenChapterMenu,
  onVoiceChange,
  onTtsModelChangeForCharacter,
  onPreviewCustomVoice,
  onPreviewCharacterVoice,
  onAutoAssignVoices,
  onGenerate,
}: AudiobookSetupStepProps) => {
  const [voiceManagementOpen, setVoiceManagementOpen] = useState(false)
  const [voiceManagementModel, setVoiceManagementModel] = useState<TtsModel>(ttsModel)

  const handleOpenVoiceManagement = (model: TtsModel) => {
    setVoiceManagementModel(model)
    setVoiceManagementOpen(true)
  }

  const voiceManagementOption = findTtsModelOption(voiceManagementModel, ttsModelOptions)
  const voiceManagementPresets = voicePresetsByModel[voiceManagementModel] || []
  const voiceManagementCustomPresets = useMemo(
    () => voiceManagementPresets.filter((preset) => preset.category === 'custom'),
    [voiceManagementPresets],
  )
  const voiceManagementMeta = voiceCatalogMetaByModel[voiceManagementModel] || null
  const voiceManagementRequiresCustomVoice = modelRequiresCustomVoice(voiceManagementModel, ttsModelOptions)
  const voiceManagementSummary = useMemo(() => {
    if (!voiceManagementMeta) return ''
    const modelLabel = voiceManagementOption?.name || getTtsModelLabel(voiceManagementModel)
    const updatedAt = voiceManagementMeta.updated_at || '—'
    if (voiceManagementRequiresCustomVoice) {
      return `${modelLabel}：当前展示 ${voiceManagementPresets.length} 个可用自定义音色，最近同步 ${updatedAt}。`
    }
    const voiceCount = voiceManagementMeta.voice_count ?? voiceManagementPresets.length
    return `${modelLabel}：官方 ${voiceCount} 种音色，最近更新 ${updatedAt}。`
  }, [
    voiceManagementMeta,
    voiceManagementModel,
    voiceManagementOption?.name,
    voiceManagementPresets.length,
    voiceManagementRequiresCustomVoice,
  ])
  const voiceManagementNotice = useMemo(() => {
    const modelLabel = voiceManagementOption?.name || getTtsModelLabel(voiceManagementModel)
    if (voiceManagementOption?.catalogStatus === 'unavailable') {
      return `${modelLabel}：${voiceManagementOption.catalogError || '音色目录不可用，请检查后端 voice catalog 配置。'}`
    }
    if (voiceManagementOption?.runtimeStatus === 'unavailable') {
      return `${modelLabel}：${voiceManagementOption.runtimeError || 'TTS 运行时模型不可用，请检查后端 adapter 注册。'}`
    }
    if (voiceManagementOption?.source === 'fallback') {
      return voiceLoading
        ? `${modelLabel}：正在同步后端模型目录与音色目录。`
        : `${modelLabel}：暂时使用前端内置模型配置，后端模型目录未返回该模型。`
    }
    return voiceManagementOption?.catalogNote
      ? `${modelLabel}：${voiceManagementOption.catalogNote}`
      : `${modelLabel}：使用后端模型目录与音色目录配置。`
  }, [voiceLoading, voiceManagementModel, voiceManagementOption])
  const voiceManagementNoticeSeverity = voiceManagementOption?.catalogStatus === 'unavailable'
    || voiceManagementOption?.runtimeStatus === 'unavailable'
    ? 'warning'
    : voiceManagementOption?.source === 'fallback'
      ? (voiceLoading ? 'info' : 'warning')
      : 'success'

  return (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', lg: 'minmax(360px, 0.92fr) minmax(0, 1.38fr)' },
        gap: 2.5,
        alignItems: { xs: 'start', lg: 'stretch' },
      }}
    >
      <Stack spacing={2.5} sx={{ minWidth: 0 }}>
        <SetupPanel
          icon={<PlaylistAddCheckIcon fontSize="small" />}
          title="章节队列"
          subtitle="选择一个未生成章节"
        >
          <ChapterSelectionPanel
            chapters={chapters}
            selectedChapters={selectedChapters}
            generatedChapterIds={generatedChapterIds}
            onToggleChapter={onToggleChapter}
            onOpenChapterMenu={onOpenChapterMenu}
          />
        </SetupPanel>
        <SetupPanel
          icon={<LibraryMusicIcon fontSize="small" />}
          title="叙事与音频"
          subtitle="输出格式、字幕、音效与配乐"
        >
          <NarrationAudioConfigPanel
            outputFormat={outputFormat}
            generateSubtitle={generateSubtitle}
            audioFxConfig={audioFxConfig}
            onOutputFormatChange={onOutputFormatChange}
            onGenerateSubtitleChange={onGenerateSubtitleChange}
            onAudioFxConfigChange={onAudioFxConfigChange}
          />
        </SetupPanel>
      </Stack>

      <SetupPanel
        icon={<VoiceIcon fontSize="small" />}
        title="角色声音"
        subtitle="旁白和当前章节角色的 TTS 与音色"
        sx={{
          minWidth: 0,
          height: { lg: '100%' },
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Alert severity="info" sx={{ mb: 2 }}>
          {selectedChapterCount > 0 ? '当前章节' : '尚未选择章节'}，未配置角色将由 AI 自动分配音色。
        </Alert>
        <Box sx={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
          <CharacterVoiceConfigPanel
            loadingCharacters={loadingCharacters}
            characterScopeLoading={characterScopeLoading}
            characterScopeError={characterScopeError}
            scopedCharacterIds={scopedCharacterIds}
            unresolvedCharacterNames={unresolvedCharacterNames}
            characterVoices={characterVoices}
            ttsModel={ttsModel}
            voiceLoading={voiceLoading}
            currentVoicePresets={currentVoicePresets}
            voicePresetsByModel={voicePresetsByModel}
            ttsModelOptions={ttsModelOptions}
            previewingCharacterId={previewingCharacterId}
            autoAssigningVoices={autoAssigningVoices}
            onVoiceChange={onVoiceChange}
            onTtsModelChangeForCharacter={onTtsModelChangeForCharacter}
            onPreviewCharacterVoice={onPreviewCharacterVoice}
            onOpenVoiceManagement={handleOpenVoiceManagement}
            onAutoAssignVoices={onAutoAssignVoices}
          />
        </Box>
      </SetupPanel>
    </Box>

    <Box sx={audiobookButtonRowSx.singlePrimary}>
      <Tooltip title={generateDisabled ? generateDisabledReason : '开始生成有声书'}>
        <span>
          <Button
            variant="contained"
            onClick={onGenerate}
            disabled={generateDisabled}
            color="primary"
          >
            {selectedChapterCount > 0 ? '开始生成本章' : '请选择章节'}
          </Button>
        </span>
      </Tooltip>
    </Box>

    <Dialog
      open={voiceManagementOpen}
      onClose={() => setVoiceManagementOpen(false)}
      fullWidth
      maxWidth="md"
    >
      <DialogTitle>音色管理</DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          在这里创建和管理克隆/设计音色；保存后回到角色卡片，为旁白或角色选择对应音色。
        </Typography>
        <VoiceCatalogStatusPanel
          ttsModel={voiceManagementModel}
          voiceCatalogMeta={voiceManagementMeta}
          voiceCatalogSummary={voiceManagementSummary}
          voiceCatalogNotice={voiceManagementNotice}
          voiceCatalogNoticeSeverity={voiceManagementNoticeSeverity}
          showCustomVoiceWorkbench={modelSupportsCustomVoiceWorkbench(voiceManagementModel, ttsModelOptions)}
          voiceError={voiceError}
          voiceLoading={voiceLoading}
          customVoicePresets={voiceManagementCustomPresets}
          cosyVoiceWorkbench={cosyVoiceWorkbench}
          customVoicePreviewingId={customVoicePreviewingId}
          onPreviewCustomVoice={onPreviewCustomVoice}
          onFetchVoiceCatalog={() => onFetchVoiceCatalog(voiceManagementModel)}
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setVoiceManagementOpen(false)}>
          关闭
        </Button>
      </DialogActions>
    </Dialog>
  </Box>
)
}

export default AudiobookSetupStep
