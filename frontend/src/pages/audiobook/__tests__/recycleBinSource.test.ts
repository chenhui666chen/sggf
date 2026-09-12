import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) => readFileSync(
  new URL(relativePath, import.meta.url),
  'utf-8',
)

describe('Audiobook recycle bin source guards', () => {
  it('keeps deleted chapter audio API wired to the backend recycle-bin endpoint', () => {
    const apiSource = readSource('../../../services/api.ts')

    expect(apiSource).toContain('listDeletedChapterAudios')
    expect(apiSource).toContain('/api/v1/audiobook/chapter-audios/deleted')
    expect(apiSource).toContain('restoreChapterAudio')
  })

  it('renders a chapter-audio recovery section in the dashboard recycle bin', () => {
    const dashboardSource = readSource('../../AudiobookDashboardPage.tsx')

    expect(dashboardSource).toContain('deletedChapterAudios')
    expect(dashboardSource).toContain('apiClient.listDeletedChapterAudios()')
    expect(dashboardSource).toContain('handleRestoreChapterAudio')
    expect(dashboardSource).toContain('apiClient.restoreChapterAudio(chapterAudioId)')
    expect(dashboardSource).toContain('audiobook.audiobookDashboard.deletedChapterAudiosSection')
  })

  it('keeps the deleted chapter audio response contract typed', () => {
    const typeSource = readSource('../../../types/audiobook.ts')

    expect(typeSource).toContain('export interface DeletedChapterAudio')
    expect(typeSource).toContain('chapter_audio_id: number')
    expect(typeSource).toContain('audiobook_project_id: number')
    expect(typeSource).toContain('delete_reason?: string | null')
  })
})
