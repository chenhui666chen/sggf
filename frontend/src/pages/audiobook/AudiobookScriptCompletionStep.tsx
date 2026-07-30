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
  onOpenScriptReview,
  onOpenScriptReviewFromApi,
  onGenerateApprovedChapterAudio,
  onCreateNewProject,
}: AudiobookScriptCompletionStepProps) => {
  const summary = buildScriptCompletionSummary(currentChapterAudios)
  const reviewTargetChapterId = resolveScriptReviewTargetChapterId(currentChapterAudios)
  const isSeedScene = audioEngineMode === 'seed_scene'
  const canGenerateAudio = summary.approvedChapterCount > 0 && !generating
  const generateTooltip = summary.approvedChapterCount === 0
    ? '请先批准至少一个章节剧本'
    : generating
      ? '当前已有生成任务正在执行'
      : ''
  const summaryItems = [
    { label: '剧本章节', value: summary.scriptChapterCount },
    { label: '剧本片段', value: summary.segmentCount },
    { label: '自动评审', value: summary.reviewedChapterCount },
    { label: '已批准', value: summary.approvedChapterCount },
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
              场景剧本已生成
            </Typography>
            <Typography variant="body2" color="text.secondary">
              台词、角色表演与声场设计已就绪，等待审阅批准。
            </Typography>
          </Box>
        </Box>
        <Chip
          size="small"
          icon={<GraphicEqIcon />}
          label={isSeedScene ? 'Seed Audio 1.0 · 等待渲染' : '分轨音频引擎 · 等待生成'}
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
            if (reviewTargetChapterId !== null) {
              onOpenScriptEditor(reviewTargetChapterId)
            }
          }}
          sx={audiobookButtonSx.brandContained}
        >
          审阅并批准
        </Button>

        {hasScriptReview && (
          <Button
            variant="outlined"
            startIcon={<FactCheckIcon />}
            onClick={onOpenScriptReview}
            sx={audiobookButtonSx.brandOutlined}
          >
            查看自动评审
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
                ? '正在提交...'
                : isSeedScene
                  ? '生成场景音频'
                  : '生成分轨音频'}
            </Button>
          </span>
        </Tooltip>

        <Button
          variant="text"
          startIcon={<AddIcon />}
          onClick={onCreateNewProject}
          sx={{ ml: { xs: 0, md: 'auto' } }}
        >
          开始新项目
        </Button>
      </Box>

      {summary.pendingApprovalCount > 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          还有 {summary.pendingApprovalCount} 个章节等待批准
        </Typography>
      )}

      <ChapterScriptResults
        chapterAudios={currentChapterAudios}
        chapters={chapters}
        audiobookProjectId={audiobookProjectId}
        onOpenScriptEditor={onOpenScriptEditor}
        onOpenScriptReview={onOpenScriptReviewFromApi}
      />
    </Paper>
  )
}

export default AudiobookScriptCompletionStep
