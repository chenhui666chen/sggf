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
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import LibraryMusicIcon from '@mui/icons-material/LibraryMusic'
import PlaylistAddCheckIcon from '@mui/icons-material/PlaylistAddCheck'
import VoiceIcon from '@mui/icons-material/RecordVoiceOver'
import { useTranslation } from 'react-i18next'

import CharacterVoiceConfigPanel from './CharacterVoiceConfigPanel'
import ChapterSelectionPanel from './ChapterSelectionPanel'
import NarrationAudioConfigPanel from './NarrationAudioConfigPanel'
import VoiceCatalogStatusPanel from './VoiceCatalogStatusPanel'
import VoicePoolWorkbench from './VoicePoolWorkbench'
import { useAudiobookSceneVoicePool } from './useAudiobookSceneVoicePool'
import { markSeedSceneIncompatibleVoicePresets } from './seedSceneVoiceCompatibility'
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
  AudioEngineMode,
  AudioOutputFormat,
  Chapter,
  ChapterRenderState,
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
  audioFxConfig: AudioFxConfig
  audioEngineMode: AudioEngineMode
  chapters: Chapter[]
  selectedChapters: number[]
  generatedChapterIds: ReadonlySet<number>
  chapterStateById?: Record<number, ChapterRenderState>
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
  onAudioFxConfigChange: (value: AudioFxConfig) => void
  onAudioEngineModeChange: (value: AudioEngineMode) => void
  onToggleChapter: (chapterId: number) => void
  onOpenChapterMenu: (event: MouseEvent<HTMLButtonElement>, chapter: Chapter) => void
  onOpenGeneratedChapter: (chapterId: number) => void
  onVoiceChange: (characterId: number, voiceId: string, preset?: VoicePreset) => void
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
  audioFxConfig,
  audioEngineMode,
  chapters,
  selectedChapters,
  generatedChapterIds,
  chapterStateById,
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
  onAudioFxConfigChange,
  onAudioEngineModeChange,
  onToggleChapter,
  onOpenChapterMenu,
  onOpenGeneratedChapter,
  onVoiceChange,
  onTtsModelChangeForCharacter,
  onPreviewCustomVoice,
  onPreviewCharacterVoice,
  onAutoAssignVoices,
  onGenerate,
}: AudiobookSetupStepProps) => {
  const { t } = useTranslation()
  const [voiceManagementOpen, setVoiceManagementOpen] = useState(false)
  const [voiceManagementModel, setVoiceManagementModel] = useState<TtsModel>(ttsModel)
  const sceneVoicePool = useAudiobookSceneVoicePool()

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
      return t('audiobook.audiobookSetupStep.customVoiceSummary', {
        model: modelLabel,
        total: voiceManagementPresets.length,
        updatedAt,
      })
    }
    const voiceCount = voiceManagementMeta.voice_count ?? voiceManagementPresets.length
    return t('audiobook.audiobookSetupStep.officialVoiceSummary', {
      model: modelLabel,
      total: voiceCount,
      updatedAt,
    })
  }, [
    t,
    voiceManagementMeta,
    voiceManagementModel,
    voiceManagementOption?.name,
    voiceManagementPresets.length,
    voiceManagementRequiresCustomVoice,
  ])
  const voiceManagementNotice = useMemo(() => {
    const modelLabel = voiceManagementOption?.name || getTtsModelLabel(voiceManagementModel)
    const withModelPrefix = (note: string) =>
      t('audiobook.audiobookSetupStep.notePrefix', { model: modelLabel, note })
    if (voiceManagementOption?.catalogStatus === 'unavailable') {
      return withModelPrefix(voiceManagementOption.catalogError || t('audiobook.audiobookSetupStep.catalogUnavailable'))
    }
    if (voiceManagementOption?.runtimeStatus === 'unavailable') {
      return withModelPrefix(voiceManagementOption.runtimeError || t('audiobook.audiobookSetupStep.runtimeUnavailable'))
    }
    if (voiceManagementOption?.source === 'fallback') {
      return voiceLoading
        ? withModelPrefix(t('audiobook.audiobookSetupStep.syncingCatalog'))
        : withModelPrefix(t('audiobook.audiobookSetupStep.fallbackCatalog'))
    }
    return voiceManagementOption?.catalogNote
      ? withModelPrefix(voiceManagementOption.catalogNote)
      : withModelPrefix(t('audiobook.audiobookSetupStep.usingServerCatalog'))
  }, [t, voiceLoading, voiceManagementModel, voiceManagementOption])
  const voiceManagementNoticeSeverity = voiceManagementOption?.catalogStatus === 'unavailable'
    || voiceManagementOption?.runtimeStatus === 'unavailable'
    ? 'warning'
    : voiceManagementOption?.source === 'fallback'
      ? (voiceLoading ? 'info' : 'warning')
      : 'success'
  const effectiveVoicePresetsByModel = useMemo(() => {
    if (audioEngineMode !== 'seed_scene') return voicePresetsByModel
    const models = new Set<TtsModel>([
      ttsModel,
      ...Object.keys(voicePresetsByModel),
      ...characterVoices.map((voice) => voice.ttsModel).filter((model): model is TtsModel => Boolean(model)),
    ])
    const next: Record<TtsModel, VoicePreset[]> = { ...voicePresetsByModel }
    for (const model of models) {
      const merged = [...(voicePresetsByModel[model] || []), ...sceneVoicePool.presets]
      const deduped = merged.filter(
        (preset, index) => merged.findIndex((item) => item.id === preset.id) === index,
      )
      // 场景生成模式白名单：标记不兼容音色（其他供应商官方音色）为禁用，
      // 与后端 voice_reference_resolver 的白名单保持一致，避免渲染时被拒绝。
      next[model] = markSeedSceneIncompatibleVoicePresets(deduped)
    }
    return next
  }, [audioEngineMode, characterVoices, sceneVoicePool.presets, ttsModel, voicePresetsByModel])
  const effectiveCurrentVoicePresets = audioEngineMode === 'seed_scene'
    ? effectiveVoicePresetsByModel[ttsModel] || currentVoicePresets
    : currentVoicePresets

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
          title={t('audiobook.audiobookSetupStep.chapterQueueTitle')}
          subtitle={t('audiobook.audiobookSetupStep.chapterQueueSubtitle')}
        >
          <Box
            sx={{
              mb: 1.5,
              p: 1.25,
              borderRadius: 1,
              backgroundColor: 'action.hover',
              border: '1px solid',
              borderColor: 'divider',
            }}
          >
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
              {t('audiobook.audiobookSetupStep.engineModeLabel')}
            </Typography>
            <ToggleButtonGroup
              exclusive
              size="small"
              fullWidth
              aria-label={t('audiobook.audiobookSetupStep.engineModeLabel')}
              value={audioEngineMode}
              onChange={(_, value: AudioEngineMode | null) => {
                if (value) onAudioEngineModeChange(value)
              }}
              sx={{
                height: 36,
                '& .MuiToggleButton-root': {
                  gap: 0.75,
                  px: 1.25,
                  letterSpacing: 0,
                  whiteSpace: 'nowrap',
                },
              }}
            >
              <ToggleButton value="legacy_stems" aria-label={t('audiobook.audiobookSetupStep.legacyStemsLabel')}>
                <GraphicEqIcon fontSize="small" />
                {t('audiobook.audiobookSetupStep.legacyStemsLabel')}
              </ToggleButton>
              <ToggleButton value="seed_scene" aria-label={t('audiobook.audiobookSetupStep.seedSceneLabel')}>
                <AutoAwesomeIcon fontSize="small" />
                {t('audiobook.audiobookSetupStep.seedSceneLabel')}
              </ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <ChapterSelectionPanel
            chapters={chapters}
            selectedChapters={selectedChapters}
            generatedChapterIds={generatedChapterIds}
            chapterStateById={chapterStateById}
            onToggleChapter={onToggleChapter}
            onOpenChapterMenu={onOpenChapterMenu}
            onOpenGeneratedChapter={onOpenGeneratedChapter}
          />
        </SetupPanel>
        <SetupPanel
          icon={<LibraryMusicIcon fontSize="small" />}
          title={t('audiobook.audiobookSetupStep.narrationTitle')}
          subtitle={t('audiobook.audiobookSetupStep.narrationSubtitle')}
        >
          <NarrationAudioConfigPanel
            outputFormat={outputFormat}
            audioFxConfig={audioFxConfig}
            audioEngineMode={audioEngineMode}
            onOutputFormatChange={onOutputFormatChange}
            onAudioFxConfigChange={onAudioFxConfigChange}
          />
        </SetupPanel>
      </Stack>

      <SetupPanel
        icon={<VoiceIcon fontSize="small" />}
        title={t('audiobook.audiobookSetupStep.voicesTitle')}
        subtitle={t('audiobook.audiobookSetupStep.voicesSubtitle')}
        sx={{
          minWidth: 0,
          height: { lg: '100%' },
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <Alert severity="info" sx={{ mb: 2 }}>
          {selectedChapterCount > 0
            ? t('audiobook.audiobookSetupStep.chapterSelectedNotice')
            : t('audiobook.audiobookSetupStep.chapterNotSelectedNotice')}
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
            currentVoicePresets={effectiveCurrentVoicePresets}
            voicePresetsByModel={effectiveVoicePresetsByModel}
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
      <Tooltip title={generateDisabled ? generateDisabledReason : t('audiobook.audiobookSetupStep.generateScriptLabel')}>
        <span>
          <Button
            variant="contained"
            onClick={onGenerate}
            disabled={generateDisabled}
            color="primary"
          >
            {selectedChapterCount > 0
              ? t('audiobook.audiobookSetupStep.generateScriptLabel')
              : t('audiobook.audiobookSetupStep.selectChapterLabel')}
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
      <DialogTitle>{t('audiobook.audiobookSetupStep.voiceManagementTitle')}</DialogTitle>
      <DialogContent dividers>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t('audiobook.audiobookSetupStep.voiceManagementHint')}
        </Typography>
        {audioEngineMode === 'seed_scene' ? (
          <VoicePoolWorkbench
            privateAssets={sceneVoicePool.privateAssets}
            publicVoices={sceneVoicePool.publicVoices}
            taxonomy={sceneVoicePool.taxonomy}
            loading={sceneVoicePool.loading}
            error={sceneVoicePool.error}
            onRefresh={sceneVoicePool.refresh}
          />
        ) : (
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
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setVoiceManagementOpen(false)}>
          {t('action.close')}
        </Button>
      </DialogActions>
    </Dialog>
  </Box>
)
}

export default AudiobookSetupStep
