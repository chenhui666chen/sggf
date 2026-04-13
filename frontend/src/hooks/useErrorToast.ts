import { useCallback, useState } from 'react'
import type { CollectFeedback } from '@/types/dreamweaver'

export interface UseErrorToastReturn {
  feedback: CollectFeedback | null
  setFeedback: (feedback: CollectFeedback | null) => void
  showError: (message: string) => void
  showSuccess: (message: string) => void
  clearFeedback: () => void
  extractAndShowError: (error: unknown, fallback: string) => Promise<void>
}

export function useErrorToast(): UseErrorToastReturn {
  const [feedback, setFeedback] = useState<CollectFeedback | null>(null)

  const showError = useCallback((message: string) => {
    setFeedback({ type: 'error', text: message })
  }, [])

  const showSuccess = useCallback((message: string) => {
    setFeedback({ type: 'success', text: message })
  }, [])

  const clearFeedback = useCallback(() => {
    setFeedback(null)
  }, [])

  const extractAndShowError = useCallback(async (error: unknown, fallback: string) => {
    let message = fallback
    
    if (error && typeof error === 'object') {
      const axiosError = error as { response?: { data?: { detail?: unknown } } }
      if (axiosError.response?.data?.detail) {
        const detail = axiosError.response.data.detail
        if (typeof detail === 'string') {
          message = detail
        } else if (typeof detail === 'object' && detail !== null) {
          const detailObj = detail as Record<string, unknown>
          if (typeof detailObj.message === 'string') {
            message = detailObj.message
          }
        }
      } else if ('message' in error && typeof (error as Record<string, unknown>).message === 'string') {
        message = String((error as Record<string, unknown>).message)
      }
    } else if (error instanceof Error) {
      message = error.message || fallback
    }
    
    showError(message)
  }, [showError])

  return {
    feedback,
    setFeedback,
    showError,
    showSuccess,
    clearFeedback,
    extractAndShowError,
  }
}
