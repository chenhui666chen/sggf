import { useEffect, useMemo, useState } from 'react'

import { apiClient } from '../../services/api'
import { resolveGeneratedChapterIdsFromProjects } from './chapterSelectionUtils'
import type { AudiobookProjectDetail, ChapterAudio } from './types'


export const useAudiobookGeneratedChapterIds = ({
  projectId,
  currentChapterAudios,
}: {
  projectId: number | null
  currentChapterAudios: ChapterAudio[]
}) => {
  const [projectHistory, setProjectHistory] = useState<AudiobookProjectDetail[]>([])

  useEffect(() => {
    if (!projectId) {
      setProjectHistory([])
      return
    }

    let cancelled = false
    setProjectHistory([])
    const loadGeneratedChapters = async () => {
      try {
        const response = await apiClient.getAudiobookProjectsByProject(projectId, {
          include_chapter_audios: true,
        })
        if (!cancelled) {
          setProjectHistory(Array.isArray(response.data) ? response.data : [])
        }
      } catch {
        if (!cancelled) {
          setProjectHistory([])
        }
      }
    }

    void loadGeneratedChapters()
    return () => {
      cancelled = true
    }
  }, [projectId])

  return useMemo(
    () => resolveGeneratedChapterIdsFromProjects(projectHistory, currentChapterAudios),
    [currentChapterAudios, projectHistory],
  )
}
