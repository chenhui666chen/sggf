import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { getLocalAssetExternalDirectoryHandleMock } = vi.hoisted(() => ({
  getLocalAssetExternalDirectoryHandleMock: vi.fn(),
}))

vi.mock('../localAssetExternalDirectory', () => ({
  getLocalAssetExternalDirectoryHandle: getLocalAssetExternalDirectoryHandleMock,
}))

import {
  __probeOpfsAvailabilityForTest,
  __resetLocalAssetVaultStateForTest,
  __resetOpfsUnavailableWarningForTest,
  deleteLocalAsset,
  getLocalAsset,
  listLocalAssetInventory,
  saveLocalAsset,
} from '../localAssetVault'

beforeEach(() => {
  getLocalAssetExternalDirectoryHandleMock.mockReset()
  getLocalAssetExternalDirectoryHandleMock.mockResolvedValue(null)
})

function schedule(callback: () => void): void {
  queueMicrotask(callback)
}

function toFile(blob: Blob, name: string): File {
  if (typeof File !== 'undefined') {
    return new File([blob], name, { type: blob.type })
  }

  return Object.assign(blob, {
    name,
    lastModified: Date.now(),
  }) as File
}

class FakeWritableFileStream {
  private nextBlob: Blob

  constructor(
    private readonly files: Map<string, Blob>,
    private readonly name: string,
  ) {
    this.nextBlob = files.get(name) ?? new Blob()
  }

  async write(data: Blob | BufferSource | string): Promise<void> {
    this.nextBlob = data instanceof Blob ? data : new Blob([data])
  }

  async close(): Promise<void> {
    this.files.set(this.name, this.nextBlob)
  }
}

class FakeFileHandle {
  constructor(
    private readonly files: Map<string, Blob>,
    private readonly name: string,
  ) {}

  async createWritable(): Promise<FakeWritableFileStream> {
    return new FakeWritableFileStream(this.files, this.name)
  }

  async getFile(): Promise<File> {
    const blob = this.files.get(this.name)
    if (!blob) {
      throw new Error('NotFoundError')
    }
    return toFile(blob, this.name)
  }
}

class FakeDirectoryHandle {
  private readonly directories = new Map<string, FakeDirectoryHandle>()
  private readonly files = new Map<string, Blob>()

  constructor(
    private readonly behavior: {
      removeEntryErrorMessage?: string | null
    } = {},
  ) {}

  async getDirectoryHandle(name: string, options?: { create?: boolean }): Promise<FakeDirectoryHandle> {
    const existing = this.directories.get(name)
    if (existing) {
      return existing
    }
    if (!options?.create) {
      throw new Error('NotFoundError')
    }

    const next = new FakeDirectoryHandle(this.behavior)
    this.directories.set(name, next)
    return next
  }

  async getFileHandle(name: string, options?: { create?: boolean }): Promise<FakeFileHandle> {
    if (!this.files.has(name) && !options?.create) {
      throw new Error('NotFoundError')
    }
    if (!this.files.has(name) && options?.create) {
      this.files.set(name, new Blob())
    }

    return new FakeFileHandle(this.files, name)
  }

  async removeEntry(name: string): Promise<void> {
    if (this.behavior.removeEntryErrorMessage) {
      throw new Error(this.behavior.removeEntryErrorMessage)
    }

    if (this.files.delete(name)) {
      return
    }

    const directory = this.directories.get(name)
    if (!directory) {
      throw new Error('NotFoundError')
    }
    if (!directory.isEmpty()) {
      throw new Error('DirectoryNotEmpty')
    }

    this.directories.delete(name)
  }

  hasFile(pathSegments: string[]): boolean {
    if (pathSegments.length === 0) {
      return false
    }

    if (pathSegments.length === 1) {
      return this.files.has(pathSegments[0])
    }

    const [next, ...rest] = pathSegments
    const directory = this.directories.get(next)
    return directory ? directory.hasFile(rest) : false
  }

  private isEmpty(): boolean {
    return this.directories.size === 0 && this.files.size === 0
  }
}

type FakeRecord = Record<string, unknown> & { assetUuid: string }

class FakeObjectStore {
  readonly indexNames: { contains: (name: string) => boolean }

  constructor(
    private readonly records: Map<string, FakeRecord>,
    private readonly indexes: Set<string>,
    private readonly transaction: FakeTransaction,
  ) {
    this.indexNames = {
      contains: (name: string) => this.indexes.has(name),
    }
  }

  createIndex(name: string): void {
    this.indexes.add(name)
  }

  get(assetUuid: string): IDBRequest<FakeRecord | undefined> {
    return this.createRequest(() => this.records.get(assetUuid))
  }

  put(record: FakeRecord): IDBRequest<string> {
    return this.createRequest(() => {
      this.records.set(record.assetUuid, record)
      return record.assetUuid
    })
  }

  delete(assetUuid: string): IDBRequest<undefined> {
    return this.createRequest(() => {
      this.records.delete(assetUuid)
      return undefined
    })
  }

  getAll(): IDBRequest<FakeRecord[]> {
    return this.createRequest(() => Array.from(this.records.values()))
  }

  private createRequest<T>(resolver: () => T): IDBRequest<T> {
    const request = {
      result: undefined as T,
      error: null as DOMException | null,
      onsuccess: null as ((this: IDBRequest<T>, ev: Event) => unknown) | null,
      onerror: null as ((this: IDBRequest<T>, ev: Event) => unknown) | null,
    } as unknown as IDBRequest<T>
    const mutableRequest = request as { result: T; onsuccess?: ((this: IDBRequest<T>, ev: Event) => unknown) | null }

    schedule(() => {
      mutableRequest.result = resolver()
      mutableRequest.onsuccess?.call(request, new Event('success'))
      this.transaction.complete()
    })

    return request
  }
}

class FakeTransaction {
  oncomplete: ((this: IDBTransaction, ev: Event) => unknown) | null = null
  onerror: ((this: IDBTransaction, ev: Event) => unknown) | null = null
  onabort: ((this: IDBTransaction, ev: Event) => unknown) | null = null
  error: DOMException | null = null

  constructor(
    private readonly records: Map<string, FakeRecord>,
    private readonly indexes: Set<string>,
  ) {}

  objectStore(): IDBObjectStore {
    return new FakeObjectStore(this.records, this.indexes, this) as unknown as IDBObjectStore
  }

  complete(): void {
    schedule(() => {
      this.oncomplete?.call(this as unknown as IDBTransaction, new Event('complete'))
    })
  }
}

class FakeDatabase {
  onversionchange: ((this: IDBDatabase, ev: Event) => unknown) | null = null
  private hasStore = false

  readonly objectStoreNames = {
    contains: (name: string) => this.hasStore && name === 'assets',
  }

  constructor(
    private readonly records: Map<string, FakeRecord>,
    private readonly indexes: Set<string>,
  ) {}

  createObjectStore(): IDBObjectStore {
    this.hasStore = true
    return new FakeObjectStore(this.records, this.indexes, new FakeTransaction(this.records, this.indexes)) as unknown as IDBObjectStore
  }

  transaction(): IDBTransaction {
    this.hasStore = true
    return new FakeTransaction(this.records, this.indexes) as unknown as IDBTransaction
  }

  close(): void {
    // noop
  }
}

function installFakeIndexedDb(): void {
  const records = new Map<string, FakeRecord>()
  const indexes = new Set<string>()
  const database = new FakeDatabase(records, indexes)

  const indexedDb = {
    open: () => {
      const upgradeTransaction = new FakeTransaction(records, indexes)
      const request = {
        result: database as unknown as IDBDatabase,
        error: null as DOMException | null,
        transaction: upgradeTransaction as unknown as IDBTransaction,
        onsuccess: null as ((this: IDBOpenDBRequest, ev: Event) => unknown) | null,
        onerror: null as ((this: IDBOpenDBRequest, ev: Event) => unknown) | null,
        onupgradeneeded: null as ((this: IDBOpenDBRequest, ev: IDBVersionChangeEvent) => unknown) | null,
      } as IDBOpenDBRequest

      schedule(() => {
        if (!database.objectStoreNames.contains('assets')) {
          request.onupgradeneeded?.call(request, new Event('upgradeneeded') as IDBVersionChangeEvent)
        }
        schedule(() => {
          request.onsuccess?.call(request, new Event('success'))
        })
      })

      return request
    },
  }

  Object.defineProperty(globalThis, 'indexedDB', {
    configurable: true,
    value: indexedDb,
  })
}

function installFakeNavigator(rootDirectory: FakeDirectoryHandle): void {
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: {
      storage: {
        getDirectory: async () => rootDirectory,
        persisted: async () => false,
        persist: async () => true,
      },
    },
  })
}

describe('localAssetVault OPFS 降级路径', () => {
  const originalNavigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator')

  beforeEach(async () => {
    await __resetLocalAssetVaultStateForTest()
    __resetOpfsUnavailableWarningForTest()
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(async () => {
    await __resetLocalAssetVaultStateForTest()
    vi.restoreAllMocks()
    if (originalNavigatorDescriptor) {
      Object.defineProperty(globalThis, 'navigator', originalNavigatorDescriptor)
    } else {
      // @ts-expect-error allow cleanup in Node env
      delete globalThis.navigator
    }
  })

  function stubNavigator(navigator: unknown): void {
    Object.defineProperty(globalThis, 'navigator', {
      configurable: true,
      value: navigator,
    })
  }

  it('当 navigator.storage.getDirectory 不存在时降级并只发出一次 warn', async () => {
    stubNavigator({ storage: {} })
    const warnMock = console.warn as unknown as ReturnType<typeof vi.fn>

    const first = await __probeOpfsAvailabilityForTest()
    const second = await __probeOpfsAvailabilityForTest()

    expect(first).toBe(false)
    expect(second).toBe(false)
    expect(warnMock).toHaveBeenCalledTimes(1)
    expect(String(warnMock.mock.calls[0]?.[0] ?? '')).toMatch(/OPFS 不可用/)
  })

  it('当 navigator.storage.getDirectory 抛错时降级并只发出一次 warn', async () => {
    stubNavigator({
      storage: {
        getDirectory: () => {
          throw new Error('boom')
        },
      },
    })
    const warnMock = console.warn as unknown as ReturnType<typeof vi.fn>

    const first = await __probeOpfsAvailabilityForTest()
    const second = await __probeOpfsAvailabilityForTest()

    expect(first).toBe(false)
    expect(second).toBe(false)
    expect(warnMock).toHaveBeenCalledTimes(1)
    expect(String(warnMock.mock.calls[0]?.[0] ?? '')).toMatch(/OPFS 不可用/)
  })
})

describe('localAssetVault 生命周期治理', () => {
  const originalNavigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'navigator')
  const originalIndexedDbDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'indexedDB')

  beforeEach(async () => {
    await __resetLocalAssetVaultStateForTest()
  })

  afterEach(async () => {
    await __resetLocalAssetVaultStateForTest()
    vi.restoreAllMocks()

    if (originalNavigatorDescriptor) {
      Object.defineProperty(globalThis, 'navigator', originalNavigatorDescriptor)
    } else {
      // @ts-expect-error allow cleanup in Node env
      delete globalThis.navigator
    }

    if (originalIndexedDbDescriptor) {
      Object.defineProperty(globalThis, 'indexedDB', originalIndexedDbDescriptor)
    } else {
      // @ts-expect-error allow cleanup in Node env
      delete globalThis.indexedDB
    }
  })

  it('删除本地资产时会同时清理索引记录与 OPFS 文件', async () => {
    const rootDirectory = new FakeDirectoryHandle()
    installFakeIndexedDb()
    installFakeNavigator(rootDirectory)

    const saved = await saveLocalAsset({
      assetUuid: 'asset-1',
      mediaKind: 'image',
      blob: new Blob(['cover'], { type: 'image/png' }),
    })

    expect(saved.storageDriver).toBe('opfs')
    expect(rootDirectory.hasFile(String(saved.storagePath).split('/'))).toBe(true)
    expect(await getLocalAsset('asset-1')).not.toBeNull()

    expect(await deleteLocalAsset('asset-1')).toBe(true)
    expect(await getLocalAsset('asset-1')).toBeNull()
    expect(rootDirectory.hasFile(String(saved.storagePath).split('/'))).toBe(false)
  })

  it('同一 assetUuid 重新保存且路径变化时会清理旧 OPFS 文件', async () => {
    const rootDirectory = new FakeDirectoryHandle()
    installFakeIndexedDb()
    installFakeNavigator(rootDirectory)

    const first = await saveLocalAsset({
      assetUuid: 'asset-2',
      mediaKind: 'image',
      blob: new Blob(['frame-a'], { type: 'image/png' }),
    })
    const second = await saveLocalAsset({
      assetUuid: 'asset-2',
      mediaKind: 'audio',
      blob: new Blob(['frame-b'], { type: 'audio/mpeg' }),
    })

    expect(first.storagePath).not.toBe(second.storagePath)
    expect(rootDirectory.hasFile(String(first.storagePath).split('/'))).toBe(false)
    expect(rootDirectory.hasFile(String(second.storagePath).split('/'))).toBe(true)

    const record = await getLocalAsset('asset-2')
    expect(record?.storagePath).toBe(second.storagePath)
    expect(await record?.blob.text()).toBe('frame-b')
  })

  it('删除 OPFS 文件失败时不会先删除索引记录', async () => {
    const rootDirectory = new FakeDirectoryHandle({ removeEntryErrorMessage: 'PermissionDenied' })
    installFakeIndexedDb()
    installFakeNavigator(rootDirectory)

    const saved = await saveLocalAsset({
      assetUuid: 'asset-3',
      mediaKind: 'image',
      blob: new Blob(['cover'], { type: 'image/png' }),
    })

    await expect(deleteLocalAsset('asset-3')).rejects.toThrow('删除 OPFS 本地资产失败')
    expect(rootDirectory.hasFile(String(saved.storagePath).split('/'))).toBe(true)

    const record = await getLocalAsset('asset-3')
    expect(record).not.toBeNull()
    expect(record?.storagePath).toBe(saved.storagePath)
  })

  it('preferredStorageDriver = external_directory 时优先写入用户目录', async () => {
    const opfsRootDirectory = new FakeDirectoryHandle()
    const externalRootDirectory = new FakeDirectoryHandle()
    installFakeIndexedDb()
    installFakeNavigator(opfsRootDirectory)
    getLocalAssetExternalDirectoryHandleMock.mockResolvedValue(externalRootDirectory)

    const saved = await saveLocalAsset({
      assetUuid: 'asset-external-1',
      mediaKind: 'audio',
      blob: new Blob(['demo-audio'], { type: 'audio/mpeg' }),
      downloadUri: 'https://example.com/demo.mp3',
      preferredStorageDriver: 'external_directory',
    })

    expect(saved.storageDriver).toBe('external_directory')
    expect(saved.persistLevel).toBe('user_directory')
    expect(saved.storagePath).toBe('audio/asset-external-1.mp3')
    expect(saved.externalRelativePath).toBe('audio/asset-external-1.mp3')
    expect(externalRootDirectory.hasFile(['audio', 'asset-external-1.mp3'])).toBe(true)
    expect(opfsRootDirectory.hasFile(['local_asset_vault', 'audio', 'asset-external-1'])).toBe(false)

    const record = await getLocalAsset('asset-external-1')
    expect(record?.storageDriver).toBe('external_directory')
    expect(record?.persistLevel).toBe('user_directory')
    expect(record?.metadata?.local_storage_driver).toBe('external_directory')
    expect(record?.metadata?.local_persist_level).toBe('user_directory')
    expect(record?.metadata?.external_relative_path).toBe('audio/asset-external-1.mp3')
    expect(await record?.blob.text()).toBe('demo-audio')
  })

  it('external_directory 不可用时会回退到 OPFS', async () => {
    const opfsRootDirectory = new FakeDirectoryHandle()
    installFakeIndexedDb()
    installFakeNavigator(opfsRootDirectory)
    getLocalAssetExternalDirectoryHandleMock.mockResolvedValue(null)

    const saved = await saveLocalAsset({
      assetUuid: 'asset-external-fallback',
      mediaKind: 'audio',
      blob: new Blob(['demo-fallback'], { type: 'audio/mpeg' }),
      preferredStorageDriver: 'external_directory',
    })

    expect(saved.storageDriver).toBe('opfs')
    expect(saved.persistLevel).toBe('persistent_requested')
    expect(saved.externalRelativePath).toBeNull()
    expect(opfsRootDirectory.hasFile(['local_asset_vault', 'audio', 'asset-external-fallback'])).toBe(true)
  })

  it('删除 external_directory 文件失败时不会先删除索引记录', async () => {
    const opfsRootDirectory = new FakeDirectoryHandle()
    const externalRootDirectory = new FakeDirectoryHandle({ removeEntryErrorMessage: 'PermissionDenied' })
    installFakeIndexedDb()
    installFakeNavigator(opfsRootDirectory)
    getLocalAssetExternalDirectoryHandleMock.mockResolvedValue(externalRootDirectory)

    const saved = await saveLocalAsset({
      assetUuid: 'asset-external-2',
      mediaKind: 'audio',
      blob: new Blob(['demo-audio'], { type: 'audio/mpeg' }),
      downloadUri: 'https://example.com/demo.mp3',
      preferredStorageDriver: 'external_directory',
    })

    await expect(deleteLocalAsset('asset-external-2')).rejects.toThrow('external_directory')
    expect(externalRootDirectory.hasFile(['audio', 'asset-external-2.mp3'])).toBe(true)

    const record = await getLocalAsset('asset-external-2')
    expect(record).not.toBeNull()
    expect(record?.storageDriver).toBe(saved.storageDriver)
    expect(record?.externalRelativePath).toBe(saved.externalRelativePath)
  })

  it('can list the local asset inventory without loading blob payloads', async () => {
    const opfsRootDirectory = new FakeDirectoryHandle()
    installFakeIndexedDb()
    installFakeNavigator(opfsRootDirectory)

    await saveLocalAsset({
      assetUuid: 'asset-inventory-1',
      mediaKind: 'image',
      blob: new Blob(['cover'], { type: 'image/png' }),
      title: '封面',
      sourceModule: 'asset_studio',
    })
    await saveLocalAsset({
      assetUuid: 'asset-inventory-2',
      mediaKind: 'audio',
      blob: new Blob(['audio'], { type: 'audio/mpeg' }),
      title: '音频',
      sourceModule: 'audiobook',
    })

    const inventory = await listLocalAssetInventory()

    expect(inventory).toHaveLength(2)
    expect(inventory.map((item) => item.assetUuid).sort()).toEqual(['asset-inventory-1', 'asset-inventory-2'])
    expect(inventory.find((item) => item.assetUuid === 'asset-inventory-2')).toMatchObject({
      assetUuid: 'asset-inventory-2',
      mediaKind: 'audio',
      title: '音频',
      sourceModule: 'audiobook',
      storageDriver: 'opfs',
    })
    expect(inventory.every((item) => !('blob' in item))).toBe(true)
  })
})
