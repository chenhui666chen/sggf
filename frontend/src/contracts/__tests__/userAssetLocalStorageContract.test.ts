import { describe, expect, it } from 'vitest'

import {
  buildUserAssetMetadataContract,
  USER_ASSET_ACTIVE_LOCAL_PERSIST_LEVELS,
  USER_ASSET_ACTIVE_LOCAL_STORAGE_DRIVERS,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH,
  USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH,
  USER_ASSET_LOCAL_PERSIST_LEVELS,
  USER_ASSET_LOCAL_STORAGE_DRIVERS,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION,
  USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA,
  USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH,
  USER_ASSET_RESERVED_LOCAL_PERSIST_LEVELS,
  USER_ASSET_RESERVED_LOCAL_STORAGE_DRIVERS,
  normalizeUserAssetMetadataContract,
} from '../userAssetLocalStorageContract'

function extractStringEnumValues(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return []
  }
  return value.filter((item): item is string => typeof item === 'string')
}

describe('userAssetLocalStorageContract', () => {
  it('keeps JSON schema enums in sync with runtime constants', () => {
    const driverEnum = extractStringEnumValues(
      USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA.properties?.local_storage_driver?.enum,
    )
    const persistEnum = extractStringEnumValues(
      USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA.properties?.local_persist_level?.enum,
    )

    expect(driverEnum).toEqual([...USER_ASSET_LOCAL_STORAGE_DRIVERS])
    expect(persistEnum).toEqual([...USER_ASSET_LOCAL_PERSIST_LEVELS])
    expect(USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA.additionalProperties).toBe(true)
    expect(USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION).toBe(
      USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA['x-contract-version'],
    )
    expect(USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH).toBe(
      USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA['x-contract-doc'],
    )
    expect(USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER).toBe(
      USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA['x-contract-owner'],
    )
    expect(USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH).toBe(
      USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA.properties?.local_storage_path?.maxLength,
    )
    expect(USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH).toBe(
      USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA.properties?.external_relative_path?.maxLength,
    )
  })

  it('normalizes known local storage fields and preserves extra metadata', () => {
    const normalized = normalizeUserAssetMetadataContract({
      local_storage_driver: 'OPFS',
      local_storage_path: ' local_asset_vault/audio/demo ',
      local_persist_level: 'PERSISTENT_REQUESTED',
      external_relative_path: ' exports/demo.mp3 ',
      extra_flag: true,
    })

    expect(normalized).toEqual({
      local_storage_driver: 'opfs',
      local_storage_path: 'local_asset_vault/audio/demo',
      local_persist_level: 'persistent_requested',
      external_relative_path: 'exports/demo.mp3',
      extra_flag: true,
    })
  })

  it('builds metadata by merging parts in order before normalization', () => {
    const merged = buildUserAssetMetadataContract(
      { feature: 'asset', local_storage_driver: 'legacy_indexeddb' },
      null,
      { local_storage_driver: 'OPFS', local_storage_path: ' local/demo/path ' },
      { local_persist_level: 'PERSISTENT_REQUESTED', feature: 'asset-v2' },
    )

    expect(merged).toEqual({
      feature: 'asset-v2',
      local_storage_driver: 'opfs',
      local_storage_path: 'local/demo/path',
      local_persist_level: 'persistent_requested',
    })
  })

  it('rejects invalid known enum values', () => {
    expect(() =>
      normalizeUserAssetMetadataContract({
        local_storage_driver: 'nas_share',
      }),
    ).toThrow('metadata_json.local_storage_driver')

    expect(() =>
      normalizeUserAssetMetadataContract({
        local_persist_level: 'pinned_forever',
      }),
    ).toThrow('metadata_json.local_persist_level')
  })

  it('accepts external_directory and user_directory after contract activation', () => {
    const normalized = normalizeUserAssetMetadataContract({
      local_storage_driver: 'EXTERNAL_DIRECTORY',
      local_persist_level: 'USER_DIRECTORY',
      external_relative_path: ' exports/demo.mp3 ',
    })

    expect(normalized).toEqual({
      local_storage_driver: 'external_directory',
      local_persist_level: 'user_directory',
      external_relative_path: 'exports/demo.mp3',
    })
  })

  it('truncates known path fields using schema maxLength', () => {
    const tooLongPath = 'a'.repeat(USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH + 20)
    const tooLongExternalPath = 'b'.repeat(USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH + 20)

    const normalized = normalizeUserAssetMetadataContract({
      local_storage_path: tooLongPath,
      external_relative_path: tooLongExternalPath,
    })

    expect(normalized.local_storage_path).toBe('a'.repeat(USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH))
    expect(normalized.external_relative_path).toBe('b'.repeat(USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH))
  })

  it('reserved/active 集合与 schema x-reserved-values 保持一致', () => {
    const driverReservedFromSchema =
      (USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA.properties?.local_storage_driver as
        | { 'x-reserved-values'?: string[] }
        | undefined)?.['x-reserved-values'] ?? []
    const persistReservedFromSchema =
      (USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA.properties?.local_persist_level as
        | { 'x-reserved-values'?: string[] }
        | undefined)?.['x-reserved-values'] ?? []

    expect([...USER_ASSET_RESERVED_LOCAL_STORAGE_DRIVERS]).toEqual(driverReservedFromSchema)
    expect([...USER_ASSET_RESERVED_LOCAL_PERSIST_LEVELS]).toEqual(persistReservedFromSchema)

    const activeDrivers = USER_ASSET_LOCAL_STORAGE_DRIVERS.filter(
      (item) => !USER_ASSET_RESERVED_LOCAL_STORAGE_DRIVERS.includes(item as never),
    )
    const activePersistLevels = USER_ASSET_LOCAL_PERSIST_LEVELS.filter(
      (item) => !USER_ASSET_RESERVED_LOCAL_PERSIST_LEVELS.includes(item as never),
    )
    expect([...USER_ASSET_ACTIVE_LOCAL_STORAGE_DRIVERS]).toEqual(activeDrivers)
    expect([...USER_ASSET_ACTIVE_LOCAL_PERSIST_LEVELS]).toEqual(activePersistLevels)
  })
})
