import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

const themeSource = readSource('../audiobookTheme.ts')
const completionSource = readSource('../AudiobookCompletionStep.tsx')
const setupSource = readSource('../AudiobookSetupStep.tsx')
const chapterAudioItemSource = readSource('../ChapterAudioResultItem.tsx')
const exportActionsSource = readSource('../ProjectExportActions.tsx')
const deleteDialogSource = readSource('../ChapterDeleteConfirmDialog.tsx')
const historyDialogSource = readSource('../HistoryDialog.tsx')
const resumableAlertSource = readSource('../ResumableChaptersAlert.tsx')
const reviewReportUtilsSource = readSource('../scriptReviewReportUtils.ts')
const taskStageDetailsSource = readSource('../TaskStageDetails.tsx')
const chapterActionsMenuSource = readSource('../ChapterActionsMenu.tsx')

describe('Audiobook button style source guards', () => {
  it('keeps semantic audiobook button variants available and applied', () => {
    for (const variant of [
      'successOutlined',
      'dangerOutlined',
      'dangerContained',
      'warningOutlined',
      'neutralOutlined',
      'collectOutlined',
      'brandIcon',
      'collectIcon',
      'neutralIcon',
    ]) {
      expect(themeSource).toContain(`${variant}: {`)
    }

    expect(completionSource).toContain('audiobookButtonSx.successOutlined')
    expect(completionSource).not.toContain('borderColor: audiobookColors.successMain')

    expect(chapterAudioItemSource).toContain('audiobookButtonSx.collectIcon')
    expect(chapterAudioItemSource).toContain('audiobookButtonSx.neutralIcon')
    expect(chapterAudioItemSource).not.toContain('borderColor: isPlaying')

    expect(exportActionsSource).toContain('audiobookButtonSx.brandContained')
    expect(deleteDialogSource).toContain('audiobookButtonSx.dangerContained')
    expect(historyDialogSource).toContain('audiobookButtonSx.dangerContained')
    expect(resumableAlertSource).toContain('audiobookButtonSx.warningOutlined')
  })

  it('keeps color roles grouped by semantic usage', () => {
    for (const roleGroup of [
      'audiobookColorRoles',
      'destructiveAction: {',
      'reviewRisk: {',
      'taskStatus: {',
      'notice: {',
      'pending: {',
    ]) {
      expect(themeSource).toContain(roleGroup)
    }

    expect(deleteDialogSource).toContain('audiobookColorRoles.destructiveAction')
    expect(chapterActionsMenuSource).toContain('audiobookColorRoles.destructiveAction')
    expect(historyDialogSource).toContain('audiobookColorRoles.taskStatus')
    expect(reviewReportUtilsSource).toContain('audiobookColorRoles.reviewRisk')
    expect(taskStageDetailsSource).toContain('audiobookColorRoles.taskStatus')
    expect(taskStageDetailsSource).not.toContain('failed: { bg: audiobookColors.dangerChip')
  })

  it('keeps responsive audiobook button row presets applied to dense action rows', () => {
    expect(themeSource).toContain('audiobookButtonRowSx')
    expect(themeSource).toContain('centeredWrap: {')
    expect(themeSource).toContain("minWidth: { xs: 'calc(50% - 6px)', sm: 'auto' }")
    expect(themeSource).toContain("flex: { xs: '1 1 calc(50% - 6px)', sm: '0 1 auto' }")
    expect(themeSource).toContain("whiteSpace: 'normal'")
    expect(themeSource).toContain('singlePrimary: {')

    expect(completionSource).toContain('audiobookButtonRowSx.centeredWrap')
    expect(completionSource).not.toContain("display: 'flex', gap: 1.5, justifyContent: 'center'")

    expect(setupSource).toContain('audiobookButtonRowSx.singlePrimary')
  })
})
