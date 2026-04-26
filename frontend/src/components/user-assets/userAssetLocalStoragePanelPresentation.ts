import type { LocalAssetExternalDirectoryStatus } from '@/utils/localAssetExternalDirectory'
import type { LocalAssetVaultInventoryRecord } from '@/utils/localAssetVault'
import type { UserAssetRecord } from '@/services/api'
import {
  getUserAssetSourceInfo,
  type UserAssetProjectTitleMap,
} from '@/contracts/userAssetSourceReaders'
import type {
  UserAssetExternalDirectoryAssetHealthItem,
  UserAssetExternalDirectoryAssetHealthSummary,
} from './userAssetLocalDiagnosticsPresentation'

export type LocalStoragePanelCopy = {
  severity: 'info' | 'warning' | 'success'
  summary: string
  pickLabel: string
  showRecoverAccess: boolean
  clearEnabled: boolean
  statusLabel: string
  statusTone: 'default' | 'info' | 'success' | 'warning'
  guidance: string | null
  backupHint: string | null
}

export type UserAssetLocalStorageActionMetricSpec = {
  key: string
  label: string
  value: number
}

export type UserAssetLocalStorageActionIssueType = 'directory_inaccessible' | 'missing_local_copy'

export type UserAssetLocalStorageActionIssueItem = {
  key: string
  assetId: number
  issueType: UserAssetLocalStorageActionIssueType
  title: string
  assetUuid: string
  sourceModule: string
  localStoragePath: string | null
  externalRelativePath: string | null
  actionHint: string
  restorableAsset: UserAssetRecord | null
  sourceActionPath: string | null
  sourceActionLabel: string | null
}

export type UserAssetLocalStorageActionReport = {
  mode: 'preview' | 'restore'
  scope: 'current_page' | 'filtered_scope'
  severity: 'info' | 'success' | 'warning' | 'error'
  title: string
  summary: string
  completedAtLabel: string
  metrics: UserAssetLocalStorageActionMetricSpec[]
  issueItems: UserAssetLocalStorageActionIssueItem[]
}

function buildDirectoryLabel(directoryName: string | null | undefined): string {
  const normalized = String(directoryName || '').trim()
  return normalized || '未命名目录'
}

export function buildUserAssetLocalStorageSupportLabel(
  status: LocalAssetExternalDirectoryStatus | null,
  loading: boolean,
): string {
  if (loading) {
    return '检查中'
  }

  return status?.supported ? '支持 File System Access API' : '不支持 File System Access API'
}

export function buildUserAssetRecordedDirectoryLabel(
  status: LocalAssetExternalDirectoryStatus | null,
  loading: boolean,
): string {
  if (loading) {
    return '读取中'
  }

  if (!status?.configured) {
    return '未配置'
  }

  return buildDirectoryLabel(status.directoryName)
}

export function buildUserAssetLocalStoragePanelCopy(
  status: LocalAssetExternalDirectoryStatus | null,
  loading: boolean,
): LocalStoragePanelCopy {
  if (loading) {
    return {
      severity: 'info',
      summary: '正在检查用户目录状态。',
      pickLabel: '选择目录',
      showRecoverAccess: false,
      clearEnabled: false,
      statusLabel: '检查中',
      statusTone: 'info',
      guidance: null,
      backupHint: null,
    }
  }

  if (!status?.supported) {
    return {
      severity: 'warning',
      summary: '当前浏览器不支持 File System Access API，无法把新收录资产直接写入用户目录。',
      pickLabel: '当前不可用',
      showRecoverAccess: false,
      clearEnabled: Boolean(status?.configured),
      statusLabel: '浏览器不支持',
      statusTone: 'default',
      guidance: '当前只能继续使用浏览器本地存储，无法直接写入用户目录。',
      backupHint: null,
    }
  }

  if (!status.configured) {
    return {
      severity: 'info',
      summary: '尚未配置用户目录。配置后，手动收录的新资产会优先写入你选择的本地目录。',
      pickLabel: '选择目录',
      showRecoverAccess: false,
      clearEnabled: false,
      statusLabel: '未配置',
      statusTone: 'info',
      guidance: '完成配置后，新的显式收录会优先写入所选目录。',
      backupHint: null,
    }
  }

  const directoryLabel = buildDirectoryLabel(status.directoryName)
  if (status.permission === 'granted') {
    return {
      severity: 'success',
      summary: `已连接用户目录：${directoryLabel}。新的手动收录资产会优先写入该目录。`,
      pickLabel: '更换目录',
      showRecoverAccess: false,
      clearEnabled: true,
      statusLabel: '已连接',
      statusTone: 'success',
      guidance: null,
      backupHint: '该目录已经是真实系统目录，可直接纳入你自己的常规文件备份或同步流程。',
    }
  }

  if (status.permission === 'prompt') {
    return {
      severity: 'warning',
      summary: `已记录用户目录：${directoryLabel}，但浏览器需要重新授权后才能继续使用。`,
      pickLabel: '重新选择目录',
      showRecoverAccess: true,
      clearEnabled: true,
      statusLabel: '待恢复授权',
      statusTone: 'warning',
      guidance: '先尝试“恢复访问”，如果浏览器仍要求重新授权，再重新选择目录。',
      backupHint: '恢复访问后，建议再确认该目录中的资产文件是否已纳入你的常规备份流程。',
    }
  }

  if (status.permission === 'denied') {
    return {
      severity: 'warning',
      summary: `已记录用户目录：${directoryLabel}，但当前权限已失效，请重新选择目录。`,
      pickLabel: '重新选择目录',
      showRecoverAccess: true,
      clearEnabled: true,
      statusLabel: '权限失效',
      statusTone: 'warning',
      guidance: '先尝试“恢复访问”，如果浏览器仍拒绝，再重新选择目录。',
      backupHint: '恢复访问后，建议再确认该目录中的资产文件是否已纳入你的常规备份流程。',
    }
  }

  return {
    severity: 'info',
    summary: `已记录用户目录：${directoryLabel}，当前无法确认权限状态，建议刷新或重新选择目录。`,
    pickLabel: '重新选择目录',
    showRecoverAccess: true,
    clearEnabled: true,
    statusLabel: '状态未知',
    statusTone: 'info',
    guidance: '建议先刷新状态；若仍无法确认，再重新选择目录。',
    backupHint: '确认目录可用后，可把该目录纳入你自己的常规文件备份或同步流程。',
  }
}

function formatBackupGuideTimestamp(value: Date): string {
  return value.toLocaleString('zh-CN', { hour12: false })
}

function padDateSegment(value: number): string {
  return String(value).padStart(2, '0')
}

export function buildUserAssetLocalStorageBackupGuideFilename(date = new Date()): string {
  const year = date.getFullYear()
  const month = padDateSegment(date.getMonth() + 1)
  const day = padDateSegment(date.getDate())
  const hours = padDateSegment(date.getHours())
  const minutes = padDateSegment(date.getMinutes())
  const seconds = padDateSegment(date.getSeconds())

  return `user-asset-local-storage-backup-guide-${year}${month}${day}-${hours}${minutes}${seconds}.md`
}

export function buildUserAssetLocalStorageInventoryFilename(date = new Date()): string {
  const year = date.getFullYear()
  const month = padDateSegment(date.getMonth() + 1)
  const day = padDateSegment(date.getDate())
  const hours = padDateSegment(date.getHours())
  const minutes = padDateSegment(date.getMinutes())
  const seconds = padDateSegment(date.getSeconds())

  return `user-asset-local-storage-inventory-${year}${month}${day}-${hours}${minutes}${seconds}.json`
}

export function buildUserAssetLocalStorageRebuildListFilename(date = new Date()): string {
  const year = date.getFullYear()
  const month = padDateSegment(date.getMonth() + 1)
  const day = padDateSegment(date.getDate())
  const hours = padDateSegment(date.getHours())
  const minutes = padDateSegment(date.getMinutes())
  const seconds = padDateSegment(date.getSeconds())

  return `user-asset-local-storage-rebuild-list-${year}${month}${day}-${hours}${minutes}${seconds}.json`
}

export function countUserAssetLocalStorageRebuildCandidates(
  summary: UserAssetExternalDirectoryAssetHealthSummary | null | undefined,
): number {
  if (!summary) {
    return 0
  }

  return Math.max(0, summary.inaccessibleAssetCount) + Math.max(0, summary.missingLocalCopyCount)
}

export function buildUserAssetLocalStorageActionIssueTypeLabel(
  issueType: UserAssetLocalStorageActionIssueType,
): string {
  if (issueType === 'directory_inaccessible') {
    return '目录异常'
  }

  return '缺失副本'
}

function buildUserAssetLocalStorageActionReportSeverity(input: {
  restoredCount: number
  existingCount: number
  blockedCount: number
  failedCount: number
  inaccessibleAssetCount: number
}): UserAssetLocalStorageActionReport['severity'] {
  if (
    input.failedCount > 0
    && input.restoredCount <= 0
    && input.existingCount <= 0
    && input.blockedCount <= 0
  ) {
    return 'error'
  }

  if (input.failedCount > 0 || input.blockedCount > 0 || input.inaccessibleAssetCount > 0) {
    return 'warning'
  }

  if (input.restoredCount > 0 || input.existingCount > 0) {
    return 'success'
  }

  return 'info'
}

export function buildUserAssetLocalStorageActionReport(input: {
  mode?: 'preview' | 'restore'
  scope: 'current_page' | 'filtered_scope'
  scannedAssetCount: number
  trackedAssetCount: number
  missingLocalCopyCount: number
  inaccessibleAssetCount: number
  restoredCount: number
  existingCount: number
  blockedCount: number
  failedCount: number
  healthSummary?: UserAssetExternalDirectoryAssetHealthSummary | null
  issueAssets?: UserAssetRecord[]
  projectTitleMap?: UserAssetProjectTitleMap
  completedAt?: Date
}): UserAssetLocalStorageActionReport {
  const completedAt = input.completedAt ?? new Date()
  const mode = input.mode ?? 'restore'
  const scopeLabel = input.scope === 'current_page' ? '当前页' : '当前筛选'
  const isPreview = mode === 'preview'

  let summary = ''
  if (input.scannedAssetCount <= 0) {
    summary = `${scopeLabel}内没有可扫描的资产。`
  } else if (input.trackedAssetCount <= 0) {
    summary = `已扫描${scopeLabel} ${input.scannedAssetCount} 项资产，未发现登记为用户目录副本的资产。`
  } else if (input.missingLocalCopyCount <= 0 && input.inaccessibleAssetCount > 0) {
    summary = `已扫描${scopeLabel} ${input.scannedAssetCount} 项资产，发现 ${input.inaccessibleAssetCount} 项登记为用户目录副本的资产因目录不可访问，暂时无法直接重建。`
  } else if (input.missingLocalCopyCount <= 0) {
    summary = `已扫描${scopeLabel} ${input.scannedAssetCount} 项资产，${input.trackedAssetCount} 项登记为用户目录副本，当前未发现缺失副本。`
  } else if (isPreview) {
    summary = `已扫描${scopeLabel} ${input.scannedAssetCount} 项资产，${input.trackedAssetCount} 项登记为用户目录副本，其中 ${input.missingLocalCopyCount} 项缺失副本可执行重建。`
  } else {
    summary = `已扫描${scopeLabel} ${input.scannedAssetCount} 项资产，${input.trackedAssetCount} 项登记为用户目录副本，其中 ${input.missingLocalCopyCount} 项缺失副本已进入重建流程。`
  }

  return {
    mode,
    scope: input.scope,
    severity: buildUserAssetLocalStorageActionReportSeverity(input),
    title: `${scopeLabel}${isPreview ? '扫描结果' : '重建结果'}`,
    summary,
    completedAtLabel: formatBackupGuideTimestamp(completedAt),
    metrics: [
      {
        key: 'scanned-assets',
        label: '已扫描',
        value: Math.max(0, input.scannedAssetCount),
      },
      {
        key: 'tracked-assets',
        label: '目录副本',
        value: Math.max(0, input.trackedAssetCount),
      },
      {
        key: 'missing-assets',
        label: '缺失副本',
        value: Math.max(0, input.missingLocalCopyCount),
      },
      ...(input.restoredCount > 0
        ? [{
            key: 'restored-assets',
            label: '已恢复',
            value: Math.max(0, input.restoredCount),
          }]
        : []),
      ...(input.existingCount > 0
        ? [{
            key: 'existing-assets',
            label: '已存在',
            value: Math.max(0, input.existingCount),
          }]
        : []),
      ...(input.inaccessibleAssetCount > 0
        ? [{
            key: 'inaccessible-assets',
            label: '目录异常',
            value: Math.max(0, input.inaccessibleAssetCount),
          }]
        : []),
      ...(input.blockedCount > 0
        ? [{
            key: 'blocked-assets',
            label: '受阻',
            value: Math.max(0, input.blockedCount),
          }]
        : []),
      ...(input.failedCount > 0
        ? [{
            key: 'failed-assets',
            label: '失败',
            value: Math.max(0, input.failedCount),
          }]
        : []),
    ],
    issueItems: buildUserAssetLocalStorageActionIssueItems(
      input.healthSummary,
      input.issueAssets,
      input.projectTitleMap,
    ),
  }
}

function buildUserAssetLocalStorageRebuildActionHint(
  issueType: UserAssetLocalStorageActionIssueType,
): string {
  if (issueType === 'directory_inaccessible') {
    return '先恢复用户目录访问，再重新验证目录副本；若目录已迁移，请重新选择目录并按来源页重新收录。'
  }

  return '从来源页重新收录该资产，补回用户目录中的长期副本。'
}

function buildUserAssetLocalStorageActionIssueItem(
  asset: UserAssetExternalDirectoryAssetHealthItem,
  issueType: UserAssetLocalStorageActionIssueType,
  restorableAsset: UserAssetRecord | null,
  projectTitleMap?: UserAssetProjectTitleMap,
): UserAssetLocalStorageActionIssueItem {
  const sourceInfo = restorableAsset ? getUserAssetSourceInfo(restorableAsset, projectTitleMap) : null

  return {
    key: `${issueType}:${asset.assetId}:${asset.assetUuid}`,
    assetId: asset.assetId,
    issueType,
    title: asset.title,
    assetUuid: asset.assetUuid,
    sourceModule: asset.sourceModule,
    localStoragePath: asset.localStoragePath,
    externalRelativePath: asset.externalRelativePath,
    actionHint: buildUserAssetLocalStorageRebuildActionHint(issueType),
    restorableAsset,
    sourceActionPath: sourceInfo?.backPath || null,
    sourceActionLabel: sourceInfo?.backLabel || null,
  }
}

function buildUserAssetLocalStorageActionIssueItems(
  summary: UserAssetExternalDirectoryAssetHealthSummary | null | undefined,
  issueAssets: UserAssetRecord[] | null | undefined,
  projectTitleMap?: UserAssetProjectTitleMap,
): UserAssetLocalStorageActionIssueItem[] {
  if (!summary) {
    return []
  }

  const issueAssetMap = new Map((issueAssets || []).map((asset) => [asset.id, asset]))

  return [
    ...(summary.missingLocalCopyAssets || []).map((asset) =>
      buildUserAssetLocalStorageActionIssueItem(
        asset,
        'missing_local_copy',
        issueAssetMap.get(asset.assetId) || null,
        projectTitleMap,
      )),
    ...(summary.inaccessibleAssets || []).map((asset) =>
      buildUserAssetLocalStorageActionIssueItem(
        asset,
        'directory_inaccessible',
        issueAssetMap.get(asset.assetId) || null,
        projectTitleMap,
      )),
  ]
}

function buildUserAssetLocalStorageRebuildListItem(
  asset: UserAssetExternalDirectoryAssetHealthItem,
  issueType: UserAssetLocalStorageActionIssueType,
) {
  return {
    issue_type: issueType,
    action_hint: buildUserAssetLocalStorageRebuildActionHint(issueType),
    asset_id: asset.assetId,
    asset_uuid: asset.assetUuid,
    title: asset.title,
    source_module: asset.sourceModule,
    local_storage_driver: asset.localStorageDriver,
    local_storage_path: asset.localStoragePath,
    external_relative_path: asset.externalRelativePath,
    source_uri: asset.sourceUri,
    preview_uri: asset.previewUri,
    download_uri: asset.downloadUri,
  }
}

export function buildUserAssetLocalStorageBackupGuide(options: {
  status: LocalAssetExternalDirectoryStatus | null
  loading: boolean
  generatedAt?: Date
}): string {
  const {
    status,
    loading,
    generatedAt = new Date(),
  } = options

  const panelCopy = buildUserAssetLocalStoragePanelCopy(status, loading)
  const supportLabel = buildUserAssetLocalStorageSupportLabel(status, loading)
  const recordedDirectoryLabel = buildUserAssetRecordedDirectoryLabel(status, loading)

  const lines = [
    '# 用户资产本地目录备份说明',
    '',
    `生成时间：${formatBackupGuideTimestamp(generatedAt)}`,
    `当前状态：${panelCopy.statusLabel}`,
    `浏览器支持：${supportLabel}`,
    `已记录目录：${recordedDirectoryLabel}`,
    '',
    '## 当前说明',
    panelCopy.summary,
    '',
    '## 当前优先入口',
    '- Asset Studio 显式收录',
    '- Audiobook 手动收录',
    '',
    '## 当前仍保留在浏览器本地存储中的内容',
    '- 播放器试听缓存等自动本地缓存仍保留在浏览器管理的本地存储中',
    '',
    '## 恢复与备份建议',
  ]

  if (panelCopy.guidance) {
    lines.push(`- ${panelCopy.guidance}`)
  }
  if (panelCopy.backupHint) {
    lines.push(`- ${panelCopy.backupHint}`)
  }
  if (!panelCopy.guidance && !panelCopy.backupHint) {
    lines.push('- 当前没有额外恢复或备份提示，可继续按既有目录流程使用。')
  }

  lines.push(
    '',
    '## 使用边界',
    '- 用户目录中的文件属于真实系统文件，可纳入你自己的备份或同步工具。',
    '- 浏览器站点存储中的自动缓存仍可能受到浏览器清理策略影响。',
    '- 如果用户目录权限失效，需要在用户中心重新恢复访问或重新选择目录。',
  )

  return lines.join('\n')
}

export function buildUserAssetLocalStorageInventoryExport(options: {
  status: LocalAssetExternalDirectoryStatus | null
  loading: boolean
  inventory: LocalAssetVaultInventoryRecord[]
  generatedAt?: Date
}): string {
  const {
    status,
    loading,
    inventory,
    generatedAt = new Date(),
  } = options

  const panelCopy = buildUserAssetLocalStoragePanelCopy(status, loading)
  const supportLabel = buildUserAssetLocalStorageSupportLabel(status, loading)
  const recordedDirectoryLabel = buildUserAssetRecordedDirectoryLabel(status, loading)
  const storageDriverSummary = inventory.reduce<Record<string, number>>((acc, item) => {
    const key = item.storageDriver || 'unknown'
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})
  const persistLevelSummary = inventory.reduce<Record<string, number>>((acc, item) => {
    const key = item.persistLevel || 'unknown'
    acc[key] = (acc[key] || 0) + 1
    return acc
  }, {})

  return JSON.stringify({
    generated_at: generatedAt.toISOString(),
    directory_status: {
      status_label: panelCopy.statusLabel,
      browser_support: supportLabel,
      recorded_directory: recordedDirectoryLabel,
      summary: panelCopy.summary,
      guidance: panelCopy.guidance,
      backup_hint: panelCopy.backupHint,
    },
    summary: {
      total_assets: inventory.length,
      storage_drivers: storageDriverSummary,
      persist_levels: persistLevelSummary,
    },
    items: inventory.map((item) => ({
      asset_uuid: item.assetUuid,
      media_kind: item.mediaKind,
      mime_type: item.mimeType ?? null,
      file_size: item.fileSize ?? null,
      source_module: item.sourceModule ?? null,
      title: item.title ?? null,
      source_uri: item.sourceUri ?? null,
      preview_uri: item.previewUri ?? null,
      download_uri: item.downloadUri ?? null,
      storage_driver: item.storageDriver,
      storage_path: item.storagePath ?? null,
      external_relative_path: item.externalRelativePath ?? null,
      persist_level: item.persistLevel,
      created_at: item.createdAt,
      updated_at: item.updatedAt,
      metadata_json: item.metadata || {},
    })),
  }, null, 2)
}

export function buildUserAssetLocalStorageRebuildListExport(options: {
  status: LocalAssetExternalDirectoryStatus | null
  loading: boolean
  healthSummary: UserAssetExternalDirectoryAssetHealthSummary | null | undefined
  generatedAt?: Date
}): string {
  const {
    status,
    loading,
    healthSummary,
    generatedAt = new Date(),
  } = options

  const panelCopy = buildUserAssetLocalStoragePanelCopy(status, loading)
  const supportLabel = buildUserAssetLocalStorageSupportLabel(status, loading)
  const recordedDirectoryLabel = buildUserAssetRecordedDirectoryLabel(status, loading)
  const rebuildCandidateCount = countUserAssetLocalStorageRebuildCandidates(healthSummary)
  const inaccessibleAssets = healthSummary?.inaccessibleAssets ?? []
  const missingLocalCopyAssets = healthSummary?.missingLocalCopyAssets ?? []

  return JSON.stringify({
    generated_at: generatedAt.toISOString(),
    directory_status: {
      status_label: panelCopy.statusLabel,
      browser_support: supportLabel,
      recorded_directory: recordedDirectoryLabel,
      summary: panelCopy.summary,
      guidance: panelCopy.guidance,
      backup_hint: panelCopy.backupHint,
      supported: status?.supported ?? false,
      configured: status?.configured ?? false,
      permission: status?.permission ?? 'unknown',
    },
    summary: {
      tracked_assets: Math.max(0, healthSummary?.trackedAssetCount || 0),
      inaccessible_asset_count: Math.max(0, healthSummary?.inaccessibleAssetCount || 0),
      missing_local_copy_count: Math.max(0, healthSummary?.missingLocalCopyCount || 0),
      rebuild_candidate_count: rebuildCandidateCount,
    },
    items: [
      ...inaccessibleAssets.map((asset) => buildUserAssetLocalStorageRebuildListItem(asset, 'directory_inaccessible')),
      ...missingLocalCopyAssets.map((asset) => buildUserAssetLocalStorageRebuildListItem(asset, 'missing_local_copy')),
    ],
  }, null, 2)
}
