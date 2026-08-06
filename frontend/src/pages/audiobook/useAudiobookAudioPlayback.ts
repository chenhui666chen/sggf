import { useCallback, useEffect, useMemo, useRef } from 'react'

import type { PlayAudioOptions } from './hookTypes'

// AudioPicker、片段试听和整章播放器可能同时挂载；模块级仲裁保证同一页面
// 始终只有一个受控 Audio 实例在播放。
let activePlaybackStop: (() => void) | null = null

const clampPlaybackStartRatio = (value: number): number =>
  Math.max(0, Math.min(0.95, value))

const resolvePlaybackStartTime = (
  audioElement: HTMLAudioElement,
  options?: PlayAudioOptions,
): number => {
  if (Number.isFinite(options?.startTime) && (options?.startTime ?? 0) > 0) {
    return options?.startTime ?? 0
  }

  if (!Number.isFinite(options?.startRatio) || (options?.startRatio ?? 0) <= 0) {
    return 0
  }

  const duration = Number.isFinite(audioElement.duration) ? audioElement.duration : 0
  if (duration <= 0) return 0

  return duration * clampPlaybackStartRatio(options?.startRatio ?? 0)
}

const applyPlaybackStart = (
  audioElement: HTMLAudioElement,
  options?: PlayAudioOptions,
) => {
  const startTime = resolvePlaybackStartTime(audioElement, options)
  if (startTime <= 0) return

  const duration = Number.isFinite(audioElement.duration) ? audioElement.duration : 0
  const maxStartTime = duration > 0 ? Math.max(0, duration - 0.05) : startTime
  audioElement.currentTime = Math.min(startTime, maxStartTime)
}

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
    audioElement.onloadedmetadata = null
    audioElement.removeAttribute('src')
    releaseManagedObjectUrl()
    if (activePlaybackStop === stopManagedPlayback) {
      activePlaybackStop = null
    }
  }, [audioElement, releaseManagedObjectUrl])

  const claimPlayback = useCallback(() => {
    if (activePlaybackStop && activePlaybackStop !== stopManagedPlayback) {
      activePlaybackStop()
    }
    activePlaybackStop = stopManagedPlayback
  }, [stopManagedPlayback])

  const playManagedBlob = useCallback(
    async (blob: Blob, options?: PlayAudioOptions) => {
      claimPlayback()
      audioElement.pause()
      audioElement.onended = null
      audioElement.onloadedmetadata = null
      releaseManagedObjectUrl()

      const objectUrl = window.URL.createObjectURL(blob)
      managedObjectUrlRef.current = objectUrl
      audioElement.src = objectUrl
      audioElement.onloadedmetadata = () => applyPlaybackStart(audioElement, options)
      audioElement.onended = () => {
        options?.onEnded?.()
        releaseManagedObjectUrl()
        if (activePlaybackStop === stopManagedPlayback) {
          activePlaybackStop = null
        }
      }
      if (audioElement.readyState >= 1) {
        applyPlaybackStart(audioElement, options)
      }

      try {
        await audioElement.play()
        return objectUrl
      } catch (error) {
        if (activePlaybackStop === stopManagedPlayback) {
          activePlaybackStop = null
        }
        releaseManagedObjectUrl()
        throw error
      }
    },
    [audioElement, claimPlayback, releaseManagedObjectUrl, stopManagedPlayback],
  )

  const playExternalUrl = useCallback(
    async (url: string, options?: PlayAudioOptions) => {
      claimPlayback()
      audioElement.pause()
      audioElement.onended = null
      audioElement.onloadedmetadata = null
      releaseManagedObjectUrl()
      audioElement.src = url
      audioElement.onloadedmetadata = () => applyPlaybackStart(audioElement, options)
      audioElement.onended = () => {
        options?.onEnded?.()
        if (activePlaybackStop === stopManagedPlayback) {
          activePlaybackStop = null
        }
      }
      if (audioElement.readyState >= 1) {
        applyPlaybackStart(audioElement, options)
      }
      await audioElement.play()
    },
    [audioElement, claimPlayback, releaseManagedObjectUrl, stopManagedPlayback],
  )

  useEffect(() => () => stopManagedPlayback(), [stopManagedPlayback])

  return {
    audioElement,
    playExternalUrl,
    playManagedBlob,
    releaseManagedObjectUrl,
    stopManagedPlayback,
  }
}
