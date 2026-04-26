import contractDocument from './userAssetLocalStorage.schema.json'

import {
  USER_ASSET_ACTIVE_LOCAL_PERSIST_LEVELS,
  USER_ASSET_ACTIVE_LOCAL_STORAGE_DRIVERS,
  USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH,
  USER_ASSET_LOCAL_PERSIST_LEVELS,
  USER_ASSET_LOCAL_STORAGE_DRIVERS,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_ID,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION,
  USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH,
  USER_ASSET_RESERVED_LOCAL_PERSIST_LEVELS,
  USER_ASSET_RESERVED_LOCAL_STORAGE_DRIVERS,
  type UserAssetActiveLocalPersistLevel,
  type UserAssetActiveLocalStorageDriver,
  type UserAssetLocalPersistLevel,
  type UserAssetLocalStorageDriver,
  type UserAssetLocalStorageMetadata,
  type UserAssetMetadata,
} from './userAssetLocalStorageContract.generated'

export const USER_ASSET_LOCAL_STORAGE_METADATA_SCHEMA = contractDocument

export {
  USER_ASSET_ACTIVE_LOCAL_PERSIST_LEVELS,
  USER_ASSET_ACTIVE_LOCAL_STORAGE_DRIVERS,
  USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH,
  USER_ASSET_LOCAL_PERSIST_LEVELS,
  USER_ASSET_LOCAL_STORAGE_DRIVERS,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_DOC_PATH,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_ID,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_OWNER,
  USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT_VERSION,
  USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH,
  USER_ASSET_RESERVED_LOCAL_PERSIST_LEVELS,
  USER_ASSET_RESERVED_LOCAL_STORAGE_DRIVERS,
}

export type {
  UserAssetActiveLocalPersistLevel,
  UserAssetActiveLocalStorageDriver,
  UserAssetLocalPersistLevel,
  UserAssetLocalStorageDriver,
  UserAssetLocalStorageMetadata,
  UserAssetMetadata,
}

function isObjectMetadataPart(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function normalizeOptionalText(value: unknown, maxLength?: number, fieldName?: string): string | null {
  if (value === null || value === undefined) {
    return null
  }
  const normalized = String(value).trim()
  if (!normalized) {
    return null
  }
  if (typeof maxLength === 'number' && normalized.length > maxLength) {
    // 前端侧的"截断"是防御性行为；一旦触发即代表调用方传入的路径会被丢尾，
    // 上报 warning 以便开发期发现契约被截断的情况。后端同字段采用"超长拒绝"。
    console.warn(
      `[userAssetLocalStorageContract] ${fieldName ?? 'value'} length ${normalized.length} exceeds ${maxLength}, truncated.`,
    )
    return normalized.slice(0, maxLength)
  }
  return normalized
}

function normalizeOptionalEnumValue<T extends readonly string[]>(
  value: unknown,
  activeValues: T,
  fieldName: string,
  reservedValues: readonly string[] = [],
): T[number] | null {
  const normalized = normalizeOptionalText(value)
  if (normalized === null) {
    return null
  }

  const lowered = normalized.toLowerCase()
  if (reservedValues.includes(lowered)) {
    throw new Error(`${fieldName} = ${JSON.stringify(lowered)} 为 reserved 取值，运行时尚未实现，禁止写入`)
  }

  if ((activeValues as readonly string[]).includes(lowered)) {
    return lowered as T[number]
  }

  const reservedHint = reservedValues.length
    ? `；${reservedValues.join(', ')} 为 reserved 取值`
    : ''
  throw new Error(`${fieldName} 必须是 ${activeValues.join(', ')} 之一${reservedHint}`)
}

export function normalizeUserAssetMetadataContract(
  metadata: Record<string, unknown> | UserAssetMetadata | null | undefined,
): UserAssetMetadata {
  const nextMetadata: UserAssetMetadata =
    isObjectMetadataPart(metadata) ? { ...metadata } : {}

  if ('local_storage_driver' in nextMetadata) {
    nextMetadata.local_storage_driver = normalizeOptionalEnumValue(
      nextMetadata.local_storage_driver,
      USER_ASSET_ACTIVE_LOCAL_STORAGE_DRIVERS,
      'metadata_json.local_storage_driver',
      USER_ASSET_RESERVED_LOCAL_STORAGE_DRIVERS,
    )
  }

  if ('local_persist_level' in nextMetadata) {
    nextMetadata.local_persist_level = normalizeOptionalEnumValue(
      nextMetadata.local_persist_level,
      USER_ASSET_ACTIVE_LOCAL_PERSIST_LEVELS,
      'metadata_json.local_persist_level',
      USER_ASSET_RESERVED_LOCAL_PERSIST_LEVELS,
    )
  }

  if ('local_storage_path' in nextMetadata) {
    nextMetadata.local_storage_path = normalizeOptionalText(
      nextMetadata.local_storage_path,
      USER_ASSET_LOCAL_STORAGE_PATH_MAX_LENGTH,
      'metadata_json.local_storage_path',
    )
  }

  if ('external_relative_path' in nextMetadata) {
    nextMetadata.external_relative_path = normalizeOptionalText(
      nextMetadata.external_relative_path,
      USER_ASSET_EXTERNAL_RELATIVE_PATH_MAX_LENGTH,
      'metadata_json.external_relative_path',
    )
  }

  return nextMetadata
}

export function buildUserAssetMetadataContract(
  ...parts: Array<Record<string, unknown> | UserAssetMetadata | null | undefined>
): UserAssetMetadata {
  const merged: Record<string, unknown> = {}

  for (const part of parts) {
    if (!isObjectMetadataPart(part)) {
      continue
    }
    Object.assign(merged, part)
  }

  return normalizeUserAssetMetadataContract(merged)
}
