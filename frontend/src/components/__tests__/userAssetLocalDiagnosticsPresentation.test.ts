import { beforeAll, describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'

import { bootstrapI18n } from '@/i18n'

import type { LegacyLocalAssetMigrationStatus } from '@/utils/localAssetMigration'
import type { LocalAssetExternalDirectoryStatus } from '@/utils/localAssetExternalDirectory'

import {
  buildUserAssetExternalDirectoryAssetHealthNotice,
  buildUserAssetExternalDirectoryNotice,
  buildUserAssetLocalDiagnosticsNotice,
  buildUserAssetLocalDiagnosticsNotices,
} from '../user-assets/userAssetLocalDiagnosticsPresentation'

function createStatus(
  overrides: Partial<LegacyLocalAssetMigrationStatus> = {},
): LegacyLocalAssetMigrationStatus {
  return {
    version: 2,
    phase: 'partial',
    startedAt: '2026-04-24T10:00:00.000Z',
    finishedAt: '2026-04-24T10:00:01.000Z',
    error: null,
    scanned: 3,
    migrated: 2,
    skipped: 1,
    failed: 0,
    ...overrides,
  }
}

function createExternalDirectoryStatus(
  overrides: Partial<LocalAssetExternalDirectoryStatus> = {},
): LocalAssetExternalDirectoryStatus {
  return {
    supported: true,
    configured: true,
    directoryName: 'Novel Assets',
    permission: 'denied',
    ...overrides,
  }
}

let t: TFunction

beforeAll(async () => {
  const instance = await bootstrapI18n('zh-CN')
  t = instance.t.bind(instance)
})

describe('userAssetLocalDiagnosticsPresentation', () => {
  it('returns null for empty or completed status', () => {
    expect(buildUserAssetLocalDiagnosticsNotice(null, t)).toBeNull()
    expect(buildUserAssetLocalDiagnosticsNotice(createStatus({ phase: 'completed' }), t)).toBeNull()
  })

  it('builds an info notice for running migration', () => {
    expect(buildUserAssetLocalDiagnosticsNotice(createStatus({ phase: 'running' }), t)).toEqual({
      severity: 'info',
      text: '本地副本迁移正在后台执行，当前浏览器中的旧版缓存会逐步迁移到更稳定的本地存储。',
    })
  })

  it('builds a warning notice for partial migration', () => {
    expect(buildUserAssetLocalDiagnosticsNotice(createStatus(), t)).toEqual({
      severity: 'warning',
      text: '检测到本地副本迁移未完全完成，已迁移 2 项，跳过 1 项，失败 0 项。后续启动时会继续重试。',
    })
  })

  it('builds a warning notice for failed migration', () => {
    expect(buildUserAssetLocalDiagnosticsNotice(createStatus({
      phase: 'failed',
      error: 'boom',
    }), t)).toEqual({
      severity: 'warning',
      text: '本地副本迁移失败：boom。后续启动时会继续重试。',
    })
  })

  it('builds a warning notice for denied external directory access', () => {
    expect(buildUserAssetExternalDirectoryNotice(createExternalDirectoryStatus(), t)).toEqual({
      severity: 'warning',
      text: '已记录用户目录“Novel Assets”，但当前权限已失效。建议先尝试“恢复访问”，若仍失败再重新选择目录。',
    })
  })

  it('skips external directory notice when directory is healthy', () => {
    expect(buildUserAssetExternalDirectoryNotice(createExternalDirectoryStatus({
      permission: 'granted',
    }), t)).toBeNull()
  })

  it('combines migration and external directory notices', () => {
    expect(buildUserAssetLocalDiagnosticsNotices({
      migrationStatus: createStatus(),
      externalDirectoryStatus: createExternalDirectoryStatus(),
      externalDirectoryAssetHealthSummary: null,
      t,
    })).toEqual([
      {
        severity: 'warning',
        text: '检测到本地副本迁移未完全完成，已迁移 2 项，跳过 1 项，失败 0 项。后续启动时会继续重试。',
      },
      {
        severity: 'warning',
        text: '已记录用户目录“Novel Assets”，但当前权限已失效。建议先尝试“恢复访问”，若仍失败再重新选择目录。',
      },
    ])
  })

  it('builds a warning notice when external directory assets cannot be verified', () => {
    expect(buildUserAssetExternalDirectoryAssetHealthNotice({
      trackedAssetCount: 3,
      inaccessibleAssetCount: 3,
      missingLocalCopyCount: 0,
      inaccessibleAssets: [],
      missingLocalCopyAssets: [],
    }, t)).toEqual({
      severity: 'warning',
      text: '当前列表中有 3 项资产登记为用户目录副本，但目录暂不可用，暂时无法校验这些本地副本。恢复目录访问后可重新验证。',
    })
  })

  it('builds a warning notice when external directory copies are missing', () => {
    expect(buildUserAssetExternalDirectoryAssetHealthNotice({
      trackedAssetCount: 4,
      inaccessibleAssetCount: 0,
      missingLocalCopyCount: 2,
      inaccessibleAssets: [],
      missingLocalCopyAssets: [],
    }, t)).toEqual({
      severity: 'warning',
      text: '检测到 2 项登记为用户目录副本的资产当前未读取到本地副本。若这是你主动清理后的预期状态可忽略；若希望恢复长期持有，请从来源页重新收录。',
    })
  })

  it('combines directory health notice into diagnostics list', () => {
    expect(buildUserAssetLocalDiagnosticsNotices({
      migrationStatus: null,
      externalDirectoryStatus: createExternalDirectoryStatus({
        permission: 'granted',
      }),
      externalDirectoryAssetHealthSummary: {
        trackedAssetCount: 2,
        inaccessibleAssetCount: 0,
        missingLocalCopyCount: 1,
        inaccessibleAssets: [],
        missingLocalCopyAssets: [],
      },
      t,
    })).toEqual([
      {
        severity: 'warning',
        text: '检测到 1 项登记为用户目录副本的资产当前未读取到本地副本。若这是你主动清理后的预期状态可忽略；若希望恢复长期持有，请从来源页重新收录。',
      },
    ])
  })
})
