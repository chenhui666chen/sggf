import { describe, expect, it } from 'vitest'

import {
  buildAudiobookChapterAssetUuid,
  buildAudiobookLabelsAssetUuid,
  buildAudiobookSubtitleAssetUuid,
} from '../audiobookAssetIds'

describe('audiobook asset ids', () => {
  it('builds stable audiobook asset identifiers', () => {
    expect(buildAudiobookChapterAssetUuid(12, 34)).toBe('audiobook-12-34')
    expect(buildAudiobookSubtitleAssetUuid(12, 34, 'vtt')).toBe('audiobook-subtitle-12-34-vtt')
    expect(buildAudiobookLabelsAssetUuid(12, 34)).toBe('audiobook-labels-12-34')
  })
})
