import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

const hookSource = readSource('../useAudiobookChapterAudioActions.ts')
const resultsSource = readSource('../ChapterAudioResults.tsx')
const pageSource = readSource('../../AudiobookPage.tsx')
const completionStepSource = readSource('../AudiobookCompletionStep.tsx')

describe('audiobook chapter audio collecting state source guards', () => {
  it('keeps collecting state scoped per chapter', () => {
    expect(hookSource).toContain('collectingChapterIdsRef')
    expect(hookSource).toContain('collectingChapterIds')
    expect(pageSource).toContain('collectingChapterIds')
    expect(completionStepSource).toContain('collectingChapterIds: ReadonlySet<number>')
    expect(resultsSource).toContain('collectingChapterIds.has(chapterAudio.chapter_id)')
    expect(resultsSource).toContain('collectDisabled={isCollecting}')
  })
})
