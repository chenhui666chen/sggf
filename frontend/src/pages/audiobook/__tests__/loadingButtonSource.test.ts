import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

const textImportSource = readSource('../TextProjectImportDialog.tsx')
const chapterDeleteSource = readSource('../ChapterDeleteConfirmDialog.tsx')
const clonePanelSource = readSource('../CosyVoiceCloneVoicePanel.tsx')
const designPanelSource = readSource('../CosyVoiceDesignVoicePanel.tsx')
const characterConfigSource = readSource('../CharacterVoiceConfigPanel.tsx')
const characterCardSource = readSource('../CharacterVoiceCard.tsx')
const characterCardControlsSource = readSource('../CharacterVoiceCardControls.tsx')
const characterVoiceSettingsSource = readSource('../useAudiobookCharacterVoiceSettings.ts')
const characterVoicePreviewSource = readSource('../useAudiobookCharacterVoicePreview.ts')
const chapterAudioItemSource = readSource('../ChapterAudioResultItem.tsx')
const voiceActionsSource = readSource('../useAudiobookVoiceActions.ts')
const cosyVoiceListSource = readSource('../CosyVoiceCustomVoiceList.tsx')

describe('Audiobook loading button source guards', () => {
  it('keeps regular buttons using startIcon spinners instead of replacing action text', () => {
    expect(textImportSource).toContain('startIcon={creating ? <CircularProgress')
    expect(textImportSource).toContain("{creating ? '创建中...' : '创建并开始配置音色'}")
    expect(textImportSource).not.toMatch(/>\s*\{creating \? <CircularProgress/)

    expect(chapterDeleteSource).toContain('startIcon={deleting ? <CircularProgress')
    expect(chapterDeleteSource).toContain("{deleting ? '删除中...' : '确认删除'}")
    expect(chapterDeleteSource).not.toMatch(/>\s*\{deleting \? <CircularProgress/)

    expect(clonePanelSource).toContain('startIcon={cloneLoading ? <CircularProgress')
    expect(clonePanelSource).toContain('startIcon={cloneUploading ? <CircularProgress')
    expect(designPanelSource).toContain('startIcon={designLoading ? <CircularProgress')
    expect(characterConfigSource).toContain('startIcon={autoAssigningVoices ? <CircularProgress')
    expect(characterCardSource).toContain('startIcon={isPreviewing ? <CircularProgress')
  })

  it('switches CosyVoice design creation to preview playback after design succeeds', () => {
    expect(designPanelSource).toContain('designPreviewAudioUrl')
    expect(designPanelSource).toContain('designPreviewVoiceId')
    expect(designPanelSource).toContain('onPreviewDesignVoice')
    expect(designPanelSource).toContain('hasDesignPreviewTarget')
    expect(designPanelSource).toContain("'试听'")
    expect(designPanelSource).toContain('label="声音描述"')
    expect(designPanelSource).toContain('minRows={3}')
    expect(designPanelSource).not.toContain('label="试听文本"')
    expect(designPanelSource).not.toContain('onDesignPreviewTextChange')
    expect(voiceActionsSource).toContain('designPreviewVoiceId')
    expect(voiceActionsSource).toContain('playManagedBlob')
    expect(voiceActionsSource).toContain('apiClient.previewTTS')
    expect(voiceActionsSource).toContain('DEFAULT_DESIGN_PREVIEW_TEXT')
    expect(voiceActionsSource).toContain('normalizeCosyVoicePreviewAudioUrl')
    expect(voiceActionsSource).not.toContain("setDesignName('')")
    expect(voiceActionsSource).not.toContain("setDesignPrompt('')")
    expect(voiceActionsSource).not.toContain('setDesignPreviewText(DEFAULT_DESIGN_PREVIEW_TEXT)')
  })

  it('keeps custom voice lists compact and uses icon playback actions', () => {
    expect(cosyVoiceListSource).toContain('VISIBLE_CUSTOM_VOICE_LIMIT = 3')
    expect(cosyVoiceListSource).toContain('visiblePresets')
    expect(cosyVoiceListSource).toContain('hiddenPresetCount')
    expect(cosyVoiceListSource).toContain('IconButton')
    expect(cosyVoiceListSource).toContain('PlayArrowIcon')
    expect(cosyVoiceListSource).toContain('DeleteOutlineIcon')
    expect(cosyVoiceListSource).toContain('onPreviewCustomVoice')
  })

  it('keeps CosyVoice remote custom voices manageable when local presets are empty', () => {
    expect(cosyVoiceListSource).not.toContain('if (customVoicePresets.length === 0)')
    expect(cosyVoiceListSource).toContain("useState(customVoicePresets.length === 0)")
    expect(cosyVoiceListSource).toContain('detailsLoaded')
    expect(cosyVoiceListSource).toContain('setDetailsLoaded(true)')
    expect(cosyVoiceListSource).toContain('showDetails && !detailsLoaded')
    expect(cosyVoiceListSource).toContain('details.length > 0 || detailsLoading || detailsLoaded')
    expect(cosyVoiceListSource).toContain('onPreviewCustomVoice(detailPreset)')
    expect(cosyVoiceListSource).toContain('onRequestDeleteVoice(clone.voice_id')
  })

  it('keeps character cards focused on model, voice, preview, and voice management only', () => {
    expect(characterCardSource).not.toContain('getTtsStyleControlLabels')
    expect(characterCardSource).not.toContain('styleControlLabels.map')
    expect(characterCardSource).not.toContain('控制方式')
    expect(characterCardSource).toContain('音色管理')
    expect(characterCardSource).toContain('onOpenVoiceManagement')
  })

  it('moves clone and design voice authoring out of character cards', () => {
    expect(characterCardSource).not.toContain('voiceCloneDataUrl')
    expect(characterCardSource).not.toContain('onVoiceCloneDataUrlChange')
    expect(characterCardSource).not.toContain('onVoiceDesignPromptChange')
    expect(characterCardSource).not.toContain('mimo-v2.5-tts-voiceclone')
    expect(characterCardSource).not.toContain('audio.voice')
    expect(characterCardSource).not.toContain('Voice Design Prompt')
    expect(characterVoiceSettingsSource).not.toContain('handleVoiceDesignPromptChange')
    expect(characterVoiceSettingsSource).not.toContain('handleVoiceCloneDataUrlChange')
  })

  it('removes role-level voice profiling and tuning controls from character voice setup', () => {
    expect(characterCardSource).not.toContain('CharacterVoiceTraitControls')
    expect(characterCardSource).not.toContain('CharacterVoiceTuningControls')
    expect(characterCardControlsSource).not.toContain('CharacterVoiceTraitControls')
    expect(characterCardControlsSource).not.toContain('CharacterVoiceTuningControls')
    expect(characterConfigSource).not.toContain('onVoiceTypeChange')
    expect(characterConfigSource).not.toContain('onPersonalityChange')
    expect(characterConfigSource).not.toContain('onEmotionTendencyChange')
    expect(characterConfigSource).not.toContain('onRecommendVoiceType')
    expect(characterConfigSource).not.toContain('onVolumeChange')
    expect(characterConfigSource).not.toContain('onSpeedChange')
    expect(characterConfigSource).not.toContain('onPitchChange')
    expect(characterVoicePreviewSource).not.toContain('volume: cv.volume')
    expect(characterVoicePreviewSource).not.toContain('speed: cv.speed')
    expect(characterVoicePreviewSource).not.toContain('pitch: cv.pitch')
    expect(characterVoicePreviewSource).not.toContain('voice_type: cv.voiceType')
  })

  it('keeps menu item primary labels stable while loading state moves to secondary text', () => {
    expect(chapterAudioItemSource).toContain('primary="继续生成"')
    expect(chapterAudioItemSource).toContain("secondary={resumingChapterId === chapterAudio.chapter_id ? '提交中...' : undefined}")
    expect(chapterAudioItemSource).not.toContain("primary={resumingChapterId === chapterAudio.chapter_id ? '提交中...' : '继续生成'}")
  })
})
