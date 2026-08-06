import { useCallback, useEffect, useMemo, useState } from 'react'

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

  const loadGeneratedChapters = useCallback(async () => {
    if (!projectId) {
      setProjectHistory([])
      return
    }
    try {
      const response = await apiClient.getAudiobookProjectsByProject(projectId, {
        include_chapter_audios: true,
      })
      setProjectHistory(Array.isArray(response.data) ? response.data : [])
    } catch {
      setProjectHistory([])
    }
  }, [projectId])

  useEffect(() => {
    if (!projectId) {
      setProjectHistory([])
      return
    }

    let cancelled = false
    setProjectHistory([])
    const load = async () => {
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

    void load()
    return () => {
      cancelled = true
    }
  }, [projectId])

  const generatedChapterIds = useMemo(
    () => resolveGeneratedChapterIdsFromProjects(projectHistory, currentChapterAudios),
    [currentChapterAudios, projectHistory],
  )

  return { generatedChapterIds, refreshGeneratedChapterIds: loadGeneratedChapters }
}
