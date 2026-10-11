import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const remixHookSource = readFileSync(
  new URL('../useAudiobookChapterRemix.ts', import.meta.url),
  'utf8',
)
const apiSource = readFileSync(
  new URL('../../../services/api.ts', import.meta.url),
  'utf8',
)
const editorDialogSource = readFileSync(
  new URL('../ScriptEditorDialog.tsx', import.meta.url),
  'utf8',
)
const pageSource = readFileSync(
  new URL('../../AudiobookPage.tsx', import.meta.url),
  'utf8',
)
const pageTypesSource = readFileSync(
  new URL('../types.ts', import.meta.url),
  'utf8',
)

describe('useAudiobookChapterRemix source contract', () => {
  it('triggers remix without force and stops when confirmation is required', () => {
    expect(remixHookSource).toContain("apiClient.remixChapter(audiobookProjectId, chapterId, { force: false })")
    expect(remixHookSource).toContain("data?.requires_confirmation && data?.missing_segments?.length")
    expect(remixHookSource).toContain('remixMissingDialogOpen')
    expect(remixHookSource).toContain('handleForceRemixChapter')
  })

  it('polls remix status until a terminal state and refreshes project detail', () => {
    for (const marker of [
      'getChapterRemixStatus',
      'REMIX_POLL_INTERVAL_MS',
      "data?.remix_status === 'completed'",
      "data?.remix_status === 'failed'",
      'onRemixCompletedRef.current?.()',
      'window.setInterval',
    ]) {
      expect(remixHookSource).toContain(marker)
    }
    expect(remixHookSource).toContain("'cancelled'")
    expect(remixHookSource).toContain("'canceled'")
  })

  it('exposes the remix chapter API on the api client', () => {
    expect(apiSource).toContain("remixChapter(audiobookProjectId: number, chapterId: number, payload: RemixChapterPayload = {})")
    expect(apiSource).toContain("getChapterRemixStatus(audiobookProjectId: number, chapterId: number)")
    expect(apiSource).toContain('`/api/v1/audiobook/projects/${audiobookProjectId}/chapters/${chapterId}/remix`')
    expect(apiSource).toContain('remix-status')
    expect(apiSource).toContain('export interface RemixChapterResponse')
    expect(apiSource).toContain('export interface ChapterRemixStatusResponse')
  })

  it('wires the remix button and missing-segment confirmation dialog into the editor', () => {
    for (const marker of [
      'onRemixChapter',
      'remixingChapter',
      'remixMissingDialogOpen',
      'remixMissingSegments',
      'onForceRemixChapter',
      'onCloseRemixMissingDialog',
      'audiobook.scriptEditor.remixChapter',
      'audiobook.scriptEditor.forceRemix',
      'REQUIRE_CONFIRMATION_REASON_LABEL_KEYS',
    ]) {
      expect(editorDialogSource).toContain(marker)
    }
  })

  it('describes stale and per-track remix failures without calling existing audio missing', () => {
    expect(editorDialogSource).toContain("stale_audio: 'audiobook.scriptEditor.reasonLabels.staleAudio'")
    expect(editorDialogSource).toContain('audiobook.scriptEditor.remixMissingBody')
    expect(editorDialogSource).toContain('REQUIRE_CONFIRMATION_ASSET_LABEL_KEYS')
    expect(editorDialogSource).toContain("segment.asset_type || 'voice'")
    expect(editorDialogSource).not.toContain('以下片段没有可用的持久化音频')
  })

  it('keeps the remix missing-segment API contract in one typed source', () => {
    expect(apiSource).toContain('export type RemixMissingSegmentReason =')
    expect(apiSource).toContain("| 'stale_audio'")
    expect(apiSource).toContain("asset_type?: 'voice' | 'mix' | 'sfx' | 'bgm'")
    expect(pageTypesSource).toContain("from '../../services/api'")
    expect(pageTypesSource).not.toContain('export interface RemixMissingSegment')
  })

  it('connects the remix hook in the audiobook page and refreshes detail on completion', () => {
    for (const marker of [
      'useAudiobookChapterRemix',
      'handleRemixChapter',
      'handleForceRemixChapter',
      'refreshAudiobookProjectDetail',
      'onRemixCompleted',
    ]) {
      expect(pageSource).toContain(marker)
    }
  })
})
