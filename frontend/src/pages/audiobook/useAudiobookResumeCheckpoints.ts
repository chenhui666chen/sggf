import { useEffect, useMemo, useState } from 'react'

import { apiClient } from '../../services/api'
import type {
  AudiobookProjectDetail,
  Chapter,
  ChapterAudio,
  GenerationCheckpoint,
} from './types'

export interface ResumableChapterEntry {
  chapterAudio: ChapterAudio
  checkpoint?: GenerationCheckpoint
  chapter?: Chapter
}

export const useAudiobookResumeCheckpoints = ({
  audiobookProject,
  chapters,
}: {
  audiobookProject: AudiobookProjectDetail | null
  chapters: Chapter[]
}) => {
  const [resumeCheckpoints, setResumeCheckpoints] = useState<Record<number, GenerationCheckpoint>>({})
  const [resumeCheckpointLoading, setResumeCheckpointLoading] = useState(false)

  const currentChapterAudios = useMemo(
    (): ChapterAudio[] => (Array.isArray(audiobookProject?.chapter_audios) ? audiobookProject.chapter_audios : []),
    [audiobookProject?.chapter_audios],
  )
  const hasChapterAudios = currentChapterAudios.length > 0

  const resumableChapterEntries = useMemo<ResumableChapterEntry[]>(() => {
    return currentChapterAudios
      .map<ResumableChapterEntry>((chapterAudio) => {
        const checkpoint = resumeCheckpoints[chapterAudio.chapter_id]
        const chapter = chapters.find((item) => item.id === chapterAudio.chapter_id)
        return {
          chapterAudio,
          checkpoint,
          chapter,
        }
      })
      .filter((entry) => Boolean(entry.checkpoint?.can_resume))
  }, [chapters, currentChapterAudios, resumeCheckpoints])

  useEffect(() => {
    let cancelled = false

    const loadResumeCheckpoints = async () => {
      const targetAudiobookProjectId = audiobookProject?.id

      if (!targetAudiobookProjectId || currentChapterAudios.length === 0) {
        setResumeCheckpoints({})
        setResumeCheckpointLoading(false)
        return
      }

      const candidateChapterIds: number[] = Array.from(
        new Set<number>(
          currentChapterAudios
            .filter((chapterAudio) => !chapterAudio?.audio_path)
            .map((chapterAudio) => Number(chapterAudio.chapter_id))
            .filter((chapterId: number) => Number.isFinite(chapterId) && chapterId > 0),
        ),
      )

      if (candidateChapterIds.length === 0) {
        setResumeCheckpoints({})
        setResumeCheckpointLoading(false)
        return
      }

      setResumeCheckpointLoading(true)

      try {
        const checkpointEntries = await Promise.all(
          candidateChapterIds.map(async (chapterId) => {
            try {
              const response = await apiClient.getGenerationCheckpoint(targetAudiobookProjectId, chapterId)
              const checkpoint = response.data as GenerationCheckpoint
              if (!checkpoint || typeof checkpoint.chapter_id !== 'number') {
                return null
              }
              return [chapterId, checkpoint] as const
            } catch {
              return null
            }
          }),
        )

        if (cancelled) return

        const nextCheckpoints = checkpointEntries.reduce((acc, entry: readonly [number, GenerationCheckpoint] | null) => {
          if (entry) {
            acc[entry[0]] = entry[1]
          }
          return acc
        }, {} as Record<number, GenerationCheckpoint>)

        setResumeCheckpoints(nextCheckpoints)
      } finally {
        if (!cancelled) {
          setResumeCheckpointLoading(false)
        }
      }
    }

    loadResumeCheckpoints()

    return () => {
      cancelled = true
    }
  }, [audiobookProject?.id, currentChapterAudios])

  return {
    currentChapterAudios,
    hasChapterAudios,
    resumeCheckpoints,
    setResumeCheckpoints,
    resumeCheckpointLoading,
    resumableChapterEntries,
  }
}
