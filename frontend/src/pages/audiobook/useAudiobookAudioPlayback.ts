import { useCallback, useEffect, useMemo, useRef } from 'react'

import type { PlayAudioOptions } from './hookTypes'

export const useAudiobookAudioPlayback = () => {
  const audioElement = useMemo(() => new Audio(), [])
  const managedObjectUrlRef = useRef<string | null>(null)

  const releaseManagedObjectUrl = useCallback(() => {
    if (managedObjectUrlRef.current) {
      window.URL.revokeObjectURL(managedObjectUrlRef.current)
      managedObjectUrlRef.current = null
    }
  }, [])

  const stopManagedPlayback = useCallback(() => {
    audioElement.pause()
    audioElement.onended = null
    audioElement.removeAttribute('src')
    releaseManagedObjectUrl()
  }, [audioElement, releaseManagedObjectUrl])

  const playManagedBlob = useCallback(
    async (blob: Blob, options?: PlayAudioOptions) => {
      audioElement.pause()
      audioElement.onended = null
      releaseManagedObjectUrl()

      const objectUrl = window.URL.createObjectURL(blob)
      managedObjectUrlRef.current = objectUrl
      audioElement.src = objectUrl
      audioElement.onended = () => {
        options?.onEnded?.()
        releaseManagedObjectUrl()
      }

      try {
        await audioElement.play()
        return objectUrl
      } catch (error) {
        releaseManagedObjectUrl()
        throw error
      }
    },
    [audioElement, releaseManagedObjectUrl],
  )

  const playExternalUrl = useCallback(
    async (url: string, options?: PlayAudioOptions) => {
      audioElement.pause()
      audioElement.onended = null
      releaseManagedObjectUrl()
      audioElement.src = url
      audioElement.onended = () => {
        options?.onEnded?.()
      }
      await audioElement.play()
    },
    [audioElement, releaseManagedObjectUrl],
  )

  useEffect(() => () => {
    audioElement.pause()
    audioElement.onended = null
    audioElement.removeAttribute('src')
    releaseManagedObjectUrl()
  }, [audioElement, releaseManagedObjectUrl])

  return {
    audioElement,
    playExternalUrl,
    playManagedBlob,
    releaseManagedObjectUrl,
    stopManagedPlayback,
  }
}
