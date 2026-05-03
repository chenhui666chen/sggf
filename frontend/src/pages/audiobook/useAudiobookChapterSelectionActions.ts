import { useCallback, type Dispatch, type SetStateAction } from 'react'

import type { Chapter } from './types'

interface UseAudiobookChapterSelectionActionsParams {
  chapters: Chapter[]
  selectedChapters: number[]
  setSelectedChapters: Dispatch<SetStateAction<number[]>>
}

export const useAudiobookChapterSelectionActions = ({
  chapters,
  selectedChapters,
  setSelectedChapters,
}: UseAudiobookChapterSelectionActionsParams) => {
  const handleToggleChapter = useCallback((chapterId: number) => {
    setSelectedChapters((prev) =>
      prev.includes(chapterId)
        ? prev.filter((id) => id !== chapterId)
        : [...prev, chapterId],
    )
  }, [setSelectedChapters])

  const handleToggleAll = useCallback(() => {
    setSelectedChapters(
      selectedChapters.length === chapters.length
        ? []
        : chapters.map((chapter) => chapter.id),
    )
  }, [chapters, selectedChapters.length, setSelectedChapters])

  return {
    handleToggleChapter,
    handleToggleAll,
  }
}
