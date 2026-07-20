import { describe, expect, it } from 'vitest'

import {
  buildAudiobookChapterAssetUuid,
  buildAudiobookChapterDownloadUrl,
  extractDownloadFilename,
} from '../utils'

describe('audiobook download utils', () => {
  it('builds stable chapter download identifiers', () => {
    expect(buildAudiobookChapterDownloadUrl(12, 34)).toBe('/api/v1/audiobook/download/12/34')
    expect(buildAudiobookChapterAssetUuid(12, 34)).toBe('audiobook-12-34')
  })

  it('extracts UTF-8 filenames from content-disposition headers', () => {
    expect(
      extractDownloadFilename(
        "attachment; filename*=UTF-8''%E7%AC%AC1%E7%AB%A0.mp3",
        'fallback.mp3',
      ),
    ).toBe('第1章.mp3')
  })

  it('falls back to ASCII filenames and final fallback values', () => {
    expect(extractDownloadFilename('attachment; filename="chapter_1.mp3"', 'fallback.mp3')).toBe(
      'chapter_1.mp3',
    )
    expect(extractDownloadFilename('', 'fallback.mp3')).toBe('fallback.mp3')
  })
})
