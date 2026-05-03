import { useState } from 'react'

export const useAudiobookRuntimeState = () => {
  const [playingChapter, setPlayingChapter] = useState<number | null>(null)
  const [resumingChapterId, setResumingChapterId] = useState<number | null>(null)

  return {
    playingChapter,
    setPlayingChapter,
    resumingChapterId,
    setResumingChapterId,
  }
}
