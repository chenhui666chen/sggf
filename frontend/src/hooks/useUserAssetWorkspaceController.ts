import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'

import type { UserAssetProjectTitleMap } from '@/contracts/userAssetSourceReaders'
import { getUserAssetMetadataPayload } from '@/contracts/userAssetSourcePayloadSelectors'
import type { UserAssetWorkspaceSectionProps } from '@/components/user-assets/UserAssetWorkspaceSection'
import {
  buildUserAssetBatchErrorFallback,
  buildUserAssetBatchSuccessMessage,
  buildUserAssetEditorSaveErrorFallback,
  buildUserAssetEditorSaveSuccessMessage,
  buildUserAssetLocalCopyBatchClearErrorMessage,
  buildUserAssetLocalCopyBatchClearSuccessMessage,
  buildUserAssetLocalCopyBatchRestoreErrorMessage,
  buildUserAssetLocalCopyBatchRestoreSuccessMessage,
  buildUserAssetLocalCopyClearErrorFallback,
  buildUserAssetLocalCopyClearSuccessMessage,
  buildUserAssetLocalCopyRestoreErrorFallback,
  buildUserAssetLocalCopyRestoreSuccessMessage,
  buildUserAssetUpdateErrorFallback,
  buildUserAssetUpdateSuccessMessage,
} from '@/components/user-assets/userAssetActionFeedbackPresentation'
import {
  buildUserAssetEditorFormData,
  getEmptyUserAssetEditorFormData,
  normalizeUserAssetEditorPayload,
  type UserAssetEditorFormData,
} from '@/components/user-assets/userAssetEditorPresentation'
import {
  buildActivateBatchUserAssetCommand,
  buildArchiveBatchUserAssetCommand,
  buildClearLocalCopyBatchUserAssetCommand,
  buildFavoriteBatchUserAssetCommand,
  buildRestoreLocalCopyBatchUserAssetCommand,
  buildUserAssetKindOptionsFromValues,
  buildUserAssetListSelectionState,
  buildUserAssetSourceOptionsFromSourceModules,
  buildUserAssetTagOptionsFromValues,
  getUserAssetActionKey,
  pruneUserAssetSelection,
  toggleSelectAllUserAssets,
  toggleUserAssetSelection,
  type UserAssetBatchActionCommand,
  type UserAssetListArchiveFilter,
  type UserAssetListFilters,
  type UserAssetListSelectionState,
  type UserAssetListViewFilter,
} from '@/components/user-assets/userAssetListPresentation'
import {
  buildUserAssetListFeedbackCopy,
  buildUserAssetOverviewMetricSpecs,
} from '@/components/user-assets/userAssetOverviewPresentation'
import {
  buildUserAssetLocalDiagnosticsNotices,
  type UserAssetExternalDirectoryAssetHealthItem,
  type UserAssetExternalDirectoryAssetHealthSummary,
  type UserAssetListStatusNotice,
} from '@/components/user-assets/userAssetLocalDiagnosticsPresentation'
import {
  apiClient,
  extractApiErrorMessage,
  type UserAssetListFilterOptions,
  type UserAssetListResponse,
  type UserAssetListSummary,
  type UserAssetRecord,
  type UserAssetRecordUpdatePayload,
} from '@/services/api'
import {
  LEGACY_LOCAL_ASSET_MIGRATION_STATUS_UPDATED_EVENT,
  type LegacyLocalAssetMigrationStatus,
  readLegacyLocalAssetMigrationStatus,
} from '@/utils/localAssetMigration'
import {
  clearLocalAssetExternalDirectoryHandle,
  getLocalAssetExternalDirectoryStatus,
  isLocalAssetExternalDirectorySupported,
  pickLocalAssetExternalDirectory,
  requestLocalAssetExternalDirectoryAccess,
  type LocalAssetExternalDirectoryStatus,
} from '@/utils/localAssetExternalDirectory'
import { downloadTextFile } from '@/utils/fileDownload'
import { getLocalAssetBlob, listLocalAssetInventory } from '@/utils/localAssetVault'
import {
  buildUserAssetLocalStorageActionReport,
  buildUserAssetLocalStorageInventoryExport,
  buildUserAssetLocalStorageInventoryFilename,
  countUserAssetLocalStorageRebuildCandidates,
  buildUserAssetLocalStorageRebuildListExport,
  buildUserAssetLocalStorageRebuildListFilename,
  type UserAssetLocalStorageActionIssueItem,
  type UserAssetLocalStorageActionReport,
} from '@/components/user-assets/userAssetLocalStoragePanelPresentation'

import {
  executeUserAssetLocalClearAction,
  executeUserAssetLocalClearBatch,
  executeUserAssetLocalRestoreAction,
  executeUserAssetLocalRestoreBatch,
  type UserAssetLocalRestoreActionResult,
} from './userAssetWorkspaceLocalActions'

export type UserAssetWorkspaceFeedback = {
  type: 'success' | 'error'
  text: string
}

type UseUserAssetWorkspaceControllerOptions = {
  projectTitleMap?: UserAssetProjectTitleMap
  publishFeedback?: (feedback: UserAssetWorkspaceFeedback) => void
  enabled?: boolean
}

export type UserAssetWorkspaceController = {
  userAssets: UserAssetRecord[]
  userAssetTotal: number
  filteredUserAssets: UserAssetRecord[]
  assetActionKey: string | null
  assetBatchSubmitting: boolean
  assetSelectionState: UserAssetListSelectionState
  loadUserAssets: (silent?: boolean) => Promise<void>
  handleToggleAssetSelection: (assetId: number) => void
  handleOpenAssetEditor: (asset: UserAssetRecord) => void
  handleRestoreLocalAssetCopy: (asset: UserAssetRecord) => Promise<void>
  handleClearLocalAssetCopy: (asset: Pick<UserAssetRecord, 'id' | 'asset_uuid' | 'storage_mode'>) => Promise<void>
  handleUpdateUserAsset: (
    assetId: number,
    payload: UserAssetRecordUpdatePayload,
    successText?: string,
  ) => Promise<void>
  workspaceSectionProps: Omit<UserAssetWorkspaceSectionProps, 'children'>
}

function buildEmptyExternalDirectoryStatus(): LocalAssetExternalDirectoryStatus {
  return {
    supported: isLocalAssetExternalDirectorySupported(),
    configured: false,
    directoryName: null,
    permission: 'unknown',
  }
}

function readUserAssetLocalStorageActionMetricValue(
  report: UserAssetLocalStorageActionReport,
  key: string,
): number {
  return Math.max(0, report.metrics.find((metric) => metric.key === key)?.value || 0)
}

function removeAssetFromExternalDirectoryHealthSummary(
  summary: UserAssetExternalDirectoryAssetHealthSummary | null,
  assetId: number,
): UserAssetExternalDirectoryAssetHealthSummary | null {
  if (!summary) {
    return null
  }

  const inaccessibleAssets = (summary.inaccessibleAssets || []).filter((asset) => asset.assetId !== assetId)
  const missingLocalCopyAssets = (summary.missingLocalCopyAssets || []).filter((asset) => asset.assetId !== assetId)
  const inaccessibleAssetCount = inaccessibleAssets.length
  const missingLocalCopyCount = missingLocalCopyAssets.length

  if (inaccessibleAssetCount <= 0 && missingLocalCopyCount <= 0) {
    return null
  }

  return {
    trackedAssetCount: Math.max(0, summary.trackedAssetCount),
    inaccessibleAssetCount,
    missingLocalCopyCount,
    inaccessibleAssets,
    missingLocalCopyAssets,
  }
}

function buildUpdatedUserAssetLocalStorageIssueActionReport(options: {
  report: UserAssetLocalStorageActionReport
  issueItem: UserAssetLocalStorageActionIssueItem
  result: UserAssetLocalRestoreActionResult
}): UserAssetLocalStorageActionReport {
  const {
    report,
    issueItem,
    result,
  } = options
  const nextIssueItems =
    result.status === 'restored' || result.status === 'already_present'
      ? report.issueItems.filter((item) => item.key !== issueItem.key)
      : report.issueItems
  const nextReport = buildUserAssetLocalStorageActionReport({
    mode: report.mode,
    scope: report.scope,
    scannedAssetCount: readUserAssetLocalStorageActionMetricValue(report, 'scanned-assets'),
    trackedAssetCount: readUserAssetLocalStorageActionMetricValue(report, 'tracked-assets'),
    missingLocalCopyCount: nextIssueItems.filter((item) => item.issueType === 'missing_local_copy').length,
    inaccessibleAssetCount: nextIssueItems.filter((item) => item.issueType === 'directory_inaccessible').length,
    restoredCount:
      readUserAssetLocalStorageActionMetricValue(report, 'restored-assets')
      + (result.status === 'restored' ? 1 : 0),
    existingCount:
      readUserAssetLocalStorageActionMetricValue(report, 'existing-assets')
      + (result.status === 'already_present' ? 1 : 0),
    blockedCount: readUserAssetLocalStorageActionMetricValue(report, 'blocked-assets'),
    failedCount: readUserAssetLocalStorageActionMetricValue(report, 'failed-assets'),
    completedAt: new Date(),
  })

  return {
    ...nextReport,
    issueItems: nextIssueItems,
  }
}

function extractLocalDirectoryErrorMessage(error: unknown, fallbackMessage: string): string {
  if (error instanceof Error && error.message) {
    return error.message
  }
  return fallbackMessage
}

const USER_ASSET_LIST_PAGE_SIZE = 24

function buildEmptyUserAssetListSummary(): UserAssetListSummary {
  return {
    total_assets: 0,
    active_asset_count: 0,
    archived_asset_count: 0,
    favorite_asset_count: 0,
    reusable_asset_count: 0,
    deliverable_asset_count: 0,
  }
}

function buildEmptyUserAssetListFilterOptions(): UserAssetListFilterOptions {
  return {
    asset_kinds: [],
    source_modules: [],
    tags: [],
  }
}

export function buildUserAssetListRequestParams(options: {
  filters: UserAssetListFilters
  page: number
  pageSize: number
}): {
  asset_kind?: string
  asset_class?: string
  source_module?: string
  tag?: string
  favorites_only?: boolean
  archive_filter: UserAssetListArchiveFilter
  page: number
  page_size: number
} {
  const {
    filters,
    page,
    pageSize,
  } = options

  const params: {
    asset_kind?: string
    asset_class?: string
    source_module?: string
    tag?: string
    favorites_only?: boolean
    archive_filter: UserAssetListArchiveFilter
    page: number
    page_size: number
  } = {
    archive_filter: filters.archiveFilter,
    page: Math.max(1, Number(page) || 1),
    page_size: Math.max(1, Number(pageSize) || USER_ASSET_LIST_PAGE_SIZE),
  }

  if (filters.kindFilter !== 'all') {
    params.asset_kind = filters.kindFilter
  }
  if (filters.sourceFilter !== 'all') {
    params.source_module = filters.sourceFilter
  }
  if (filters.tagFilter !== 'all') {
    params.tag = filters.tagFilter
  }
  if (filters.viewFilter === 'favorites') {
    params.favorites_only = true
  }
  if (filters.viewFilter === 'deliverable') {
    params.asset_class = 'deliverable'
  }
  if (filters.viewFilter === 'reusable') {
    params.asset_class = 'reusable'
  }

  return params
}

type ListUserAssetsForWorkspaceDependency = (
  params?: ReturnType<typeof buildUserAssetListRequestParams> & {
    limit?: number
  },
) => Promise<{ data: UserAssetListResponse }>

type GetLocalAssetBlobDependency = (assetUuid: string) => Promise<Blob | null | undefined>

function isExternalDirectoryBackedLocalMirrorAsset(
  asset: Pick<UserAssetRecord, 'asset_uuid' | 'storage_mode' | 'metadata_json'>,
): boolean {
  if (asset.storage_mode !== 'local_mirror') {
    return false
  }

  const assetUuid = String(asset.asset_uuid || '').trim()
  if (!assetUuid) {
    return false
  }

  return getUserAssetMetadataPayload(asset).local_storage_driver === 'external_directory'
}

function buildExternalDirectoryAssetHealthItem(
  asset: Pick<
    UserAssetRecord,
    'id' | 'asset_uuid' | 'title' | 'source_module' | 'metadata_json' | 'source_uri' | 'preview_uri' | 'download_uri'
  >,
): UserAssetExternalDirectoryAssetHealthItem {
  const metadata = getUserAssetMetadataPayload(asset)

  return {
    assetId: asset.id,
    assetUuid: String(asset.asset_uuid || '').trim(),
    title: String(asset.title || '').trim() || `资产 #${asset.id}`,
    sourceModule: String(asset.source_module || '').trim() || 'unknown',
    localStorageDriver: metadata.local_storage_driver ?? null,
    localStoragePath: metadata.local_storage_path ?? null,
    externalRelativePath: metadata.external_relative_path ?? null,
    sourceUri: asset.source_uri ?? null,
    previewUri: asset.preview_uri ?? null,
    downloadUri: asset.download_uri ?? null,
  }
}

export function resolveExternalDirectoryMissingLocalCopyAssets(
  assets: UserAssetRecord[],
  summary: UserAssetExternalDirectoryAssetHealthSummary | null | undefined,
): UserAssetRecord[] {
  const missingLocalCopyAssetIdSet = new Set(
    (summary?.missingLocalCopyAssets || []).map((asset) => asset.assetId),
  )

  if (!missingLocalCopyAssetIdSet.size) {
    return []
  }

  return assets.filter((asset) => missingLocalCopyAssetIdSet.has(asset.id))
}

export async function loadAllUserAssetsForWorkspaceRequestParams(options: {
  requestParams: ReturnType<typeof buildUserAssetListRequestParams>
  listUserAssets?: ListUserAssetsForWorkspaceDependency
  pageSize?: number
}): Promise<UserAssetRecord[]> {
  const {
    requestParams,
    listUserAssets = apiClient.listUserAssets.bind(apiClient) as ListUserAssetsForWorkspaceDependency,
    pageSize = 200,
  } = options

  const resolvedPageSize = Math.min(Math.max(1, Number(pageSize) || 200), 200)
  const assetsById = new Map<number, UserAssetRecord>()
  const orderedIds: number[] = []

  let page = 1
  let totalPages = 1

  do {
    const response = await listUserAssets({
      ...requestParams,
      page,
      page_size: resolvedPageSize,
      limit: resolvedPageSize,
    })
    const payload = response.data
    totalPages = Math.max(0, Number(payload?.total_pages) || 0)
    const items = Array.isArray(payload?.items) ? payload.items : []

    items.forEach((asset) => {
      if (!assetsById.has(asset.id)) {
        orderedIds.push(asset.id)
      }
      assetsById.set(asset.id, asset)
    })

    page += 1
  } while (page <= totalPages)

  return orderedIds
    .map((assetId) => assetsById.get(assetId))
    .filter((asset): asset is UserAssetRecord => Boolean(asset))
}

export async function probeUserAssetExternalDirectoryAssetHealthSummary(
  assets: UserAssetRecord[],
  externalDirectoryStatus: LocalAssetExternalDirectoryStatus | null,
  dependencies: {
    getLocalAssetBlobByUuid?: GetLocalAssetBlobDependency
  } = {},
): Promise<UserAssetExternalDirectoryAssetHealthSummary | null> {
  const trackedAssets = assets.filter(isExternalDirectoryBackedLocalMirrorAsset)
  if (!trackedAssets.length || externalDirectoryStatus === null) {
    return null
  }

  if (
    !externalDirectoryStatus.supported
    || !externalDirectoryStatus.configured
    || externalDirectoryStatus.permission !== 'granted'
  ) {
    return {
      trackedAssetCount: trackedAssets.length,
      inaccessibleAssetCount: trackedAssets.length,
      missingLocalCopyCount: 0,
      inaccessibleAssets: trackedAssets.map((asset) => buildExternalDirectoryAssetHealthItem(asset)),
      missingLocalCopyAssets: [],
    }
  }

  const getLocalAssetBlobByUuid = dependencies.getLocalAssetBlobByUuid ?? getLocalAssetBlob
  const results = await Promise.all(
    trackedAssets.map(async (asset) => {
      try {
        return {
          asset,
          exists: Boolean(await getLocalAssetBlobByUuid(String(asset.asset_uuid || '').trim())),
        }
      } catch {
        return {
          asset,
          exists: false,
        }
      }
    }),
  )

  const missingLocalCopyAssets = results
    .filter((result) => !result.exists)
    .map((result) => buildExternalDirectoryAssetHealthItem(result.asset))
  const missingLocalCopyCount = missingLocalCopyAssets.length

  return missingLocalCopyCount > 0
    ? {
        trackedAssetCount: trackedAssets.length,
        inaccessibleAssetCount: 0,
        missingLocalCopyCount,
        inaccessibleAssets: [],
        missingLocalCopyAssets,
      }
    : null
}

export function resolveUserAssetWorkspaceAssetListLoadingState(options: {
  enabled: boolean
  assetListLoading: boolean
  hasLoadedUserAssetsOnce: boolean
}): boolean {
  const { enabled, assetListLoading, hasLoadedUserAssetsOnce } = options
  if (!enabled) {
    return false
  }
  if (!hasLoadedUserAssetsOnce) {
    return true
  }
  return assetListLoading
}

export function useUserAssetWorkspaceController(
  options: UseUserAssetWorkspaceControllerOptions = {},
): UserAssetWorkspaceController {
  const {
    projectTitleMap,
    publishFeedback,
    enabled = true,
  } = options

  const [assetListError, setAssetListError] = useState<string | null>(null)
  const [assetListLoading, setAssetListLoading] = useState(false)
  const [hasLoadedUserAssetsOnce, setHasLoadedUserAssetsOnce] = useState(false)
  const [userAssets, setUserAssets] = useState<UserAssetRecord[]>([])
  const [userAssetTotal, setUserAssetTotal] = useState(0)
  const [userAssetPage, setUserAssetPage] = useState(1)
  const [userAssetTotalPages, setUserAssetTotalPages] = useState(0)
  const [userAssetSummary, setUserAssetSummary] = useState<UserAssetListSummary>(() => buildEmptyUserAssetListSummary())
  const [userAssetFilterOptions, setUserAssetFilterOptions] = useState<UserAssetListFilterOptions>(
    () => buildEmptyUserAssetListFilterOptions(),
  )
  const [assetActionKey, setAssetActionKey] = useState<string | null>(null)
  const [assetBatchSubmitting, setAssetBatchSubmitting] = useState(false)
  const [assetViewFilter, setAssetViewFilter] = useState<UserAssetListViewFilter>('all')
  const [assetKindFilter, setAssetKindFilter] = useState<string>('all')
  const [assetArchiveFilter, setAssetArchiveFilter] = useState<UserAssetListArchiveFilter>('active')
  const [assetSourceFilter, setAssetSourceFilter] = useState<string>('all')
  const [assetTagFilter, setAssetTagFilter] = useState<string>('all')
  const [assetEditorOpen, setAssetEditorOpen] = useState(false)
  const [editingAsset, setEditingAsset] = useState<UserAssetRecord | null>(null)
  const [assetEditorSubmitting, setAssetEditorSubmitting] = useState(false)
  const [selectedAssetIds, setSelectedAssetIds] = useState<number[]>([])
  const [assetEditorData, setAssetEditorData] = useState<UserAssetEditorFormData>(getEmptyUserAssetEditorFormData())
  const [legacyLocalAssetMigrationStatus, setLegacyLocalAssetMigrationStatus] = useState<LegacyLocalAssetMigrationStatus | null>(
    () => readLegacyLocalAssetMigrationStatus(),
  )
  const [externalDirectoryStatus, setExternalDirectoryStatus] = useState<LocalAssetExternalDirectoryStatus | null>(null)
  const [externalDirectoryAssetHealthSummary, setExternalDirectoryAssetHealthSummary] =
    useState<UserAssetExternalDirectoryAssetHealthSummary | null>(null)
  const [externalDirectoryLoading, setExternalDirectoryLoading] = useState(true)
  const [externalDirectorySubmitting, setExternalDirectorySubmitting] = useState(false)
  const [externalDirectorySubmittingLabel, setExternalDirectorySubmittingLabel] = useState<string | null>(null)
  const [lastLocalStorageActionReport, setLastLocalStorageActionReport] =
    useState<UserAssetLocalStorageActionReport | null>(null)
  const assetListRequestParams = useMemo(
    () => buildUserAssetListRequestParams({
      filters: {
        viewFilter: assetViewFilter,
        kindFilter: assetKindFilter,
        archiveFilter: assetArchiveFilter,
        sourceFilter: assetSourceFilter,
        tagFilter: assetTagFilter,
      },
      page: userAssetPage,
      pageSize: USER_ASSET_LIST_PAGE_SIZE,
    }),
    [assetArchiveFilter, assetKindFilter, assetSourceFilter, assetTagFilter, assetViewFilter, userAssetPage],
  )

  const loadUserAssets = useCallback(async (silent = false) => {
    if (!enabled) {
      return
    }
    if (!silent) setAssetListLoading(true)
    try {
      const response = await apiClient.listUserAssets(assetListRequestParams)
      const payload = response.data
      setUserAssets(Array.isArray(payload?.items) ? payload.items : [])
      setUserAssetTotal(Math.max(0, Number(payload?.total) || 0))
      setUserAssetTotalPages(Math.max(0, Number(payload?.total_pages) || 0))
      setUserAssetPage(Math.max(1, Number(payload?.page) || 1))
      setUserAssetSummary(payload?.summary || buildEmptyUserAssetListSummary())
      setUserAssetFilterOptions(payload?.filter_options || buildEmptyUserAssetListFilterOptions())
      setAssetListError(null)
    } catch (loadError) {
      setAssetListError(await extractApiErrorMessage(loadError, '加载用户资产失败'))
    } finally {
      setHasLoadedUserAssetsOnce(true)
      if (!silent) setAssetListLoading(false)
    }
  }, [assetListRequestParams, enabled])

  const loadExternalDirectoryStatus = useCallback(async (options?: { silent?: boolean }) => {
    if (!enabled) {
      return
    }
    setExternalDirectoryLoading(true)
    try {
      setExternalDirectoryStatus(await getLocalAssetExternalDirectoryStatus())
    } catch (error) {
      setExternalDirectoryStatus(buildEmptyExternalDirectoryStatus())
      if (!options?.silent) {
        publishFeedback?.({
          type: 'error',
          text: extractLocalDirectoryErrorMessage(error, '读取用户目录状态失败'),
        })
      }
    } finally {
      setExternalDirectoryLoading(false)
    }
  }, [enabled, publishFeedback])

  useEffect(() => {
    if (!enabled) {
      return undefined
    }
    void loadUserAssets()
    return undefined
  }, [enabled, loadUserAssets])

  useEffect(() => {
    if (!enabled) {
      return undefined
    }
    void loadExternalDirectoryStatus({ silent: true })
    return undefined
  }, [enabled, loadExternalDirectoryStatus])

  useEffect(() => {
    const syncLocalDiagnosticsNotice = () => {
      setLegacyLocalAssetMigrationStatus(readLegacyLocalAssetMigrationStatus())
    }

    syncLocalDiagnosticsNotice()

    if (typeof window === 'undefined') {
      return undefined
    }

    window.addEventListener(LEGACY_LOCAL_ASSET_MIGRATION_STATUS_UPDATED_EVENT, syncLocalDiagnosticsNotice)
    return () => {
      window.removeEventListener(LEGACY_LOCAL_ASSET_MIGRATION_STATUS_UPDATED_EVENT, syncLocalDiagnosticsNotice)
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      return undefined
    }
    let cancelled = false

    if (externalDirectoryLoading || externalDirectoryStatus === null) {
      return undefined
    }

    const probeExternalDirectoryAssets = async () => {
      const summary = await probeUserAssetExternalDirectoryAssetHealthSummary(userAssets, externalDirectoryStatus)
      if (cancelled) {
        return
      }
      setExternalDirectoryAssetHealthSummary(summary)
    }

    void probeExternalDirectoryAssets()

    return () => {
      cancelled = true
    }
  }, [enabled, externalDirectoryLoading, externalDirectoryStatus, userAssets])

  const assetKindOptions = useMemo(
    () => buildUserAssetKindOptionsFromValues(userAssetFilterOptions.asset_kinds || []),
    [userAssetFilterOptions.asset_kinds],
  )
  const assetTagOptions = useMemo(
    () => buildUserAssetTagOptionsFromValues(userAssetFilterOptions.tags || []),
    [userAssetFilterOptions.tags],
  )
  const assetSourceOptions = useMemo(
    () => buildUserAssetSourceOptionsFromSourceModules(userAssetFilterOptions.source_modules || []),
    [userAssetFilterOptions.source_modules],
  )
  const assetFilters = useMemo<UserAssetListFilters>(
    () => ({
      viewFilter: assetViewFilter,
      kindFilter: assetKindFilter,
      archiveFilter: assetArchiveFilter,
      sourceFilter: assetSourceFilter,
      tagFilter: assetTagFilter,
    }),
    [assetArchiveFilter, assetKindFilter, assetSourceFilter, assetTagFilter, assetViewFilter],
  )
  const filteredUserAssets = useMemo(() => userAssets, [userAssets])
  const favoriteBatchCommand = buildFavoriteBatchUserAssetCommand()
  const archiveBatchCommand = buildArchiveBatchUserAssetCommand()
  const activateBatchCommand = buildActivateBatchUserAssetCommand()
  const clearLocalCopyBatchCommand = buildClearLocalCopyBatchUserAssetCommand()
  const restoreLocalCopyBatchCommand = buildRestoreLocalCopyBatchUserAssetCommand()
  const assetOverviewMetrics = useMemo(
    () =>
      buildUserAssetOverviewMetricSpecs({
        activeAssetCount: userAssetSummary.active_asset_count,
        reusableAssetCount: userAssetSummary.reusable_asset_count,
        deliverableAssetCount: userAssetSummary.deliverable_asset_count,
        favoriteAssetCount: userAssetSummary.favorite_asset_count,
        archivedAssetCount: userAssetSummary.archived_asset_count,
      }),
    [
      userAssetSummary.active_asset_count,
      userAssetSummary.archived_asset_count,
      userAssetSummary.deliverable_asset_count,
      userAssetSummary.favorite_asset_count,
      userAssetSummary.reusable_asset_count,
    ],
  )
  const assetListFeedbackCopy = buildUserAssetListFeedbackCopy()
  const handleAssetViewFilterChange = useCallback((value: UserAssetListViewFilter) => {
    setAssetViewFilter(value)
    setUserAssetPage(1)
  }, [])
  const handleAssetKindFilterChange = useCallback((value: string) => {
    setAssetKindFilter(value)
    setUserAssetPage(1)
  }, [])
  const handleAssetSourceFilterChange = useCallback((value: string) => {
    setAssetSourceFilter(value)
    setUserAssetPage(1)
  }, [])
  const handleAssetArchiveFilterChange = useCallback((value: UserAssetListArchiveFilter) => {
    setAssetArchiveFilter(value)
    setUserAssetPage(1)
  }, [])
  const handleAssetTagFilterChange = useCallback((value: string) => {
    setAssetTagFilter(value)
    setUserAssetPage(1)
  }, [])
  const handleAssetPageChange = useCallback((value: number) => {
    setUserAssetPage(Math.max(1, value))
  }, [])
  const assetSelectionState = useMemo(
    () => buildUserAssetListSelectionState(filteredUserAssets, selectedAssetIds),
    [filteredUserAssets, selectedAssetIds],
  )
  const batchActionCommands = useMemo(
    () => [
      favoriteBatchCommand,
      archiveBatchCommand,
      activateBatchCommand,
      restoreLocalCopyBatchCommand,
      clearLocalCopyBatchCommand,
    ],
    [
      activateBatchCommand,
      archiveBatchCommand,
      clearLocalCopyBatchCommand,
      favoriteBatchCommand,
      restoreLocalCopyBatchCommand,
    ],
  )
  const localDiagnosticsNotices = useMemo<UserAssetListStatusNotice[]>(
    () => buildUserAssetLocalDiagnosticsNotices({
      migrationStatus: legacyLocalAssetMigrationStatus,
      externalDirectoryStatus,
      externalDirectoryAssetHealthSummary,
    }),
    [externalDirectoryAssetHealthSummary, externalDirectoryStatus, legacyLocalAssetMigrationStatus],
  )
  const resolvedAssetListLoading = resolveUserAssetWorkspaceAssetListLoadingState({
    enabled,
    assetListLoading,
    hasLoadedUserAssetsOnce,
  })

  useEffect(() => {
    setSelectedAssetIds((prev) => {
      const next = pruneUserAssetSelection(prev, filteredUserAssets)
      return next.length === prev.length ? prev : next
    })
  }, [filteredUserAssets])

  const handleUpdateUserAsset = useCallback(async (
    assetId: number,
    payload: UserAssetRecordUpdatePayload,
    successText = '资产信息已更新',
  ) => {
    setAssetActionKey(getUserAssetActionKey(assetId))
    try {
      await apiClient.updateUserAsset(assetId, payload)
      await loadUserAssets(true)
      publishFeedback?.({
        type: 'success',
        text: buildUserAssetUpdateSuccessMessage(successText),
      })
    } catch (updateError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(updateError, buildUserAssetUpdateErrorFallback()),
      })
    } finally {
      setAssetActionKey(null)
    }
  }, [loadUserAssets, publishFeedback])

  const handleToggleAssetSelection = useCallback((assetId: number) => {
    setSelectedAssetIds((prev) => toggleUserAssetSelection(prev, assetId))
  }, [])

  const handleToggleSelectAllFilteredAssets = useCallback(() => {
    setSelectedAssetIds(
      toggleSelectAllUserAssets(filteredUserAssets, assetSelectionState.allVisibleSelected),
    )
  }, [assetSelectionState.allVisibleSelected, filteredUserAssets])

  const handleClearSelectedAssets = useCallback(() => {
    setSelectedAssetIds([])
  }, [])

  const handleRefreshExternalDirectoryStatus = useCallback(() => {
    void loadExternalDirectoryStatus()
  }, [loadExternalDirectoryStatus])

  const runUserAssetLocalRestoreBatch = useCallback(async (
    assets: UserAssetRecord[],
    options?: {
      emptyFeedbackText?: string | null
      skipFeedback?: boolean
    },
  ) => {
    const summary = await executeUserAssetLocalRestoreBatch(assets)
    if (summary.targetAssetCount === 0) {
      if (!options?.skipFeedback && options?.emptyFeedbackText) {
        publishFeedback?.({
          type: 'success',
          text: options.emptyFeedbackText,
        })
      }
      return summary
    }

    await loadUserAssets(true)
    if (summary.handledIds.length > 0) {
      setSelectedAssetIds((prev) => prev.filter((assetId) => !summary.handledIds.includes(assetId)))
    }

    if (options?.skipFeedback) {
      return summary
    }

    if (summary.blockedCount > 0 || summary.failedCount > 0) {
      publishFeedback?.({
        type: 'error',
        text: buildUserAssetLocalCopyBatchRestoreErrorMessage(summary),
      })
      return summary
    }

    publishFeedback?.({
      type: 'success',
      text: buildUserAssetLocalCopyBatchRestoreSuccessMessage(summary),
    })
    return summary
  }, [loadUserAssets, publishFeedback])

  const updateLastLocalStorageActionReport = useCallback((report: UserAssetLocalStorageActionReport) => {
    setLastLocalStorageActionReport(report)
  }, [])

  const scanFilteredExternalDirectoryAssets = useCallback(async () => {
    const resolvedStatus = externalDirectoryStatus ?? await getLocalAssetExternalDirectoryStatus()
    if (externalDirectoryStatus === null) {
      setExternalDirectoryStatus(resolvedStatus)
    }

    const allFilteredAssets = await loadAllUserAssetsForWorkspaceRequestParams({
      requestParams: assetListRequestParams,
    })
    const healthSummary = await probeUserAssetExternalDirectoryAssetHealthSummary(
      allFilteredAssets,
      resolvedStatus,
    )
    const inaccessibleAssetCount = Math.max(0, healthSummary?.inaccessibleAssetCount || 0)
    const missingAssets = resolveExternalDirectoryMissingLocalCopyAssets(allFilteredAssets, healthSummary)

    return {
      resolvedStatus,
      allFilteredAssets,
      healthSummary,
      inaccessibleAssetCount,
      missingAssets,
    }
  }, [assetListRequestParams, externalDirectoryStatus])

  const handleExportLocalAssetInventory = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      const generatedAt = new Date()
      const inventory = await listLocalAssetInventory()
      downloadTextFile({
        content: buildUserAssetLocalStorageInventoryExport({
          status: externalDirectoryStatus,
          loading: externalDirectoryLoading,
          inventory,
          generatedAt,
        }),
        filename: buildUserAssetLocalStorageInventoryFilename(generatedAt),
        mimeType: 'application/json',
      })
      publishFeedback?.({
        type: 'success',
        text: `已导出本地资产清单，共 ${inventory.length} 条记录。`,
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, '导出本地资产清单失败'),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [externalDirectoryLoading, externalDirectoryStatus, publishFeedback])

  const handleExportLocalAssetRebuildList = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      const issueCount = countUserAssetLocalStorageRebuildCandidates(externalDirectoryAssetHealthSummary)

      if (issueCount <= 0) {
        publishFeedback?.({
          type: 'success',
          text: '当前列表没有需要导出的重建项。',
        })
        return
      }

      const generatedAt = new Date()
      downloadTextFile({
        content: buildUserAssetLocalStorageRebuildListExport({
          status: externalDirectoryStatus,
          loading: externalDirectoryLoading,
          healthSummary: externalDirectoryAssetHealthSummary,
          generatedAt,
        }),
        filename: buildUserAssetLocalStorageRebuildListFilename(generatedAt),
        mimeType: 'application/json',
      })
      publishFeedback?.({
        type: 'success',
        text: `已导出重建清单，共 ${issueCount} 项待处理记录。`,
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, '导出重建清单失败'),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [
    externalDirectoryAssetHealthSummary,
    externalDirectoryLoading,
    externalDirectoryStatus,
    publishFeedback,
  ])

  const handleRestoreMissingLocalCopies = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel('正在重建当前页缺失副本...')
    try {
      const missingAssets = resolveExternalDirectoryMissingLocalCopyAssets(filteredUserAssets, externalDirectoryAssetHealthSummary)
      const summary = await runUserAssetLocalRestoreBatch(
        missingAssets,
        {
          emptyFeedbackText: '当前页没有可直接重建的缺失副本。',
          skipFeedback: true,
        },
      )
      const report = buildUserAssetLocalStorageActionReport({
        mode: 'restore',
        scope: 'current_page',
        scannedAssetCount: filteredUserAssets.length,
        trackedAssetCount: Math.max(0, externalDirectoryAssetHealthSummary?.trackedAssetCount || 0),
        missingLocalCopyCount: missingAssets.length,
        inaccessibleAssetCount: Math.max(0, externalDirectoryAssetHealthSummary?.inaccessibleAssetCount || 0),
        restoredCount: summary.restoredCount,
        existingCount: summary.existingCount,
        blockedCount: summary.blockedCount,
        failedCount: summary.failedCount,
        healthSummary: externalDirectoryAssetHealthSummary,
        issueAssets: filteredUserAssets,
        projectTitleMap,
        completedAt: new Date(),
      })
      updateLastLocalStorageActionReport(report)
      if (summary.targetAssetCount <= 0) {
        publishFeedback?.({
          type: 'success',
          text: '当前页没有可直接重建的缺失副本。',
        })
        return
      }

      const feedbackText = summary.blockedCount > 0 || summary.failedCount > 0
        ? buildUserAssetLocalCopyBatchRestoreErrorMessage(summary)
        : buildUserAssetLocalCopyBatchRestoreSuccessMessage(summary)
      publishFeedback?.({
        type: summary.blockedCount > 0 || summary.failedCount > 0 ? 'error' : 'success',
        text: feedbackText,
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, '重建当前页缺失副本失败'),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [
    externalDirectoryAssetHealthSummary,
    filteredUserAssets,
    projectTitleMap,
    publishFeedback,
    runUserAssetLocalRestoreBatch,
    updateLastLocalStorageActionReport,
  ])

  const handleRestoreLocalStorageIssueItem = useCallback(async (item: UserAssetLocalStorageActionIssueItem) => {
    if (item.issueType !== 'missing_local_copy' || !item.restorableAsset) {
      publishFeedback?.({
        type: 'error',
        text: '当前明细项暂不支持直接重新收录到本地。',
      })
      return
    }

    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(`正在重新收录“${item.title}”到本地...`)
    try {
      const result = await executeUserAssetLocalRestoreAction(item.restorableAsset)
      if (result.status === 'skipped') {
        publishFeedback?.({
          type: 'error',
          text: '当前资产不支持重新收录到本地。',
        })
        return
      }

      if (result.status === 'restored' || result.status === 'already_present') {
        await loadUserAssets(true)
        setExternalDirectoryAssetHealthSummary((prev) => removeAssetFromExternalDirectoryHealthSummary(prev, item.assetId))
      }

      setLastLocalStorageActionReport((prev) => {
        if (!prev || !prev.issueItems.some((issue) => issue.key === item.key)) {
          return prev
        }
        return buildUpdatedUserAssetLocalStorageIssueActionReport({
          report: prev,
          issueItem: item,
          result,
        })
      })

      if (result.status === 'blocked') {
        publishFeedback?.({
          type: 'error',
          text: result.message || buildUserAssetLocalCopyRestoreErrorFallback(),
        })
        return
      }

      publishFeedback?.({
        type: 'success',
        text: buildUserAssetLocalCopyRestoreSuccessMessage(result.status === 'restored'),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(error, buildUserAssetLocalCopyRestoreErrorFallback()),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [loadUserAssets, publishFeedback])

  const handlePreviewFilteredMissingLocalCopies = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel('正在扫描当前筛选并校验目录副本...')
    try {
      const {
        allFilteredAssets,
        healthSummary,
        inaccessibleAssetCount,
        missingAssets,
      } = await scanFilteredExternalDirectoryAssets()

      updateLastLocalStorageActionReport(buildUserAssetLocalStorageActionReport({
        mode: 'preview',
        scope: 'filtered_scope',
        scannedAssetCount: allFilteredAssets.length,
        trackedAssetCount: Math.max(0, healthSummary?.trackedAssetCount || 0),
        missingLocalCopyCount: missingAssets.length,
        inaccessibleAssetCount,
        restoredCount: 0,
        existingCount: 0,
        blockedCount: 0,
        failedCount: 0,
        healthSummary,
        issueAssets: allFilteredAssets,
        projectTitleMap,
        completedAt: new Date(),
      }))

      if (!allFilteredAssets.length) {
        publishFeedback?.({
          type: 'success',
          text: '当前筛选内没有可扫描的资产。',
        })
        return
      }

      if (!healthSummary || healthSummary.trackedAssetCount <= 0) {
        publishFeedback?.({
          type: 'success',
          text: '已完成当前筛选扫描，未发现登记为用户目录副本的资产。',
        })
        return
      }

      if (!missingAssets.length && inaccessibleAssetCount <= 0) {
        publishFeedback?.({
          type: 'success',
          text: '已完成当前筛选扫描，当前没有需要重建的缺失副本。',
        })
        return
      }

      publishFeedback?.({
        type: inaccessibleAssetCount > 0 ? 'error' : 'success',
        text: inaccessibleAssetCount > 0
          ? `已完成当前筛选扫描：发现 ${missingAssets.length} 项缺失副本可重建，另有 ${inaccessibleAssetCount} 项因目录不可访问暂时无法处理。`
          : `已完成当前筛选扫描：发现 ${missingAssets.length} 项缺失副本可执行重建。`,
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, '扫描当前筛选失败'),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [
    projectTitleMap,
    publishFeedback,
    scanFilteredExternalDirectoryAssets,
    updateLastLocalStorageActionReport,
  ])

  const handleRestoreFilteredMissingLocalCopies = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel('正在扫描当前筛选并校验目录副本...')
    try {
      const {
        allFilteredAssets,
        healthSummary,
        inaccessibleAssetCount,
        missingAssets,
      } = await scanFilteredExternalDirectoryAssets()

      if (!allFilteredAssets.length) {
        publishFeedback?.({
          type: 'success',
          text: '当前筛选内没有可扫描的资产。',
        })
        return
      }

      const inaccessibleSuffix = inaccessibleAssetCount > 0
        ? `；另有 ${inaccessibleAssetCount} 项因目录不可访问未纳入本次重建`
        : ''

      if (!healthSummary || healthSummary.trackedAssetCount <= 0) {
        updateLastLocalStorageActionReport(buildUserAssetLocalStorageActionReport({
          mode: 'restore',
          scope: 'filtered_scope',
          scannedAssetCount: allFilteredAssets.length,
          trackedAssetCount: 0,
          missingLocalCopyCount: 0,
          inaccessibleAssetCount: 0,
          restoredCount: 0,
          existingCount: 0,
          blockedCount: 0,
          failedCount: 0,
          healthSummary,
          issueAssets: allFilteredAssets,
          projectTitleMap,
          completedAt: new Date(),
        }))
        publishFeedback?.({
          type: 'success',
          text: '当前筛选内没有登记为用户目录副本的资产。',
        })
        return
      }

      if (!missingAssets.length) {
        updateLastLocalStorageActionReport(buildUserAssetLocalStorageActionReport({
          mode: 'restore',
          scope: 'filtered_scope',
          scannedAssetCount: allFilteredAssets.length,
          trackedAssetCount: Math.max(0, healthSummary.trackedAssetCount),
          missingLocalCopyCount: 0,
          inaccessibleAssetCount,
          restoredCount: 0,
          existingCount: 0,
          blockedCount: 0,
          failedCount: 0,
          healthSummary,
          issueAssets: allFilteredAssets,
          projectTitleMap,
          completedAt: new Date(),
        }))
        publishFeedback?.({
          type: inaccessibleAssetCount > 0 ? 'error' : 'success',
          text: inaccessibleAssetCount > 0
            ? `已扫描当前筛选，发现 ${inaccessibleAssetCount} 项登记为用户目录副本的资产因目录不可访问，暂时无法直接重建，请先恢复访问后再重试。`
            : '当前筛选内没有需要重建的缺失副本。',
        })
        return
      }

      setExternalDirectorySubmittingLabel('正在重建当前筛选中缺失的本地副本...')
      const summary = await runUserAssetLocalRestoreBatch(missingAssets, { skipFeedback: true })
      updateLastLocalStorageActionReport(buildUserAssetLocalStorageActionReport({
        mode: 'restore',
        scope: 'filtered_scope',
        scannedAssetCount: allFilteredAssets.length,
        trackedAssetCount: Math.max(0, healthSummary.trackedAssetCount),
        missingLocalCopyCount: missingAssets.length,
        inaccessibleAssetCount,
        restoredCount: summary.restoredCount,
        existingCount: summary.existingCount,
        blockedCount: summary.blockedCount,
        failedCount: summary.failedCount,
        healthSummary,
        issueAssets: allFilteredAssets,
        projectTitleMap,
        completedAt: new Date(),
      }))
      const baseText = summary.blockedCount > 0 || summary.failedCount > 0
        ? buildUserAssetLocalCopyBatchRestoreErrorMessage(summary)
        : buildUserAssetLocalCopyBatchRestoreSuccessMessage(summary)
      publishFeedback?.({
        type: summary.blockedCount > 0 || summary.failedCount > 0 ? 'error' : 'success',
        text: `已扫描当前筛选，${baseText}${inaccessibleSuffix}`,
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, '扫描当前筛选并重建缺失副本失败'),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [
    projectTitleMap,
    publishFeedback,
    runUserAssetLocalRestoreBatch,
    scanFilteredExternalDirectoryAssets,
    updateLastLocalStorageActionReport,
  ])

  const handlePickExternalDirectory = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      const status = await pickLocalAssetExternalDirectory()
      setExternalDirectoryStatus(status)
      publishFeedback?.({
        type: 'success',
        text: `已连接用户目录：${status.directoryName || '未命名目录'}。后续手动收录的新资产会优先写入该目录。`,
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, '选择用户目录失败'),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [publishFeedback])

  const handleRecoverExternalDirectoryAccess = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      const status = await requestLocalAssetExternalDirectoryAccess()
      setExternalDirectoryStatus(status)

      if (status.permission === 'granted') {
        publishFeedback?.({
          type: 'success',
          text: `已恢复用户目录访问：${status.directoryName || '未命名目录'}。后续手动收录会继续优先写入该目录。`,
        })
        return
      }

      publishFeedback?.({
        type: 'error',
        text: status.permission === 'denied'
          ? '浏览器仍未授予该目录访问权限，请重新选择目录或检查浏览器权限设置。'
          : '未能恢复用户目录访问，请重试或重新选择目录。',
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, '恢复用户目录访问失败'),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [publishFeedback])

  const handleClearExternalDirectory = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      await clearLocalAssetExternalDirectoryHandle()
      await loadExternalDirectoryStatus({ silent: true })
      publishFeedback?.({
        type: 'success',
        text: '已清除用户目录配置。后续手动收录的新资产将回退到浏览器本地存储。',
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, '清除用户目录配置失败'),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [loadExternalDirectoryStatus, publishFeedback])

  const handleBatchUpdateUserAssets = useCallback(async (command: UserAssetBatchActionCommand) => {
    if (!assetSelectionState.selectedAssets.length) return

    setAssetBatchSubmitting(true)
    try {
      if (command.kind === 'restore_local_copy') {
        await runUserAssetLocalRestoreBatch(assetSelectionState.selectedAssets)
        return
      }

      if (command.kind === 'clear_local_copy') {
        const summary = await executeUserAssetLocalClearBatch(assetSelectionState.selectedAssets)
        if (summary.targetAssetCount === 0) {
          return
        }

        await loadUserAssets(true)
        if (summary.handledIds.length > 0) {
          setSelectedAssetIds((prev) => prev.filter((assetId) => !summary.handledIds.includes(assetId)))
        }

        if (summary.failedCount > 0) {
          publishFeedback?.({
            type: 'error',
            text: buildUserAssetLocalCopyBatchClearErrorMessage(summary),
          })
          return
        }

        publishFeedback?.({
          type: 'success',
          text: buildUserAssetLocalCopyBatchClearSuccessMessage(summary),
        })
        return
      }

      if (command.kind !== 'remote_update') {
        return
      }

      const response = await apiClient.batchUpdateUserAssets({
        asset_ids: assetSelectionState.selectedAssets.map((asset) => asset.id),
        updates: command.payload,
      })
      const updatedIds = Array.isArray(response.data?.asset_ids)
        ? response.data.asset_ids
        : assetSelectionState.selectedAssets.map((asset) => asset.id)
      const updatedCount = Number(response.data?.updated_count) || updatedIds.length
      await loadUserAssets(true)
      setSelectedAssetIds((prev) => prev.filter((assetId) => !updatedIds.includes(assetId)))
      publishFeedback?.({
        type: 'success',
        text: buildUserAssetBatchSuccessMessage(command, updatedCount),
      })
    } catch (batchError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(batchError, buildUserAssetBatchErrorFallback(command)),
      })
    } finally {
      setAssetBatchSubmitting(false)
    }
  }, [assetSelectionState.selectedAssets, loadUserAssets, publishFeedback, runUserAssetLocalRestoreBatch])

  const handleOpenAssetEditor = useCallback((asset: UserAssetRecord) => {
    setEditingAsset(asset)
    setAssetEditorData(buildUserAssetEditorFormData(asset))
    setAssetEditorOpen(true)
  }, [])

  const handleRestoreLocalAssetCopy = useCallback(async (asset: UserAssetRecord) => {
    setAssetActionKey(getUserAssetActionKey(asset.id))
    try {
      const result = await executeUserAssetLocalRestoreAction(asset)
      if (result.status === 'skipped') {
        return
      }

      await loadUserAssets(true)

      if (result.status === 'blocked') {
        publishFeedback?.({
          type: 'error',
          text: result.message || buildUserAssetLocalCopyRestoreErrorFallback(),
        })
        return
      }

      publishFeedback?.({
        type: 'success',
        text: buildUserAssetLocalCopyRestoreSuccessMessage(result.status === 'restored'),
      })
    } catch (restoreError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(restoreError, buildUserAssetLocalCopyRestoreErrorFallback()),
      })
    } finally {
      setAssetActionKey(null)
    }
  }, [loadUserAssets, publishFeedback])

  const handleClearLocalAssetCopy = useCallback(async (
    asset: Pick<UserAssetRecord, 'id' | 'asset_uuid' | 'storage_mode'>,
  ) => {
    setAssetActionKey(getUserAssetActionKey(asset.id))
    try {
      const result = await executeUserAssetLocalClearAction(asset)
      if (result.status === 'skipped') {
        return
      }

      await loadUserAssets(true)
      publishFeedback?.({
        type: 'success',
        text: buildUserAssetLocalCopyClearSuccessMessage(result.cleared),
      })
    } catch (clearError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(clearError, buildUserAssetLocalCopyClearErrorFallback()),
      })
    } finally {
      setAssetActionKey(null)
    }
  }, [loadUserAssets, publishFeedback])

  const handleCloseAssetEditor = useCallback(() => {
    if (assetEditorSubmitting) return
    setAssetEditorOpen(false)
    setEditingAsset(null)
    setAssetEditorData(getEmptyUserAssetEditorFormData())
  }, [assetEditorSubmitting])

  const handleSaveAssetEditor = useCallback(async () => {
    if (!editingAsset) return
    const normalized = normalizeUserAssetEditorPayload(assetEditorData)
    if (normalized.validationError || !normalized.payload) {
      publishFeedback?.({
        type: 'error',
        text: normalized.validationError || buildUserAssetEditorSaveErrorFallback(),
      })
      return
    }

    setAssetEditorSubmitting(true)
    try {
      await apiClient.updateUserAsset(editingAsset.id, normalized.payload)
      await loadUserAssets(true)
      publishFeedback?.({
        type: 'success',
        text: buildUserAssetEditorSaveSuccessMessage(),
      })
      setAssetEditorOpen(false)
      setEditingAsset(null)
      setAssetEditorData(getEmptyUserAssetEditorFormData())
    } catch (saveError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(saveError, buildUserAssetEditorSaveErrorFallback()),
      })
    } finally {
      setAssetEditorSubmitting(false)
    }
  }, [assetEditorData, editingAsset, loadUserAssets, publishFeedback])

  const workspaceSectionProps = useMemo<Omit<UserAssetWorkspaceSectionProps, 'children'>>(
    () => ({
      overviewMetrics: assetOverviewMetrics,
      listSection: {
        filterToolbar: {
          filters: assetFilters,
          kindOptions: assetKindOptions,
          sourceOptions: assetSourceOptions,
          tagOptions: assetTagOptions,
          filteredCount: userAssetTotal,
          loading: resolvedAssetListLoading,
          onViewFilterChange: handleAssetViewFilterChange,
          onKindFilterChange: handleAssetKindFilterChange,
          onSourceFilterChange: handleAssetSourceFilterChange,
          onArchiveFilterChange: handleAssetArchiveFilterChange,
          onTagFilterChange: handleAssetTagFilterChange,
          onRefresh: () => void loadUserAssets(),
        },
        batchToolbar: {
          selection: assetSelectionState,
          batchCommands: batchActionCommands,
          batchSubmitting: assetBatchSubmitting,
          onToggleSelectAll: handleToggleSelectAllFilteredAssets,
          onClearSelection: handleClearSelectedAssets,
          onRunBatchAction: (command) => void handleBatchUpdateUserAssets(command),
        },
        localStoragePanel: {
          status: externalDirectoryStatus,
          healthSummary: externalDirectoryAssetHealthSummary,
          submittingLabel: externalDirectorySubmittingLabel,
          lastActionReport: lastLocalStorageActionReport,
          loading: externalDirectoryLoading,
          submitting: externalDirectorySubmitting,
          onRefresh: handleRefreshExternalDirectoryStatus,
          onExportLocalAssetInventory: () => void handleExportLocalAssetInventory(),
          onRestoreMissingLocalCopies: () => void handleRestoreMissingLocalCopies(),
          onRestoreIssueItem: (item) => void handleRestoreLocalStorageIssueItem(item),
          onPreviewFilteredMissingLocalCopies: () => void handlePreviewFilteredMissingLocalCopies(),
          onRestoreFilteredMissingLocalCopies: () => void handleRestoreFilteredMissingLocalCopies(),
          onExportLocalAssetRebuildList: () => void handleExportLocalAssetRebuildList(),
          onPickDirectory: () => void handlePickExternalDirectory(),
          onRecoverAccess: () => void handleRecoverExternalDirectoryAccess(),
          onClearDirectory: () => void handleClearExternalDirectory(),
        },
        statusNotices: localDiagnosticsNotices,
        warningMessage: assetListError,
        isLoading: resolvedAssetListLoading,
        hasAssets: userAssetTotal > 0,
        hasFilteredAssets: filteredUserAssets.length > 0,
        pagination: {
          page: userAssetPage,
          totalPages: userAssetTotalPages,
          totalItems: userAssetTotal,
          pageSize: USER_ASSET_LIST_PAGE_SIZE,
          currentPageCount: filteredUserAssets.length,
          disabled: resolvedAssetListLoading,
          onPageChange: handleAssetPageChange,
        },
        emptyCollectionMessage: assetListFeedbackCopy.emptyCollectionMessage,
        emptyFilterMessage: assetListFeedbackCopy.emptyFilterMessage,
      },
      editorDialog: {
        open: assetEditorOpen,
        formData: assetEditorData,
        submitting: assetEditorSubmitting,
        hasAsset: Boolean(editingAsset),
        onClose: handleCloseAssetEditor,
        onSave: () => void handleSaveAssetEditor(),
        onFormDataChange: setAssetEditorData,
      },
    }),
    [
      assetEditorData,
      assetEditorOpen,
      assetEditorSubmitting,
      assetFilters,
      assetKindOptions,
      assetListError,
      assetListFeedbackCopy.emptyCollectionMessage,
      assetListFeedbackCopy.emptyFilterMessage,
      assetOverviewMetrics,
      assetSelectionState,
      assetSourceOptions,
      assetTagOptions,
      assetBatchSubmitting,
      batchActionCommands,
      editingAsset,
      filteredUserAssets.length,
      handleAssetArchiveFilterChange,
      handleAssetKindFilterChange,
      handleAssetPageChange,
      handleAssetSourceFilterChange,
      handleAssetTagFilterChange,
      handleAssetViewFilterChange,
      handleBatchUpdateUserAssets,
      handleClearExternalDirectory,
      handleClearSelectedAssets,
      handleCloseAssetEditor,
      handleExportLocalAssetInventory,
      handleRestoreMissingLocalCopies,
      handleRestoreLocalStorageIssueItem,
      handlePreviewFilteredMissingLocalCopies,
      handleRestoreFilteredMissingLocalCopies,
      handleExportLocalAssetRebuildList,
      handlePickExternalDirectory,
      handleRecoverExternalDirectoryAccess,
      handleRefreshExternalDirectoryStatus,
      handleSaveAssetEditor,
      handleToggleSelectAllFilteredAssets,
      loadUserAssets,
      localDiagnosticsNotices,
      resolvedAssetListLoading,
      externalDirectoryLoading,
      externalDirectoryAssetHealthSummary,
      externalDirectoryStatus,
      externalDirectorySubmitting,
      externalDirectorySubmittingLabel,
      lastLocalStorageActionReport,
      userAssetTotal,
      userAssetPage,
      userAssetTotalPages,
    ],
  )

  return {
    userAssets,
    userAssetTotal,
    filteredUserAssets,
    assetActionKey,
    assetBatchSubmitting,
    assetSelectionState,
    loadUserAssets,
    handleToggleAssetSelection,
    handleOpenAssetEditor,
    handleRestoreLocalAssetCopy,
    handleClearLocalAssetCopy,
    handleUpdateUserAsset,
    workspaceSectionProps,
  }
}
