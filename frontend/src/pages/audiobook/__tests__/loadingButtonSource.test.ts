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
const chapterAudioItemSource = readSource('../ChapterAudioResultItem.tsx')

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

  it('keeps menu item primary labels stable while loading state moves to secondary text', () => {
    expect(chapterAudioItemSource).toContain('primary="继续生成"')
    expect(chapterAudioItemSource).toContain("secondary={resumingChapterId === chapterAudio.chapter_id ? '提交中...' : undefined}")
    expect(chapterAudioItemSource).not.toContain("primary={resumingChapterId === chapterAudio.chapter_id ? '提交中...' : '继续生成'}")
  })
})
