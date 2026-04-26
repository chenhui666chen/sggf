type FileSystemPermissionMode = 'read' | 'readwrite'
type FileSystemPermissionStateLike = 'granted' | 'denied' | 'prompt'

export interface LocalAssetExternalDirectoryHandle {
  kind?: string
  name?: string
  getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<LocalAssetExternalDirectoryHandle>
  getFileHandle(name: string, options?: { create?: boolean }): Promise<{
    createWritable(): Promise<{
      write(data: Blob | BufferSource | string): Promise<void>
      close(): Promise<void>
    }>
    getFile(): Promise<File>
  }>
  removeEntry?(name: string, options?: { recursive?: boolean }): Promise<void>
  queryPermission?(descriptor?: { mode?: FileSystemPermissionMode }): Promise<FileSystemPermissionStateLike>
  requestPermission?(descriptor?: { mode?: FileSystemPermissionMode }): Promise<FileSystemPermissionStateLike>
}

export type LocalAssetExternalDirectoryPermissionState =
  | FileSystemPermissionStateLike
  | 'unknown'

export type LocalAssetExternalDirectoryStatus = {
  supported: boolean
  configured: boolean
  directoryName: string | null
  permission: LocalAssetExternalDirectoryPermissionState
}

export type PreferredLocalAssetStorageDriver = 'external_directory' | null

type LocalAssetExternalDirectorySnapshot = {
  directoryName: string | null
  updatedAt: string
}

type StoredExternalDirectoryRecord = {
  key: string
  value: unknown
}

const DB_NAME = 'novel-writing-agent-local-asset-external-directory'
const DB_VERSION = 1
const STORE_NAME = 'settings'
const DIRECTORY_HANDLE_KEY = 'active-directory-handle'
const DIRECTORY_SNAPSHOT_KEY = 'active-directory-snapshot'

let databasePromise: Promise<IDBDatabase> | null = null

function wrapRequest<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('IndexedDB request failed'))
  })
}

function waitForTransaction(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve, reject) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => reject(transaction.error || new Error('IndexedDB transaction failed'))
    transaction.onabort = () => reject(transaction.error || new Error('IndexedDB transaction aborted'))
  })
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
          database.createObjectStore(STORE_NAME, { keyPath: 'key' })
        }
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

async function readSettingRecord<T>(key: string): Promise<T | null> {
  const database = await openDatabase()
  const transaction = database.transaction(STORE_NAME, 'readonly')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)
  const record = (await wrapRequest(store.get(key))) as StoredExternalDirectoryRecord | undefined
  await transactionDone
  return (record?.value as T | undefined) ?? null
}

async function writeSettingRecord(key: string, value: unknown): Promise<void> {
  const database = await openDatabase()
  const transaction = database.transaction(STORE_NAME, 'readwrite')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)
  await wrapRequest(store.put({ key, value }))
  await transactionDone
}

async function deleteSettingRecord(key: string): Promise<void> {
  const database = await openDatabase()
  const transaction = database.transaction(STORE_NAME, 'readwrite')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)
  await wrapRequest(store.delete(key))
  await transactionDone
}

function getDirectoryPicker():
  | ((options?: { mode?: FileSystemPermissionMode }) => Promise<LocalAssetExternalDirectoryHandle>)
  | null {
  if (typeof window === 'undefined') {
    return null
  }

  const candidate = (window as Window & {
    showDirectoryPicker?: (options?: { mode?: FileSystemPermissionMode }) => Promise<LocalAssetExternalDirectoryHandle>
  }).showDirectoryPicker

  return typeof candidate === 'function' ? candidate : null
}

async function resolveDirectoryPermission(
  handle: LocalAssetExternalDirectoryHandle,
  mode: FileSystemPermissionMode,
  options?: { prompt?: boolean },
): Promise<LocalAssetExternalDirectoryPermissionState> {
  const queryPermission = handle.queryPermission
  const requestPermission = handle.requestPermission

  try {
    if (typeof queryPermission === 'function') {
      const permission = await queryPermission.call(handle, { mode })
      if (permission === 'granted' || permission === 'denied') {
        return permission
      }
      if (permission === 'prompt' && options?.prompt && typeof requestPermission === 'function') {
        const nextPermission = await requestPermission.call(handle, { mode })
        return nextPermission === 'granted' || nextPermission === 'denied' ? nextPermission : 'prompt'
      }
      return permission
    }

    if (options?.prompt && typeof requestPermission === 'function') {
      const permission = await requestPermission.call(handle, { mode })
      return permission === 'granted' || permission === 'denied' ? permission : 'prompt'
    }
  } catch {
    return 'unknown'
  }

  return 'unknown'
}

function readDirectoryName(handle: LocalAssetExternalDirectoryHandle): string | null {
  const normalized = String(handle.name || '').trim()
  return normalized || null
}

async function persistDirectorySnapshot(handle: LocalAssetExternalDirectoryHandle): Promise<void> {
  const snapshot: LocalAssetExternalDirectorySnapshot = {
    directoryName: readDirectoryName(handle),
    updatedAt: new Date().toISOString(),
  }
  await writeSettingRecord(DIRECTORY_SNAPSHOT_KEY, snapshot)
}

export function isLocalAssetExternalDirectorySupported(): boolean {
  return getDirectoryPicker() !== null
}

export async function rememberLocalAssetExternalDirectoryHandle(
  handle: LocalAssetExternalDirectoryHandle,
): Promise<LocalAssetExternalDirectoryStatus> {
  await writeSettingRecord(DIRECTORY_HANDLE_KEY, handle)
  await persistDirectorySnapshot(handle)
  const permission = await resolveDirectoryPermission(handle, 'readwrite')

  return {
    supported: isLocalAssetExternalDirectorySupported(),
    configured: true,
    directoryName: readDirectoryName(handle),
    permission,
  }
}

export async function pickLocalAssetExternalDirectory(): Promise<LocalAssetExternalDirectoryStatus> {
  const picker = getDirectoryPicker()
  if (!picker) {
    throw new Error('当前浏览器不支持 File System Access API 目录选择')
  }

  const handle = await picker({ mode: 'readwrite' })
  return rememberLocalAssetExternalDirectoryHandle(handle)
}

export async function getLocalAssetExternalDirectoryHandle(options?: {
  mode?: FileSystemPermissionMode
  prompt?: boolean
}): Promise<LocalAssetExternalDirectoryHandle | null> {
  const handle = await readSettingRecord<LocalAssetExternalDirectoryHandle>(DIRECTORY_HANDLE_KEY)
  if (!handle) {
    return null
  }

  const permission = await resolveDirectoryPermission(handle, options?.mode || 'readwrite', options)
  if (permission === 'denied') {
    return null
  }
  if (permission === 'prompt' && (typeof handle.requestPermission === 'function' || typeof handle.queryPermission === 'function')) {
    return null
  }

  return handle
}

export async function getLocalAssetExternalDirectoryStatus(): Promise<LocalAssetExternalDirectoryStatus> {
  const supported = isLocalAssetExternalDirectorySupported()
  const snapshot = await readSettingRecord<LocalAssetExternalDirectorySnapshot>(DIRECTORY_SNAPSHOT_KEY)
  const handle = await readSettingRecord<LocalAssetExternalDirectoryHandle>(DIRECTORY_HANDLE_KEY)

  if (!handle) {
    return {
      supported,
      configured: false,
      directoryName: snapshot?.directoryName ?? null,
      permission: 'unknown',
    }
  }

  const permission = await resolveDirectoryPermission(handle, 'readwrite')
  return {
    supported,
    configured: true,
    directoryName: readDirectoryName(handle) ?? snapshot?.directoryName ?? null,
    permission,
  }
}

export async function requestLocalAssetExternalDirectoryAccess(): Promise<LocalAssetExternalDirectoryStatus> {
  const supported = isLocalAssetExternalDirectorySupported()
  const snapshot = await readSettingRecord<LocalAssetExternalDirectorySnapshot>(DIRECTORY_SNAPSHOT_KEY)
  const handle = await readSettingRecord<LocalAssetExternalDirectoryHandle>(DIRECTORY_HANDLE_KEY)

  if (!handle) {
    return {
      supported,
      configured: false,
      directoryName: snapshot?.directoryName ?? null,
      permission: 'unknown',
    }
  }

  const permission = await resolveDirectoryPermission(handle, 'readwrite', { prompt: true })
  const directoryName = readDirectoryName(handle) ?? snapshot?.directoryName ?? null

  if (permission === 'granted') {
    await persistDirectorySnapshot(handle)
  }

  return {
    supported,
    configured: true,
    directoryName,
    permission,
  }
}

export async function resolvePreferredLocalAssetStorageDriver(): Promise<PreferredLocalAssetStorageDriver> {
  const handle = await getLocalAssetExternalDirectoryHandle({ mode: 'readwrite' })
  return handle ? 'external_directory' : null
}

export function didLocalAssetExternalDirectoryFallback(
  preferredStorageDriver: PreferredLocalAssetStorageDriver,
  actualStorageDriver: string | null | undefined,
): boolean {
  return preferredStorageDriver === 'external_directory' && actualStorageDriver !== 'external_directory'
}

export async function clearLocalAssetExternalDirectoryHandle(): Promise<void> {
  await Promise.all([
    deleteSettingRecord(DIRECTORY_HANDLE_KEY),
    deleteSettingRecord(DIRECTORY_SNAPSHOT_KEY),
  ])
}

export async function __resetLocalAssetExternalDirectoryStateForTest(): Promise<void> {
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
