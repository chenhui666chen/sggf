import { useMemo, type RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Chip,
  Grid,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import type { Theme } from '@mui/material/styles'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import FormattedContent from '../common/FormattedContent'
import { withAlpha } from '@/theme'
import {
  formatStoryExpansionDocument,
  type StoryExpansionContentKind,
} from '@/utils/storyExpansionResultFormatter'
import type {
  StoryExpansionChangeCardTone,
  StoryExpansionChangeCardView,
  StoryExpansionDeltaSectionView,
  StoryExpansionExecutionRoundView,
  StoryExpansionFinalSectionView,
  StoryExpansionResultDisplayView,
  StoryExpansionResultQuickJumpItem,
  StoryExpansionResultSectionKey,
} from '@/utils/storyExpansionResultView'

export interface StoryExpansionSummaryCard {
  label: string
  text: string
}

export interface StoryExpansionQuickJumpItemWithRef extends StoryExpansionResultQuickJumpItem {
  targetRef: RefObject<HTMLDivElement | null>
}

interface MetricCardProps {
  label: string
  value: string
  helperText?: string
  accentColor?: string
}

interface TextSectionCardProps {
  title: string
  content: string
  emptyText?: string
  contentKind?: StoryExpansionContentKind
  minHeight?: number
  onCopy?: () => void
}

function getChangeCardAppearance(tone: StoryExpansionChangeCardTone): {
  borderColor: string | ((theme: Theme) => string)
  background?: string | ((theme: Theme) => string)
  backgroundColor?: string | ((theme: Theme) => string)
  itemBackground: string | ((theme: Theme) => string)
} {
  if (tone === 'success') {
    return {
      // 状态卡：边框与底色走 success 语义 token，双模反相
      borderColor: (theme) => withAlpha(theme.palette.success.main, 0.24),
      background: (theme) =>
        `linear-gradient(180deg, ${theme.palette.success.light} 0%, ${theme.palette.background.paper} 100%)`,
      itemBackground: (theme) => withAlpha(theme.palette.success.main, 0.05),
    }
  }

  if (tone === 'warning') {
    return {
      borderColor: (theme) => withAlpha(theme.palette.warning.main, 0.25),
      background: (theme) =>
        `linear-gradient(180deg, ${theme.palette.warning.light} 0%, ${theme.palette.background.paper} 100%)`,
      itemBackground: (theme) => withAlpha(theme.palette.warning.main, 0.05),
    }
  }

  return {
    borderColor: 'divider',
    backgroundColor: 'background.paper',
    itemBackground: 'grey.100',
  }
}

function MetricCard({
  label,
  value,
  helperText,
  accentColor = '#0f766e', // sg-color-fixed: 模块 teal 指标色（颜色即数据）
}: MetricCardProps) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.75,
        height: '100%',
        borderRadius: 2,
        borderColor: 'rgba(15, 118, 110, 0.16)', // sg-color-fixed: teal 品牌边框（低 alpha 数据色）
        background: (theme) =>
          `linear-gradient(180deg, ${theme.palette.background.paper} 0%, ${theme.palette.grey[100]} 100%)`,
      }}
    >
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography
        variant="h6"
        sx={{
          mt: 0.6,
          fontWeight: 700,
          color: accentColor,
          lineHeight: 1.25,
          wordBreak: 'break-word',
        }}
      >
        {value}
      </Typography>
      {helperText ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
          {helperText}
        </Typography>
      ) : null}
    </Paper>
  )
}

function TextSectionCard({
  title,
  content,
  emptyText,
  contentKind = 'generic',
  minHeight = 220,
  onCopy,
}: TextSectionCardProps) {
  const { t } = useTranslation()
  const formattedContent = useMemo(
    () => formatStoryExpansionDocument(content || '', contentKind),
    [content, contentKind],
  )

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        height: '100%',
        borderRadius: 2.5,
        border: '1px solid',
        borderColor: 'divider',
        backgroundColor: 'background.paper',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 1,
          mb: 1.5,
        }}
      >
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        {onCopy ? (
          <Button
            size="small"
            variant="outlined"
            startIcon={<ContentCopyIcon fontSize="small" />}
            onClick={onCopy}
            sx={{ borderRadius: 1.5, textTransform: 'none' }}
          >
            {t('storyExpansion.resultSections.copy')}
          </Button>
        ) : null}
      </Box>

      <Box
        sx={{
          maxHeight: minHeight,
          minHeight: Math.min(minHeight, 180),
          overflow: 'auto',
          p: 2,
          borderRadius: 2,
          border: '1px solid',
          borderColor: 'divider',
          bgcolor: 'grey.100',
        }}
      >
        {formattedContent ? (
          <FormattedContent
            content={formattedContent}
            sx={{
              fontSize: '0.92rem',
              lineHeight: 1.8,
              '& p:first-of-type': {
                marginTop: 0,
              },
              '& p:last-of-type': {
                marginBottom: 0,
              },
            }}
          />
        ) : (
          <Typography variant="body2" color="text.secondary">
            {emptyText || t('storyExpansion.resultSections.emptyContent')}
          </Typography>
        )}
      </Box>
    </Paper>
  )
}

interface StoryExpansionOverviewSectionProps {
  expansionModeLabel: string
  strategyLabel: string
  intentLabel: string
  preserveWrittenModeLabel: string
  executionModeLabel: string
  resultDisplay: StoryExpansionResultDisplayView
}

export function StoryExpansionOverviewSection({
  expansionModeLabel,
  strategyLabel,
  intentLabel,
  preserveWrittenModeLabel,
  executionModeLabel,
  resultDisplay,
}: StoryExpansionOverviewSectionProps) {
  const { t } = useTranslation()
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2.25,
        borderRadius: 3,
        border: '1px solid',
        borderColor: 'rgba(15, 118, 110, 0.18)', // sg-color-fixed: teal 品牌边框（低 alpha 数据色）
        background: (theme) =>
          `linear-gradient(135deg, ${withAlpha(theme.palette.success.main, 0.05)} 0%, ${theme.palette.grey[100]} 52%, ${theme.palette.background.paper} 100%)`,
      }}
    >
      <Stack spacing={1.5}>
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
            gap: 2,
            flexWrap: 'wrap',
          }}
        >
          <Box>
            <Typography
              variant="overline"
              sx={{
                color: '#0f766e', // sg-color-fixed: teal 品牌字色（颜色即数据）
                letterSpacing: 1.4,
              }}
            >
              {t('storyExpansion.resultSections.overviewTitle')}
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.5 }}>
              {expansionModeLabel}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              {resultDisplay.executionModeReasonText}
            </Typography>
            <Typography
              variant="body2"
              sx={{
                mt: 0.75,
                fontWeight: 600,
                color: resultDisplay.completionStatusTone === 'warning' ? '#b45309' : '#0f766e', // sg-color-fixed: 完成状态数据色（琥珀/teal）
              }}
            >
              {resultDisplay.completionStatusDescription}
            </Typography>
          </Box>

          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip
              label={resultDisplay.completionStatusLabel}
              color={resultDisplay.completionStatusTone}
              variant="filled"
            />
            {resultDisplay.remainingGoalChipLabel ? (
              <Chip label={resultDisplay.remainingGoalChipLabel} color="warning" variant="outlined" />
            ) : null}
            <Chip label={t('storyExpansion.resultSections.strategyChip', { label: strategyLabel })} color="primary" variant="outlined" />
            <Chip label={t('storyExpansion.resultSections.intentChip', { label: intentLabel })} color="secondary" variant="outlined" />
            <Chip label={t('storyExpansion.resultSections.writtenContextChip', { label: preserveWrittenModeLabel })} variant="outlined" />
            <Chip label={t('storyExpansion.resultSections.executionModeChip', { label: executionModeLabel })} variant="outlined" />
          </Stack>
        </Box>

        <Grid container spacing={1.5}>
          <Grid item xs={12} sm={6} lg={3}>
            <MetricCard
              label={t('storyExpansion.resultSections.metricChapters')}
              value={resultDisplay.chapterMetricValue}
              accentColor="#0f766e" // sg-color-fixed: 状态数据色
            />
          </Grid>
          <Grid item xs={12} sm={6} lg={3}>
            <MetricCard
              label={t('storyExpansion.resultSections.metricCharacters')}
              value={resultDisplay.characterMetricValue}
              accentColor="#15803d" // sg-color-fixed: 状态数据色
            />
          </Grid>
          <Grid item xs={12} sm={6} lg={3}>
            <MetricCard
              label={t('storyExpansion.resultSections.metricScore')}
              value={resultDisplay.scoreMetricValue}
              helperText={resultDisplay.scoreMetricHelperText}
              accentColor="#b45309" // sg-color-fixed: 状态数据色
            />
          </Grid>
          <Grid item xs={12} sm={6} lg={3}>
            <MetricCard
              label={t('storyExpansion.resultSections.metricRounds')}
              value={resultDisplay.roundsMetricValue}
              helperText={resultDisplay.roundsMetricHelperText}
              accentColor="#1d4ed8" // sg-color-fixed: 状态数据色
            />
          </Grid>
        </Grid>

        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          <Chip
            label={resultDisplay.addedChapterChipLabel}
            color={resultDisplay.addedChapterCount > 0 ? 'success' : 'default'}
            variant="outlined"
          />
          <Chip
            label={resultDisplay.addedCharacterChipLabel}
            color={resultDisplay.addedCharacterCount > 0 ? 'secondary' : 'default'}
            variant="outlined"
          />
          {resultDisplay.executionRoundsChipLabel ? (
            <Chip label={resultDisplay.executionRoundsChipLabel} variant="outlined" />
          ) : null}
          {resultDisplay.alignmentRepairsChipLabel ? (
            <Chip
              label={resultDisplay.alignmentRepairsChipLabel}
              color="success"
              variant="outlined"
            />
          ) : null}
          {resultDisplay.alignmentWarningsChipLabel ? (
            <Chip
              label={resultDisplay.alignmentWarningsChipLabel}
              color="warning"
              variant="outlined"
            />
          ) : null}
        </Stack>
      </Stack>
    </Paper>
  )
}

interface StoryExpansionQuickJumpBarProps {
  items: StoryExpansionQuickJumpItemWithRef[]
  onJump: (sectionRef: RefObject<HTMLDivElement | null>) => void
}

export function StoryExpansionQuickJumpBar({
  items,
  onJump,
}: StoryExpansionQuickJumpBarProps) {
  const { t } = useTranslation()
  return (
    <Paper
      elevation={0}
      sx={{
        p: 1.5,
        borderRadius: 2.5,
        border: '1px solid',
        borderColor: 'divider',
        backgroundColor: (theme) => withAlpha(theme.palette.background.paper, 0.92),
        backdropFilter: 'blur(8px)',
        position: 'sticky',
        top: -17,
        zIndex: 2,
      }}
    >
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
        {t('storyExpansion.resultSections.quickJumpTitle')}
      </Typography>
      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
        {items.map((item) => (
          <Chip
            key={item.key}
            label={item.label}
            clickable
            onClick={() => onJump(item.targetRef)}
            variant="outlined"
            sx={{ borderRadius: 1.5 }}
          />
        ))}
      </Stack>
    </Paper>
  )
}

interface StoryExpansionSummarySectionProps {
  summary: StoryExpansionSummaryCard
}

export function StoryExpansionSummarySection({
  summary,
}: StoryExpansionSummarySectionProps) {
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2.5,
        border: '1px solid',
        borderColor: 'divider',
        backgroundColor: 'background.paper',
      }}
    >
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        {summary.label}
      </Typography>
      <FormattedContent
        content={summary.text}
        sx={{
          fontSize: '0.95rem',
          lineHeight: 1.8,
          '& p': { margin: 0 },
        }}
      />
    </Paper>
  )
}

interface StoryExpansionChangeCardsSectionProps {
  cards: StoryExpansionChangeCardView[]
  autoImproveAction?: {
    label: string
    hint?: string | null
    loading: boolean
    onClick: () => void
  } | null
}

export function StoryExpansionChangeCardsSection({
  cards,
  autoImproveAction,
}: StoryExpansionChangeCardsSectionProps) {
  const { t } = useTranslation()
  return (
    <Grid container spacing={2}>
      {cards.map((card) => {
        const appearance = getChangeCardAppearance(card.tone)

        return (
          <Grid item xs={12} md={card.kind === 'outline_operations' ? true : 4} key={card.key}>
            <Paper
              elevation={0}
              sx={{
                p: 2,
                height: '100%',
                borderRadius: 2.5,
                border: '1px solid',
                borderColor: appearance.borderColor,
                ...(appearance.background ? { background: appearance.background } : {}),
                ...(appearance.backgroundColor ? { backgroundColor: appearance.backgroundColor } : {}),
              }}
            >
              <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.25 }}>
                {card.title}
              </Typography>

              {card.kind === 'chips' ? (
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  {card.chips.map((name) => (
                    <Chip key={name} label={name} color="secondary" variant="outlined" />
                  ))}
                </Box>
              ) : null}

              {card.kind === 'messages' ? (
                <Stack spacing={1}>
                  {card.messages.map((message, index) => (
                    <Paper
                      key={`${message}-${index}`}
                      variant="outlined"
                      sx={{ p: 1.25, borderRadius: 2, bgcolor: appearance.itemBackground }}
                    >
                      <Typography variant="body2" color="text.secondary">
                        {message}
                      </Typography>
                    </Paper>
                  ))}
                  {card.key === 'score-improvements' && autoImproveAction ? (
                    <Box sx={{ pt: 0.5 }}>
                      <Button
                        variant="contained"
                        color="warning"
                        onClick={autoImproveAction.onClick}
                        disabled={autoImproveAction.loading}
                        sx={{ borderRadius: 2, textTransform: 'none' }}
                      >
                        {autoImproveAction.loading ? t('storyExpansion.resultSections.improving') : autoImproveAction.label}
                      </Button>
                      {autoImproveAction.hint ? (
                        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.9 }}>
                          {autoImproveAction.hint}
                        </Typography>
                      ) : null}
                    </Box>
                  ) : null}
                </Stack>
              ) : null}

              {card.kind === 'outline_operations' ? (
                <Stack spacing={1.25}>
                  {card.outlineOperations.map((op) => (
                    <Paper
                      key={op.key}
                      variant="outlined"
                      sx={{ p: 1.5, borderRadius: 2 }}
                    >
                      <Stack
                        direction="row"
                        spacing={1}
                        useFlexGap
                        flexWrap="wrap"
                        alignItems="center"
                        sx={{ mb: op.goal ? 0.75 : 0 }}
                      >
                        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                          {op.title}
                        </Typography>
                        <Chip
                          size="small"
                          label={op.requestedLabel}
                          variant="outlined"
                        />
                        <Chip
                          size="small"
                          label={op.generatedLabel}
                          color="success"
                          variant="outlined"
                        />
                      </Stack>
                      {op.goal ? (
                        <Typography variant="body2" color="text.secondary">
                          {op.goal}
                        </Typography>
                      ) : null}
                      {op.generatedTitles.length > 0 ? (
                        <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 1 }}>
                          {op.generatedTitles.map((title) => (
                            <Chip key={title} label={title} size="small" />
                          ))}
                        </Box>
                      ) : null}
                    </Paper>
                  ))}
                </Stack>
              ) : null}
            </Paper>
          </Grid>
        )
      })}
    </Grid>
  )
}

interface StoryExpansionExecutionRoundsSectionProps {
  rounds: StoryExpansionExecutionRoundView[]
}

export function StoryExpansionExecutionRoundsSection({
  rounds,
}: StoryExpansionExecutionRoundsSectionProps) {
  const { t } = useTranslation()
  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        borderRadius: 2.5,
        border: '1px solid',
        borderColor: 'divider',
        backgroundColor: 'background.paper',
      }}
    >
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.25 }}>
        {t('storyExpansion.resultSections.roundsDetailTitle')}
      </Typography>
      <Grid container spacing={1.5}>
        {rounds.map((round) => (
          <Grid item xs={12} md={6} xl={4} key={round.key}>
            <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, height: '100%' }}>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 1 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                  {round.title}
                </Typography>
                {round.tailSupplementLabel ? (
                  <Chip
                    size="small"
                    label={round.tailSupplementLabel}
                    color="warning"
                    variant="outlined"
                  />
                ) : null}
                {round.strategyLabel ? (
                  <Chip size="small" label={round.strategyLabel} variant="outlined" />
                ) : null}
              </Stack>

              <Stack spacing={0.6}>
                <Typography variant="body2" color="text.secondary">
                  {round.chapterRangeText}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {round.characterRangeText}
                </Typography>
                {round.plotIncrementText ? (
                  <Typography variant="body2" color="text.secondary">
                    {round.plotIncrementText}
                  </Typography>
                ) : null}
                {round.characterIncrementText ? (
                  <Typography variant="body2" color="text.secondary">
                    {round.characterIncrementText}
                  </Typography>
                ) : null}
                {round.postValidationScoreText ? (
                  <Typography variant="body2" color="text.secondary">
                    {round.postValidationScoreText}
                  </Typography>
                ) : null}
              </Stack>
            </Paper>
          </Grid>
        ))}
      </Grid>
    </Paper>
  )
}

interface StoryExpansionDeltaSectionsProps {
  sections: StoryExpansionDeltaSectionView[]
  onCopy: (text: string, message: string) => void
}

export function StoryExpansionDeltaSections({
  sections,
  onCopy,
}: StoryExpansionDeltaSectionsProps) {
  return (
    <Grid container spacing={2}>
      {sections.map((section) => (
        <Grid item xs={12} lg={4} key={section.key}>
          <TextSectionCard
            title={section.title}
            content={section.content}
            contentKind={section.contentKind}
            minHeight={260}
            onCopy={() => onCopy(section.content, section.copyMessage)}
          />
        </Grid>
      ))}
    </Grid>
  )
}

interface StoryExpansionFinalSectionsProps {
  sections: StoryExpansionFinalSectionView[]
  sectionRefs: Record<StoryExpansionResultSectionKey, RefObject<HTMLDivElement | null>>
  onCopy: (text: string, message: string) => void
}

export function StoryExpansionFinalSections({
  sections,
  sectionRefs,
  onCopy,
}: StoryExpansionFinalSectionsProps) {
  return (
    <Grid container spacing={2}>
      {sections.map((section) => (
        <Grid item xs={12} lg={section.lg} key={section.key}>
          <Box ref={sectionRefs[section.key]} sx={{ height: '100%' }}>
            <TextSectionCard
              title={section.title}
              content={section.content}
              contentKind={section.contentKind}
              minHeight={560}
              onCopy={() => onCopy(section.content, section.copyMessage)}
            />
          </Box>
        </Grid>
      ))}
    </Grid>
  )
}
