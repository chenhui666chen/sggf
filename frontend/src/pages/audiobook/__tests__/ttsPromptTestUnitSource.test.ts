import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

describe('independent TTS prompt test unit source contract', () => {
  it('removes prompt review from the audiobook generation page', () => {
    const audiobookPageSource = readSource('../../AudiobookPage.tsx')

    expect(audiobookPageSource).not.toContain('PromptStrategyReviewPanel')
    expect(audiobookPageSource).not.toContain('sourceProjectId={selectedProjectId ?? routeProjectId}')
  })

  it('exposes a protected standalone route and dashboard entry', () => {
    const appSource = readSource('../../../App.tsx')
    const dashboardSource = readSource('../../AudiobookDashboardPage.tsx')

    expect(appSource).toContain("const TtsPromptTestPage = lazy(() => import('@/pages/TtsPromptTestPage'))")
    expect(appSource).toContain('path="/audiobook-tts-test"')
    expect(dashboardSource).toContain("navigate('/audiobook-tts-test')")
    expect(dashboardSource).toContain('TTS 测试')
  })

  it('loads model-specific cases and previews through independent APIs', () => {
    const pageSource = readSource('../../TtsPromptTestPage.tsx')
    const apiSource = readSource('../../../services/api.ts')

    expect(pageSource).toContain('apiClient.getTtsPromptTestCases')
    expect(pageSource).toContain('apiClient.previewTtsPromptTestCase')
    expect(pageSource).toContain('provider_prompt_snapshot')
    expect(pageSource).not.toContain('audiobookProjectId')
    expect(pageSource).not.toContain('chapterId')
    expect(apiSource).toContain('/api/v1/audiobook/tts/test-cases')
    expect(apiSource).toContain('/api/v1/audiobook/tts/test-preview')
  })
})
