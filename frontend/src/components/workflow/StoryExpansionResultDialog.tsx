import { useMemo, useRef, type RefObject } from 'react'
import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'
import { getStoryExpansionSignals } from '@/utils/storyExpansionFeedback'
import { getStoryExpansionExecutionModeLabel } from '@/utils/storyExpansionLabels'
import { createStoryExpansionResultView } from '@/utils/storyExpansionResultModel'
import {
  createStoryExpansionResultDisplayView,
  type StoryExpansionResultSectionKey,
} from '@/utils/storyExpansionResultView'
import type {
  StoryExpansionResult,
} from '@/types/storyExpansion'
import {
  StoryExpansionChangeCardsSection,
  StoryExpansionDeltaSections,
  StoryExpansionExecutionRoundsSection,
  StoryExpansionFinalSections,
  StoryExpansionOverviewSection,
  StoryExpansionQuickJumpBar,
  StoryExpansionSummarySection,
  type StoryExpansionQuickJumpItemWithRef,
  type StoryExpansionSummaryCard,
} from './StoryExpansionResultSections'

export type StoryExpansionSummary = StoryExpansionSummaryCard

export interface StoryExpansionResultDialogProps {
  open: boolean
  result: StoryExpansionResult | null
  expansionModeLabel: string
  strategyLabel: string
  intentLabel: string
  preserveWrittenModeLabel: string
  writtenContextLabel?: string
  summary: StoryExpansionSummary | null
  repairingAutoImprove?: boolean
  onAutoImprove?: () => void
  onClose: () => void
  onCopied: (message: string) => void
}

export default function StoryExpansionResultDialog({
  open,
  result,
  expansionModeLabel,
  strategyLabel,
  intentLabel,
  preserveWrittenModeLabel,
  writtenContextLabel,
  summary,
  repairingAutoImprove = false,
  onAutoImprove,
  onClose,
  onCopied,
}: StoryExpansionResultDialogProps) {
  const { t } = useTranslation()
  const view = useMemo(() => createStoryExpansionResultView(result), [result])
  const normalizedResult = view?.result ?? null
  const executionModeLabel = getStoryExpansionExecutionModeLabel(normalizedResult?.execution_mode, undefined, t)
  const { repairedMessages, advisoryMessages } = getStoryExpansionSignals(normalizedResult)
  const summaryRef = useRef<HTMLDivElement | null>(null)
  const changesRef = useRef<HTMLDivElement | null>(null)
  const roundsRef = useRef<HTMLDivElement | null>(null)
  const deltaRef = useRef<HTMLDivElement | null>(null)
  const outlineRef = useRef<HTMLDivElement | null>(null)
  const charactersRef = useRef<HTMLDivElement | null>(null)
  const resultDisplay = useMemo(
    () => createStoryExpansionResultDisplayView({
      view,
      summaryLabel: summary?.label,
      writtenContextLabel,
      repairedMessages,
      advisoryMessages,
    }, t),
    [advisoryMessages, repairedMessages, summary?.label, t, view, writtenContextLabel],
  )
  const sectionRefs = useMemo<Record<StoryExpansionResultSectionKey, RefObject<HTMLDivElement | null>>>(
    () => ({
      summary: summaryRef,
      changes: changesRef,
      rounds: roundsRef,
      delta: deltaRef,
      outline: outlineRef,
      characters: charactersRef,
    }),
    [],
  )
  const quickJumpItems = useMemo<StoryExpansionQuickJumpItemWithRef[]>(
    () => resultDisplay.quickJumpItems.map((item) => ({
      ...item,
      targetRef: sectionRefs[item.key],
    })),
    [resultDisplay.quickJumpItems, sectionRefs],
  )
  const autoImproveAction = useMemo(
    () => (
      onAutoImprove && resultDisplay.canAutoImprove
        ? {
          label: resultDisplay.autoImproveActionLabel || t('storyExpansion.result.autoImproveActionLabel'),
          hint: resultDisplay.autoImproveHint,
          loading: repairingAutoImprove,
          onClick: onAutoImprove,
        }
        : null
    ),
    [
      onAutoImprove,
      repairingAutoImprove,
      resultDisplay.autoImproveActionLabel,
      resultDisplay.autoImproveHint,
      resultDisplay.canAutoImprove,
    ],
  )

  const handleCopy = async (text: string, message: string) => {
    if (!text?.trim()) {
      return
    }
    await navigator.clipboard.writeText(text)
    onCopied(message)
  }

  const scrollToSection = (sectionRef: RefObject<HTMLDivElement | null>) => {
    sectionRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    })
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xl" fullWidth>
      <DialogTitle sx={{ pb: 1.5 }}>{t('storyExpansion.resultDialog.title')}</DialogTitle>
      <DialogContent dividers sx={{ bgcolor: 'grey.100' }}>
        {view ? (
          <Stack spacing={2.25}>
            <StoryExpansionOverviewSection
              expansionModeLabel={expansionModeLabel}
              strategyLabel={strategyLabel}
              intentLabel={intentLabel}
              preserveWrittenModeLabel={preserveWrittenModeLabel}
              executionModeLabel={executionModeLabel}
              resultDisplay={resultDisplay}
            />

            {quickJumpItems.length > 1 ? (
              <StoryExpansionQuickJumpBar items={quickJumpItems} onJump={scrollToSection} />
            ) : null}

            {summary ? (
              <Box ref={summaryRef}>
                <StoryExpansionSummarySection summary={summary} />
              </Box>
            ) : null}

            {resultDisplay.hasChangesSection ? (
              <Box ref={changesRef}>
                <StoryExpansionChangeCardsSection
                  cards={resultDisplay.changeCardViews}
                  autoImproveAction={autoImproveAction}
                />
              </Box>
            ) : null}

            {resultDisplay.executionRoundViews.length > 0 ? (
              <Box ref={roundsRef}>
                <StoryExpansionExecutionRoundsSection rounds={resultDisplay.executionRoundViews} />
              </Box>
            ) : null}

            {resultDisplay.hasDeltaSection ? (
              <Box ref={deltaRef}>
                <StoryExpansionDeltaSections sections={resultDisplay.deltaSectionViews} onCopy={handleCopy} />
              </Box>
            ) : null}

            <StoryExpansionFinalSections
              sections={resultDisplay.finalSectionViews}
              sectionRefs={sectionRefs}
              onCopy={handleCopy}
            />
          </Stack>
        ) : (
          <Typography color="text.secondary">{t('storyExpansion.resultDialog.noResult')}</Typography>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 2 }}>
        {autoImproveAction ? (
          <Button
            onClick={autoImproveAction.onClick}
            variant="outlined"
            color="warning"
            disabled={autoImproveAction.loading}
            sx={{ borderRadius: 2 }}
          >
            {autoImproveAction.loading ? t('storyExpansion.resultSections.improving') : autoImproveAction.label}
          </Button>
        ) : null}
        <Button onClick={onClose} variant="contained" sx={{ borderRadius: 2 }}>
          {t('action.close')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
