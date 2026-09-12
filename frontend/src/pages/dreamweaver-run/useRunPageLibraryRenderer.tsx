import type { TFunction } from 'i18next'
import { ImageList, Stack } from '@mui/material'
import {
  DreamweaverCharacterLibraryBucketSection,
  DreamweaverLibraryGroupSection,
  DreamweaverLibrarySummaryChips,
} from './libraryViews'
import {
  PendingLibraryNotice,
  PendingLibraryControls,
  PendingLibraryReadyShell,
  PendingLibraryReadyActions,
  PendingLibraryReviewShell,
  PendingLibraryRuntimeStatus,
  PendingLibrarySummarySection,
} from './pendingViews'
import {
  resolvePendingLibraryNoticeSeverity,
  buildPendingLibraryControlsProps,
  buildPendingLibraryRuntimeStatusProps,
} from './runPageConfigHelpers'
import {
  buildCharacterLibraryBuckets,
  CharacterLibraryBucket,
} from './runPageHelpers'
import {
  type LibraryDisplayGroup,
  type LibraryGroupSummary,
} from './runPageLibraryHelpers'
import type { LibraryDisplayItem, LibraryPayload } from '@/types/dreamweaver'

type RenderLibraryDisplayCard = (item: LibraryDisplayItem) => React.ReactNode

interface CreateRunPageLibraryRendererDeps {
  libraryLoading: boolean
  libraryError: string | null
  library: LibraryPayload | null
  libraryApproved: boolean
  libraryGridCols: number
  librarySummary: LibraryGroupSummary
  libraryGroups: LibraryDisplayGroup[]
  hasLibraryItems: boolean
  libraryPromptReviewMessage: string
  promptReviewReady: boolean
  promptReviewRequiredSnapshot: boolean
  selectedProjectId: number | null
  canResumeFromLibrary: boolean
  resumeLoading: boolean
  loadLibrary: () => Promise<string | null>
  approveLibrary: (payload: { approve_all?: boolean; roles?: string[]; approved?: boolean }) => Promise<void>
  resumeGeneration: () => void
  handleClickStep: (step: number) => void
  renderArtifactsDebugPanel: () => React.ReactNode
  renderRunSnapshotPreviewPane: (options: { shotEmptyText: string }) => React.ReactNode
  renderLibraryDisplayCard: RenderLibraryDisplayCard
  t: TFunction
}

export function createRunPageLibraryRenderer(deps: CreateRunPageLibraryRendererDeps) {
  const {
    libraryLoading,
    libraryError,
    library,
    libraryApproved,
    libraryGridCols,
    librarySummary,
    libraryGroups,
    hasLibraryItems,
    libraryPromptReviewMessage,
    promptReviewReady,
    promptReviewRequiredSnapshot,
    selectedProjectId,
    canResumeFromLibrary,
    resumeLoading,
    loadLibrary,
    approveLibrary,
    resumeGeneration,
    handleClickStep,
    renderArtifactsDebugPanel,
    renderRunSnapshotPreviewPane,
    renderLibraryDisplayCard,
    t,
  } = deps

  const renderCharacterLibraryBucketSection = (bucket: CharacterLibraryBucket) => {
    const bucketItemCount = bucket.items.length
    const generatedCount = bucket.items.filter((item) => Boolean(item.hasRenderableImage)).length

    return (
      <DreamweaverCharacterLibraryBucketSection
        bucketKey={bucket.bucketKey}
        name={bucket.name}
        viewCount={bucketItemCount}
        generatedCount={generatedCount}
        content={
          <ImageList cols={libraryGridCols} gap={8} sx={{ m: 0 }}>
            {bucket.items.map(renderLibraryDisplayCard)}
          </ImageList>
        }
      />
    )
  }

  const renderLibrarySummaryChips = (summary: LibraryGroupSummary, totalLabel: string) => (
    <DreamweaverLibrarySummaryChips totalLabel={totalLabel} summary={summary} />
  )

  const renderCharacterLibraryGroupGrid = (items: LibraryDisplayItem[]) => {
    const orderedBuckets = buildCharacterLibraryBuckets(items, t)

    return (
      <Stack spacing={1}>
        {orderedBuckets.map(renderCharacterLibraryBucketSection)}
      </Stack>
    )
  }

  const renderLibraryGroupGrid = (group: LibraryDisplayGroup) => {
    if (group.key !== 'character') {
      return (
        <ImageList cols={libraryGridCols} gap={8} sx={{ m: 0 }}>
          {group.items.map(renderLibraryDisplayCard)}
        </ImageList>
      )
    }

    return renderCharacterLibraryGroupGrid(group.items)
  }

  const renderLibraryGroupSection = (group: LibraryDisplayGroup) => (
    <DreamweaverLibraryGroupSection
      groupKey={group.key}
      label={group.label}
      summaryChips={renderLibrarySummaryChips(group.summary, t('dreamweaverRun.libraryTotal'))}
      content={renderLibraryGroupGrid(group)}
    />
  )

  const renderPendingLibrarySummaryChips = () => renderLibrarySummaryChips(librarySummary, t('dreamweaverRun.libraryTotalPlaceholder'))

  const approveAllLibrary = () => approveLibrary({ approve_all: true, approved: true })

  const renderPendingLibraryReviewView = () => {
    const noticeSeverity = resolvePendingLibraryNoticeSeverity(libraryApproved, promptReviewReady, false)
    const controlsProps = buildPendingLibraryControlsProps({
      selectedProjectId,
      libraryLoading,
      canResumeFromLibrary,
      resumeLoading,
    })
    const runtimeStatusProps = buildPendingLibraryRuntimeStatusProps({
      libraryError,
      libraryLoading,
      library,
    })

    const librarySummaryChips = hasLibraryItems ? renderPendingLibrarySummaryChips() : null
    const libraryGroupSections = hasLibraryItems ? <>{libraryGroups.map(renderLibraryGroupSection)}</> : null

    return (
      <PendingLibraryReviewShell
        notice={
          <PendingLibraryNotice
            severity={noticeSeverity}
            message={libraryPromptReviewMessage}
          />
        }
        controls={
          <PendingLibraryControls
            onLoadLibrary={loadLibrary}
            onApproveAll={approveAllLibrary}
            {...controlsProps}
            onResume={resumeGeneration}
          />
        }
        runtimeStatus={
          <PendingLibraryRuntimeStatus {...runtimeStatusProps} />
        }
        summarySection={
          <PendingLibrarySummarySection
            emptyText={t('dreamweaverRun.libraryEmptyNotLoaded')}
            summaryChips={librarySummaryChips}
            groups={libraryGroupSections}
          />
        }
        debugPanel={renderArtifactsDebugPanel()}
      />
    )
  }

  const viewLibraryStep = () => handleClickStep(2)
  const viewPromptReviewStep = () => handleClickStep(1)

  const libraryResumeDisabled = !canResumeFromLibrary

  const renderPendingLibraryReadyView = () => {
    const noticeSeverity = resolvePendingLibraryNoticeSeverity(libraryApproved, promptReviewReady, true)

    return (
      <PendingLibraryReadyShell
        notice={
          <PendingLibraryNotice
            severity={noticeSeverity}
            message={libraryPromptReviewMessage}
            action={
              <PendingLibraryReadyActions
                onViewLibrary={viewLibraryStep}
                showPromptReviewAction={promptReviewRequiredSnapshot}
                onViewPromptReview={viewPromptReviewStep}
                onResume={resumeGeneration}
                resumeDisabled={libraryResumeDisabled}
                resumeLoading={resumeLoading}
              />
            }
          />
        }
        snapshotPreview={renderRunSnapshotPreviewPane({
          shotEmptyText: t('dreamweaverRun.libraryNoSnapshotAvailable'),
        })}
      />
    )
  }

  return {
    renderLibraryGroupSection,
    renderPendingLibraryReviewView,
    renderPendingLibraryReadyView,
  }
}
