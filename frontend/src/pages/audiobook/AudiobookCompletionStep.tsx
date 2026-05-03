import {
  Box,
  Button,
  CircularProgress,
  Paper,
  Typography,
} from '@mui/material'
import CheckIcon from '@mui/icons-material/CheckCircle'
import HeadphonesIcon from '@mui/icons-material/Headphones'

import AudiobookCompletionStats from './AudiobookCompletionStats'
import ChapterAudioResults from './ChapterAudioResults'
import ProjectExportActions from './ProjectExportActions'
import { audiobookButtonSx, audiobookColors } from './audiobookTheme'
import type {
  AudiobookProjectDetail,
  Chapter,
  ChapterAudio,
  GenerationCheckpoint,
} from './types'

interface AudiobookCompletionStepProps {
  audiobookProject: AudiobookProjectDetail | null
  lastGenerationMode: 'full' | 'script_only'
  hasChapterAudios: boolean
  browserPlayerLoading: boolean
  exportingProjectM4b: boolean
  exportingProjectAudacity: boolean
  hasActiveM4bExportTask: boolean
  hasActiveAudacityExportTask: boolean
  currentChapterAudios: ChapterAudio[]
  chapters: Chapter[]
  playingChapter: number | null
  collectingChapterId: number | null
  resumeCheckpoints: Record<number, GenerationCheckpoint>
  generating: boolean
  resumingChapterId: number | null
  hasScriptReview: boolean
  onOpenBrowserPlayer: () => void
  onExportProjectM4b: () => void
  onExportProjectAudacity: () => void
  onPlayAudio: (chapterId: number) => void
  onDownloadAudio: (chapterId: number) => void
  onCollectChapterAudio: (chapterAudio: ChapterAudio) => void
  onOpenScriptEditor: (chapterId: number) => void
  onResumeChapterGeneration: (chapterId: number) => void
  onOpenScriptReview: () => void
  onGenerateApprovedChapterAudio: () => void
  onCreateNewProject: () => void
}

const AudiobookCompletionStep = ({
  audiobookProject,
  lastGenerationMode,
  hasChapterAudios,
  browserPlayerLoading,
  exportingProjectM4b,
  exportingProjectAudacity,
  hasActiveM4bExportTask,
  hasActiveAudacityExportTask,
  currentChapterAudios,
  chapters,
  playingChapter,
  collectingChapterId,
  resumeCheckpoints,
  generating,
  resumingChapterId,
  hasScriptReview,
  onOpenBrowserPlayer,
  onExportProjectM4b,
  onExportProjectAudacity,
  onPlayAudio,
  onDownloadAudio,
  onCollectChapterAudio,
  onOpenScriptEditor,
  onResumeChapterGeneration,
  onOpenScriptReview,
  onGenerateApprovedChapterAudio,
  onCreateNewProject,
}: AudiobookCompletionStepProps) => (
  <Paper sx={{ p: 4, backgroundColor: audiobookColors.surfacePaper }}>
    <Box sx={{ textAlign: 'center', mb: 3 }}>
      <CheckIcon sx={{ fontSize: 80, color: audiobookColors.successMain, mb: 2 }} />
      <Typography variant="h5" sx={{ mb: 2 }}>
        生成完成！
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {lastGenerationMode === 'script_only'
          ? '剧本与评审已生成，接下来可以逐章审稿、修改剧本，再生成音频'
          : '您的有声书已经准备好了'}
      </Typography>
    </Box>

    {audiobookProject && (
      <AudiobookCompletionStats audiobookProject={audiobookProject} />
    )}

    <Box sx={{ display: 'flex', gap: 1.5, justifyContent: 'center', flexWrap: 'wrap', mb: 3 }}>
      {hasChapterAudios && (
        <Button
          variant="contained"
          startIcon={browserPlayerLoading ? <CircularProgress size={18} color="inherit" /> : <HeadphonesIcon />}
          onClick={onOpenBrowserPlayer}
          disabled={browserPlayerLoading}
          color="primary"
        >
          {browserPlayerLoading ? '加载播放器...' : '打开浏览器播放器'}
        </Button>
      )}

      <ProjectExportActions
        hasChapterAudios={hasChapterAudios}
        completedChapters={audiobookProject?.completed_chapters}
        exportingProjectM4b={exportingProjectM4b}
        exportingProjectAudacity={exportingProjectAudacity}
        hasActiveM4bExportTask={hasActiveM4bExportTask}
        hasActiveAudacityExportTask={hasActiveAudacityExportTask}
        onExportProjectM4b={onExportProjectM4b}
        onExportProjectAudacity={onExportProjectAudacity}
      />

      {hasScriptReview && (
        <Button
          variant="outlined"
          onClick={onOpenScriptReview}
          sx={audiobookButtonSx.brandOutlined}
        >
          查看剧本评审
        </Button>
      )}

      {audiobookProject && (
        <Button
          variant="outlined"
          onClick={onGenerateApprovedChapterAudio}
          sx={{
            borderColor: audiobookColors.successMain,
            color: audiobookColors.success,
            '&:hover': {
              borderColor: audiobookColors.success,
              backgroundColor: audiobookColors.successSoft,
            },
          }}
        >
          对已审批章节生成音频
        </Button>
      )}

      <Button
        variant="contained"
        onClick={onCreateNewProject}
        sx={audiobookButtonSx.brandContained}
      >
        生成新项目
      </Button>
    </Box>

    <ChapterAudioResults
      chapterAudios={currentChapterAudios}
      chapters={chapters}
      playingChapter={playingChapter}
      collectingChapterId={collectingChapterId}
      resumeCheckpoints={resumeCheckpoints}
      generating={generating}
      resumingChapterId={resumingChapterId}
      onPlayAudio={onPlayAudio}
      onDownloadAudio={onDownloadAudio}
      onCollectChapterAudio={onCollectChapterAudio}
      onOpenScriptEditor={onOpenScriptEditor}
      onResumeChapterGeneration={onResumeChapterGeneration}
    />
  </Paper>
)

export default AudiobookCompletionStep
