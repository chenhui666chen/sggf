import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const dialogSource = readFileSync(
  new URL('../ScriptEditorDialog.tsx', import.meta.url),
  'utf8',
)

describe('ScriptEditorDialog editing-workbench layout', () => {
  it('keeps an integrated single-segment editing workbench for script and audio cues', () => {
    for (const marker of [
      'EDITOR_SURFACE_COLORS',
      'EDITOR_TRACK_COLORS',
      'EDITOR_BOTTOM_SAFE_AREA',
      "app: '#080a0d'",
      "panel: '#17191f'",
      "accent: '#10d7e2'",
      "sfxOrange: '#ff8a2a'",
      "musicPurple: '#8b5cf6'",
      'audiobook.scriptEditor.singleSegmentWorkbench',
      'segmentNavigatorSx',
      'focusSegmentPanelSx',
      'segmentInspectorSx',
      'editorTabsSx',
      'editorFloatingPaperSx',
      'editorDetailsPanelSx',
      'editorMutedTextSx',
      'editorEmbeddedContentSx',
      'scrollbarColor',
      'MuiSlider-rail',
      'env(safe-area-inset-bottom)',
      'MuiListItemText-primary',
      'MuiListItemText-secondary',
      'MuiAlert-standardInfo',
      'MuiDivider-wrapper',
      'mutedTextColor={EDITOR_SURFACE_COLORS.muted}',
      'dangerTextColor={EDITOR_SURFACE_COLORS.danger}',
      'fullScreen',
      "width: '100vw'",
      "height: '100dvh'",
      'borderRadius: 0',
      'CloseIcon',
      "aria-label={t('audiobook.scriptEditor.closeEditor')}",
      'selectedSegmentProgress',
      'visibleSegmentCards',
      'audiobook.scriptEditor.enterReview',
      'audiobook.scriptEditor.reviewReport',
      'audiobook.scriptEditor.approveScript',
      'timelinePanelSx',
      'audiobook.scriptEditor.trackLabels.scriptVoice',
      'audiobook.scriptEditor.trackLabels.sfx',
      'audiobook.scriptEditor.trackLabels.music',
      'audiobook.scriptEditor.inspectorTitle',
      'audiobook.scriptEditor.currentSegment',
      'audiobook.scriptEditor.timelineRuler',
      'selectedSegmentIndex',
      'timelineScale',
      'TIMELINE_SCALE_OPTIONS',
      'TIMELINE_SCALE_MARKS',
      "aria-label={t('audiobook.scriptEditor.timelineZoomAria')}",
      'audiobook.scriptEditor.currentPosition',
      'audiobook.scriptEditor.previousSegment',
      'audiobook.scriptEditor.nextSegment',
      'handlePreviousSegment',
      'handleNextSegment',
      'buildTimelineModel',
      'timelineContentWidth',
      'playheadLeft',
      'timelineContentRef',
      'timelineSeeking',
      'resolveTimelineSeekSegmentIndex',
      'resolveTimelineSeekPlaybackType',
      'handleTimelineSeekAtClientX',
      'handleTimelineSeekPointerDown',
      "onPreviewSegmentAudio(seekIndex, scriptSegments[seekIndex], resolveTimelineSeekPlaybackType",
      'timelineLabelsColumnSx',
      'timelineTrackContentSx',
      'TIMELINE_PRIMARY_TRACK_HEIGHT',
      'TIMELINE_AUDIO_TRACK_HEIGHT',
      'timelineTracksHeight',
      'menuPaperSx={editorFloatingPaperSx}',
      'onSelectClip',
      'onAdjustClip',
      'handleAdjustTimelineClip',
      'timelineEdits',
      'onChangeTimelineEdits',
      'adjustTimelineClipEdit',
      'applyTimelineEdits',
      'isTimelineClipEditable',
      'resize-start',
      'resize-end',
      'scriptVoice',
      'clipsByTrack',
      'useMemo',
      'useCallback',
    ]) {
      expect(dialogSource).toContain(marker)
    }

    expect(dialogSource).toContain("gridTemplateRows: 'minmax(0, 1fr)'")
    expect(dialogSource).toContain("gridTemplateRows: 'minmax(0, 1fr) auto'")
    expect(dialogSource).toContain('const EDITOR_BOTTOM_SAFE_AREA = 24')
    expect(dialogSource).toContain('marks={TIMELINE_SCALE_MARKS}')
    expect(dialogSource).not.toContain('<DialogActions')
    expect(dialogSource).not.toContain('DialogActions,')
    expect(dialogSource).not.toContain('DialogTitle,')
    expect(dialogSource).not.toContain("gridTemplateRows: 'minmax(0, 1fr) minmax(270px, 32vh)'")
    expect(dialogSource).not.toContain('const EDITOR_BOTTOM_SAFE_AREA = 72')
    expect(dialogSource).not.toContain('marks={TIMELINE_SCALE_OPTIONS}')
    expect(dialogSource).not.toContain("label: '紧凑'")
    expect(dialogSource).not.toContain("label: '标准'")
    expect(dialogSource).not.toContain("label: '精细'")
    expect(dialogSource).not.toContain('editorToolbarSx')
    expect(dialogSource).not.toContain('workbenchActionBarSx')
    expect(dialogSource).not.toContain('剪辑工具栏')
    expect(dialogSource).not.toContain('仅保存剧本')
    expect(dialogSource).not.toContain('保存并生成该章节音频')
    expect(dialogSource).not.toContain('buildTimelineBlocks')
    expect(dialogSource).not.toContain('setTimelineEdits')
    expect(dialogSource).not.toContain("key: 'text'")
    expect(dialogSource).not.toContain("key: 'voice'")
    expect(dialogSource).not.toContain("bgcolor: '#ffffff'")
    expect(dialogSource).not.toContain("bgcolor: '#f8fafc'")
    expect(dialogSource).not.toContain("bgcolor: '#eef2f7'")
    expect(dialogSource).not.toContain("borderColor: 'divider'")
    expect(dialogSource).not.toContain('color="text.secondary"')
    expect(dialogSource).not.toContain('audiobookColors')
    expect(dialogSource).not.toContain('audiobookButtonSx')
  })
})
