import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import EditNoteIcon from '@mui/icons-material/EditNote'
import FactCheckIcon from '@mui/icons-material/FactCheck'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import { useTranslation } from 'react-i18next'

import ChapterScriptResults from './ChapterScriptResults'
import {
  buildScriptCompletionSummary,
  resolveScriptReviewTargetChapterId,
} from './completionViewUtils'
import {
  audiobookButtonSx,
  audiobookColors,
  audiobookPanelSx,
} from './audiobookTheme'
import type { AudioEngineMode, Chapter, ChapterAudio } from './types'

interface AudiobookScriptCompletionStepProps {
  audioEngineMode: AudioEngineMode
  currentChapterAudios: ChapterAudio[]
  chapters: Chapter[]
  generating: boolean
  hasScriptReview: boolean
  audiobookProjectId?: number
  onOpenScriptEditor: (chapterId: number) => void
  /** GUIDE §2.5：seed_scene 章节的审阅入口分流到场景编辑器。 */
  onOpenSceneEditor?: (chapterId: number) => void
  onOpenScriptReview: () => void
  onOpenScriptReviewFromApi?: (audiobookProjectId: number, chapterId: number) => void
  onGenerateApprovedChapterAudio: () => void
  onCreateNewProject: () => void
}

const AudiobookScriptCompletionStep = ({
  audioEngineMode,
  currentChapterAudios,
  chapters,
  generating,
  hasScriptReview,
  audiobookProjectId,
  onOpenScriptEditor,
  onOpenSceneEditor,
  onOpenScriptReview,
  onOpenScriptReviewFromApi,
  onGenerateApprovedChapterAudio,
  onCreateNewProject,
}: AudiobookScriptCompletionStepProps) => {
  const { t } = useTranslation()
  const summary = buildScriptCompletionSummary(currentChapterAudios)
  const reviewTargetChapterId = resolveScriptReviewTargetChapterId(currentChapterAudios)
  const isSeedScene = audioEngineMode === 'seed_scene'
  const canGenerateAudio = summary.approvedChapterCount > 0 && !generating
  const generateTooltip = summary.approvedChapterCount === 0
    ? t('audiobook.audiobookScriptCompletionStep.approveFirstTooltip')
    : generating
      ? t('audiobook.audiobookScriptCompletionStep.taskRunningTooltip')
      : ''
  const summaryItems = [
    { label: t('audiobook.audiobookScriptCompletionStep.scriptChapters'), value: summary.scriptChapterCount },
    { label: t('audiobook.audiobookScriptCompletionStep.scriptSegments'), value: summary.segmentCount },
    { label: t('audiobook.audiobookScriptCompletionStep.autoReviewed'), value: summary.reviewedChapterCount },
    { label: t('audiobook.audiobookScriptCompletionStep.approved'), value: summary.approvedChapterCount },
  ]

  return (
    <Paper
      component="section"
      variant="outlined"
      sx={{
        ...audiobookPanelSx,
        p: { xs: 2, sm: 3 },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: { xs: 'flex-start', sm: 'center' },
          justifyContent: 'space-between',
          flexDirection: { xs: 'column', sm: 'row' },
          gap: 2,
          mb: 2.5,
        }}
      >
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5, minWidth: 0 }}>
          <Box
            sx={{
              width: 44,
              height: 44,
              flexShrink: 0,
              display: 'grid',
              placeItems: 'center',
              borderRadius: 1,
              color: audiobookColors.success,
              backgroundColor: audiobookColors.successSoft,
            }}
          >
            <CheckCircleOutlineIcon />
          </Box>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>
              {t('audiobook.audiobookScriptCompletionStep.title')}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {t('audiobook.audiobookScriptCompletionStep.subtitle')}
            </Typography>
          </Box>
        </Box>
        <Chip
          size="small"
          icon={<GraphicEqIcon />}
          label={isSeedScene
            ? t('audiobook.audiobookScriptCompletionStep.seedEngineChip')
            : t('audiobook.audiobookScriptCompletionStep.trackEngineChip')}
          color={isSeedScene ? 'primary' : 'default'}
          variant="outlined"
          sx={{ flexShrink: 0 }}
        />
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: 'repeat(2, minmax(0, 1fr))', md: 'repeat(4, minmax(0, 1fr))' },
          borderTop: '1px solid',
          borderBottom: '1px solid',
          borderColor: 'divider',
          mb: 2.5,
        }}
      >
        {summaryItems.map((item) => (
          <Box key={item.label} sx={{ px: { xs: 1, sm: 2 }, py: 1.75, textAlign: 'center' }}>
            <Typography variant="h5" sx={{ fontWeight: 700, color: 'text.primary' }}>
              {item.value}
            </Typography>
            <Typography variant="caption" color="text.secondary">
              {item.label}
            </Typography>
          </Box>
        ))}
      </Box>

      <Box
        sx={{
          display: 'flex',
          gap: 1.25,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <Button
          variant="contained"
          startIcon={<EditNoteIcon />}
          disabled={reviewTargetChapterId === null}
          onClick={() => {
            if (reviewTargetChapterId === null) return
            // GUIDE §2.5：seed_scene 章节走场景编辑器，避免落入 legacy 单片段工作台
            if (isSeedScene && onOpenSceneEditor) {
              onOpenSceneEditor(reviewTargetChapterId)
              return
            }
            onOpenScriptEditor(reviewTargetChapterId)
          }}
          sx={audiobookButtonSx.brandContained}
        >
          {t('audiobook.audiobookScriptCompletionStep.reviewAndApprove')}
        </Button>

        {hasScriptReview && (
          <Button
            variant="outlined"
            startIcon={<FactCheckIcon />}
            onClick={onOpenScriptReview}
            sx={audiobookButtonSx.brandOutlined}
          >
            {t('audiobook.audiobookScriptCompletionStep.viewAutoReview')}
          </Button>
        )}

        <Tooltip title={generateTooltip} disableHoverListener={!generateTooltip}>
          <span>
            <Button
              variant="contained"
              color="success"
              startIcon={generating ? <CircularProgress size={18} color="inherit" /> : <GraphicEqIcon />}
              disabled={!canGenerateAudio}
              onClick={onGenerateApprovedChapterAudio}
            >
              {generating
                ? t('audiobook.audiobookScriptCompletionStep.submitting')
                : isSeedScene
                  ? t('audiobook.audiobookScriptCompletionStep.generateSceneAudio')
                  : t('audiobook.audiobookScriptCompletionStep.generateTrackAudio')}
            </Button>
          </span>
        </Tooltip>

        <Button
          variant="text"
          startIcon={<AddIcon />}
          onClick={onCreateNewProject}
          sx={{ ml: { xs: 0, md: 'auto' } }}
        >
          {t('audiobook.audiobookScriptCompletionStep.startNewProject')}
        </Button>
      </Box>

      {summary.pendingApprovalCount > 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          {t('audiobook.audiobookScriptCompletionStep.pendingApprovalHint', { total: summary.pendingApprovalCount })}
        </Typography>
      )}

      <ChapterScriptResults
        chapterAudios={currentChapterAudios}
        chapters={chapters}
        audiobookProjectId={audiobookProjectId}
        audioEngineMode={audioEngineMode}
        onOpenScriptEditor={onOpenScriptEditor}
        onOpenSceneEditor={onOpenSceneEditor}
        onOpenScriptReview={onOpenScriptReviewFromApi}
      />
    </Paper>
  )
}

export default AudiobookScriptCompletionStep
