import { describe, expect, it } from 'vitest'

import {
  buildAudiobookSourceFocusPlan,
  buildDreamweaverLibrarySourceActivationPlan,
  buildDreamweaverLibrarySourceScrollPlan,
  buildDreamweaverRunSourceNavigationPlan,
  buildUserAssetLibraryFocusSelectors,
  buildUserAssetSourceRestoreKey,
  readUserAssetSourceAudiobookRouteRequest,
  readUserAssetSourceLibraryAssetId,
  readUserAssetSourceRunId,
} from '../userAssetSourceNavigation'

describe('userAssetSourceNavigation', () => {
  it('reads run and library asset query params with trimming and validation', () => {
    const searchParams = new URLSearchParams('runId=%20run-300%20&assetId=12')
    expect(readUserAssetSourceRunId(searchParams)).toBe('run-300')
    expect(readUserAssetSourceLibraryAssetId(searchParams)).toBe(12)

    const invalidSearchParams = new URLSearchParams('runId=%20%20%20&assetId=0')
    expect(readUserAssetSourceRunId(invalidSearchParams)).toBeNull()
    expect(readUserAssetSourceLibraryAssetId(invalidSearchParams)).toBeNull()
  })

  it('reads audiobook route request and only keeps supported focus modes', () => {
    const searchParams = new URLSearchParams(
      'audiobookProjectId=21&chapterId=7&focus=SCRIPT-EDITOR',
    )
    expect(readUserAssetSourceAudiobookRouteRequest(searchParams)).toEqual({
      audiobookProjectId: 21,
      chapterId: 7,
      focus: 'script-editor',
    })

    const unsupportedFocusSearchParams = new URLSearchParams(
      'audiobookProjectId=2&chapterId=3&focus=details',
    )
    expect(readUserAssetSourceAudiobookRouteRequest(unsupportedFocusSearchParams)).toEqual({
      audiobookProjectId: 2,
      chapterId: 3,
      focus: null,
    })
  })

  it('builds restore keys only when all segments are available', () => {
    expect(buildUserAssetSourceRestoreKey(3, 'run-300')).toBe('3:run-300')
    expect(buildUserAssetSourceRestoreKey(5, 21, 7, 'script-editor')).toBe('5:21:7:script-editor')
    expect(buildUserAssetSourceRestoreKey(5, null, 7)).toBeNull()
    expect(buildUserAssetSourceRestoreKey('  ', 7)).toBeNull()
  })

  it('builds library focus selectors for direct asset and character fallback targets', () => {
    expect(buildUserAssetLibraryFocusSelectors(12, 8)).toEqual({
      targetSelector: '[data-library-asset-id="12"]',
      fallbackSelector: '[data-library-character-entity-id="8"]',
    })
    expect(buildUserAssetLibraryFocusSelectors(null, null)).toEqual({
      targetSelector: null,
      fallbackSelector: null,
    })
  })

  it('builds a run navigation plan only when the deep-link has not been consumed', () => {
    expect(buildDreamweaverRunSourceNavigationPlan({
      selectedProjectId: 3,
      requestedRunId: 'run-300',
      handledRestoreKey: null,
    })).toEqual({
      restoreKey: '3:run-300',
      runId: 'run-300',
    })

    expect(buildDreamweaverRunSourceNavigationPlan({
      selectedProjectId: 3,
      requestedRunId: 'run-300',
      handledRestoreKey: '3:run-300',
    })).toBeNull()
  })

  it('builds library activation and scroll plans for direct asset focus', () => {
    expect(buildDreamweaverLibrarySourceActivationPlan({
      projectId: 7,
      requestedLibraryAssetId: 12,
      requestedCharacterEntityId: 8,
      loading: false,
      handledFocusKey: null,
    })).toEqual({
      focusKey: '7:12',
      characterEntityId: 8,
      shouldOpenCharacterViews: true,
    })

    expect(buildDreamweaverLibrarySourceScrollPlan({
      projectId: 7,
      requestedLibraryAssetId: 12,
      requestedCharacterEntityId: 8,
      characterViewsOpen: true,
      loading: false,
      domAvailable: true,
      handledScrollKey: null,
    })).toEqual({
      scrollKey: '7:12:dialog',
      targetSelector: '[data-library-asset-id="12"]',
      fallbackSelector: '[data-library-character-entity-id="8"]',
    })
  })

  it('blocks library scroll planning until dialog context is ready for character assets', () => {
    expect(buildDreamweaverLibrarySourceScrollPlan({
      projectId: 7,
      requestedLibraryAssetId: 12,
      requestedCharacterEntityId: 8,
      characterViewsOpen: false,
      loading: false,
      domAvailable: true,
      handledScrollKey: null,
    })).toBeNull()
  })

  it('builds an audiobook focus plan and marks whether project detail needs refresh', () => {
    expect(buildAudiobookSourceFocusPlan({
      selectedProjectId: 5,
      requestedAudiobookProjectId: 21,
      requestedSourceChapterId: 7,
      requestedSourceFocus: 'script-editor',
      loadedAudiobookProjectId: 18,
      currentAudiobookProjectId: 18,
      handledFocusKey: null,
    })).toEqual({
      focusKey: '5:21:7:script-editor',
      targetAudiobookProjectId: 21,
      chapterId: 7,
      focusMode: 'script-editor',
      shouldRefreshProject: true,
    })

    expect(buildAudiobookSourceFocusPlan({
      selectedProjectId: 5,
      requestedAudiobookProjectId: null,
      requestedSourceChapterId: 7,
      requestedSourceFocus: null,
      loadedAudiobookProjectId: 21,
      currentAudiobookProjectId: 18,
      handledFocusKey: '5:21:7:script-editor',
    })).toBeNull()
  })
})
