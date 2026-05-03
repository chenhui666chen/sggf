import {
  Box,
  Typography,
} from '@mui/material'

import ChapterAudioResultItem from './ChapterAudioResultItem'
import type { Chapter, ChapterAudio, GenerationCheckpoint } from './types'

interface ChapterAudioResultsProps {
  chapterAudios: ChapterAudio[]
  chapters: Chapter[]
  playingChapter: number | null
  collectingChapterId: number | null
  resumeCheckpoints: Record<number, GenerationCheckpoint>
  generating: boolean
  resumingChapterId: number | null
  onPlayAudio: (chapterId: number) => void
  onDownloadAudio: (chapterId: number) => void
  onCollectChapterAudio: (chapterAudio: ChapterAudio) => void
  onOpenScriptEditor: (chapterId: number) => void
  onResumeChapterGeneration: (chapterId: number) => void
}

const ChapterAudioResults = ({
  chapterAudios,
  chapters,
  playingChapter,
  collectingChapterId,
  resumeCheckpoints,
  generating,
  resumingChapterId,
  onPlayAudio,
  onDownloadAudio,
  onCollectChapterAudio,
  onOpenScriptEditor,
  onResumeChapterGeneration,
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
          const isCollecting = collectingChapterId === chapterAudio.chapter_id
          const resumeCheckpoint = resumeCheckpoints[chapterAudio.chapter_id]

          return (
            <ChapterAudioResultItem
              key={chapterAudio.id}
              chapterAudio={chapterAudio}
              chapter={chapter}
              isPlaying={isPlaying}
              isCollecting={isCollecting}
              collectDisabled={collectingChapterId !== null}
              resumeCheckpoint={resumeCheckpoint}
              generating={generating}
              resumingChapterId={resumingChapterId}
              onPlayAudio={onPlayAudio}
              onDownloadAudio={onDownloadAudio}
              onCollectChapterAudio={onCollectChapterAudio}
              onOpenScriptEditor={onOpenScriptEditor}
              onResumeChapterGeneration={onResumeChapterGeneration}
            />
          )
        })}
      </Box>
    </Box>
  )
}

export default ChapterAudioResults
