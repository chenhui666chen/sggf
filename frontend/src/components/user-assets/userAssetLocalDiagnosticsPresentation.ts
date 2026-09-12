import type { TFunction } from 'i18next'
import type { LegacyLocalAssetMigrationStatus } from '@/utils/localAssetMigration'
import type { LocalAssetExternalDirectoryStatus } from '@/utils/localAssetExternalDirectory'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

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

function buildMigrationProgressSummary(status: LegacyLocalAssetMigrationStatus, t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  return translate('userAsset.diagnostics.migrationProgress', {
    migrated: status.migrated,
    skipped: status.skipped,
    failed: status.failed,
  })
}

export function buildUserAssetLocalDiagnosticsNotice(
  status: LegacyLocalAssetMigrationStatus | null,
  t?: TFunction,
): UserAssetListStatusNotice | null {
  const translate = t ?? DEFAULT_TRANSLATE
  if (!status || status.phase === 'completed') {
    return null
  }

  if (status.phase === 'running') {
    return {
      severity: 'info',
      text: translate('userAsset.diagnostics.migrationRunning'),
    }
  }

  if (status.phase === 'failed') {
    return {
      severity: 'warning',
      text: translate('userAsset.diagnostics.migrationFailed', {
        error: status.error || translate('userAsset.common.unknownError'),
      }),
    }
  }

  return {
    severity: 'warning',
    text: translate('userAsset.diagnostics.migrationIncomplete', {
      progress: buildMigrationProgressSummary(status, t),
    }),
  }
}

function buildDirectoryLabel(directoryName: string | null | undefined, t?: TFunction): string {
  const translate = t ?? DEFAULT_TRANSLATE
  const normalized = String(directoryName || '').trim()
  return normalized || translate('userAsset.common.unnamedDirectory')
}

export function buildUserAssetExternalDirectoryNotice(
  status: LocalAssetExternalDirectoryStatus | null,
  t?: TFunction,
): UserAssetListStatusNotice | null {
  const translate = t ?? DEFAULT_TRANSLATE
  if (!status?.supported || !status.configured) {
    return null
  }

  const directoryLabel = buildDirectoryLabel(status.directoryName, t)
  if (status.permission === 'granted') {
    return null
  }

  if (status.permission === 'prompt') {
    return {
      severity: 'warning',
      text: translate('userAsset.diagnostics.directoryPrompt', { directory: directoryLabel }),
    }
  }

  if (status.permission === 'denied') {
    return {
      severity: 'warning',
      text: translate('userAsset.diagnostics.directoryDenied', { directory: directoryLabel }),
    }
  }

  return {
    severity: 'info',
    text: translate('userAsset.diagnostics.directoryUnknown', { directory: directoryLabel }),
  }
}

export function buildUserAssetLocalDiagnosticsNotices(input: {
  migrationStatus: LegacyLocalAssetMigrationStatus | null
  externalDirectoryStatus: LocalAssetExternalDirectoryStatus | null
  externalDirectoryAssetHealthSummary?: UserAssetExternalDirectoryAssetHealthSummary | null
  t?: TFunction
}): UserAssetListStatusNotice[] {
  return [
    buildUserAssetLocalDiagnosticsNotice(input.migrationStatus, input.t),
    buildUserAssetExternalDirectoryNotice(input.externalDirectoryStatus, input.t),
    buildUserAssetExternalDirectoryAssetHealthNotice(input.externalDirectoryAssetHealthSummary ?? null, input.t),
  ].filter((notice): notice is UserAssetListStatusNotice => notice !== null)
}

export function buildUserAssetExternalDirectoryAssetHealthNotice(
  summary: UserAssetExternalDirectoryAssetHealthSummary | null,
  t?: TFunction,
): UserAssetListStatusNotice | null {
  const translate = t ?? DEFAULT_TRANSLATE
  if (!summary || summary.trackedAssetCount <= 0) {
    return null
  }

  if (summary.inaccessibleAssetCount > 0) {
    return {
      severity: 'warning',
      text: translate('userAsset.diagnostics.healthInaccessible', { count: summary.inaccessibleAssetCount }),
    }
  }

  if (summary.missingLocalCopyCount > 0) {
    return {
      severity: 'warning',
      text: translate('userAsset.diagnostics.healthMissingCopy', { count: summary.missingLocalCopyCount }),
    }
  }

  return null
}
