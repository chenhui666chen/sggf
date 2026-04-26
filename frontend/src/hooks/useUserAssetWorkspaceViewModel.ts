import {
  useCallback,
  useMemo,
} from 'react'

import type { UserAssetCardsGridProps } from '@/components/user-assets/UserAssetCardsGrid'
import type { UserAssetWorkspaceContentProps } from '@/components/user-assets/UserAssetWorkspaceContent'
import {
  buildUserCenterAssetFacade,
  type UserCenterAssetFacade,
} from '@/components/user-assets/userCenterAssetFacadeHelper'
import {
  resolveUserCenterUserAssetCount,
  runUserCenterAssetRefresh,
} from '@/components/user-assets/userCenterAssetSummaryHelper'
import {
  buildUserCenterAssetWorkspaceInput,
  type UserCenterAssetWorkspacePointsOverviewInput,
  type UserCenterAssetWorkspaceProjectInput,
} from '@/components/user-assets/userCenterAssetWorkspaceInputHelper'
import type { UserAssetProjectTitleMap } from '@/contracts/userAssetSourceReaders'

import {
  useUserAssetPreviewObjectUrls,
  type UserAssetPreviewObjectUrlsState,
} from './useUserAssetPreviewObjectUrls'
import {
  useUserAssetWorkspaceController,
  type UserAssetWorkspaceController,
  type UserAssetWorkspaceFeedback,
} from './useUserAssetWorkspaceController'

type UseUserAssetWorkspaceViewModelOptions = {
  projects?: UserCenterAssetWorkspaceProjectInput[]
  pointsOverview?: UserCenterAssetWorkspacePointsOverviewInput | null
  publishFeedback?: (feedback: UserAssetWorkspaceFeedback) => void
  refreshUserCenterData?: (silent?: boolean) => Promise<void> | void
  navigateToPath?: (path: string) => void
  fallbackPath?: string
  enabled?: boolean
}

type BuildUserAssetCardsGridPropsOptions = Pick<
  UserAssetWorkspaceController,
  | 'filteredUserAssets'
  | 'assetActionKey'
  | 'assetBatchSubmitting'
  | 'handleToggleAssetSelection'
  | 'handleOpenAssetEditor'
  | 'handleRestoreLocalAssetCopy'
  | 'handleClearLocalAssetCopy'
  | 'handleUpdateUserAsset'
> & {
  projectTitleMap?: UserAssetProjectTitleMap
  assetSelectionState: UserAssetCardsGridProps['assetSelectionState']
  previewObjectUrls: Pick<UserAssetPreviewObjectUrlsState, 'localObjectUrls' | 'protectedObjectUrls'>
  onNavigateToPath: (path: string) => void
}

export type UserAssetWorkspaceViewModel = Pick<
  UserAssetWorkspaceController,
  never
> & {
  assetFacade: UserCenterAssetFacade
}

export function resolveUserAssetWorkspaceNavigationPath(
  path: string | null | undefined,
  fallbackPath = '/user-center',
): string {
  const normalizedPath = String(path || '').trim()
  return normalizedPath || fallbackPath
}

export function buildUserAssetCardsGridProps(
  options: BuildUserAssetCardsGridPropsOptions,
): UserAssetCardsGridProps {
  const {
    filteredUserAssets,
    projectTitleMap,
    assetActionKey,
    assetBatchSubmitting,
    assetSelectionState,
    previewObjectUrls,
    handleToggleAssetSelection,
    onNavigateToPath,
    handleOpenAssetEditor,
    handleRestoreLocalAssetCopy,
    handleClearLocalAssetCopy,
    handleUpdateUserAsset,
  } = options

  return {
    assets: filteredUserAssets,
    projectTitleMap,
    assetActionKey,
    assetBatchSubmitting,
    assetSelectionState,
    previewObjectUrls,
    onToggleSelection: handleToggleAssetSelection,
    onNavigateToPath,
    onEditAsset: handleOpenAssetEditor,
    onRestoreLocalCopyAsset: handleRestoreLocalAssetCopy,
    onClearLocalCopyAsset: handleClearLocalAssetCopy,
    onUpdateAsset: handleUpdateUserAsset,
  }
}

export function buildUserAssetWorkspaceContentProps(options: {
  workspaceSectionProps: UserAssetWorkspaceContentProps['workspaceSectionProps']
  cardsGridProps: UserAssetWorkspaceContentProps['cardsGridProps']
  onNavigateToIssueSource?: ((path: string) => void) | null
}): UserAssetWorkspaceContentProps {
  const localStoragePanel = options.workspaceSectionProps.listSection.localStoragePanel

  return {
    workspaceSectionProps: {
      ...options.workspaceSectionProps,
      listSection: {
        ...options.workspaceSectionProps.listSection,
        localStoragePanel: localStoragePanel
          ? {
              ...localStoragePanel,
              onNavigateToIssueSource: options.onNavigateToIssueSource || null,
            }
          : localStoragePanel,
      },
    },
    cardsGridProps: options.cardsGridProps,
  }
}

export function resolveUserAssetWorkspacePreviewAssets(
  assets: UserAssetWorkspaceController['filteredUserAssets'],
  enabled = true,
): UserAssetWorkspaceController['filteredUserAssets'] {
  return enabled ? assets : []
}

export function useUserAssetWorkspaceViewModel(
  options: UseUserAssetWorkspaceViewModelOptions = {},
): UserAssetWorkspaceViewModel {
  const {
    projects,
    pointsOverview,
    publishFeedback,
    refreshUserCenterData,
    navigateToPath,
    fallbackPath = '/user-center',
    enabled = true,
  } = options

  const workspaceInput = useMemo(
    () => buildUserCenterAssetWorkspaceInput({
      projects,
      pointsOverview,
    }),
    [pointsOverview, projects],
  )

  const controller = useUserAssetWorkspaceController({
    projectTitleMap: workspaceInput.projectTitleMap,
    publishFeedback,
    enabled,
  })
  const previewAssets = useMemo(
    () => resolveUserAssetWorkspacePreviewAssets(controller.filteredUserAssets, enabled),
    [controller.filteredUserAssets, enabled],
  )
  const {
    localObjectUrls,
    protectedObjectUrls,
  } = useUserAssetPreviewObjectUrls({
    assets: previewAssets,
    enabled,
  })

  const handleNavigateToAssetPath = useCallback((path: string) => {
    navigateToPath?.(resolveUserAssetWorkspaceNavigationPath(path, fallbackPath))
  }, [fallbackPath, navigateToPath])

  const userAssetCount = useMemo(
    () => resolveUserCenterUserAssetCount(workspaceInput.connectedUserAssetCount, controller.userAssetTotal),
    [controller.userAssetTotal, workspaceInput.connectedUserAssetCount],
  )

  const refreshUserCenterAssets = useCallback(() => {
    runUserCenterAssetRefresh({
      refreshUserCenterData,
      refreshUserAssets: controller.loadUserAssets,
    })
  }, [controller.loadUserAssets, refreshUserCenterData])

  const cardsGridProps = useMemo(
    () => buildUserAssetCardsGridProps({
      filteredUserAssets: controller.filteredUserAssets,
      projectTitleMap: workspaceInput.projectTitleMap,
      assetActionKey: controller.assetActionKey,
      assetBatchSubmitting: controller.assetBatchSubmitting,
      assetSelectionState: controller.assetSelectionState,
      previewObjectUrls: {
        localObjectUrls,
        protectedObjectUrls,
      },
      handleToggleAssetSelection: controller.handleToggleAssetSelection,
      onNavigateToPath: handleNavigateToAssetPath,
      handleOpenAssetEditor: controller.handleOpenAssetEditor,
      handleRestoreLocalAssetCopy: controller.handleRestoreLocalAssetCopy,
      handleClearLocalAssetCopy: controller.handleClearLocalAssetCopy,
      handleUpdateUserAsset: controller.handleUpdateUserAsset,
    }),
    [
      controller.filteredUserAssets,
      controller.assetActionKey,
      controller.assetBatchSubmitting,
      controller.assetSelectionState,
      controller.handleToggleAssetSelection,
      controller.handleOpenAssetEditor,
      controller.handleRestoreLocalAssetCopy,
      controller.handleClearLocalAssetCopy,
      controller.handleUpdateUserAsset,
      handleNavigateToAssetPath,
      localObjectUrls,
      protectedObjectUrls,
      workspaceInput.projectTitleMap,
    ],
  )

  const workspaceContentProps = useMemo(
    () => buildUserAssetWorkspaceContentProps({
      workspaceSectionProps: controller.workspaceSectionProps,
      cardsGridProps,
      onNavigateToIssueSource: handleNavigateToAssetPath,
    }),
    [cardsGridProps, controller.workspaceSectionProps, handleNavigateToAssetPath],
  )

  const assetFacade = useMemo(
    () => buildUserCenterAssetFacade({
      userAssetCount,
      refreshUserCenterAssets,
      workspaceContentProps,
    }),
    [refreshUserCenterAssets, userAssetCount, workspaceContentProps],
  )

  return {
    assetFacade,
  }
}
