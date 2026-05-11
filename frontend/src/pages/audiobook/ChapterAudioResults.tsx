import {
  Box,
  Typography,
} from '@mui/material'

import ChapterAudioResultItem from './ChapterAudioResultItem'
import type { Chapter, ChapterAudio, GenerationCheckpoint, TtsModel } from './types'

interface ChapterAudioResultsProps {
  chapterAudios: ChapterAudio[]
  chapters: Chapter[]
  playingChapter: number | null
  collectingChapterIds: ReadonlySet<number>
  resumeCheckpoints: Record<number, GenerationCheckpoint>
  generating: boolean
  resumingChapterId: number | null
  ttsModel?: TtsModel
  projectId?: number
  audiobookProjectId?: number
  onPlayAudio: (chapterId: number) => void
  onDownloadAudio: (chapterId: number) => void
  onCollectChapterAudio: (chapterAudio: ChapterAudio) => void
  onOpenScriptEditor: (chapterId: number) => void
  onResumeChapterGeneration: (chapterId: number) => void
  onOpenScriptReview?: (audiobookProjectId: number, chapterId: number) => void
}

const ChapterAudioResults = ({
  chapterAudios,
  chapters,
  playingChapter,
  collectingChapterIds,
  resumeCheckpoints,
  generating,
  resumingChapterId,
  ttsModel,
  projectId,
  audiobookProjectId,
  onPlayAudio,
  onDownloadAudio,
  onCollectChapterAudio,
  onOpenScriptEditor,
  onResumeChapterGeneration,
  onOpenScriptReview,
}: ChapterAudioResultsProps) => {
  if (chapterAudios.length === 0) {
    return null
  }

  return (
    <Box sx={{ width: '100%', mt: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
        章节结果
      </Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
        {chapterAudios.map((chapterAudio) => {
          const chapter = chapters.find((item) => item.id === chapterAudio.chapter_id)
          const isPlaying = playingChapter === chapterAudio.chapter_id
          const isCollecting = collectingChapterIds.has(chapterAudio.chapter_id)
          const resumeCheckpoint = resumeCheckpoints[chapterAudio.chapter_id]

          return (
            <ChapterAudioResultItem
              key={chapterAudio.id}
              chapterAudio={chapterAudio}
              chapter={chapter}
              isPlaying={isPlaying}
              isCollecting={isCollecting}
              collectDisabled={isCollecting}
              resumeCheckpoint={resumeCheckpoint}
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
              onOpenScriptReview={onOpenScriptReview}
            />
          )
        })}
      </Box>
    </Box>
  )
}

export default ChapterAudioResults
