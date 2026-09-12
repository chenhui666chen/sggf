import type { TFunction } from 'i18next'

import type { UserAssetRecord } from '@/services/api'

import {
  extractAudiobookChapterAssetRef,
  extractAudiobookChapterTraceInfo,
  extractDreamweaverLibraryAssetId,
  extractDreamweaverLibraryTraceInfo,
  extractDreamweaverMergedRunId,
  extractUserAssetProjectId,
} from './userAssetSourcePayloadSelectors'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

type UserAssetSourceReadable = Pick<
  UserAssetRecord,
  'source_module' | 'project_id' | 'source_payload_json' | 'metadata_json'
>

export type UserAssetProjectTitleMap = ReadonlyMap<number, string>

export type UserAssetSourceInfo = {
  label: string
  summary: string
  traceLabel?: string | null
  projectLabel?: string | null
  backPath?: string | null
  backLabel?: string | null
}

export type ProtectedUserAssetRef =
  | { kind: 'dreamweaver_library'; libraryAssetId: number }
  | { kind: 'dreamweaver_run'; runId: string }
  | { kind: 'audiobook'; audiobookProjectId: number; chapterId: number }

function appendQueryParams(
  path: string,
  params: Record<string, string | number | null | undefined>,
): string {
  const searchParams = new URLSearchParams()

  Object.entries(params).forEach(([key, value]) => {
    if (value == null) return
    const normalized = typeof value === 'number' ? String(value) : String(value).trim()
    if (!normalized) return
    searchParams.set(key, normalized)
  })

  const query = searchParams.toString()
  return query ? `${path}?${query}` : path
}

function getUserAssetProjectLabel(
  asset: UserAssetSourceReadable,
  projectTitleMap?: UserAssetProjectTitleMap,
  t?: TFunction,
): string | null {
  const translate = t ?? DEFAULT_TRANSLATE
  const projectId = extractUserAssetProjectId(asset)
  return projectId ? projectTitleMap?.get(projectId) || translate('userAsset.projectFallback', { id: projectId }) : null
}

function getDreamweaverEntityTypeLabel(entityType: string | null | undefined, t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  const normalized = String(entityType || '').trim().toLowerCase()
  if (normalized === 'character') return translate('userAsset.source.entityCharacter')
  if (normalized === 'scene') return translate('userAsset.source.entityScene')
  if (normalized === 'prop') return translate('userAsset.source.entityProp')
  return translate('userAsset.source.entityMaterial')
}

export function getUserAssetSourceModule(asset: Pick<UserAssetRecord, 'source_module'>): string {
  return String(asset.source_module || '').trim().toLowerCase()
}

export function getProtectedUserAssetRef(asset: UserAssetSourceReadable): ProtectedUserAssetRef | null {
  const sourceModule = getUserAssetSourceModule(asset)

  const libraryAssetId = sourceModule === 'dreamweaver_library' ? extractDreamweaverLibraryAssetId(asset) : null
  if (libraryAssetId) return { kind: 'dreamweaver_library', libraryAssetId }

  const runId = sourceModule === 'dreamweaver_run' ? extractDreamweaverMergedRunId(asset) : null
  if (runId) return { kind: 'dreamweaver_run', runId }

  const audiobookRef = sourceModule === 'audiobook' ? extractAudiobookChapterAssetRef(asset) : null
  if (audiobookRef) return { kind: 'audiobook', ...audiobookRef }

  return null
}

export function isProtectedUserAsset(asset: UserAssetSourceReadable): boolean {
  return getProtectedUserAssetRef(asset) !== null
}

export function formatDreamweaverViewLabel(
  view: string | null | undefined,
  t?: TFunction,
): string | null {
  const translate = t ?? DEFAULT_TRANSLATE
  const normalized = String(view || '').trim().toLowerCase()
  if (!normalized) return null
  if (normalized === 'front') return translate('userAsset.source.viewFront')
  if (normalized === 'side') return translate('userAsset.source.viewSide')
  if (normalized === 'back') return translate('userAsset.source.viewBack')
  if (normalized === 'bust_front') return translate('userAsset.source.viewBustFront')
  if (normalized === 'bust_three_quarter') return translate('userAsset.source.viewBustThreeQuarter')
  if (normalized === 'bust_side') return translate('userAsset.source.viewBustSide')
  return normalized
}

export function getUserAssetSourceInfo(
  asset: UserAssetSourceReadable,
  projectTitleMap?: UserAssetProjectTitleMap,
  t?: TFunction,
): UserAssetSourceInfo {
  const translate = t ?? DEFAULT_TRANSLATE
  const sourceModule = getUserAssetSourceModule(asset)
  const projectId = extractUserAssetProjectId(asset)
  const projectLabel = getUserAssetProjectLabel(asset, projectTitleMap, t)

  if (sourceModule === 'asset_studio') {
    return {
      label: translate('userAsset.source.assetStudio'),
      summary: projectLabel
        ? translate('userAsset.source.fromAssetStudioWithProject', { project: projectLabel })
        : translate('userAsset.source.fromAssetStudio'),
      projectLabel,
      backPath: '/asset-studio',
      backLabel: translate('userAsset.source.goAssetStudio'),
    }
  }

  if (sourceModule === 'dreamweaver_library') {
    const traceInfo = extractDreamweaverLibraryTraceInfo(asset)
    const libraryAssetId = extractDreamweaverLibraryAssetId(asset)
    const entityTypeLabel = getDreamweaverEntityTypeLabel(traceInfo.entityType, t)
    const viewLabel = formatDreamweaverViewLabel(traceInfo.view, t)
    return {
      label: translate('userAsset.source.dreamweaverLibrary'),
      summary: projectLabel
        ? translate('userAsset.source.fromDreamweaverLibraryWithProject', { project: projectLabel })
        : translate('userAsset.source.fromDreamweaverLibrary'),
      traceLabel: viewLabel ? `${entityTypeLabel} · ${viewLabel}` : entityTypeLabel,
      projectLabel,
      backPath: projectId
        ? appendQueryParams(`/drama/${projectId}/library`, {
            assetId: libraryAssetId,
          })
        : '/drama',
      backLabel: projectId ? translate('userAsset.source.goLibrary') : translate('userAsset.source.goDramaModule'),
    }
  }

  if (sourceModule === 'dreamweaver_run') {
    const runId = extractDreamweaverMergedRunId(asset)
    return {
      label: translate('userAsset.source.dreamweaverRun'),
      summary: projectLabel
        ? translate('userAsset.source.fromDreamweaverRunWithProject', { project: projectLabel })
        : translate('userAsset.source.fromDreamweaverRun'),
      traceLabel: runId ? `run_id ${runId}` : translate('userAsset.source.runResult'),
      projectLabel,
      backPath: projectId
        ? appendQueryParams(`/drama/${projectId}`, {
            runId,
          })
        : '/drama',
      backLabel: projectId ? translate('userAsset.source.backDramaProject') : translate('userAsset.source.goDramaModule'),
    }
  }

  if (sourceModule === 'audiobook') {
    const chapterTraceInfo = extractAudiobookChapterTraceInfo(asset)
    const audiobookProjectId = chapterTraceInfo.audiobookProjectId
    const chapterId = chapterTraceInfo.chapterId
    const chapterNumber = chapterTraceInfo.chapterNumber
    const chapterTitle = chapterTraceInfo.chapterTitle || ''
    const safeChapterId = typeof chapterId === 'number' && chapterId > 0 ? chapterId : null
    const traceLabel = chapterNumber
      ? chapterTitle
        ? translate('userAsset.source.chapterTraceWithTitle', { number: chapterNumber, title: chapterTitle })
        : translate('userAsset.source.chapterTracePlain', { number: chapterNumber })
      : chapterTitle || (safeChapterId ? translate('userAsset.source.chapterFallback', { id: safeChapterId }) : translate('userAsset.source.chapterAudio'))

    return {
      label: translate('userAsset.source.audiobook'),
      summary: projectLabel
        ? translate('userAsset.source.fromAudiobookWithProject', { project: projectLabel })
        : translate('userAsset.source.fromAudiobook'),
      traceLabel,
      projectLabel,
      backPath: projectId
        ? appendQueryParams(`/audiobook/${projectId}`, {
            audiobookProjectId,
            chapterId: safeChapterId,
            focus: safeChapterId ? 'script-editor' : null,
          })
        : '/audiobook-dashboard',
      backLabel: projectId ? translate('userAsset.source.backAudiobookProject') : translate('userAsset.source.goAudiobookModule'),
    }
  }

  return {
    label: String(asset.source_module || '').trim() || translate('userAsset.source.unclassified'),
    summary: translate('userAsset.source.unknownModuleSummary'),
    projectLabel,
  }
}
