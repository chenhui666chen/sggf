import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const browserSource = readFileSync(
  new URL('../AudioLibraryBrowser.tsx', import.meta.url),
  'utf8',
)

const apiSource = readFileSync(
  new URL('../../../services/api.ts', import.meta.url),
  'utf8',
)

const candidateReviewSource = readFileSync(
  new URL('../SfxCandidateReviewDialog.tsx', import.meta.url),
  'utf8',
)

const manifestImportSource = readFileSync(
  new URL('../SfxManifestImportDialog.tsx', import.meta.url),
  'utf8',
)

const purgeSource = readFileSync(
  new URL('../AudioLibraryPurgeDialog.tsx', import.meta.url),
  'utf8',
)

describe('AudioLibraryBrowser source guards', () => {
  it('keeps the library browser read-only for public third-party assets', () => {
    expect(browserSource).toContain('音频素材库')
    expect(browserSource).toContain('getAudioLibraryStats')
    expect(browserSource).toContain('browseSoundEffects')
    expect(browserSource).toContain('browseMusic')
    expect(browserSource).toContain('getAudioLibraryPreviewUrl')
    expect(browserSource).toContain('SfxCandidateReviewDialog')
    expect(browserSource).toContain('SfxManifestImportDialog')
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

  it('exposes scene filtering for audiobook sound effects', () => {
    expect(browserSource).toContain('sfxSceneFilter')
    expect(browserSource).toContain('setSfxScenes')
    expect(browserSource).toContain('scene: sfxSceneFilter')
    expect(browserSource).toContain('entry.scenes')

    expect(apiSource).toContain('sfx_scenes?: string[]')
    expect(apiSource).toContain('scene?: string')
    expect(apiSource).toContain("query.set('scene', params.scene)")
  })

  it('keeps candidate review as manifest-only workflow', () => {
    expect(candidateReviewSource).toContain('候选清单审核')
    expect(candidateReviewSource).toContain('listSfxCandidates')
    expect(candidateReviewSource).toContain('buildSfxCandidateManifestDraft')
    expect(candidateReviewSource).toContain('本地文件')
    expect(candidateReviewSource).toContain('manifest')

    expect(candidateReviewSource).not.toContain('downloadSfxToLibrary')
    expect(candidateReviewSource).not.toContain('searchPublicSfx')
    expect(candidateReviewSource).not.toContain('CloudDownloadIcon')
  })

  it('keeps manifest import as two-step local workflow', () => {
    expect(manifestImportSource).toContain('manifest 导入')
    expect(manifestImportSource).toContain('importSfxManifest')
    expect(manifestImportSource).toContain('dry_run')
    expect(manifestImportSource).toContain('confirm')
    expect(manifestImportSource).toContain('我确认')

    expect(manifestImportSource).not.toContain('downloadSfxToLibrary')
    expect(manifestImportSource).not.toContain('searchPublicSfx')
    expect(manifestImportSource).not.toContain('CloudDownloadIcon')
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

  it('keeps audio library management actions admin-only', () => {
    expect(browserSource).toContain('state.auth')
    expect(browserSource).toContain('role.code === \'admin\'')
    expect(browserSource).toContain('role.code === \'super_admin\'')
    expect(browserSource).toContain('isAdmin &&')
    expect(browserSource).toContain('deleteAudioLibraryAsset')
    expect(browserSource).toContain('DeleteOutlineIcon')
    expect(apiSource).toContain('/api/v1/audiobook/audio-library/assets/')
  })

  it('shows quality, license, source, and attribution metadata in library results', () => {
    expect(browserSource).toContain('质量')
    expect(browserSource).toContain('授权')
    expect(browserSource).toContain('允许商用')
    expect(browserSource).toContain('需署名')
    expect(browserSource).toContain('作者')
    expect(browserSource).toContain('quality_score')
    expect(browserSource).toContain('license_commercial')
    expect(browserSource).toContain('attribution_required')
    expect(browserSource).toContain('attribution_text')

    expect(apiSource).toContain('quality_score?: number')
    expect(apiSource).toContain('license_commercial?: boolean')
    expect(apiSource).toContain('attribution_required?: boolean')
    expect(apiSource).toContain('attribution_text?: string')
  })
})
