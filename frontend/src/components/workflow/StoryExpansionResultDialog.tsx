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
  onClose,
  onCopied,
}: StoryExpansionResultDialogProps) {
  const view = useMemo(() => createStoryExpansionResultView(result), [result])
  const normalizedResult = view?.result ?? null
  const executionModeLabel = getStoryExpansionExecutionModeLabel(normalizedResult?.execution_mode)
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
    }),
    [advisoryMessages, repairedMessages, summary?.label, view, writtenContextLabel],
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
      <DialogTitle sx={{ pb: 1.5 }}>协同扩展结果</DialogTitle>
      <DialogContent dividers sx={{ bgcolor: '#f8fafc' }}>
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
                <StoryExpansionChangeCardsSection cards={resultDisplay.changeCardViews} />
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
          <Typography color="text.secondary">暂无协同结果</Typography>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 2 }}>
        <Button onClick={onClose} variant="contained" sx={{ borderRadius: 2 }}>
          关闭
        </Button>
      </DialogActions>
    </Dialog>
  )
}
