import type { Chapter, ChapterAudio } from './types'


export const resolveGeneratedChapterIds = (
  chapterAudios: readonly ChapterAudio[],
): Set<number> => {
  const generatedChapterIds = new Set<number>()
  for (const chapterAudio of chapterAudios) {
    const scriptStatus = String(chapterAudio.script_status || '').trim().toLowerCase()
    if (
      chapterAudio.has_script
      || Boolean(chapterAudio.audio_path)
      || scriptStatus === 'reviewed'
      || scriptStatus === 'approved'
    ) {
      generatedChapterIds.add(chapterAudio.chapter_id)
    }
  }
  return generatedChapterIds
}

export const resolveGeneratedChapterIdsFromProjects = (
  audiobookProjects: readonly { chapter_audios?: ChapterAudio[] | null }[],
  currentChapterAudios: readonly ChapterAudio[] = [],
): Set<number> => resolveGeneratedChapterIds([
  ...audiobookProjects.flatMap((project) => project.chapter_audios || []),
  ...currentChapterAudios,
])

export const normalizeSingleChapterSelection = ({
  chapters,
  selectedChapterIds,
  lockedChapterIds,
}: {
  chapters: readonly Chapter[]
  selectedChapterIds: readonly number[]
  lockedChapterIds: ReadonlySet<number>
}): number[] => {
  const availableChapterIds = new Set(
    chapters
      .filter((chapter) => !lockedChapterIds.has(chapter.id))
      .map((chapter) => chapter.id),
  )
  const selectedChapterId = selectedChapterIds.find((chapterId) => availableChapterIds.has(chapterId))
  if (selectedChapterId) {
    return [selectedChapterId]
  }
  const firstAvailableChapter = chapters.find((chapter) => availableChapterIds.has(chapter.id))
  return firstAvailableChapter ? [firstAvailableChapter.id] : []
}

export const toggleSingleChapterSelection = ({
  selectedChapterIds,
  chapterId,
  lockedChapterIds,
}: {
  selectedChapterIds: readonly number[]
  chapterId: number
  lockedChapterIds: ReadonlySet<number>
}): number[] => {
  const currentChapterId = selectedChapterIds[0]
  if (lockedChapterIds.has(chapterId)) {
    return currentChapterId ? [currentChapterId] : []
  }
  return [chapterId]
}
