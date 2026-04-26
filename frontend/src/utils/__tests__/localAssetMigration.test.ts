import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  LEGACY_LOCAL_ASSET_MIGRATION_STATUS_STORAGE_KEY,
  LEGACY_LOCAL_ASSET_MIGRATION_STATUS_UPDATED_EVENT,
  readLegacyLocalAssetMigrationStatus,
  runLegacyLocalAssetMigrationWithStatus,
  shouldRunLegacyLocalAssetMigration,
} from '../localAssetMigration'
import { migrateLegacyLocalAssetsToOpfs } from '../localAssetVault'

vi.mock('../localAssetVault', () => ({
  migrateLegacyLocalAssetsToOpfs: vi.fn(),
}))

function createMemoryStorage(): Storage {
  const store = new Map<string, string>()

  return {
    get length() {
      return store.size
    },
    clear() {
      store.clear()
    },
    getItem(key) {
      return store.has(key) ? store.get(key)! : null
    },
    key(index) {
      return Array.from(store.keys())[index] ?? null
    },
    removeItem(key) {
      store.delete(key)
    },
    setItem(key, value) {
      store.set(key, String(value))
    },
  }
}

describe('localAssetMigration', () => {
  const originalLocalStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  const originalWindowDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'window')

  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      value: createMemoryStorage(),
    })

    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: new EventTarget(),
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    if (originalLocalStorageDescriptor) {
      Object.defineProperty(globalThis, 'localStorage', originalLocalStorageDescriptor)
    } else {
      // @ts-expect-error allow cleanup in test env
      delete globalThis.localStorage
    }

    if (originalWindowDescriptor) {
      Object.defineProperty(globalThis, 'window', originalWindowDescriptor)
    } else {
      // @ts-expect-error allow cleanup in test env
      delete globalThis.window
    }
  })

  it('读取非法状态快照时返回 null', () => {
    globalThis.localStorage.setItem(LEGACY_LOCAL_ASSET_MIGRATION_STATUS_STORAGE_KEY, '{bad json')

    expect(readLegacyLocalAssetMigrationStatus()).toBeNull()
    expect(shouldRunLegacyLocalAssetMigration()).toBe(true)
  })

  it('完成且无失败项的迁移快照会阻止重复调度', () => {
    globalThis.localStorage.setItem(
      LEGACY_LOCAL_ASSET_MIGRATION_STATUS_STORAGE_KEY,
      JSON.stringify({
        version: 2,
        phase: 'completed',
        startedAt: '2026-04-24T10:00:00.000Z',
        finishedAt: '2026-04-24T10:00:01.000Z',
        error: null,
        scanned: 4,
        migrated: 4,
        skipped: 0,
        failed: 0,
      }),
    )

    expect(shouldRunLegacyLocalAssetMigration()).toBe(false)
  })

  it('有 skipped 项时会持久化 partial 状态并继续允许重试', async () => {
    const migrateMock = vi.mocked(migrateLegacyLocalAssetsToOpfs)
    const eventListener = vi.fn()
    window.addEventListener(LEGACY_LOCAL_ASSET_MIGRATION_STATUS_UPDATED_EVENT, eventListener)

    migrateMock.mockResolvedValue({
      scanned: 3,
      migrated: 2,
      skipped: 1,
      failed: 0,
    })

    const status = await runLegacyLocalAssetMigrationWithStatus()

    expect(status.phase).toBe('partial')
    expect(status.error).toBe('仍有 legacy 资产未完全迁移：1 个未迁移完成')
    expect(status.scanned).toBe(3)
    expect(status.migrated).toBe(2)
    expect(status.skipped).toBe(1)
    expect(status.failed).toBe(0)
    expect(eventListener).toHaveBeenCalledTimes(2)
    expect(shouldRunLegacyLocalAssetMigration()).toBe(true)
    expect(readLegacyLocalAssetMigrationStatus()).toEqual(status)

    window.removeEventListener(LEGACY_LOCAL_ASSET_MIGRATION_STATUS_UPDATED_EVENT, eventListener)
  })

  it('全部迁移完成时会持久化 completed 状态', async () => {
    const migrateMock = vi.mocked(migrateLegacyLocalAssetsToOpfs)
    migrateMock.mockResolvedValue({
      scanned: 2,
      migrated: 2,
      skipped: 0,
      failed: 0,
    })

    const status = await runLegacyLocalAssetMigrationWithStatus()

    expect(status.phase).toBe('completed')
    expect(status.error).toBeNull()
    expect(shouldRunLegacyLocalAssetMigration()).toBe(false)
    expect(readLegacyLocalAssetMigrationStatus()).toEqual(status)
  })

  it('迁移抛错时会持久化 failed 状态并保留错误摘要', async () => {
    const migrateMock = vi.mocked(migrateLegacyLocalAssetsToOpfs)
    migrateMock.mockRejectedValue(new Error('boom'))

    const status = await runLegacyLocalAssetMigrationWithStatus()

    expect(status.phase).toBe('failed')
    expect(status.error).toBe('boom')
    expect(status.finishedAt).not.toBeNull()
    expect(shouldRunLegacyLocalAssetMigration()).toBe(true)
    expect(readLegacyLocalAssetMigrationStatus()).toEqual(status)
  })
})
