import { useCallback, useEffect, useRef, useState } from 'react'
import type { CollectFeedback } from '@/types/dreamweaver'

type ToastId = string | number

interface ToastItem extends CollectFeedback {
  id: ToastId
  createdAt: number
}

interface UseToastReturn {
  toasts: ToastItem[]
  showSuccess: (text: string) => ToastId
  showError: (text: string) => ToastId
  removeToast: (id: ToastId) => void
  clearAll: () => void
}

const TOAST_LIMIT = 5
const DEFAULT_DURATION = 5000

export function useToast(): UseToastReturn {
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const timersRef = useRef<Map<ToastId, ReturnType<typeof setTimeout>>>(new Map())

  const removeToast = useCallback((id: ToastId) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
    const timer = timersRef.current.get(id)
    if (timer) {
      clearTimeout(timer)
      timersRef.current.delete(id)
    }
  }, [])

  const addToast = useCallback((type: 'success' | 'error', text: string): ToastId => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
    const newToast: ToastItem = {
      id,
      type,
      text,
      createdAt: Date.now(),
    }

    setToasts((prev) => {
      const next = [...prev, newToast]
      return next.slice(-TOAST_LIMIT)
    })

    const timer = setTimeout(() => {
      removeToast(id)
    }, DEFAULT_DURATION)
    timersRef.current.set(id, timer)

    return id
  }, [removeToast])

  const showSuccess = useCallback((text: string) => {
    return addToast('success', text)
  }, [addToast])

  const showError = useCallback((text: string) => {
    return addToast('error', text)
  }, [addToast])

  const clearAll = useCallback(() => {
    setToasts([])
    timersRef.current.forEach((timer) => clearTimeout(timer))
    timersRef.current.clear()
  }, [])

  useEffect(() => {
    return () => {
      timersRef.current.forEach((timer) => clearTimeout(timer))
      timersRef.current.clear()
    }
  }, [])

  return {
    toasts,
    showSuccess,
    showError,
    removeToast,
    clearAll,
  }
}
