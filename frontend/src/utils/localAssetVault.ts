import { buildUserAssetMetadataContract } from '@/contracts/userAssetLocalStorageContract'
import type {
  UserAssetLocalPersistLevel as LocalAssetPersistLevel,
  UserAssetLocalStorageDriver as LocalAssetStorageDriver,
  UserAssetLocalStorageMetadata,
  UserAssetMetadata,
} from '@/types/userAsset'
import { getLocalAssetExternalDirectoryHandle } from './localAssetExternalDirectory'

export interface LocalAssetVaultRecord {
  assetUuid: string
  mediaKind: string
  blob: Blob
  mimeType?: string | null
  fileSize?: number | null
  sourceModule?: string | null
  title?: string | null
  sourceUri?: string | null
  previewUri?: string | null
  downloadUri?: string | null
  metadata?: UserAssetMetadata
  createdAt: string
  updatedAt: string
  storageDriver: LocalAssetStorageDriver
  storagePath?: string | null
  externalRelativePath?: string | null
  persistLevel: LocalAssetPersistLevel
}

export type LocalAssetVaultInventoryRecord = Omit<LocalAssetVaultRecord, 'blob'>

interface LocalAssetVaultIndexRecord extends Omit<LocalAssetVaultRecord, 'blob'> {
  blob?: Blob | null
}

export interface SaveLocalAssetInput {
  assetUuid: string
  mediaKind: string
  blob: Blob
  mimeType?: string | null
  fileSize?: number | null
  sourceModule?: string | null
  title?: string | null
  sourceUri?: string | null
  previewUri?: string | null
  downloadUri?: string | null
  metadata?: UserAssetMetadata
  preferredStorageDriver?: ExplicitPreferredLocalAssetStorageDriver | null
}

// 窄化后的"显式首选驱动"：调用方只能主动选择 external_directory / opfs；
// legacy_indexeddb 仅在运行时作为兜底路径，不允许业务页面显式选择。
export type ExplicitPreferredLocalAssetStorageDriver = Exclude<
  LocalAssetStorageDriver,
  'legacy_indexeddb'
>

interface VaultWritableFileStream {
  write(data: Blob | BufferSource | string): Promise<void>
  close(): Promise<void>
}

interface VaultFileSystemFileHandle {
  createWritable(): Promise<VaultWritableFileStream>
  getFile(): Promise<File>
}

interface VaultFileSystemDirectoryHandle {
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<VaultFileSystemDirectoryHandle>
  getFileHandle(name: string, options?: { create?: boolean }): Promise<VaultFileSystemFileHandle>
  removeEntry?(name: string, options?: { recursive?: boolean }): Promise<void>
}

type StorageManagerWithDirectory = StorageManager & {
  getDirectory?: () => Promise<VaultFileSystemDirectoryHandle>
}

const DB_NAME = 'novel-writing-agent-local-assets'
const DB_VERSION = 2
const STORE_NAME = 'assets'
const OPFS_ROOT_DIRECTORY = 'local_asset_vault'

let databasePromise: Promise<IDBDatabase> | null = null
let persistentStorageGranted = false

function normalizeAssetUuid(assetUuid: string): string {
  const normalized = String(assetUuid || '').trim()
  if (!normalized) {
    throw new Error('assetUuid 不能为空')
  }
  return normalized
}

function normalizeMediaKind(mediaKind: string): string {
  const normalized = String(mediaKind || '').trim()
  return normalized || 'file'
}

function wrapRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('IndexedDB 请求失败'))
  })
}

function waitForTransaction(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error || new Error('IndexedDB 事务失败'))
    transaction.onabort = () => reject(transaction.error || new Error('IndexedDB 事务已中止'))
  })
}

function ensureStoreIndexes(store: IDBObjectStore): void {
  if (!store.indexNames.contains('mediaKind')) {
    store.createIndex('mediaKind', 'mediaKind', { unique: false })
  }
  if (!store.indexNames.contains('sourceModule')) {
    store.createIndex('sourceModule', 'sourceModule', { unique: false })
  }
  if (!store.indexNames.contains('updatedAt')) {
    store.createIndex('updatedAt', 'updatedAt', { unique: false })
  }
  if (!store.indexNames.contains('storageDriver')) {
    store.createIndex('storageDriver', 'storageDriver', { unique: false })
  }
  if (!store.indexNames.contains('persistLevel')) {
    store.createIndex('persistLevel', 'persistLevel', { unique: false })
  }
}

async function openDatabase(): Promise<IDBDatabase> {
  if (typeof indexedDB === 'undefined') {
    throw new Error('当前环境不支持 IndexedDB')
  }

  if (!databasePromise) {
    databasePromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION)

      request.onupgradeneeded = () => {
        const database = request.result
        if (!database.objectStoreNames.contains(STORE_NAME)) {
          const store = database.createObjectStore(STORE_NAME, { keyPath: 'assetUuid' })
          ensureStoreIndexes(store)
          return
        }

        const transaction = request.transaction
        if (!transaction) {
          throw new Error('IndexedDB 升级事务不可用')
        }
        ensureStoreIndexes(transaction.objectStore(STORE_NAME))
      }

      request.onsuccess = () => {
        const database = request.result
        database.onversionchange = () => {
          database.close()
        }
        resolve(database)
      }

      request.onerror = () => {
        reject(request.error || new Error('无法打开 IndexedDB'))
      }
    })
  }

  return databasePromise
}

function getStorageManager(): StorageManagerWithDirectory | null {
  if (typeof navigator === 'undefined' || !navigator.storage) {
    return null
  }
  return navigator.storage as StorageManagerWithDirectory
}

function encodeStoragePathSegment(value: string, fallback: string): string {
  const normalized = String(value || '').trim() || fallback
  return encodeURIComponent(normalized)
}

function buildOpfsStoragePath(assetUuid: string, mediaKind: string): string {
  return [
    OPFS_ROOT_DIRECTORY,
    encodeStoragePathSegment(mediaKind, 'file'),
    encodeStoragePathSegment(assetUuid, 'asset'),
  ].join('/')
}

function normalizeExtension(value: string | null | undefined): string {
  const normalized = String(value || '').trim().toLowerCase()
  if (!normalized) {
    return ''
  }

  const withDot = normalized.startsWith('.') ? normalized : `.${normalized}`
  return /^[.][a-z0-9]+$/.test(withDot) ? withDot : ''
}

function resolveExtensionFromMimeType(mimeType: string | null | undefined): string {
  const normalized = String(mimeType || '').trim().toLowerCase()
  const extensionMap: Record<string, string> = {
    'audio/flac': '.flac',
    'audio/mpeg': '.mp3',
    'audio/mp4': '.m4a',
    'audio/ogg': '.ogg',
    'audio/wav': '.wav',
    'audio/webm': '.webm',
    'image/gif': '.gif',
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'text/plain': '.txt',
    'text/vtt': '.vtt',
    'video/mp4': '.mp4',
    'video/webm': '.webm',
  }

  return extensionMap[normalized] || ''
}

function resolveExtensionFromUri(uri: string | null | undefined): string {
  const normalized = String(uri || '').trim()
  if (!normalized) {
    return ''
  }

  const withoutQuery = normalized.split(/[?#]/)[0] || ''
  const match = withoutQuery.match(/\.([a-z0-9]+)$/i)
  return match ? normalizeExtension(match[1]) : ''
}

function resolveLocalAssetFileExtension(input: {
  mimeType?: string | null
  downloadUri?: string | null
  previewUri?: string | null
  sourceUri?: string | null
  existing?: string | null
}): string {
  return normalizeExtension(input.existing)
    || resolveExtensionFromMimeType(input.mimeType)
    || resolveExtensionFromUri(input.downloadUri)
    || resolveExtensionFromUri(input.previewUri)
    || resolveExtensionFromUri(input.sourceUri)
}

function buildExternalRelativePath(
  assetUuid: string,
  mediaKind: string,
  extension: string,
): string {
  return [
    encodeStoragePathSegment(mediaKind, 'file'),
    `${encodeStoragePathSegment(assetUuid, 'asset')}${normalizeExtension(extension)}`,
  ].join('/')
}

function resolveExternalStoragePath(
  record:
    | Pick<LocalAssetVaultIndexRecord, 'externalRelativePath' | 'storagePath'>
    | Pick<LocalAssetVaultRecord, 'externalRelativePath' | 'storagePath'>
    | null
    | undefined,
): string | null {
  return record?.externalRelativePath || record?.storagePath || null
}

let opfsUnavailableWarned = false

function warnOpfsUnavailableOnce(reason: string, error?: unknown): void {
  if (opfsUnavailableWarned) {
    return
  }
  opfsUnavailableWarned = true
  if (error) {
    console.warn(`[localAssetVault] OPFS 不可用，降级到 legacy_indexeddb：${reason}`, error)
  } else {
    console.warn(`[localAssetVault] OPFS 不可用，降级到 legacy_indexeddb：${reason}`)
  }
}

async function getOpfsRootDirectory(): Promise<VaultFileSystemDirectoryHandle | null> {
  const storageManager = getStorageManager()
  if (!storageManager || typeof storageManager.getDirectory !== 'function') {
    warnOpfsUnavailableOnce('navigator.storage.getDirectory 不可用')
    return null
  }

  try {
    return await storageManager.getDirectory()
  } catch (error) {
    warnOpfsUnavailableOnce('navigator.storage.getDirectory 调用抛出异常', error)
    return null
  }
}

export function __resetOpfsUnavailableWarningForTest(): void {
  opfsUnavailableWarned = false
}

export async function __probeOpfsAvailabilityForTest(): Promise<boolean> {
  const directory = await getOpfsRootDirectory()
  return directory !== null
}

export async function __resetLocalAssetVaultStateForTest(): Promise<void> {
  persistentStorageGranted = false
  opfsUnavailableWarned = false

  if (databasePromise) {
    try {
      const database = await databasePromise
      database.close()
    } catch {
      // ignore
    }
  }

  databasePromise = null
}

function splitStoragePathSegments(storagePath: string): string[] {
  return String(storagePath || '')
    .split('/')
    .map((segment) => segment.trim())
    .filter(Boolean)
}

async function resolveDirectoryParentHandle(
  rootDirectory: VaultFileSystemDirectoryHandle | null,
  storagePath: string,
  options?: { create?: boolean },
): Promise<{
  rootDirectory: VaultFileSystemDirectoryHandle
  parentDirectory: VaultFileSystemDirectoryHandle
  pathSegments: string[]
} | null> {
  if (!rootDirectory) {
    return null
  }

  const pathSegments = splitStoragePathSegments(storagePath)
  if (pathSegments.length < 2) {
    return null
  }

  let currentDirectory = rootDirectory
  const create = Boolean(options?.create)

  for (const segment of pathSegments.slice(0, -1)) {
    currentDirectory = await currentDirectory.getDirectoryHandle(segment, { create })
  }

  return {
    rootDirectory,
    parentDirectory: currentDirectory,
    pathSegments,
  }
}

async function getDirectoryFileHandle(
  rootDirectory: VaultFileSystemDirectoryHandle | null,
  storagePath: string,
  options?: { create?: boolean },
): Promise<VaultFileSystemFileHandle | null> {
  const resolved = await resolveDirectoryParentHandle(rootDirectory, storagePath, options)
  if (!resolved) {
    return null
  }

  return resolved.parentDirectory.getFileHandle(resolved.pathSegments[resolved.pathSegments.length - 1], {
    create: Boolean(options?.create),
  })
}

export async function requestLocalAssetPersistence(): Promise<LocalAssetPersistLevel> {
  if (persistentStorageGranted) {
    return 'persistent_requested'
  }

  const storageManager = getStorageManager()
  if (!storageManager) {
    return 'best_effort'
  }

  try {
    if (typeof storageManager.persisted === 'function') {
      const alreadyPersisted = await storageManager.persisted()
      if (alreadyPersisted) {
        persistentStorageGranted = true
        return 'persistent_requested'
      }
    }

    if (typeof storageManager.persist === 'function') {
      const granted = await storageManager.persist()
      if (granted) {
        persistentStorageGranted = true
        return 'persistent_requested'
      }
    }
  } catch {
    return 'best_effort'
  }

  return 'best_effort'
}

function buildLocalStorageMetadata(
  metadata: UserAssetMetadata | undefined,
  storageDriver: LocalAssetStorageDriver,
  storagePath: string | null,
  persistLevel: LocalAssetPersistLevel,
  externalRelativePath?: string | null,
): UserAssetMetadata {
  return buildUserAssetMetadataContract(metadata, {
    local_storage_driver: storageDriver,
    local_storage_path: storagePath || null,
    local_persist_level: persistLevel,
    external_relative_path: externalRelativePath || null,
  })
}

function normalizeIndexRecord(record: LocalAssetVaultIndexRecord): LocalAssetVaultIndexRecord {
  const storagePath = record.storagePath || null
  const storageDriver = record.storageDriver || (storagePath ? 'opfs' : 'legacy_indexeddb')
  const persistLevel = record.persistLevel || 'best_effort'
  const externalRelativePath = record.externalRelativePath || null

  return {
    ...record,
    mediaKind: normalizeMediaKind(record.mediaKind),
    storageDriver,
    storagePath,
    externalRelativePath,
    persistLevel,
    metadata: buildLocalStorageMetadata(
      record.metadata,
      storageDriver,
      storagePath,
      persistLevel,
      externalRelativePath,
    ),
  }
}

export function extractLocalAssetStorageMetadata(
  record: Pick<LocalAssetVaultRecord, 'storageDriver' | 'storagePath' | 'externalRelativePath' | 'persistLevel'>,
): UserAssetLocalStorageMetadata {
  const normalized = buildUserAssetMetadataContract({
    local_storage_driver: record.storageDriver,
    local_storage_path: record.storagePath || null,
    local_persist_level: record.persistLevel,
    external_relative_path: record.externalRelativePath || null,
  })

  return {
    local_storage_driver: normalized.local_storage_driver ?? null,
    local_storage_path: normalized.local_storage_path ?? null,
    local_persist_level: normalized.local_persist_level ?? null,
    external_relative_path: normalized.external_relative_path ?? null,
  }
}

function toPublicRecord(indexRecord: LocalAssetVaultIndexRecord, blob: Blob): LocalAssetVaultRecord {
  return {
    assetUuid: indexRecord.assetUuid,
    mediaKind: indexRecord.mediaKind,
    blob,
    mimeType: indexRecord.mimeType ?? null,
    fileSize: indexRecord.fileSize ?? blob.size ?? null,
    sourceModule: indexRecord.sourceModule ?? null,
    title: indexRecord.title ?? null,
    sourceUri: indexRecord.sourceUri ?? null,
    previewUri: indexRecord.previewUri ?? null,
    downloadUri: indexRecord.downloadUri ?? null,
    metadata: indexRecord.metadata || {},
    createdAt: indexRecord.createdAt,
    updatedAt: indexRecord.updatedAt,
    storageDriver: indexRecord.storageDriver,
    storagePath: indexRecord.storagePath ?? null,
    externalRelativePath: indexRecord.externalRelativePath ?? null,
    persistLevel: indexRecord.persistLevel,
  }
}

function toInventoryRecord(indexRecord: LocalAssetVaultIndexRecord): LocalAssetVaultInventoryRecord {
  return {
    assetUuid: indexRecord.assetUuid,
    mediaKind: indexRecord.mediaKind,
    mimeType: indexRecord.mimeType ?? null,
    fileSize: indexRecord.fileSize ?? null,
    sourceModule: indexRecord.sourceModule ?? null,
    title: indexRecord.title ?? null,
    sourceUri: indexRecord.sourceUri ?? null,
    previewUri: indexRecord.previewUri ?? null,
    downloadUri: indexRecord.downloadUri ?? null,
    metadata: indexRecord.metadata || {},
    createdAt: indexRecord.createdAt,
    updatedAt: indexRecord.updatedAt,
    storageDriver: indexRecord.storageDriver,
    storagePath: indexRecord.storagePath ?? null,
    externalRelativePath: indexRecord.externalRelativePath ?? null,
    persistLevel: indexRecord.persistLevel,
  }
}

function normalizeStorageError(error: unknown, fallbackMessage: string): Error {
  const errorName = error instanceof Error ? error.name : ''
  if (errorName === 'QuotaExceededError') {
    return new Error('本地存储空间不足，请清理浏览器站点数据或减少缓存资产后重试')
  }

  if (error instanceof Error && error.message) {
    return error
  }

  return new Error(fallbackMessage)
}

async function readIndexRecord(
  database: IDBDatabase,
  assetUuid: string,
): Promise<LocalAssetVaultIndexRecord | null> {
  const transaction = database.transaction(STORE_NAME, 'readonly')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)
  const record = (await wrapRequest(store.get(assetUuid))) as LocalAssetVaultIndexRecord | undefined
  await transactionDone
  return record ? normalizeIndexRecord(record) : null
}

async function writeIndexRecord(
  database: IDBDatabase,
  record: LocalAssetVaultIndexRecord,
): Promise<void> {
  const transaction = database.transaction(STORE_NAME, 'readwrite')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)
  await wrapRequest(store.put(record))
  await transactionDone
}

async function deleteIndexRecord(
  database: IDBDatabase,
  assetUuid: string,
): Promise<void> {
  const transaction = database.transaction(STORE_NAME, 'readwrite')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)
  await wrapRequest(store.delete(assetUuid))
  await transactionDone
}

async function readAllIndexRecords(
  database: IDBDatabase,
): Promise<LocalAssetVaultIndexRecord[]> {
  const transaction = database.transaction(STORE_NAME, 'readonly')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)
  const records = (await wrapRequest(store.getAll())) as LocalAssetVaultIndexRecord[] | undefined
  await transactionDone
  if (!Array.isArray(records)) {
    return []
  }

  return records.map((record) => normalizeIndexRecord(record))
}

async function writeBlobToDirectory(
  rootDirectory: VaultFileSystemDirectoryHandle | null,
  storagePath: string,
  blob: Blob,
): Promise<boolean> {
  const fileHandle = await getDirectoryFileHandle(rootDirectory, storagePath, { create: true })
  if (!fileHandle) {
    return false
  }

  const writable = await fileHandle.createWritable()
  await writable.write(blob)
  await writable.close()
  return true
}

async function writeBlobToOpfs(
  assetUuid: string,
  mediaKind: string,
  blob: Blob,
): Promise<{ storagePath: string } | null> {
  const storagePath = buildOpfsStoragePath(assetUuid, mediaKind)
  const wrote = await writeBlobToDirectory(await getOpfsRootDirectory(), storagePath, blob)
  return wrote ? { storagePath } : null
}

async function writeBlobToExternalDirectory(input: {
  assetUuid: string
  mediaKind: string
  blob: Blob
  mimeType?: string | null
  downloadUri?: string | null
  previewUri?: string | null
  sourceUri?: string | null
  existingExternalRelativePath?: string | null
}): Promise<{ storagePath: string; externalRelativePath: string } | null> {
  const rootDirectory = await getLocalAssetExternalDirectoryHandle({ mode: 'readwrite' })
  if (!rootDirectory) {
    return null
  }

  const extension = resolveLocalAssetFileExtension({
    mimeType: input.mimeType ?? input.blob.type,
    downloadUri: input.downloadUri,
    previewUri: input.previewUri,
    sourceUri: input.sourceUri,
    existing: input.existingExternalRelativePath,
  })
  const externalRelativePath = buildExternalRelativePath(input.assetUuid, input.mediaKind, extension)
  const wrote = await writeBlobToDirectory(rootDirectory, externalRelativePath, input.blob)

  return wrote
    ? {
        storagePath: externalRelativePath,
        externalRelativePath,
      }
    : null
}

async function readBlobFromDirectory(
  rootDirectory: VaultFileSystemDirectoryHandle | null,
  storagePath: string | null | undefined,
): Promise<Blob | null> {
  if (!storagePath) {
    return null
  }

  try {
    const fileHandle = await getDirectoryFileHandle(rootDirectory, storagePath)
    if (!fileHandle) {
      return null
    }
    return await fileHandle.getFile()
  } catch {
    return null
  }
}

async function readBlobFromOpfs(storagePath: string | null | undefined): Promise<Blob | null> {
  return readBlobFromDirectory(await getOpfsRootDirectory(), storagePath)
}

async function readBlobFromExternalDirectory(
  indexRecord: Pick<LocalAssetVaultIndexRecord, 'storagePath' | 'externalRelativePath'>,
): Promise<Blob | null> {
  const storagePath = resolveExternalStoragePath(indexRecord)
  if (!storagePath) {
    return null
  }

  return readBlobFromDirectory(
    await getLocalAssetExternalDirectoryHandle({ mode: 'read' }),
    storagePath,
  )
}

async function cleanupEmptyDirectoryHandles(
  rootDirectory: VaultFileSystemDirectoryHandle,
  directoryPathSegments: string[],
): Promise<void> {
  if (typeof rootDirectory.removeEntry !== 'function' || directoryPathSegments.length === 0) {
    return
  }

  for (let depth = directoryPathSegments.length; depth > 0; depth -= 1) {
    try {
      let parentDirectory = rootDirectory
      for (const segment of directoryPathSegments.slice(0, depth - 1)) {
        parentDirectory = await parentDirectory.getDirectoryHandle(segment)
      }

      await parentDirectory.removeEntry?.(directoryPathSegments[depth - 1])
    } catch {
      break
    }
  }
}

function isNotFoundLikeStorageError(error: unknown): boolean {
  if (!(error instanceof Error)) {
    return false
  }

  return error.name === 'NotFoundError' || error.message.includes('NotFoundError')
}

function buildDeleteOpfsPathError(storagePath: string): Error {
  return new Error(`删除 OPFS 本地资产失败：${storagePath}`)
}

async function deletePathFromDirectory(
  rootDirectory: VaultFileSystemDirectoryHandle | null,
  storagePath: string | null | undefined,
  errorFactory: (storagePath: string) => Error,
  options?: { strict?: boolean },
): Promise<boolean> {
  if (!storagePath) {
    return true
  }

  try {
    const resolved = await resolveDirectoryParentHandle(rootDirectory, storagePath)
    if (!resolved || typeof resolved.parentDirectory.removeEntry !== 'function') {
      if (options?.strict) {
        throw errorFactory(storagePath)
      }
      return false
    }

    const entryName = resolved.pathSegments[resolved.pathSegments.length - 1]
    await resolved.parentDirectory.removeEntry(entryName)
    await cleanupEmptyDirectoryHandles(resolved.rootDirectory, resolved.pathSegments.slice(0, -1))
    return true
  } catch (error) {
    if (isNotFoundLikeStorageError(error)) {
      return true
    }
    if (options?.strict) {
      throw errorFactory(storagePath)
    }
    return false
  }
}

function buildDeleteExternalDirectoryPathError(storagePath: string): Error {
  return new Error(`删除 external_directory 本地资产失败: ${storagePath}`)
}

async function deleteExternalDirectoryPath(
  indexRecord: Pick<LocalAssetVaultIndexRecord, 'storagePath' | 'externalRelativePath'>,
  options?: { strict?: boolean },
): Promise<boolean> {
  return deletePathFromDirectory(
    await getLocalAssetExternalDirectoryHandle({ mode: 'readwrite' }),
    resolveExternalStoragePath(indexRecord),
    buildDeleteExternalDirectoryPathError,
    options,
  )
}

async function deleteStoredArtifact(
  indexRecord: Pick<LocalAssetVaultIndexRecord, 'storageDriver' | 'storagePath' | 'externalRelativePath'>,
  options?: { strict?: boolean },
): Promise<boolean> {
  if (indexRecord.storageDriver === 'external_directory') {
    return deleteExternalDirectoryPath(indexRecord, options)
  }

  if (indexRecord.storageDriver === 'opfs') {
    return deleteOpfsPath(indexRecord.storagePath, options)
  }

  return true
}

function resolvePreferredStorageDriver(
  preferredStorageDriver: ExplicitPreferredLocalAssetStorageDriver | null | undefined,
  existing: LocalAssetVaultIndexRecord | null,
): ExplicitPreferredLocalAssetStorageDriver {
  if (preferredStorageDriver) {
    return preferredStorageDriver
  }

  if (existing?.storageDriver === 'external_directory') {
    return 'external_directory'
  }

  return 'opfs'
}

async function deleteOpfsPath(
  storagePath: string | null | undefined,
  options?: { strict?: boolean },
): Promise<boolean> {
  return deletePathFromDirectory(await getOpfsRootDirectory(), storagePath, buildDeleteOpfsPathError, options)
}

async function maybeMigrateLegacyBlobToOpfs(
  database: IDBDatabase,
  indexRecord: LocalAssetVaultIndexRecord,
): Promise<LocalAssetVaultIndexRecord | null> {
  if (!(indexRecord.blob instanceof Blob)) {
    return null
  }

  try {
    const opfsWriteResult = await writeBlobToOpfs(indexRecord.assetUuid, indexRecord.mediaKind, indexRecord.blob)
    if (!opfsWriteResult) {
      return null
    }

    const persistLevel = await requestLocalAssetPersistence()
    const migratedRecord: LocalAssetVaultIndexRecord = {
      ...indexRecord,
      storageDriver: 'opfs',
      storagePath: opfsWriteResult.storagePath,
      persistLevel,
      metadata: buildLocalStorageMetadata(indexRecord.metadata, 'opfs', opfsWriteResult.storagePath, persistLevel),
      blob: null,
      updatedAt: new Date().toISOString(),
    }

    await writeIndexRecord(database, migratedRecord)
    return migratedRecord
  } catch {
    return null
  }
}

async function resolveIndexRecordBlob(indexRecord: LocalAssetVaultIndexRecord): Promise<Blob | null> {
  if (indexRecord.storageDriver === 'external_directory') {
    const externalBlob = await readBlobFromExternalDirectory(indexRecord)
    if (externalBlob) {
      return externalBlob
    }
  }

  if (indexRecord.storageDriver === 'opfs') {
    const opfsBlob = await readBlobFromOpfs(indexRecord.storagePath)
    if (opfsBlob) {
      return opfsBlob
    }
  }

  if (indexRecord.blob instanceof Blob) {
    return indexRecord.blob
  }

  return null
}

export async function saveLocalAsset(input: SaveLocalAssetInput): Promise<LocalAssetVaultRecord> {
  let existing: LocalAssetVaultIndexRecord | null = null
  let storageDriver: LocalAssetStorageDriver = 'legacy_indexeddb'
  let storagePath: string | null = null
  let externalRelativePath: string | null = null

  try {
    const database = await openDatabase()
    const assetUuid = normalizeAssetUuid(input.assetUuid)
    const mediaKind = normalizeMediaKind(input.mediaKind)
    existing = await readIndexRecord(database, assetUuid)
    const now = new Date().toISOString()
    const preferredStorageDriver = resolvePreferredStorageDriver(input.preferredStorageDriver, existing)
    let persistLevel: LocalAssetPersistLevel = 'best_effort'

    let legacyBlob: Blob | null = input.blob

    if (preferredStorageDriver === 'external_directory') {
      try {
        const externalWriteResult = await writeBlobToExternalDirectory({
          assetUuid,
          mediaKind,
          blob: input.blob,
          mimeType: input.mimeType ?? input.blob.type,
          downloadUri: input.downloadUri,
          previewUri: input.previewUri,
          sourceUri: input.sourceUri,
          existingExternalRelativePath: resolveExternalStoragePath(existing),
        })
        if (externalWriteResult) {
          storageDriver = 'external_directory'
          storagePath = externalWriteResult.storagePath
          externalRelativePath = externalWriteResult.externalRelativePath
          persistLevel = 'user_directory'
          legacyBlob = null
          // 即便显式收录已落入用户目录，仍在后台并行申请 OPFS 持久化许可，
          // 为后续"用户目录不可用 → 回退 OPFS"链路提供兜底，避免浏览器清理策略更激进地回收回退数据。
          void requestLocalAssetPersistence().catch(() => undefined)
        }
      } catch (error) {
        console.warn('external_directory write failed, falling back to OPFS or legacy IndexedDB blob', error)
      }
    }

    if (storageDriver !== 'external_directory') {
      persistLevel = await requestLocalAssetPersistence()

      try {
      const opfsWriteResult = await writeBlobToOpfs(assetUuid, mediaKind, input.blob)
        if (opfsWriteResult) {
          storageDriver = 'opfs'
          storagePath = opfsWriteResult.storagePath
          externalRelativePath = null
          legacyBlob = null
        }
    } catch (error) {
      console.warn('OPFS 写入失败，已回退到 IndexedDB blob：', error)
    }

    }

    if (storageDriver === 'legacy_indexeddb') {
      persistLevel = 'best_effort'
    }

    const nextRecord: LocalAssetVaultIndexRecord = {
      assetUuid,
      mediaKind,
      mimeType: (input.mimeType ?? input.blob.type) || existing?.mimeType || null,
      fileSize: input.fileSize ?? input.blob.size ?? existing?.fileSize ?? null,
      sourceModule: input.sourceModule ?? existing?.sourceModule ?? null,
      title: input.title ?? existing?.title ?? null,
      sourceUri: input.sourceUri ?? existing?.sourceUri ?? null,
      previewUri: input.previewUri ?? existing?.previewUri ?? null,
      downloadUri: input.downloadUri ?? existing?.downloadUri ?? null,
      storageDriver,
      storagePath,
      externalRelativePath,
      persistLevel,
      metadata: buildLocalStorageMetadata(
        input.metadata ?? existing?.metadata,
        storageDriver,
        storagePath,
        persistLevel,
        externalRelativePath,
      ),
      blob: legacyBlob,
      createdAt: existing?.createdAt || now,
      updatedAt: now,
    }

    await writeIndexRecord(database, nextRecord)

    const shouldCleanupExistingArtifact = Boolean(
      existing
      && (
        existing.storageDriver !== nextRecord.storageDriver
        || existing.storagePath !== nextRecord.storagePath
        || existing.externalRelativePath !== nextRecord.externalRelativePath
      ),
    )
    if (existing && shouldCleanupExistingArtifact) {
      await deleteStoredArtifact(existing)
    }

    return toPublicRecord(nextRecord, input.blob)
  } catch (error) {
    const shouldCleanupPendingArtifact =
      storageDriver !== 'legacy_indexeddb'
      && (
        storageDriver !== existing?.storageDriver
        || storagePath !== existing?.storagePath
        || externalRelativePath !== existing?.externalRelativePath
      )

    if (shouldCleanupPendingArtifact) {
      await deleteStoredArtifact({
        storageDriver,
        storagePath,
        externalRelativePath,
      })
    }
    throw normalizeStorageError(error, '保存本地资产失败')
  }
}

export async function getLocalAsset(assetUuid: string): Promise<LocalAssetVaultRecord | null> {
  const database = await openDatabase()
  const normalizedAssetUuid = normalizeAssetUuid(assetUuid)
  let indexRecord = await readIndexRecord(database, normalizedAssetUuid)

  if (!indexRecord) {
    return null
  }

  if (indexRecord.storageDriver !== 'opfs' && indexRecord.blob instanceof Blob) {
    const migratedRecord = await maybeMigrateLegacyBlobToOpfs(database, indexRecord)
    if (migratedRecord) {
      indexRecord = migratedRecord
    }
  }

  const blob = await resolveIndexRecordBlob(indexRecord)
  if (!blob) {
    return null
  }

  return toPublicRecord(indexRecord, blob)
}

export async function getLocalAssetBlob(assetUuid: string): Promise<Blob | null> {
  const record = await getLocalAsset(assetUuid)
  return record?.blob || null
}

export async function deleteLocalAsset(assetUuid: string): Promise<boolean> {
  try {
    const database = await openDatabase()
    const normalizedAssetUuid = normalizeAssetUuid(assetUuid)
    const existing = await readIndexRecord(database, normalizedAssetUuid)

    if (!existing) {
      return false
    }

    await deleteStoredArtifact(existing, { strict: true })
    await deleteIndexRecord(database, normalizedAssetUuid)

    return true
  } catch (error) {
    throw normalizeStorageError(error, '删除本地资产失败')
  }
}

export async function listLocalAssetInventory(): Promise<LocalAssetVaultInventoryRecord[]> {
  const database = await openDatabase()
  const records = await readAllIndexRecords(database)

  return records
    .sort((left, right) => {
      const updatedAtDiff = Date.parse(right.updatedAt) - Date.parse(left.updatedAt)
      if (updatedAtDiff !== 0) {
        return updatedAtDiff
      }
      return left.assetUuid.localeCompare(right.assetUuid)
    })
    .map((record) => toInventoryRecord(record))
}

export interface MigrateLegacyLocalAssetsResult {
  scanned: number
  migrated: number
  skipped: number
  failed: number
}

async function readAllLegacyIndexRecords(
  database: IDBDatabase,
): Promise<LocalAssetVaultIndexRecord[]> {
  const records = await readAllIndexRecords(database)
  return records
    .filter((record) => record.storageDriver !== 'opfs' && record.blob instanceof Blob)
}

export async function migrateLegacyLocalAssetsToOpfs(): Promise<MigrateLegacyLocalAssetsResult> {
  const result: MigrateLegacyLocalAssetsResult = {
    scanned: 0,
    migrated: 0,
    skipped: 0,
    failed: 0,
  }

  let database: IDBDatabase
  try {
    database = await openDatabase()
  } catch {
    return result
  }

  const rootDirectory = await getOpfsRootDirectory()
  if (!rootDirectory) {
    return result
  }

  let legacyRecords: LocalAssetVaultIndexRecord[]
  try {
    legacyRecords = await readAllLegacyIndexRecords(database)
  } catch {
    return result
  }

  result.scanned = legacyRecords.length

  for (const indexRecord of legacyRecords) {
    try {
      const migrated = await maybeMigrateLegacyBlobToOpfs(database, indexRecord)
      if (migrated) {
        result.migrated += 1
      } else {
        result.skipped += 1
      }
    } catch {
      result.failed += 1
    }
  }

  return result
}
