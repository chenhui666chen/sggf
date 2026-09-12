import type { TFunction } from 'i18next'
import type { AppLanguage } from '@/i18n'
import { formatDateTimeWithSeconds } from '@/i18n/format'
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

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

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

function buildDirectoryLabel(directoryName: string | null | undefined, t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  const normalized = String(directoryName || '').trim()
  return normalized || translate('userAsset.localStorage.unnamedDirectory')
}

export function buildUserAssetLocalStorageSupportLabel(
  status: LocalAssetExternalDirectoryStatus | null,
  loading: boolean,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (loading) {
    return translate('userAsset.localStorage.checking')
  }

  return status?.supported
    ? translate('userAsset.localStorage.supportSupported')
    : translate('userAsset.localStorage.supportUnsupported')
}

export function buildUserAssetRecordedDirectoryLabel(
  status: LocalAssetExternalDirectoryStatus | null,
  loading: boolean,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (loading) {
    return translate('userAsset.localStorage.reading')
  }

  if (!status?.configured) {
    return translate('userAsset.localStorage.unconfigured')
  }

  return buildDirectoryLabel(status.directoryName, t)
}

export function buildUserAssetLocalStoragePanelCopy(
  status: LocalAssetExternalDirectoryStatus | null,
  loading: boolean,
  t?: TFunction,
): LocalStoragePanelCopy {
  const translate = t ?? DEFAULT_TRANSLATE
  if (loading) {
    return {
      severity: 'info',
      summary: translate('userAsset.localStorage.checkingSummary'),
      pickLabel: translate('userAsset.localStorage.checkingPick'),
      showRecoverAccess: false,
      clearEnabled: false,
      statusLabel: translate('userAsset.localStorage.checking'),
      statusTone: 'info',
      guidance: null,
      backupHint: null,
    }
  }

  if (!status?.supported) {
    return {
      severity: 'warning',
      summary: translate('userAsset.localStorage.unsupportedSummary'),
      pickLabel: translate('userAsset.localStorage.unsupportedPick'),
      showRecoverAccess: false,
      clearEnabled: Boolean(status?.configured),
      statusLabel: translate('userAsset.localStorage.unsupportedStatus'),
      statusTone: 'default',
      guidance: translate('userAsset.localStorage.unsupportedGuidance'),
      backupHint: null,
    }
  }

  if (!status.configured) {
    return {
      severity: 'info',
      summary: translate('userAsset.localStorage.unconfiguredSummary'),
      pickLabel: translate('userAsset.localStorage.pickDirectory'),
      showRecoverAccess: false,
      clearEnabled: false,
      statusLabel: translate('userAsset.localStorage.unconfigured'),
      statusTone: 'info',
      guidance: translate('userAsset.localStorage.unconfiguredGuidance'),
      backupHint: null,
    }
  }

  const directoryLabel = buildDirectoryLabel(status.directoryName, t)
  if (status.permission === 'granted') {
    return {
      severity: 'success',
      summary: translate('userAsset.localStorage.grantedSummary', { directory: directoryLabel }),
      pickLabel: translate('userAsset.localStorage.changeDirectory'),
      showRecoverAccess: false,
      clearEnabled: true,
      statusLabel: translate('userAsset.localStorage.grantedStatus'),
      statusTone: 'success',
      guidance: null,
      backupHint: translate('userAsset.localStorage.grantedBackupHint'),
    }
  }

  if (status.permission === 'prompt') {
    return {
      severity: 'warning',
      summary: translate('userAsset.localStorage.promptSummary', { directory: directoryLabel }),
      pickLabel: translate('userAsset.localStorage.repickDirectory'),
      showRecoverAccess: true,
      clearEnabled: true,
      statusLabel: translate('userAsset.localStorage.promptStatus'),
      statusTone: 'warning',
      guidance: translate('userAsset.localStorage.promptGuidance'),
      backupHint: translate('userAsset.localStorage.promptBackupHint'),
    }
  }

  if (status.permission === 'denied') {
    return {
      severity: 'warning',
      summary: translate('userAsset.localStorage.deniedSummary', { directory: directoryLabel }),
      pickLabel: translate('userAsset.localStorage.repickDirectory'),
      showRecoverAccess: true,
      clearEnabled: true,
      statusLabel: translate('userAsset.localStorage.deniedStatus'),
      statusTone: 'warning',
      guidance: translate('userAsset.localStorage.deniedGuidance'),
      backupHint: translate('userAsset.localStorage.deniedBackupHint'),
    }
  }

  return {
    severity: 'info',
    summary: translate('userAsset.localStorage.unknownSummary', { directory: directoryLabel }),
    pickLabel: translate('userAsset.localStorage.repickDirectory'),
    showRecoverAccess: true,
    clearEnabled: true,
    statusLabel: translate('userAsset.localStorage.unknownStatus'),
    statusTone: 'info',
    guidance: translate('userAsset.localStorage.unknownGuidance'),
    backupHint: translate('userAsset.localStorage.unknownBackupHint'),
  }
}

function formatBackupGuideTimestamp(value: Date, locale?: AppLanguage): string {
  return formatDateTimeWithSeconds(value, { locale })
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
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (issueType === 'directory_inaccessible') {
    return translate('userAsset.localStorage.issueTypeDirectory')
  }

  return translate('userAsset.localStorage.issueTypeMissing')
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
  /** 时间文案的显示语言，由调用方从 useAppLanguage 取。 */
  locale?: AppLanguage
  t?: TFunction
}): UserAssetLocalStorageActionReport {
  const translate = input.t ?? DEFAULT_TRANSLATE
  const completedAt = input.completedAt ?? new Date()
  const mode = input.mode ?? 'restore'
  const scopeLabel = input.scope === 'current_page'
    ? translate('userAsset.localStorage.scopeCurrentPage')
    : translate('userAsset.localStorage.scopeFiltered')
  const isPreview = mode === 'preview'

  let summary = ''
  if (input.scannedAssetCount <= 0) {
    summary = translate('userAsset.localStorage.reportNoAssets', { scope: scopeLabel })
  } else if (input.trackedAssetCount <= 0) {
    summary = translate('userAsset.localStorage.reportNoTracked', { scope: scopeLabel, count: input.scannedAssetCount })
  } else if (input.missingLocalCopyCount <= 0 && input.inaccessibleAssetCount > 0) {
    summary = translate('userAsset.localStorage.reportInaccessible', { scope: scopeLabel, count: input.scannedAssetCount, inaccessible: input.inaccessibleAssetCount })
  } else if (input.missingLocalCopyCount <= 0) {
    summary = translate('userAsset.localStorage.reportUpToDate', { scope: scopeLabel, count: input.scannedAssetCount, tracked: input.trackedAssetCount })
  } else if (isPreview) {
    summary = translate('userAsset.localStorage.reportPreviewMissing', { scope: scopeLabel, count: input.scannedAssetCount, tracked: input.trackedAssetCount, missing: input.missingLocalCopyCount })
  } else {
    summary = translate('userAsset.localStorage.reportRestoredMissing', { scope: scopeLabel, count: input.scannedAssetCount, tracked: input.trackedAssetCount, missing: input.missingLocalCopyCount })
  }

  return {
    mode,
    scope: input.scope,
    severity: buildUserAssetLocalStorageActionReportSeverity(input),
    title: isPreview
      ? translate('userAsset.localStorage.reportPreviewTitle', { scope: scopeLabel })
      : translate('userAsset.localStorage.reportRestoreTitle', { scope: scopeLabel }),
    summary,
    completedAtLabel: formatBackupGuideTimestamp(completedAt, input.locale),
    metrics: [
      {
        key: 'scanned-assets',
        label: translate('userAsset.localStorage.metricScanned'),
        value: Math.max(0, input.scannedAssetCount),
      },
      {
        key: 'tracked-assets',
        label: translate('userAsset.localStorage.metricTracked'),
        value: Math.max(0, input.trackedAssetCount),
      },
      {
        key: 'missing-assets',
        label: translate('userAsset.localStorage.metricMissing'),
        value: Math.max(0, input.missingLocalCopyCount),
      },
      ...(input.restoredCount > 0
        ? [{
            key: 'restored-assets',
            label: translate('userAsset.localStorage.metricRestored'),
            value: Math.max(0, input.restoredCount),
          }]
        : []),
      ...(input.existingCount > 0
        ? [{
            key: 'existing-assets',
            label: translate('userAsset.localStorage.metricExisting'),
            value: Math.max(0, input.existingCount),
          }]
        : []),
      ...(input.inaccessibleAssetCount > 0
        ? [{
            key: 'inaccessible-assets',
            label: translate('userAsset.localStorage.metricInaccessible'),
            value: Math.max(0, input.inaccessibleAssetCount),
          }]
        : []),
      ...(input.blockedCount > 0
        ? [{
            key: 'blocked-assets',
            label: translate('userAsset.localStorage.metricBlocked'),
            value: Math.max(0, input.blockedCount),
          }]
        : []),
      ...(input.failedCount > 0
        ? [{
            key: 'failed-assets',
            label: translate('userAsset.localStorage.metricFailed'),
            value: Math.max(0, input.failedCount),
          }]
        : []),
    ],
    issueItems: buildUserAssetLocalStorageActionIssueItems(
      input.healthSummary,
      input.issueAssets,
      input.projectTitleMap,
      input.t,
    ),
  }
}

function buildUserAssetLocalStorageRebuildActionHint(
  issueType: UserAssetLocalStorageActionIssueType,
  t?: TFunction,
): string {
  const translate = t ?? DEFAULT_TRANSLATE
  if (issueType === 'directory_inaccessible') {
    return translate('userAsset.localStorage.hintDirectoryInaccessible')
  }

  return translate('userAsset.localStorage.hintMissingLocalCopy')
}

function buildUserAssetLocalStorageActionIssueItem(
  asset: UserAssetExternalDirectoryAssetHealthItem,
  issueType: UserAssetLocalStorageActionIssueType,
  restorableAsset: UserAssetRecord | null,
  projectTitleMap?: UserAssetProjectTitleMap,
  t?: TFunction,
): UserAssetLocalStorageActionIssueItem {
  const sourceInfo = restorableAsset ? getUserAssetSourceInfo(restorableAsset, projectTitleMap, t) : null

  return {
    key: `${issueType}:${asset.assetId}:${asset.assetUuid}`,
    assetId: asset.assetId,
    issueType,
    title: asset.title,
    assetUuid: asset.assetUuid,
    sourceModule: asset.sourceModule,
    localStoragePath: asset.localStoragePath,
    externalRelativePath: asset.externalRelativePath,
    actionHint: buildUserAssetLocalStorageRebuildActionHint(issueType, t),
    restorableAsset,
    sourceActionPath: sourceInfo?.backPath || null,
    sourceActionLabel: sourceInfo?.backLabel || null,
  }
}

function buildUserAssetLocalStorageActionIssueItems(
  summary: UserAssetExternalDirectoryAssetHealthSummary | null | undefined,
  issueAssets: UserAssetRecord[] | null | undefined,
  projectTitleMap?: UserAssetProjectTitleMap,
  t?: TFunction,
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
        t,
      )),
    ...(summary.inaccessibleAssets || []).map((asset) =>
      buildUserAssetLocalStorageActionIssueItem(
        asset,
        'directory_inaccessible',
        issueAssetMap.get(asset.assetId) || null,
        projectTitleMap,
        t,
      )),
  ]
}

function buildUserAssetLocalStorageRebuildListItem(
  asset: UserAssetExternalDirectoryAssetHealthItem,
  issueType: UserAssetLocalStorageActionIssueType,
  t?: TFunction,
) {
  return {
    issue_type: issueType,
    action_hint: buildUserAssetLocalStorageRebuildActionHint(issueType, t),
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
  /** 导出文档里时间文案的显示语言。 */
  locale?: AppLanguage
  t?: TFunction
}): string {
  const {
    status,
    loading,
    generatedAt = new Date(),
    locale,
  } = options
  const translate = options.t ?? DEFAULT_TRANSLATE

  const panelCopy = buildUserAssetLocalStoragePanelCopy(status, loading, options.t)
  const supportLabel = buildUserAssetLocalStorageSupportLabel(status, loading, options.t)
  const recordedDirectoryLabel = buildUserAssetRecordedDirectoryLabel(status, loading, options.t)

  const lines = [
    translate('userAsset.localStorage.guideTitle'),
    '',
    translate('userAsset.localStorage.guideGeneratedAt', { time: formatBackupGuideTimestamp(generatedAt, locale) }),
    translate('userAsset.localStorage.guideStatus', { status: panelCopy.statusLabel }),
    translate('userAsset.localStorage.guideBrowserSupport', { support: supportLabel }),
    translate('userAsset.localStorage.guideRecordedDirectory', { directory: recordedDirectoryLabel }),
    '',
    translate('userAsset.localStorage.guideCurrentSummaryTitle'),
    panelCopy.summary,
    '',
    translate('userAsset.localStorage.guidePriorityEntryTitle'),
    translate('userAsset.localStorage.guidePriorityEntryAssetStudio'),
    translate('userAsset.localStorage.guidePriorityEntryAudiobook'),
    '',
    translate('userAsset.localStorage.guideBrowserStorageTitle'),
    translate('userAsset.localStorage.guideBrowserStorageLine'),
    '',
    translate('userAsset.localStorage.guideBackupAdviceTitle'),
  ]

  if (panelCopy.guidance) {
    lines.push(`- ${panelCopy.guidance}`)
  }
  if (panelCopy.backupHint) {
    lines.push(`- ${panelCopy.backupHint}`)
  }
  if (!panelCopy.guidance && !panelCopy.backupHint) {
    lines.push(translate('userAsset.localStorage.guideNoBackupAdvice'))
  }

  lines.push(
    '',
    translate('userAsset.localStorage.guideBoundaryTitle'),
    translate('userAsset.localStorage.guideBoundarySystemFiles'),
    translate('userAsset.localStorage.guideBoundaryBrowserStorage'),
    translate('userAsset.localStorage.guideBoundaryPermission'),
  )

  return lines.join('\n')
}

export function buildUserAssetLocalStorageInventoryExport(options: {
  status: LocalAssetExternalDirectoryStatus | null
  loading: boolean
  inventory: LocalAssetVaultInventoryRecord[]
  generatedAt?: Date
  t?: TFunction
}): string {
  const {
    status,
    loading,
    inventory,
    generatedAt = new Date(),
  } = options

  const panelCopy = buildUserAssetLocalStoragePanelCopy(status, loading, options.t)
  const supportLabel = buildUserAssetLocalStorageSupportLabel(status, loading, options.t)
  const recordedDirectoryLabel = buildUserAssetRecordedDirectoryLabel(status, loading, options.t)
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
  t?: TFunction
}): string {
  const {
    status,
    loading,
    healthSummary,
    generatedAt = new Date(),
  } = options

  const panelCopy = buildUserAssetLocalStoragePanelCopy(status, loading, options.t)
  const supportLabel = buildUserAssetLocalStorageSupportLabel(status, loading, options.t)
  const recordedDirectoryLabel = buildUserAssetRecordedDirectoryLabel(status, loading, options.t)
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
      ...inaccessibleAssets.map((asset) => buildUserAssetLocalStorageRebuildListItem(asset, 'directory_inaccessible', options.t)),
      ...missingLocalCopyAssets.map((asset) => buildUserAssetLocalStorageRebuildListItem(asset, 'missing_local_copy', options.t)),
    ],
  }, null, 2)
}
