import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf8',
)

describe('BrowserPlayer contract source guards', () => {
  it('uses explicit audiobook_project_id for player API calls and local state', () => {
    const typesSource = readSource('../../../components/audiobook/browserPlayerTypes.ts')
    const hookSource = readSource('../useAudiobookBrowserPlayer.ts')
    const playerSource = readSource('../../../components/audiobook/BrowserPlayer.tsx')
    const routeSource = readSource('../../../../../backend/app/api/v1/audiobook_api/routes_subtitle.py')

    expect(routeSource).toContain('"audiobook_project_id": audiobook_project_id')
    expect(typesSource).toContain('audiobook_project_id?: number')
    expect(hookSource).toContain('audiobook_project_id: data.audiobook_project_id ?? data.project_id')
    expect(playerSource).toContain('const audiobookProjectId = projectData.audiobook_project_id ?? projectData.project_id')
    expect(playerSource).toContain('writeStoredBrowserPlayerState(localStorage, audiobookProjectId, snapshot)')
    expect(playerSource).toContain('apiClient.getChapterSubtitle(')
    expect(playerSource).toContain('audiobookProjectId,')
  })
})
