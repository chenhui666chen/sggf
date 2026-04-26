import type { UserAssetRecord } from '@/services/api'

import {
  extractAudiobookChapterAssetRef,
  extractAudiobookChapterTraceInfo,
  extractDreamweaverLibraryAssetId,
  extractDreamweaverLibraryTraceInfo,
  extractDreamweaverMergedRunId,
  extractUserAssetProjectId,
} from './userAssetSourcePayloadSelectors'

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
): string | null {
  const projectId = extractUserAssetProjectId(asset)
  return projectId ? projectTitleMap?.get(projectId) || `项目 #${projectId}` : null
}

function getDreamweaverEntityTypeLabel(entityType: string | null | undefined): string {
  const normalized = String(entityType || '').trim().toLowerCase()
  if (normalized === 'character') return '角色'
  if (normalized === 'scene') return '场景'
  if (normalized === 'prop') return '道具'
  return '素材'
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

export function formatDreamweaverViewLabel(view: string | null | undefined): string | null {
  const normalized = String(view || '').trim().toLowerCase()
  if (!normalized) return null
  if (normalized === 'front') return '正面'
  if (normalized === 'side') return '侧面'
  if (normalized === 'back') return '背面'
  if (normalized === 'bust_front') return '半身正面'
  if (normalized === 'bust_three_quarter') return '半身四分之三侧'
  if (normalized === 'bust_side') return '半身侧面'
  return normalized
}

export function getUserAssetSourceInfo(
  asset: UserAssetSourceReadable,
  projectTitleMap?: UserAssetProjectTitleMap,
): UserAssetSourceInfo {
  const sourceModule = getUserAssetSourceModule(asset)
  const projectId = extractUserAssetProjectId(asset)
  const projectLabel = getUserAssetProjectLabel(asset, projectTitleMap)

  if (sourceModule === 'asset_studio') {
    return {
      label: '资产工坊',
      summary: projectLabel ? `来自资产工坊，关联项目：${projectLabel}。` : '来自资产工坊。',
      projectLabel,
      backPath: '/asset-studio',
      backLabel: '前往资产工坊',
    }
  }

  if (sourceModule === 'dreamweaver_library') {
    const traceInfo = extractDreamweaverLibraryTraceInfo(asset)
    const libraryAssetId = extractDreamweaverLibraryAssetId(asset)
    const entityTypeLabel = getDreamweaverEntityTypeLabel(traceInfo.entityType)
    const viewLabel = formatDreamweaverViewLabel(traceInfo.view)
    return {
      label: '短剧素材库',
      summary: projectLabel ? `来自短剧素材库，沉淀于项目 ${projectLabel}。` : '来自短剧素材库。',
      traceLabel: viewLabel ? `${entityTypeLabel} · ${viewLabel}` : entityTypeLabel,
      projectLabel,
      backPath: projectId
        ? appendQueryParams(`/drama/${projectId}/library`, {
            assetId: libraryAssetId,
          })
        : '/drama',
      backLabel: projectId ? '前往素材库' : '前往短剧模块',
    }
  }

  if (sourceModule === 'dreamweaver_run') {
    const runId = extractDreamweaverMergedRunId(asset)
    return {
      label: '短剧成片',
      summary: projectLabel ? `来自短剧运行结果，关联项目：${projectLabel}。` : '来自短剧运行结果。',
      traceLabel: runId ? `run_id ${runId}` : '运行结果',
      projectLabel,
      backPath: projectId
        ? appendQueryParams(`/drama/${projectId}`, {
            runId,
          })
        : '/drama',
      backLabel: projectId ? '回到短剧项目' : '前往短剧模块',
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
      ? `第${chapterNumber}章${chapterTitle ? ` · ${chapterTitle}` : ''}`
      : chapterTitle || (safeChapterId ? `章节 #${safeChapterId}` : '章节音频')

    return {
      label: '有声书音频',
      summary: projectLabel ? `来自有声书章节成品，关联项目：${projectLabel}。` : '来自有声书章节成品。',
      traceLabel,
      projectLabel,
      backPath: projectId
        ? appendQueryParams(`/audiobook/${projectId}`, {
            audiobookProjectId,
            chapterId: safeChapterId,
            focus: safeChapterId ? 'script-editor' : null,
          })
        : '/audiobook-dashboard',
      backLabel: projectId ? '回到有声书项目' : '前往有声书模块',
    }
  }

  return {
    label: String(asset.source_module || '').trim() || '未分类来源',
    summary: '该资产已进入用户中心统一治理，具体生产仍建议回到原模块处理。',
    projectLabel,
  }
}
