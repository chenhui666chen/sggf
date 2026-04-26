import type { LegacyLocalAssetMigrationStatus } from '@/utils/localAssetMigration'
import type { LocalAssetExternalDirectoryStatus } from '@/utils/localAssetExternalDirectory'

export type UserAssetListStatusNotice = {
  severity: 'info' | 'warning'
  text: string
}

export type UserAssetExternalDirectoryAssetHealthItem = {
  assetId: number
  assetUuid: string
  title: string
  sourceModule: string
  localStorageDriver: string | null
  localStoragePath: string | null
  externalRelativePath: string | null
  sourceUri: string | null
  previewUri: string | null
  downloadUri: string | null
}

export type UserAssetExternalDirectoryAssetHealthSummary = {
  trackedAssetCount: number
  inaccessibleAssetCount: number
  missingLocalCopyCount: number
  inaccessibleAssets: UserAssetExternalDirectoryAssetHealthItem[]
  missingLocalCopyAssets: UserAssetExternalDirectoryAssetHealthItem[]
}

function buildMigrationProgressSummary(status: LegacyLocalAssetMigrationStatus): string {
  return `已迁移 ${status.migrated} 项，跳过 ${status.skipped} 项，失败 ${status.failed} 项。`
}

export function buildUserAssetLocalDiagnosticsNotice(
  status: LegacyLocalAssetMigrationStatus | null,
): UserAssetListStatusNotice | null {
  if (!status || status.phase === 'completed') {
    return null
  }

  if (status.phase === 'running') {
    return {
      severity: 'info',
      text: '本地副本迁移正在后台执行，当前浏览器中的旧版缓存会逐步迁移到更稳定的本地存储。',
    }
  }

  if (status.phase === 'failed') {
    return {
      severity: 'warning',
      text: `本地副本迁移失败：${status.error || '未知错误'}。后续启动时会继续重试。`,
    }
  }

  return {
    severity: 'warning',
    text: `检测到本地副本迁移未完全完成，${buildMigrationProgressSummary(status)}后续启动时会继续重试。`,
  }
}

function buildDirectoryLabel(directoryName: string | null | undefined): string {
  const normalized = String(directoryName || '').trim()
  return normalized || '未命名目录'
}

export function buildUserAssetExternalDirectoryNotice(
  status: LocalAssetExternalDirectoryStatus | null,
): UserAssetListStatusNotice | null {
  if (!status?.supported || !status.configured) {
    return null
  }

  const directoryLabel = buildDirectoryLabel(status.directoryName)
  if (status.permission === 'granted') {
    return null
  }

  if (status.permission === 'prompt') {
    return {
      severity: 'warning',
      text: `已记录用户目录“${directoryLabel}”，但浏览器需要重新授权后才能继续写入。建议先尝试“恢复访问”，失败后再重新选择目录。`,
    }
  }

  if (status.permission === 'denied') {
    return {
      severity: 'warning',
      text: `已记录用户目录“${directoryLabel}”，但当前权限已失效。建议先尝试“恢复访问”，若仍失败再重新选择目录。`,
    }
  }

  return {
    severity: 'info',
    text: `已记录用户目录“${directoryLabel}”，但当前无法确认权限状态。建议刷新状态，必要时重新选择目录。`,
  }
}

export function buildUserAssetLocalDiagnosticsNotices(input: {
  migrationStatus: LegacyLocalAssetMigrationStatus | null
  externalDirectoryStatus: LocalAssetExternalDirectoryStatus | null
  externalDirectoryAssetHealthSummary?: UserAssetExternalDirectoryAssetHealthSummary | null
}): UserAssetListStatusNotice[] {
  return [
    buildUserAssetLocalDiagnosticsNotice(input.migrationStatus),
    buildUserAssetExternalDirectoryNotice(input.externalDirectoryStatus),
    buildUserAssetExternalDirectoryAssetHealthNotice(input.externalDirectoryAssetHealthSummary ?? null),
  ].filter((notice): notice is UserAssetListStatusNotice => notice !== null)
}

export function buildUserAssetExternalDirectoryAssetHealthNotice(
  summary: UserAssetExternalDirectoryAssetHealthSummary | null,
): UserAssetListStatusNotice | null {
  if (!summary || summary.trackedAssetCount <= 0) {
    return null
  }

  if (summary.inaccessibleAssetCount > 0) {
    return {
      severity: 'warning',
      text: `当前列表中有 ${summary.inaccessibleAssetCount} 项资产登记为用户目录副本，但目录暂不可用，暂时无法校验这些本地副本。恢复目录访问后可重新验证。`,
    }
  }

  if (summary.missingLocalCopyCount > 0) {
    return {
      severity: 'warning',
      text: `检测到 ${summary.missingLocalCopyCount} 项登记为用户目录副本的资产当前未读取到本地副本。若这是你主动清理后的预期状态可忽略；若希望恢复长期持有，请从来源页重新收录。`,
    }
  }

  return null
}
