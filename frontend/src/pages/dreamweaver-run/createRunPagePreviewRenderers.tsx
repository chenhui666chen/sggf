import type { TFunction } from 'i18next'
import type { DreamweaverAssetPlanItem, LibraryDisplayItem, LibraryAsset, DreamweaverLibraryPlanItem, DreamweaverScriptEntities } from '@/types/dreamweaver'
import type { SafetyBlockedShotItem } from './diagnosticSections'
import {
  DreamweaverRunAssetPreviewGrid,
  DreamweaverAssetPlanGrid,
  DreamweaverScriptStageSnapshotView,
  DreamweaverStreamingPreview,
} from './previewSections'
import {
  DreamweaverLibraryDisplayCard,
} from './libraryViews'
import { SafetyBlockedAlert } from './diagnosticSections'
import {
  resolveLibraryDisplayCardState,
  summarizeScriptEntities,
  resolveStreamingTexts,
} from './runPageHelpers'

interface CreateRunPagePreviewRenderersDeps {
  sharedAssetGridProps: {
    previewsByUri: Record<string, string>
    loadingByUri: Record<string, boolean>
    errorsByUri: Record<string, string | null | undefined>
    canInteract: boolean
    onLoadPreview: (uri: string) => void
    onDownload: (uri: string) => void
    formatPath: (value: unknown) => string | null
  }
  missingRoleSet: Set<string>
  libraryPreviewLoading: Record<number, boolean>
  libraryPreviewErrors: Record<number, string>
  libraryLoading: boolean
  approveLibrary: (payload: { roles: string[]; approved: boolean }) => Promise<void>
  loadLibraryPreviewWrapper: (asset: LibraryAsset, options?: { force?: boolean }) => Promise<void>
  openRegenerateDialog: (asset: LibraryAsset) => void
  openRegenerateDialogForRole: (role: string, title: string) => void
  streamSnapshots: Record<string, string>
  activeStreamKeys: string[]
  libraryPlanItems: DreamweaverLibraryPlanItem[]
  assetPlanItems: DreamweaverAssetPlanItem[]
  assetPlanSummary: { total: number; done: number; planned: number; images: number; videos: number }
  mergedVideoPlan: DreamweaverAssetPlanItem | null
  hasNonMergedVideoAssets: boolean
  hasMergedVideoPlan: boolean
  nonMergedVideoAssets: DreamweaverAssetPlanItem[]
  snapshotPlanText: string
  snapshotScriptText: string
  snapshotScriptApproved: boolean
  snapshotCharacterProfiles: unknown[]
  snapshotAudioMarkers: unknown[]
  snapshotScriptEntities: DreamweaverScriptEntities | null
  snapshotScriptGeneration: unknown
  safetyBlockedShots: SafetyBlockedShotItem[]
  openSafetyBlockedShot: (shotId: string) => void
  t: TFunction
}

export function createRunPagePreviewRenderers(deps: CreateRunPagePreviewRenderersDeps) {
  const {
    sharedAssetGridProps,
    missingRoleSet,
    libraryPreviewLoading,
    libraryPreviewErrors,
    libraryLoading,
    approveLibrary,
    loadLibraryPreviewWrapper,
    openRegenerateDialog,
    openRegenerateDialogForRole,
    streamSnapshots,
    activeStreamKeys,
    libraryPlanItems,
    assetPlanItems,
    assetPlanSummary,
    mergedVideoPlan,
    hasNonMergedVideoAssets,
    hasMergedVideoPlan,
    nonMergedVideoAssets,
    snapshotPlanText,
    snapshotScriptText,
    snapshotScriptApproved,
    snapshotCharacterProfiles,
    snapshotAudioMarkers,
    snapshotScriptEntities,
    snapshotScriptGeneration,
    safetyBlockedShots,
    openSafetyBlockedShot,
    t,
  } = deps

  const renderRunAssetPreviewGrid = (title: string, uris: string[], kind: 'image' | 'video') => (
    <DreamweaverRunAssetPreviewGrid
      title={title}
      uris={uris}
      kind={kind}
      {...sharedAssetGridProps}
    />
  )

  const renderAssetPlanGrid = (title: string, items: DreamweaverAssetPlanItem[]) => (
    <DreamweaverAssetPlanGrid
      title={title}
      items={items}
      {...sharedAssetGridProps}
    />
  )

  const resolveLibraryDisplayCardStateLocal = (item: LibraryDisplayItem) =>
    resolveLibraryDisplayCardState(item, missingRoleSet, libraryPreviewLoading, libraryPreviewErrors, t)

  const renderLibraryDisplayCard = (item: LibraryDisplayItem) => {
    const state = resolveLibraryDisplayCardStateLocal(item)
    const cardAsset = state.asset

    return (
      <DreamweaverLibraryDisplayCard
        itemKey={item.key}
        title={item.title}
        aspectRatio={String(item.aspectRatio)}
        state={state}
        libraryLoading={libraryLoading}
        onToggleApprove={
          cardAsset ? () => approveLibrary({ roles: [cardAsset!.role], approved: !state.approved }) : undefined
        }
        onLoadPreview={
          cardAsset ? () => loadLibraryPreviewWrapper(cardAsset!, { force: true }) : undefined
        }
        onOpenRegenerate={
          cardAsset ? () => openRegenerateDialog(cardAsset!) : () => openRegenerateDialogForRole(item.role, item.title)
        }
      />
    )
  }

  const renderStreamingPreview = (step: number) => {
    const streamingTexts = resolveStreamingTexts(streamSnapshots)

    return (
      <DreamweaverStreamingPreview
        step={step}
        activeStreamKeys={activeStreamKeys}
        {...streamingTexts}
        libraryPlanItems={libraryPlanItems}
        assetPlanItems={assetPlanItems}
        assetPlanSummary={assetPlanSummary}
        mergedVideoPlan={mergedVideoPlan ?? null}
        assetPlanGrid={hasNonMergedVideoAssets ? renderAssetPlanGrid(t('dreamweaverRun.assetPlaceholderCard'), nonMergedVideoAssets) : null}
        mergedVideoPlanGrid={hasMergedVideoPlan ? renderAssetPlanGrid(t('dreamweaverRun.mergedVideoPlaceholder'), [mergedVideoPlan!]) : null}
      />
    )
  }

  const renderScriptStageSnapshot = () => (
    <DreamweaverScriptStageSnapshotView
      planText={snapshotPlanText.trim()}
      scriptText={snapshotScriptText.trim()}
      scriptApproved={snapshotScriptApproved}
      characterProfiles={snapshotCharacterProfiles}
      audioMarkers={snapshotAudioMarkers}
      scriptEntities={snapshotScriptEntities}
      scriptGeneration={snapshotScriptGeneration}
      entitySummary={summarizeScriptEntities(snapshotScriptEntities, t)}
    />
  )

  const renderSafetyBlockedAlert = () => (
    <SafetyBlockedAlert shots={safetyBlockedShots} onOpenShot={openSafetyBlockedShot} />
  )

  return {
    renderRunAssetPreviewGrid,
    renderAssetPlanGrid,
    renderLibraryDisplayCard,
    renderStreamingPreview,
    renderScriptStageSnapshot,
    renderSafetyBlockedAlert,
  }
}
