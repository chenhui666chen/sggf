export interface ChapterNumberLike {
  id?: number | null
  chapter_number?: number | null
}

export function selectLatestChapterForOverwrite<T extends ChapterNumberLike>(
  chapters: T[] | null | undefined,
): T | null {
  if (!Array.isArray(chapters) || chapters.length === 0) {
    return null
  }

  return chapters.reduce<T | null>((latest, chapter) => {
    const chapterNumber = Number(chapter?.chapter_number)
    if (!Number.isFinite(chapterNumber)) {
      return latest
    }
    if (!latest) {
      return chapter
    }
    const latestNumber = Number(latest.chapter_number)
    if (!Number.isFinite(latestNumber) || chapterNumber > latestNumber) {
      return chapter
    }
    return latest
  }, null)
}