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
    expect(dashboardSource).toContain('audiobook.audiobookDashboard.ttsTest')
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

  it('keeps Seed scene A/B review inside the standalone test unit', () => {
    const pageSource = readSource('../../TtsPromptTestPage.tsx')
    const scenePanelSource = readSource('../../SeedSceneTestPanel.tsx')
    const apiSource = readSource('../../../services/api.ts')

    expect(pageSource).toContain("value=\"seed_scene\"")
    expect(pageSource).toContain('SeedSceneTestPanel')
    expect(pageSource).toContain('latestTtsPreview')
    expect(scenePanelSource).toContain('apiClient.getSeedSceneTestCases')
    expect(scenePanelSource).toContain('apiClient.previewSeedSceneTestCase')
    expect(scenePanelSource).toContain("t('audiobook.seedSceneTest.useCurrentPreview')")
    expect(scenePanelSource).toContain('force_regenerate')
    expect(scenePanelSource).not.toContain('audiobookProjectId')
    expect(scenePanelSource).not.toContain('chapterId')
    expect(apiSource).toContain('/api/v1/audiobook/scene-audio/test-cases')
    expect(apiSource).toContain('/api/v1/audiobook/scene-audio/test-preview')
  })

  it('binds each Seed reference slot from its own model voice preview', () => {
    const scenePanelSource = readSource('../../SeedSceneTestPanel.tsx')
    const apiSource = readSource('../../../services/api.ts')

    expect(scenePanelSource).toContain('apiClient.getTtsModels')
    expect(scenePanelSource).toContain('apiClient.getTtsVoices')
    expect(scenePanelSource).toContain('apiClient.previewTTSCached')
    expect(scenePanelSource).toContain('SEED_REFERENCE_VOICE_PREVIEW_TEXT')
    expect(scenePanelSource).toContain('modelUsesBasicNumericSpeedControl(selectedModel)')
    expect(scenePanelSource).not.toContain('speed: selectedVoice?.default_params?.speed ?? 1,')
    expect(scenePanelSource).toContain('buildSeedSceneReferencePayload')
    expect(scenePanelSource).toContain("t('audiobook.seedSceneTest.boundNativeSuffix')")
    expect(scenePanelSource).toContain('audioUrl: result.audioUrl')
    expect(scenePanelSource).toContain('audioDataBase64: await blobToBase64(result.blob)')
    expect(scenePanelSource).not.toContain('disabled={!latestTtsPreview}')
    expect(apiSource).toContain('audio_url?: string')
    expect(apiSource).toContain('audio_data_base64?: string')
  })

  it('routes local review requests to the IPv4 backend listener', () => {
    const viteSource = readSource('../../../../vite.config.ts')

    // 允许 VITE_DEV_BACKEND_TARGET 覆盖（连本机以外/其他端口的后端时要能改），
    // 但兜底值必须是 IPv4 字面量：写成 localhost 会被解析到 IPv6，代理直接 504。
    expect(viteSource).toContain(
      "const LOCAL_BACKEND_TARGET = process.env.VITE_DEV_BACKEND_TARGET || 'http://127.0.0.1:8000'",
    )
    expect(viteSource).toContain('target: LOCAL_BACKEND_TARGET')
    expect(viteSource).not.toContain("const LOCAL_BACKEND_TARGET = 'http://localhost:8000'")
  })
})
