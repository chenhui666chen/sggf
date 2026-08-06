import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

import * as scriptEditorUtils from '../scriptEditorUtils'

type ResolveInitialScriptSegmentFocus = (
  initialSegmentIndex: number | null | undefined,
  segmentCount: number,
  hasConsumed: boolean,
) => number | null

const resolveInitialScriptSegmentFocus = (
  scriptEditorUtils as typeof scriptEditorUtils & {
    resolveInitialScriptSegmentFocus?: ResolveInitialScriptSegmentFocus
  }
).resolveInitialScriptSegmentFocus

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
const editorDialogSource = readFileSync(
  new URL('../ScriptEditorDialog.tsx', import.meta.url),
  'utf8',
)
const reviewDialogSource = readFileSync(
  new URL('../ScriptQualityReviewDialog.tsx', import.meta.url),
  'utf8',
)

describe('script editor initial segment focus', () => {
  it('waits for segment data, clamps the requested index, and ignores an already consumed request', () => {
    expect(resolveInitialScriptSegmentFocus).toBeTypeOf('function')
    expect(resolveInitialScriptSegmentFocus?.(2, 0, false)).toBeNull()
    expect(resolveInitialScriptSegmentFocus?.(-3, 4, false)).toBe(0)
    expect(resolveInitialScriptSegmentFocus?.(9, 4, false)).toBe(3)
    expect(resolveInitialScriptSegmentFocus?.(2, 4, false)).toBe(2)
    expect(resolveInitialScriptSegmentFocus?.(2, 4, true)).toBeNull()
    expect(resolveInitialScriptSegmentFocus?.(1.5, 4, false)).toBeNull()
  })

  it('wires a one-time page-level focus request from review into the existing editor', () => {
    expect(editorStateSource).toContain('scriptEditorInitialSegmentIndex')
    expect(editorActionsSource).toContain('initialSegmentIndex?: number | null')
    expect(editorActionsSource).toContain('setScriptEditorInitialSegmentIndex(initialSegmentIndex ?? null)')
    expect(editorActionsSource).toContain('setScriptEditorInitialSegmentIndex(null)')
    expect(pageSource).toContain('initialSegmentIndex={scriptEditorInitialSegmentIndex}')
    expect(pageSource).toContain('onInitialSegmentIndexConsumed')
    expect(editorDialogSource).toContain('initialSegmentFocusConsumedRef')
    expect(editorDialogSource).toContain('resolveInitialScriptSegmentFocus(')
    expect(reviewDialogSource).toContain('onOpenScriptEditor(data.chapterId, selectedSegmentIndex)')
  })

  it('auto-resolves the audiobook project detail before opening the workbench', () => {
    // 首次进入路由（无会话恢复）时 detail 为空，打开工作台需与历史记录入口一致自动补齐，
    // 而不是直接报“请先创建有声书项目”
    expect(editorActionsSource).toContain('novelProjectId: number | null')
    expect(editorActionsSource).toContain('apiClient.getAudiobookProjectsByProject(novelProjectId)')
    expect(editorActionsSource).toContain("item?.status === 'completed'")
    expect(editorActionsSource).toContain('apiClient.getAudiobookProject(latestCompleted.id)')
    expect(editorActionsSource).toContain('setAudiobookProject(targetProject)')
    expect(editorActionsSource).toContain('setCurrentAudiobookProjectId(targetProject.id)')
    expect(editorActionsSource).toContain('getAudiobookChapterScript(targetProject.id, chapterId)')
    expect(pageSource).toContain('novelProjectId: selectedProject?.id ?? routeProjectId,')
  })
})
