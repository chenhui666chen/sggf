import {
  useCallback,
  useEffect,
  useMemo,
  useState,
} from 'react'

import { useTranslation } from 'react-i18next'

import { useAppLanguage } from '@/i18n'
import type { AppLanguage } from '@/i18n'
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

import type { TFunction } from 'i18next'

import {
  executeUserAssetLocalClearAction,
  executeUserAssetLocalClearBatch,
  executeUserAssetLocalRestoreAction,
  executeUserAssetLocalRestoreBatch,
  type UserAssetLocalRestoreActionResult,
} from './userAssetWorkspaceLocalActions'

const DEFAULT_TRANSLATE: TFunction = ((key: string) => key) as TFunction

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
  /** 时间文案的显示语言。本函数在模块级，只能由调用方递进来。 */
  locale?: AppLanguage
  t?: TFunction
}): UserAssetLocalStorageActionReport {
  const {
    report,
    issueItem,
    result,
    locale,
    t,
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
    locale,
    t,
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
  t?: TFunction,
): UserAssetExternalDirectoryAssetHealthItem {
  const translate = t ?? DEFAULT_TRANSLATE
  const metadata = getUserAssetMetadataPayload(asset)

  return {
    assetId: asset.id,
    assetUuid: String(asset.asset_uuid || '').trim(),
    title: String(asset.title || '').trim() || translate('userAsset.workspace.assetIdFallback', { id: asset.id }),
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
  t?: TFunction,
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
      inaccessibleAssets: trackedAssets.map((asset) => buildExternalDirectoryAssetHealthItem(asset, t)),
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
    .map((result) => buildExternalDirectoryAssetHealthItem(result.asset, t))
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

  // 本地目录动作报告里的时间文案跟着当前界面语言走。报告是在动作发生时定形并
  // 存进 state 的，所以这里取的是那一刻的语言。
  const { language } = useAppLanguage()
  const { t } = useTranslation()

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
      setAssetListError(await extractApiErrorMessage(loadError, t('userAsset.workspace.loadUserAssetsFailed')))
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
          text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.readDirectoryStatusFailed')),
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
      const summary = await probeUserAssetExternalDirectoryAssetHealthSummary(userAssets, externalDirectoryStatus, {}, t)
      if (cancelled) {
        return
      }
      setExternalDirectoryAssetHealthSummary(summary)
    }

    void probeExternalDirectoryAssets()

    return () => {
      cancelled = true
    }
  }, [enabled, externalDirectoryLoading, externalDirectoryStatus, userAssets, t])

  const assetKindOptions = useMemo(
    () => buildUserAssetKindOptionsFromValues(userAssetFilterOptions.asset_kinds || []),
    [userAssetFilterOptions.asset_kinds],
  )
  const assetTagOptions = useMemo(
    () => buildUserAssetTagOptionsFromValues(userAssetFilterOptions.tags || []),
    [userAssetFilterOptions.tags],
  )
  const assetSourceOptions = useMemo(
    () => buildUserAssetSourceOptionsFromSourceModules(userAssetFilterOptions.source_modules || [], t),
    [t, userAssetFilterOptions.source_modules],
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
  const favoriteBatchCommand = buildFavoriteBatchUserAssetCommand(t)
  const archiveBatchCommand = buildArchiveBatchUserAssetCommand(t)
  const activateBatchCommand = buildActivateBatchUserAssetCommand(t)
  const clearLocalCopyBatchCommand = buildClearLocalCopyBatchUserAssetCommand(t)
  const restoreLocalCopyBatchCommand = buildRestoreLocalCopyBatchUserAssetCommand(t)
  const assetOverviewMetrics = useMemo(
    () =>
      buildUserAssetOverviewMetricSpecs({
        activeAssetCount: userAssetSummary.active_asset_count,
        reusableAssetCount: userAssetSummary.reusable_asset_count,
        deliverableAssetCount: userAssetSummary.deliverable_asset_count,
        favoriteAssetCount: userAssetSummary.favorite_asset_count,
        archivedAssetCount: userAssetSummary.archived_asset_count,
      }, t),
    [
      userAssetSummary.active_asset_count,
      userAssetSummary.archived_asset_count,
      userAssetSummary.deliverable_asset_count,
      userAssetSummary.favorite_asset_count,
      userAssetSummary.reusable_asset_count,
      t,
    ],
  )
  const assetListFeedbackCopy = buildUserAssetListFeedbackCopy(t)
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
      t,
    }),
    [externalDirectoryAssetHealthSummary, externalDirectoryStatus, legacyLocalAssetMigrationStatus, t],
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
    successText?: string,
  ) => {
    setAssetActionKey(getUserAssetActionKey(assetId))
    try {
      await apiClient.updateUserAsset(assetId, payload)
      await loadUserAssets(true)
      publishFeedback?.({type: 'success', text: buildUserAssetUpdateSuccessMessage(successText, t)})
    } catch (updateError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(updateError, buildUserAssetUpdateErrorFallback(t)),
      })
    } finally {
      setAssetActionKey(null)
    }
  }, [loadUserAssets, publishFeedback, t])

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
        text: buildUserAssetLocalCopyBatchRestoreErrorMessage(summary, t),
      })
      return summary
    }

    publishFeedback?.({
      type: 'success',
      text: buildUserAssetLocalCopyBatchRestoreSuccessMessage(summary, t),
    })
    return summary
  }, [loadUserAssets, publishFeedback, t])

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
          t,
        }),
        filename: buildUserAssetLocalStorageInventoryFilename(generatedAt),
        mimeType: 'application/json',
      })
      publishFeedback?.({
        type: 'success',
        text: t('userAsset.workspace.exportInventorySuccess', { count: inventory.length }),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.exportInventoryFailed')),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [externalDirectoryLoading, externalDirectoryStatus, publishFeedback, t])

  const handleExportLocalAssetRebuildList = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      const issueCount = countUserAssetLocalStorageRebuildCandidates(externalDirectoryAssetHealthSummary)

      if (issueCount <= 0) {
        publishFeedback?.({
          type: 'success',
          text: t('userAsset.workspace.exportRebuildListEmpty'),
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
          t,
        }),
        filename: buildUserAssetLocalStorageRebuildListFilename(generatedAt),
        mimeType: 'application/json',
      })
      publishFeedback?.({
        type: 'success',
        text: t('userAsset.workspace.exportRebuildListSuccess', { count: issueCount }),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.exportRebuildListFailed')),
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
    t,
  ])

  const handleRestoreMissingLocalCopies = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(t('userAsset.workspace.restoringCurrentPage'))
    try {
      const missingAssets = resolveExternalDirectoryMissingLocalCopyAssets(filteredUserAssets, externalDirectoryAssetHealthSummary)
      const summary = await runUserAssetLocalRestoreBatch(
        missingAssets,
        {
          emptyFeedbackText: t('userAsset.workspace.currentPageNoRebuildable'),
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
        locale: language,
        t,
      })
      updateLastLocalStorageActionReport(report)
      if (summary.targetAssetCount <= 0) {
        publishFeedback?.({
          type: 'success',
          text: t('userAsset.workspace.currentPageNoRebuildable'),
        })
        return
      }

      const feedbackText = summary.blockedCount > 0 || summary.failedCount > 0
        ? buildUserAssetLocalCopyBatchRestoreErrorMessage(summary, t)
        : buildUserAssetLocalCopyBatchRestoreSuccessMessage(summary, t)
      publishFeedback?.({
        type: summary.blockedCount > 0 || summary.failedCount > 0 ? 'error' : 'success',
        text: feedbackText,
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.restoreCurrentPageFailed')),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [
    externalDirectoryAssetHealthSummary,
    filteredUserAssets,
    language,
    projectTitleMap,
    publishFeedback,
    runUserAssetLocalRestoreBatch,
    updateLastLocalStorageActionReport,
    t,
  ])

  const handleRestoreLocalStorageIssueItem = useCallback(async (item: UserAssetLocalStorageActionIssueItem) => {
    if (item.issueType !== 'missing_local_copy' || !item.restorableAsset) {
      publishFeedback?.({
        type: 'error',
        text: t('userAsset.workspace.issueItemNotRestorable'),
      })
      return
    }

    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(t('userAsset.workspace.restoringIssueItem', { title: item.title }))
    try {
      const result = await executeUserAssetLocalRestoreAction(item.restorableAsset)
      if (result.status === 'skipped') {
        publishFeedback?.({
          type: 'error',
          text: t('userAsset.workspace.assetNotRestorable'),
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
          locale: language,
          t,
        })
      })

      if (result.status === 'blocked') {
        publishFeedback?.({
          type: 'error',
          text: result.message || buildUserAssetLocalCopyRestoreErrorFallback(t),
        })
        return
      }

      publishFeedback?.({
        type: 'success',
        text: buildUserAssetLocalCopyRestoreSuccessMessage(result.status === 'restored', t),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(error, buildUserAssetLocalCopyRestoreErrorFallback(t)),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [language, loadUserAssets, publishFeedback, t])

  const handlePreviewFilteredMissingLocalCopies = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(t('userAsset.workspace.scanningFiltered'))
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
        locale: language,
        t,
      }))

      if (!allFilteredAssets.length) {
        publishFeedback?.({
          type: 'success',
          text: t('userAsset.workspace.filteredNoAssets'),
        })
        return
      }

      if (!healthSummary || healthSummary.trackedAssetCount <= 0) {
        publishFeedback?.({
          type: 'success',
          text: t('userAsset.workspace.scanNoTracked'),
        })
        return
      }

      if (!missingAssets.length && inaccessibleAssetCount <= 0) {
        publishFeedback?.({
          type: 'success',
          text: t('userAsset.workspace.scanNoMissing'),
        })
        return
      }

      publishFeedback?.({
        type: inaccessibleAssetCount > 0 ? 'error' : 'success',
        text: inaccessibleAssetCount > 0
          ? t('userAsset.workspace.scanPartialInaccessible', {
              missing: missingAssets.length,
              inaccessible: inaccessibleAssetCount,
            })
          : t('userAsset.workspace.scanPartial', { count: missingAssets.length }),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.scanFilteredFailed')),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [
    language,
    projectTitleMap,
    publishFeedback,
    scanFilteredExternalDirectoryAssets,
    updateLastLocalStorageActionReport,
    t,
  ])

  const handleRestoreFilteredMissingLocalCopies = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(t('userAsset.workspace.scanningFiltered'))
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
          text: t('userAsset.workspace.filteredNoAssets'),
        })
        return
      }

      const inaccessibleSuffix = inaccessibleAssetCount > 0
        ? t('userAsset.workspace.restoreInaccessibleSuffix', { count: inaccessibleAssetCount })
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
          locale: language,
          t,
        }))
        publishFeedback?.({
          type: 'success',
          text: t('userAsset.workspace.filteredNoTracked'),
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
          locale: language,
          t,
        }))
        publishFeedback?.({
          type: inaccessibleAssetCount > 0 ? 'error' : 'success',
          text: inaccessibleAssetCount > 0
            ? t('userAsset.workspace.scannedInaccessibleOnly', { count: inaccessibleAssetCount })
            : t('userAsset.workspace.filteredNoMissing'),
        })
        return
      }

      setExternalDirectorySubmittingLabel(t('userAsset.workspace.restoringFiltered'))
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
        locale: language,
        t,
      }))
      const baseText = summary.blockedCount > 0 || summary.failedCount > 0
        ? buildUserAssetLocalCopyBatchRestoreErrorMessage(summary, t)
        : buildUserAssetLocalCopyBatchRestoreSuccessMessage(summary, t)
      publishFeedback?.({
        type: summary.blockedCount > 0 || summary.failedCount > 0 ? 'error' : 'success',
        text: t('userAsset.workspace.scannedRestoreSummary', { result: baseText, suffix: inaccessibleSuffix }),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.scanAndRestoreFailed')),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [
    language,
    projectTitleMap,
    publishFeedback,
    runUserAssetLocalRestoreBatch,
    scanFilteredExternalDirectoryAssets,
    updateLastLocalStorageActionReport,
    t,
  ])

  const handlePickExternalDirectory = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      const status = await pickLocalAssetExternalDirectory()
      setExternalDirectoryStatus(status)
      publishFeedback?.({
        type: 'success',
        text: t('userAsset.workspace.pickDirectorySuccess', {
          directory: status.directoryName || t('userAsset.common.unnamedDirectory'),
        }),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.pickDirectoryFailed')),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [publishFeedback, t])

  const handleRecoverExternalDirectoryAccess = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      const status = await requestLocalAssetExternalDirectoryAccess()
      setExternalDirectoryStatus(status)

      if (status.permission === 'granted') {
        publishFeedback?.({
          type: 'success',
          text: t('userAsset.workspace.recoverAccessSuccess', {
            directory: status.directoryName || t('userAsset.common.unnamedDirectory'),
          }),
        })
        return
      }

      publishFeedback?.({
        type: 'error',
        text: status.permission === 'denied'
          ? t('userAsset.workspace.recoverAccessDenied')
          : t('userAsset.workspace.recoverAccessUnknown'),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.recoverAccessFailed')),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [publishFeedback, t])

  const handleClearExternalDirectory = useCallback(async () => {
    setExternalDirectorySubmitting(true)
    setExternalDirectorySubmittingLabel(null)
    try {
      await clearLocalAssetExternalDirectoryHandle()
      await loadExternalDirectoryStatus({ silent: true })
      publishFeedback?.({
        type: 'success',
        text: t('userAsset.workspace.clearDirectorySuccess'),
      })
    } catch (error) {
      publishFeedback?.({
        type: 'error',
        text: extractLocalDirectoryErrorMessage(error, t('userAsset.workspace.clearDirectoryFailed')),
      })
    } finally {
      setExternalDirectorySubmitting(false)
      setExternalDirectorySubmittingLabel(null)
    }
  }, [loadExternalDirectoryStatus, publishFeedback, t])

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
            text: buildUserAssetLocalCopyBatchClearErrorMessage(summary, t),
          })
          return
        }

        publishFeedback?.({
          type: 'success',
          text: buildUserAssetLocalCopyBatchClearSuccessMessage(summary, t),
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
        text: buildUserAssetBatchSuccessMessage(command, updatedCount, t),
      })
    } catch (batchError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(batchError, buildUserAssetBatchErrorFallback(command, t)),
      })
    } finally {
      setAssetBatchSubmitting(false)
    }
  }, [assetSelectionState.selectedAssets, loadUserAssets, publishFeedback, runUserAssetLocalRestoreBatch, t])

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
          text: result.message || buildUserAssetLocalCopyRestoreErrorFallback(t),
        })
        return
      }

      publishFeedback?.({
        type: 'success',
        text: buildUserAssetLocalCopyRestoreSuccessMessage(result.status === 'restored', t),
      })
    } catch (restoreError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(restoreError, buildUserAssetLocalCopyRestoreErrorFallback(t)),
      })
    } finally {
      setAssetActionKey(null)
    }
  }, [loadUserAssets, publishFeedback, t])

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
        text: buildUserAssetLocalCopyClearSuccessMessage(result.cleared, t),
      })
    } catch (clearError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(clearError, buildUserAssetLocalCopyClearErrorFallback(t)),
      })
    } finally {
      setAssetActionKey(null)
    }
  }, [loadUserAssets, publishFeedback, t])

  const handleCloseAssetEditor = useCallback(() => {
    if (assetEditorSubmitting) return
    setAssetEditorOpen(false)
    setEditingAsset(null)
    setAssetEditorData(getEmptyUserAssetEditorFormData())
  }, [assetEditorSubmitting])

  const handleSaveAssetEditor = useCallback(async () => {
    if (!editingAsset) return
    const normalized = normalizeUserAssetEditorPayload(assetEditorData, t)
    if (normalized.validationError || !normalized.payload) {
      publishFeedback?.({
        type: 'error',
        text: normalized.validationError || buildUserAssetEditorSaveErrorFallback(t),
      })
      return
    }

    setAssetEditorSubmitting(true)
    try {
      await apiClient.updateUserAsset(editingAsset.id, normalized.payload)
      await loadUserAssets(true)
      publishFeedback?.({
        type: 'success',
        text: buildUserAssetEditorSaveSuccessMessage(t),
      })
      setAssetEditorOpen(false)
      setEditingAsset(null)
      setAssetEditorData(getEmptyUserAssetEditorFormData())
    } catch (saveError) {
      publishFeedback?.({
        type: 'error',
        text: await extractApiErrorMessage(saveError, buildUserAssetEditorSaveErrorFallback(t)),
      })
    } finally {
      setAssetEditorSubmitting(false)
    }
  }, [assetEditorData, editingAsset, loadUserAssets, publishFeedback, t])

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
