export const addCollectingChapterId = (
  chapterIds: ReadonlySet<number>,
  chapterId: number,
): Set<number> => {
  const next = new Set(chapterIds)
  next.add(chapterId)
  return next
}

export const removeCollectingChapterId = (
  chapterIds: ReadonlySet<number>,
  chapterId: number,
): Set<number> => {
  const next = new Set(chapterIds)
  next.delete(chapterId)
  return next
}
