import { existsSync, readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const browserSource = readFileSync(
  new URL('../AudioLibraryBrowser.tsx', import.meta.url),
  'utf8',
)

const apiSource = readFileSync(
  new URL('../../../services/api.ts', import.meta.url),
  'utf8',
)

const pickerSource = readFileSync(
  new URL('../AudioPicker.tsx', import.meta.url),
  'utf8',
)

const segmentDetailsSource = readFileSync(
  new URL('../ScriptSegmentDetailsPanel.tsx', import.meta.url),
  'utf8',
)

const displaySource = readFileSync(
  new URL('../audioLibraryDisplay.ts', import.meta.url),
  'utf8',
)

const purgeSource = readFileSync(
  new URL('../AudioLibraryPurgeDialog.tsx', import.meta.url),
  'utf8',
)

const uploadDialogUrl = new URL('../AudioLibraryUploadDialog.tsx', import.meta.url)
const uploadDialogSource = existsSync(uploadDialogUrl) ? readFileSync(uploadDialogUrl, 'utf8') : ''

describe('AudioLibraryBrowser source guards', () => {
  it('keeps the library browser read-only for public third-party assets', () => {
    expect(browserSource).toContain('音频素材库')
    expect(browserSource).toContain('getAudioLibraryStats')
    expect(browserSource).toContain('browseSoundEffects')
    expect(browserSource).toContain('browseMusic')
    expect(browserSource).toContain('getAudioLibraryPreviewBlob')
    expect(browserSource).not.toContain('SfxCandidateReviewDialog')
    expect(browserSource).not.toContain('SfxManifestImportDialog')
    expect(browserSource).toContain('AudioLibraryPurgeDialog')

    expect(browserSource).not.toContain('从公开库导入')
    expect(browserSource).not.toContain('searchPublicSfx')
    expect(browserSource).not.toContain('downloadSfxToLibrary')
    expect(browserSource).not.toContain('CloudDownloadIcon')
  })

  it('does not expose public SFX auto-download helpers to the browser UI', () => {
    expect(apiSource).toContain('getAudioLibraryStats')
    expect(apiSource).toContain('browseSoundEffects')
    expect(apiSource).toContain('browseMusic')
    expect(apiSource).toContain('getAudioLibraryPreviewUrl')
    expect(apiSource).toContain('listSfxCandidates')
    expect(apiSource).toContain('buildSfxCandidateManifestDraft')
    expect(apiSource).toContain('importSfxManifest')

    expect(apiSource).not.toContain('downloadSfxToLibrary(')
  })

  it('plays protected library previews through authenticated blob requests', () => {
    expect(apiSource).toContain('getAudioLibraryPreviewBlob')
    expect(apiSource).toContain("responseType: 'blob'")

    expect(browserSource).toContain('getAudioLibraryPreviewBlob')
    expect(browserSource).toContain('playManagedBlob')
    expect(browserSource).not.toContain('new Audio(url)')

    expect(pickerSource).toContain('getAudioLibraryPreviewBlob')
    expect(pickerSource).toContain('playManagedBlob')
    expect(pickerSource).not.toContain('new Audio(url)')
  })

  it('passes explicit library selections to structured script segment fields', () => {
    expect(pickerSource).toContain('onSelectAsset?: (selection: AudioAssetSelection) => void')
    expect(pickerSource).toContain('onSelectAsset?.(')
    expect(segmentDetailsSource).toContain('onSelectAsset={')
    expect(segmentDetailsSource).toContain('buildSoundEffectAssetPatch')
    expect(segmentDetailsSource).toContain('buildMusicAssetPatch')
  })

  it('keeps library browsing interactions responsive on large result sets', () => {
    expect(browserSource).toContain('useVirtualizer')
    expect(browserSource).toContain('AudioLibraryVirtualList')
    expect(browserSource).toContain('memo(')
    expect(browserSource).toContain('previewLoadingKey')
    expect(browserSource).toContain('AbortController')
    expect(browserSource).toContain('timeout={0}')
    expect(apiSource).toContain('signal?: AbortSignal')
  })

  it('exposes scene filtering for audiobook sound effects', () => {
    expect(browserSource).toContain('sfxSceneFilter')
    expect(browserSource).toContain('setSfxScenes')
    expect(browserSource).toContain('scene: sfxSceneFilter')
    expect(browserSource).toContain('sfxEntry.scenes')

    expect(apiSource).toContain('sfx_scenes?: string[]')
    expect(apiSource).toContain('scene?: string')
    expect(apiSource).toContain("query.set('scene', params.scene)")
  })

  it('keeps cleanup as dry-run plus explicit confirm workflow', () => {
    expect(purgeSource).toContain('素材清理')
    expect(purgeSource).toContain('cleanupAudioLibrary')
    expect(purgeSource).toContain('dry_run')
    expect(purgeSource).toContain('confirm')
    expect(purgeSource).toContain('我确认')
    expect(purgeSource).toContain('missing_entries')
    expect(purgeSource).toContain('low_quality_entries')
    expect(purgeSource).toContain('orphaned_files')
  })

  it('invalidates destructive previews when operation parameters change', () => {
    expect(purgeSource).toContain('const currentRequestKey = JSON.stringify([')
    expect(purgeSource).toContain('previewRequestKey === currentRequestKey')
    expect(purgeSource).toContain('setPreviewRequestKey(currentRequestKey)')
    expect(purgeSource).toContain('setLibraryType(initialLibraryType)')
    expect(purgeSource).toContain('plan_token: previewPlanToken')
    expect(apiSource).toContain('plan_token?: string')

  })

  it('keeps audio library management actions admin-only', () => {
    expect(browserSource).toContain('state.auth')
    expect(browserSource).toContain('role.code === \'admin\'')
    expect(browserSource).toContain('role.code === \'super_admin\'')
    expect(browserSource).toContain('isAdmin &&')
    expect(browserSource).toContain('deleteAudioLibraryAsset')
    expect(browserSource).toContain('DeleteOutlineIcon')
    expect(apiSource).toContain('/api/v1/audiobook/audio-library/assets/')
  })

  it('keeps quality, license, source, and attribution metadata behind details', () => {
    expect(browserSource).toContain('详细信息')
    expect(browserSource).toContain('buildAudioLibraryDetailItems')
    expect(browserSource).toContain('Collapse')
    expect(displaySource).toContain('质量')
    expect(displaySource).toContain('授权')
    expect(displaySource).toContain('允许商用')
    expect(displaySource).toContain('需署名')
    expect(displaySource).toContain('作者')
    expect(displaySource).toContain('来源')
    expect(browserSource).toContain('quality_score')
    expect(browserSource).toContain('license_commercial')
    expect(browserSource).toContain('attribution_required')
    expect(browserSource).toContain('attribution_text')

    expect(apiSource).toContain('quality_score?: number')
    expect(apiSource).toContain('license_commercial?: boolean')
    expect(apiSource).toContain('attribution_required?: boolean')
    expect(apiSource).toContain('attribution_text?: string')
  })

  it('formats sound effect asset names into user-facing Chinese labels', () => {
    expect(browserSource).toContain('formatAudioAssetNameLabel')
    expect(browserSource).toContain('formatAudioAssetNameLabel(sfxEntry?.name)')
    expect(browserSource).toContain('formatAudioAssetDescriptionLabel(sfxEntry)')
    expect(pickerSource).toContain('formatAudioAssetNameLabel')
    expect(pickerSource).toContain('formatAudioKeywordLabel')
  })

  it('allows authenticated users to upload licensed shared audio assets', () => {
    expect(browserSource).toContain('AudioLibraryUploadDialog')
    expect(browserSource).toContain('上传素材')
    expect(uploadDialogSource).toContain('rightsConfirmed')
    expect(uploadDialogSource).toContain('我确认拥有该音频的共享和使用授权')
    expect(uploadDialogSource).toContain('uploadAudioLibraryAsset')
    expect(apiSource).toContain('/api/v1/audiobook/audio-library/assets/upload')
  })

  it('supports per-user star ratings without triggering preview playback', () => {
    expect(browserSource).toContain('<Rating')
    expect(browserSource).toContain('event.stopPropagation()')
    expect(browserSource).toContain('rateAudioLibraryAsset')
    expect(browserSource).toContain('auto_unpublished')
    expect(apiSource).toContain('rating_count: number')
    expect(apiSource).toContain('average_rating: number')
    expect(apiSource).toContain('user_rating?: number | null')
    expect(apiSource).toContain('/rating`')
  })

  it('shows uploaded Chinese music names before style and mood metadata', () => {
    expect(browserSource).toContain('formatAudioAssetNameLabel(musicEntry?.name)')
    expect(apiSource).toContain('name: string')
    expect(apiSource).toContain('description: string')
    expect(apiSource).toContain('tags: string[]')
  })
})
