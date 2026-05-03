import { useCallback, useState } from 'react'

import type { SnackbarState } from './hookTypes'

export const useAudiobookSnackbarState = () => {
  const [snackbar, setSnackbar] = useState<SnackbarState>({
    open: false,
    message: '',
    severity: 'info',
  })

  const handleCloseSnackbar = useCallback(() => {
    setSnackbar((prev) => ({ ...prev, open: false }))
  }, [])

  return {
    snackbar,
    setSnackbar,
    handleCloseSnackbar,
  }
}
