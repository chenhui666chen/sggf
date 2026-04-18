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
  metadata?: Record<string, any>
  createdAt: string
  updatedAt: string
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
  metadata?: Record<string, any>
}

const DB_NAME = 'novel-writing-agent-local-assets'
const DB_VERSION = 1
const STORE_NAME = 'assets'

let databasePromise: Promise<IDBDatabase> | null = null

function normalizeAssetUuid(assetUuid: string): string {
  const normalized = String(assetUuid || '').trim()
  if (!normalized) {
    throw new Error('assetUuid 不能为空')
  }
  return normalized
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
          store.createIndex('mediaKind', 'mediaKind', { unique: false })
          store.createIndex('sourceModule', 'sourceModule', { unique: false })
          store.createIndex('updatedAt', 'updatedAt', { unique: false })
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

export async function saveLocalAsset(input: SaveLocalAssetInput): Promise<LocalAssetVaultRecord> {
  const database = await openDatabase()
  const assetUuid = normalizeAssetUuid(input.assetUuid)
  const transaction = database.transaction(STORE_NAME, 'readwrite')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)

  const existing = (await wrapRequest(store.get(assetUuid))) as LocalAssetVaultRecord | undefined
  const now = new Date().toISOString()
  const nextRecord: LocalAssetVaultRecord = {
    assetUuid,
    mediaKind: String(input.mediaKind || existing?.mediaKind || 'file').trim() || 'file',
    blob: input.blob,
    mimeType: (input.mimeType ?? input.blob.type) || existing?.mimeType || null,
    fileSize: input.fileSize ?? input.blob.size ?? existing?.fileSize ?? null,
    sourceModule: input.sourceModule ?? existing?.sourceModule ?? null,
    title: input.title ?? existing?.title ?? null,
    sourceUri: input.sourceUri ?? existing?.sourceUri ?? null,
    previewUri: input.previewUri ?? existing?.previewUri ?? null,
    downloadUri: input.downloadUri ?? existing?.downloadUri ?? null,
    metadata: input.metadata ?? existing?.metadata ?? {},
    createdAt: existing?.createdAt || now,
    updatedAt: now,
  }

  await wrapRequest(store.put(nextRecord))
  await transactionDone
  return nextRecord
}

export async function getLocalAsset(assetUuid: string): Promise<LocalAssetVaultRecord | null> {
  const database = await openDatabase()
  const transaction = database.transaction(STORE_NAME, 'readonly')
  const transactionDone = waitForTransaction(transaction)
  const store = transaction.objectStore(STORE_NAME)
  const record = (await wrapRequest(store.get(normalizeAssetUuid(assetUuid)))) as LocalAssetVaultRecord | undefined
  await transactionDone
  return record || null
}

export async function getLocalAssetBlob(assetUuid: string): Promise<Blob | null> {
  const record = await getLocalAsset(assetUuid)
  return record?.blob || null
}
