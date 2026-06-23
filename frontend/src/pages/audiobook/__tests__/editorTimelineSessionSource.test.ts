import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const pageSource = readFileSync(
  new URL('../../AudiobookPage.tsx', import.meta.url),
  'utf8',
)
const editorStateSource = readFileSync(
  new URL('../useAudiobookScriptEditorState.ts', import.meta.url),
  'utf8',
)
const editorActionsSource = readFileSync(
  new URL('../useAudiobookScriptEditorActions.ts', import.meta.url),
  'utf8',
)
const editorDraftSource = readFileSync(
  new URL('../useAudiobookScriptEditorDraftState.ts', import.meta.url),
  'utf8',
)
const editorSyncSource = readFileSync(
  new URL('../useAudiobookEditorSessionSync.ts', import.meta.url),
  'utf8',
)
const conflictPreviewSource = readFileSync(
  new URL('../useAudiobookEditorConflictPreview.ts', import.meta.url),
  'utf8',
)

describe('audiobook editor timeline session wiring', () => {
  it('keeps timeline clip edits in the parent editor session instead of dialog-local state', () => {
    expect(editorStateSource).toContain('useState<TimelineClipEditMap>({})')
    expect(editorStateSource).toContain('timelineEdits')
    expect(editorStateSource).toContain('setTimelineEdits')

    expect(pageSource).toContain('timelineEdits')
    expect(pageSource).toContain('setTimelineEdits')
    expect(pageSource).toContain('onChangeTimelineEdits={setTimelineEdits}')
  })

  it('persists and restores timeline edits with editor drafts and cross-tab sync', () => {
    for (const source of [
      editorDraftSource,
      editorSyncSource,
      conflictPreviewSource,
    ]) {
      expect(source).toContain('timelineEdits')
    }

    expect(editorActionsSource).toContain('setTimelineEdits({})')
    expect(editorActionsSource).toContain('timelineEdits,')
    expect(editorActionsSource).toContain('buildGenerateAudioFromScriptPayload({')
    expect(editorDraftSource).toContain('setTimelineEdits(savedEditorSession.timelineEdits || {})')
    expect(editorDraftSource).toContain('setTimelineEdits(editorCrossTabConflict.timelineEdits || {})')
    expect(editorSyncSource).toContain('timelineEdits,')
    expect(conflictPreviewSource).toContain('timelineEdits,')
  })
})
