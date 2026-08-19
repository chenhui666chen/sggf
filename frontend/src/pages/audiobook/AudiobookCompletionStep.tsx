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
import AudiobookScriptCompletionStep from './AudiobookScriptCompletionStep'
import ChapterAudioResults from './ChapterAudioResults'
import ProjectExportActions from './ProjectExportActions'
import {
  resolveAudiobookCompletionMode,
  resolveScriptReviewTargetChapterId,
} from './completionViewUtils'
import { audiobookButtonRowSx, audiobookButtonSx, audiobookColors } from './audiobookTheme'
import type {
  AudioEngineMode,
  AudiobookProjectDetail,
  Chapter,
  ChapterAudio,
  GenerationCheckpoint,
  TtsModel,
} from './types'

interface AudiobookCompletionStepProps {
  audiobookProject: AudiobookProjectDetail | null
  lastGenerationMode: 'full' | 'script_only'
  audioEngineMode: AudioEngineMode
  hasChapterAudios: boolean
  browserPlayerLoading: boolean
  exportingProjectM4b: boolean
  exportingProjectAudacity: boolean
  hasActiveM4bExportTask: boolean
  hasActiveAudacityExportTask: boolean
  currentChapterAudios: ChapterAudio[]
  chapters: Chapter[]
  playingChapter: number | null
  collectingChapterIds: ReadonlySet<number>
  resumeCheckpoints: Record<number, GenerationCheckpoint>
  generating: boolean
  resumingChapterId: number | null
  hasScriptReview: boolean
  ttsModel?: TtsModel
  projectId?: number
  audiobookProjectId?: number
  onOpenBrowserPlayer: () => void
  onExportProjectM4b: () => void
  onExportProjectAudacity: () => void
  onPlayAudio: (chapterId: number) => void
  onDownloadAudio: (chapterId: number) => void
  onCollectChapterAudio: (chapterAudio: ChapterAudio) => void
  onOpenScriptEditor: (chapterId: number) => void
  /** GUIDE §2.5：seed_scene 章节审阅入口分流到场景编辑器。 */
  onOpenSceneEditor?: (chapterId: number) => void
  onResumeChapterGeneration: (chapterId: number) => void
  onOpenScriptReview: () => void
  onOpenScriptReviewFromApi?: (audiobookProjectId: number, chapterId: number) => void
  onGenerateApprovedChapterAudio: () => void
  onCreateNewProject: () => void
}

const AudiobookCompletionStep = ({
  audiobookProject,
  lastGenerationMode,
  audioEngineMode,
  hasChapterAudios,
  browserPlayerLoading,
  exportingProjectM4b,
  exportingProjectAudacity,
  hasActiveM4bExportTask,
  hasActiveAudacityExportTask,
  currentChapterAudios,
  chapters,
  playingChapter,
  collectingChapterIds,
  resumeCheckpoints,
  generating,
  resumingChapterId,
  hasScriptReview,
  ttsModel,
  projectId,
  audiobookProjectId,
  onOpenBrowserPlayer,
  onExportProjectM4b,
  onExportProjectAudacity,
  onPlayAudio,
  onDownloadAudio,
  onCollectChapterAudio,
  onOpenScriptEditor,
  onOpenSceneEditor,
  onResumeChapterGeneration,
  onOpenScriptReview,
  onOpenScriptReviewFromApi,
  onGenerateApprovedChapterAudio,
  onCreateNewProject,
}: AudiobookCompletionStepProps) => {
  const completionMode = resolveAudiobookCompletionMode({
    requestedMode: lastGenerationMode,
    chapterAudios: currentChapterAudios,
  })
  const scriptEditorTargetChapterId = resolveScriptReviewTargetChapterId(currentChapterAudios)

  if (completionMode === 'script_only') {
    return (
      <AudiobookScriptCompletionStep
        audioEngineMode={audioEngineMode}
        currentChapterAudios={currentChapterAudios}
        chapters={chapters}
        generating={generating}
        hasScriptReview={hasScriptReview}
        audiobookProjectId={audiobookProjectId}
        onOpenScriptEditor={onOpenScriptEditor}
        onOpenSceneEditor={onOpenSceneEditor}
        onOpenScriptReview={onOpenScriptReview}
        onOpenScriptReviewFromApi={onOpenScriptReviewFromApi}
        onGenerateApprovedChapterAudio={onGenerateApprovedChapterAudio}
        onCreateNewProject={onCreateNewProject}
      />
    )
  }

  return (
    <Paper sx={{ p: 4, backgroundColor: audiobookColors.surfacePaper }}>
      <Box sx={{ textAlign: 'center', mb: 3 }}>
        <CheckIcon sx={{ fontSize: 64, color: audiobookColors.successMain, mb: 1.5 }} />
        <Typography variant="h5" sx={{ mb: 1 }}>
          音频生成完成
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          {audioEngineMode === 'seed_scene'
            ? '场景音频已完成渲染，可以试听、验收或导出。'
            : '章节音频已生成，可以试听、验收或导出。'}
        </Typography>
      </Box>

      {audiobookProject && (
        <AudiobookCompletionStats audiobookProject={audiobookProject} />
      )}

      <Box sx={audiobookButtonRowSx.centeredWrap}>
        {hasChapterAudios && (
          <Button
            variant="contained"
            startIcon={browserPlayerLoading ? <CircularProgress size={18} color="inherit" /> : <HeadphonesIcon />}
            onClick={onOpenBrowserPlayer}
            disabled={browserPlayerLoading}
            sx={audiobookButtonSx.brandContained}
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
            onClick={() => {
              if (scriptEditorTargetChapterId) {
                onOpenScriptEditor(scriptEditorTargetChapterId)
              }
            }}
            disabled={!scriptEditorTargetChapterId}
            sx={audiobookButtonSx.brandOutlined}
          >
            打开剧本编辑器
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
        collectingChapterIds={collectingChapterIds}
        resumeCheckpoints={resumeCheckpoints}
        generating={generating}
        resumingChapterId={resumingChapterId}
        ttsModel={ttsModel}
        projectId={projectId}
        audiobookProjectId={audiobookProjectId}
        onPlayAudio={onPlayAudio}
        onDownloadAudio={onDownloadAudio}
        onCollectChapterAudio={onCollectChapterAudio}
        onOpenScriptEditor={onOpenScriptEditor}
        onResumeChapterGeneration={onResumeChapterGeneration}
        onOpenScriptReview={onOpenScriptReviewFromApi}
      />
    </Paper>
  )
}

export default AudiobookCompletionStep
