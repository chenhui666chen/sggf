import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

const pageSource = readSource('../../AudiobookPage.tsx')
const setupSource = readSource('../AudiobookSetupStep.tsx')
const chapterAudioItemSource = readSource('../ChapterAudioResultItem.tsx')
const exportActionsSource = readSource('../ProjectExportActions.tsx')
const browserControlsSource = readSource('../../../components/audiobook/BrowserPlayerControls.tsx')

describe('Audiobook disabled tooltip source guards', () => {
  it('keeps disabled action buttons wrapped with explanatory tooltips', () => {
    expect(chapterAudioItemSource).toContain('const collectTooltipTitle = isCollecting')
    expect(chapterAudioItemSource).toContain('Tooltip title={collectTooltipTitle}')
    expect(chapterAudioItemSource).toContain('disabled={collectDisabled}')

    expect(exportActionsSource).toContain('const exportTooltipTitle = !canExport')
    expect(exportActionsSource).toContain('Tooltip title={exportTooltipTitle}')
    expect(exportActionsSource).toContain('<span>')
    expect(exportActionsSource).toContain('disabled={!canExport}')

    expect(pageSource).toContain('const setupGenerateDisabledReason = generating')
    expect(setupSource).toContain('generateDisabledReason: string')
    expect(setupSource).toContain("Tooltip title={generateDisabled ? generateDisabledReason : '开始生成有声书'}")
    expect(setupSource).toContain('disabled={generateDisabled}')

    expect(browserControlsSource).toContain("Tooltip title={previousDisabled ? '当前已经是第一章' : '上一章'}")
    expect(browserControlsSource).toContain('disabled={previousDisabled}')
    expect(browserControlsSource).toContain("Tooltip title={nextDisabled ? '当前已经是最后一章' : '下一章'}")
    expect(browserControlsSource).toContain('disabled={nextDisabled}')
  })
})
