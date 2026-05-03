import { describe, expect, it } from 'vitest'

import { buildAudiobookChapterAudioAssetDescriptor } from '../chapterAudioAssetUtils'

describe('audiobook chapter audio asset utils', () => {
  it('builds a descriptor with project and chapter context', () => {
    expect(buildAudiobookChapterAudioAssetDescriptor({
      audiobookProject: { id: 11, project_id: 22 },
      chapterAudio: {
        id: 33,
        chapter_id: 44,
        chapter_number: 8,
        audio_path: ' audiobooks/chapter_008.mp3 ',
      },
      chapters: [
        { id: 44, chapter_number: 7, title: ' Opening ' },
      ],
      selectedProject: { id: 55, title: ' Star River ' },
      routeProjectId: 66,
      filename: 'chapter_007.mp3',
    })).toEqual({
      assetUuid: 'audiobook-11-44',
      title: '第7章 - Opening 有声书音频',
      projectId: 55,
      metadata: {
        audiobook_project_id: 11,
        chapter_id: 44,
        chapter_audio_id: 33,
        project_id: 55,
        project_title: 'Star River',
        chapter_title: 'Opening',
        chapter_number: 7,
        filename: 'chapter_007.mp3',
        audio_path: 'audiobooks/chapter_008.mp3',
      },
    })
  })

  it('falls back when chapter and project details are partial', () => {
    expect(buildAudiobookChapterAudioAssetDescriptor({
      audiobookProject: { id: 11, project_id: null },
      chapterAudio: {
        id: 33,
        chapter_id: 44,
        chapter_number: null,
        audio_path: '',
      },
      chapters: [],
      selectedProject: null,
      routeProjectId: 66,
      filename: 'chapter.mp3',
    })).toEqual({
      assetUuid: 'audiobook-11-44',
      title: '章节 44 有声书音频',
      projectId: 66,
      metadata: {
        audiobook_project_id: 11,
        chapter_id: 44,
        chapter_audio_id: 33,
        project_id: 66,
        project_title: null,
        chapter_title: null,
        chapter_number: null,
        filename: 'chapter.mp3',
        audio_path: null,
      },
    })
  })
})
