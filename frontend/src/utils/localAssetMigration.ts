import { migrateLegacyLocalAssetsToOpfs, type MigrateLegacyLocalAssetsResult } from './localAssetVault'

export type LegacyLocalAssetMigrationPhase = 'running' | 'completed' | 'partial' | 'failed'

export interface LegacyLocalAssetMigrationStatus extends MigrateLegacyLocalAssetsResult {
  version: 2
  phase: LegacyLocalAssetMigrationPhase
  startedAt: string
  finishedAt: string | null
  error: string | null
}

export const LEGACY_LOCAL_ASSET_MIGRATION_STATUS_STORAGE_KEY = 'legacyLocalAssetMigration:v2:status'
export const LEGACY_LOCAL_ASSET_MIGRATION_STATUS_UPDATED_EVENT = 'legacy-local-asset-migration-status-updated'

function buildBaseMigrationStatus(startedAt: string): LegacyLocalAssetMigrationStatus {
  return {
    version: 2,
    phase: 'running',
    startedAt,
    finishedAt: null,
    error: null,
    scanned: 0,
    migrated: 0,
    skipped: 0,
    failed: 0,
  }
}

function getLocalStorageSafely(): Storage | null {
  try {
    if (typeof globalThis === 'undefined') {
      return null
    }
    return globalThis.localStorage ?? null
  } catch {
    return null
  }
}

function isNonNegativeInteger(value: unknown): value is number {
  return Number.isInteger(value) && Number(value) >= 0
}

function toLegacyLocalAssetMigrationStatus(value: unknown): LegacyLocalAssetMigrationStatus | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null
  }

  const candidate = value as Record<string, unknown>
  const phase = candidate.phase
  const version = candidate.version
  const startedAt = candidate.startedAt
  const finishedAt = candidate.finishedAt
  const error = candidate.error

  if (version !== 2) {
    return null
  }
  if (phase !== 'running' && phase !== 'completed' && phase !== 'partial' && phase !== 'failed') {
    return null
  }
  if (typeof startedAt !== 'string' || !startedAt.trim()) {
    return null
  }
  if (finishedAt !== null && typeof finishedAt !== 'string') {
    return null
  }
  if (error !== null && typeof error !== 'string') {
    return null
  }
  if (
    !isNonNegativeInteger(candidate.scanned)
    || !isNonNegativeInteger(candidate.migrated)
    || !isNonNegativeInteger(candidate.skipped)
    || !isNonNegativeInteger(candidate.failed)
  ) {
    return null
  }

  return {
    version,
    phase,
    startedAt,
    finishedAt,
    error,
    scanned: candidate.scanned,
    migrated: candidate.migrated,
    skipped: candidate.skipped,
    failed: candidate.failed,
  }
}

function notifyLegacyLocalAssetMigrationStatusUpdated(): void {
  if (typeof window === 'undefined' || typeof window.dispatchEvent !== 'function') {
    return
  }

  window.dispatchEvent(new Event(LEGACY_LOCAL_ASSET_MIGRATION_STATUS_UPDATED_EVENT))
}

function persistLegacyLocalAssetMigrationStatus(status: LegacyLocalAssetMigrationStatus): void {
  const storage = getLocalStorageSafely()
  if (!storage) {
    return
  }

  try {
    storage.setItem(LEGACY_LOCAL_ASSET_MIGRATION_STATUS_STORAGE_KEY, JSON.stringify(status))
    notifyLegacyLocalAssetMigrationStatusUpdated()
  } catch {
    // ignore
  }
}

function toErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message
  }
  return 'legacy 本地资产迁移失败'
}

function resolveLegacyLocalAssetMigrationPhase(
  result: MigrateLegacyLocalAssetsResult,
): LegacyLocalAssetMigrationPhase {
  if (result.failed === 0 && result.skipped === 0) {
    return 'completed'
  }
  return 'partial'
}

function buildLegacyLocalAssetMigrationIssueSummary(
  result: MigrateLegacyLocalAssetsResult,
): string | null {
  const parts: string[] = []

  if (result.failed > 0) {
    parts.push(`${result.failed} 个迁移失败`)
  }
  if (result.skipped > 0) {
    parts.push(`${result.skipped} 个未迁移完成`)
  }

  return parts.length > 0 ? `仍有 legacy 资产未完全迁移：${parts.join('，')}` : null
}

export function readLegacyLocalAssetMigrationStatus(): LegacyLocalAssetMigrationStatus | null {
  const storage = getLocalStorageSafely()
  if (!storage) {
    return null
  }

  try {
    const raw = storage.getItem(LEGACY_LOCAL_ASSET_MIGRATION_STATUS_STORAGE_KEY)
    if (!raw) {
      return null
    }
    return toLegacyLocalAssetMigrationStatus(JSON.parse(raw))
  } catch {
    return null
  }
}

export function shouldRunLegacyLocalAssetMigration(): boolean {
  const status = readLegacyLocalAssetMigrationStatus()
  return status?.phase !== 'completed'
}

export async function runLegacyLocalAssetMigrationWithStatus(): Promise<LegacyLocalAssetMigrationStatus> {
  const startedAt = new Date().toISOString()
  const runningStatus = buildBaseMigrationStatus(startedAt)
  persistLegacyLocalAssetMigrationStatus(runningStatus)

  try {
    const result = await migrateLegacyLocalAssetsToOpfs()
    const finishedAt = new Date().toISOString()
    const phase = resolveLegacyLocalAssetMigrationPhase(result)
    const status: LegacyLocalAssetMigrationStatus = {
      ...runningStatus,
      ...result,
      phase,
      finishedAt,
      error: buildLegacyLocalAssetMigrationIssueSummary(result),
    }
    persistLegacyLocalAssetMigrationStatus(status)
    return status
  } catch (error) {
    const status: LegacyLocalAssetMigrationStatus = {
      ...runningStatus,
      phase: 'failed',
      finishedAt: new Date().toISOString(),
      error: toErrorMessage(error),
    }
    persistLegacyLocalAssetMigrationStatus(status)
    return status
  }
}
