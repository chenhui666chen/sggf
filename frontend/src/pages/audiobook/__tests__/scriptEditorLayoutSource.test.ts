import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const dialogSource = readFileSync(
  new URL('../ScriptEditorDialog.tsx', import.meta.url),
  'utf8',
)

describe('ScriptEditorDialog editing-workbench layout', () => {
  it('keeps a timeline-style editing workbench for script and audio cues', () => {
    for (const marker of [
      '剪辑工具栏',
      'workbenchActionBarSx',
      '片段轨道',
      '时间线',
      '文本轨',
      '人声轨',
      '音效轨',
      '配乐轨',
      '属性检查器',
      '当前片段',
      '时间尺',
      'selectedSegmentIndex',
      'timelineScale',
      'TIMELINE_SCALE_OPTIONS',
      '时间线缩放',
      '当前位置',
      '上一段',
      '下一段',
      'onSelectBlock',
      'handlePreviousSegment',
      'handleNextSegment',
      'buildTimelineTicks',
      'trackRowSx',
      'buildTimelineBlocks',
      'useMemo',
      'useCallback',
    ]) {
      expect(dialogSource).toContain(marker)
    }

    expect(dialogSource).toContain("gridTemplateRows: 'minmax(0, 1fr)'")
    expect(dialogSource).toContain("gridTemplateRows: 'auto minmax(0, 1fr) minmax(260px, 34vh)'")
    expect(dialogSource).not.toContain('<DialogActions')
    expect(dialogSource).not.toContain('DialogActions,')
    expect(dialogSource).not.toContain('DialogTitle,')
  })
})
