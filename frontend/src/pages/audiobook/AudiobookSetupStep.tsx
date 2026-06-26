import type { MouseEvent, ReactNode } from 'react'

import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Tooltip,
  Typography,
} from '@mui/material'
import LibraryMusicIcon from '@mui/icons-material/LibraryMusic'
import PlaylistAddCheckIcon from '@mui/icons-material/PlaylistAddCheck'
import TuneIcon from '@mui/icons-material/Tune'
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
  ttsModel: TtsModel
  ttsModelOptions: readonly TtsModelOption[]
  voiceCatalogMeta: VoiceCatalogMeta | null
  voiceCatalogSummary: string
  voiceCatalogNotice: string
  voiceCatalogNoticeSeverity: 'success' | 'warning' | 'info'
  showCustomVoiceWorkbench: boolean
  voiceError: string | null
  voiceLoading: boolean
  customVoicePresets: VoicePreset[]
  cosyVoiceWorkbench: CosyVoiceWorkbench
  narrationStyle: NarrationStyleId
  narrationStylePrompt: string
  outputFormat: AudioOutputFormat
  generateSubtitle: boolean
  audioFxConfig: AudioFxConfig
  chapters: Chapter[]
  selectedChapters: number[]
  loadingCharacters: boolean
  characterVoices: CharacterVoiceSetting[]
  currentVoicePresets: VoicePreset[]
  voicePresetsByModel: Record<TtsModel, VoicePreset[]>
  previewingCharacterId: number | null
  customVoicePreviewingId: string | null
  autoAssigningVoices: boolean
  generateDisabled: boolean
  generateDisabledReason: string
  onFetchVoiceCatalog: () => void
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
  onVoiceCloneDataUrlChange: (characterId: number, voiceCloneDataUrl: string) => void
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
  chapterCount,
  scriptOnlyMode,
  onScriptOnlyModeChange,
  ttsModel,
  ttsModelOptions,
  voiceCatalogMeta,
  voiceCatalogSummary,
  voiceCatalogNotice,
  voiceCatalogNoticeSeverity,
  showCustomVoiceWorkbench,
  voiceError,
  voiceLoading,
  customVoicePresets,
  cosyVoiceWorkbench,
  narrationStyle,
  narrationStylePrompt,
  outputFormat,
  generateSubtitle,
  audioFxConfig,
  chapters,
  selectedChapters,
  loadingCharacters,
  characterVoices,
  currentVoicePresets,
  voicePresetsByModel,
  previewingCharacterId,
  customVoicePreviewingId,
  autoAssigningVoices,
  generateDisabled,
  generateDisabledReason,
  onFetchVoiceCatalog,
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
  onVoiceCloneDataUrlChange,
  onPreviewCustomVoice,
  onPreviewCharacterVoice,
  onAutoAssignVoices,
  onGenerate,
}: AudiobookSetupStepProps) => (
  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2.5 }}>
    <Paper
      variant="outlined"
      sx={{
        ...audiobookPanelSx,
        p: { xs: 2, md: 2.5 },
        position: 'relative',
        overflow: 'hidden',
        '&::before': {
          content: '""',
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          height: 3,
          background: `linear-gradient(90deg, ${audiobookColors.collect}, ${audiobookColors.brand}, ${audiobookColors.warningMain})`,
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          flexDirection: { xs: 'column', md: 'row' },
          gap: 2,
          justifyContent: 'space-between',
          alignItems: { xs: 'stretch', md: 'center' },
        }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h5" sx={{ fontWeight: 800, fontSize: { xs: '1.25rem', md: '1.55rem' } }}>
            配置章节与角色声音
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 720 }}>
            选择要生成的章节，设置默认模型、旁白风格、音效密度和角色音色；再次选择同一章节时会重新生成剧本。
          </Typography>
        </Box>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
          <Chip
            label={`已选 ${selectedChapterCount}/${chapterCount} 章`}
            color={selectedChapterCount > 0 ? 'primary' : 'default'}
            variant="outlined"
            sx={{ height: 30 }}
          />
          <Chip
            label={scriptOnlyMode ? '仅生成剧本' : '完整音频链路'}
            color={scriptOnlyMode ? 'warning' : 'success'}
            variant="outlined"
            sx={{ height: 30 }}
          />
          <Tooltip title={generateDisabled ? generateDisabledReason : '开始生成有声书'}>
            <span>
              <Button
                variant="contained"
                onClick={onGenerate}
                disabled={generateDisabled}
                color="primary"
                sx={{
                  minHeight: 40,
                  minWidth: { xs: '100%', sm: 150 },
                  px: 2.5,
                  fontWeight: 700,
                }}
              >
                开始生成 ({selectedChapterCount}章)
              </Button>
            </span>
          </Tooltip>
        </Box>
      </Box>
    </Paper>

    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: { xs: '1fr', lg: 'minmax(320px, 0.9fr) minmax(0, 1.4fr)' },
        gap: 2.5,
        alignItems: 'start',
      }}
    >
      <Stack spacing={2.5} sx={{ minWidth: 0 }}>
        <SetupPanel
          icon={<TuneIcon fontSize="small" />}
          title="生成策略"
          subtitle="默认模型、任务范围和声音目录状态"
        >
          <Stack spacing={2}>
            <FormControl size="small" fullWidth>
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

            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 2,
                p: 1.5,
                borderRadius: 1.5,
                backgroundColor: scriptOnlyMode ? audiobookColors.warningSoft : audiobookColors.successSoft,
                border: `1px solid ${scriptOnlyMode ? audiobookColors.warningMain : audiobookColors.successMain}33`,
              }}
            >
              <Box sx={{ minWidth: 0 }}>
                <Typography variant="body2" sx={{ fontWeight: 700 }}>
                  {scriptOnlyMode ? '只生成剧本和评审' : '生成剧本、音频与导出素材'}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {scriptOnlyMode ? '适合先审稿再进入音频阶段' : '适合一次性完成可试听章节'}
                </Typography>
              </Box>
              <FormControlLabel
                sx={{ m: 0, flexShrink: 0 }}
                control={
                  <Checkbox
                    checked={scriptOnlyMode}
                    onChange={(_, checked) => onScriptOnlyModeChange(checked)}
                    color="primary"
                  />
                }
                label="仅剧本"
              />
            </Box>

            <VoiceCatalogStatusPanel
              ttsModel={ttsModel}
              voiceCatalogMeta={voiceCatalogMeta}
              voiceCatalogSummary={voiceCatalogSummary}
              voiceCatalogNotice={voiceCatalogNotice}
              voiceCatalogNoticeSeverity={voiceCatalogNoticeSeverity}
              showCustomVoiceWorkbench={showCustomVoiceWorkbench}
              voiceError={voiceError}
              voiceLoading={voiceLoading}
              customVoicePresets={customVoicePresets}
              cosyVoiceWorkbench={cosyVoiceWorkbench}
              customVoicePreviewingId={customVoicePreviewingId}
              onPreviewCustomVoice={onPreviewCustomVoice}
              onFetchVoiceCatalog={onFetchVoiceCatalog}
            />
          </Stack>
        </SetupPanel>

        <SetupPanel
          icon={<LibraryMusicIcon fontSize="small" />}
          title="叙事与音频"
          subtitle="旁白风格、输出格式、字幕、音效与配乐"
        >
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
        </SetupPanel>

      </Stack>

      <Stack spacing={2.5} sx={{ minWidth: 0 }}>
        <SetupPanel
          icon={<PlaylistAddCheckIcon fontSize="small" />}
          title="章节队列"
          subtitle="本次任务只处理已勾选章节"
        >
          <ChapterSelectionPanel
            chapters={chapters}
            selectedChapters={selectedChapters}
            onToggleAll={onToggleAllChapters}
            onToggleChapter={onToggleChapter}
            onOpenChapterMenu={onOpenChapterMenu}
          />
        </SetupPanel>

        <SetupPanel
          icon={<VoiceIcon fontSize="small" />}
          title="角色声音"
          subtitle="角色专属音色会覆盖项目默认模型"
        >
          <Alert severity="info" sx={{ mb: 2 }}>
            已选择 {selectedChapterCount}/{chapterCount} 个章节。未配置的角色将由 AI 自动分配音色。
          </Alert>
          <CharacterVoiceConfigPanel
            loadingCharacters={loadingCharacters}
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
            onVoiceCloneDataUrlChange={onVoiceCloneDataUrlChange}
            onPreviewCharacterVoice={onPreviewCharacterVoice}
            onAutoAssignVoices={onAutoAssignVoices}
          />
        </SetupPanel>
      </Stack>
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
            开始生成 ({selectedChapterCount}章)
          </Button>
        </span>
      </Tooltip>
    </Box>
  </Box>
)

export default AudiobookSetupStep
