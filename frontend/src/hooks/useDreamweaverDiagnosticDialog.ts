import { useState, useCallback } from 'react'

export type UseDreamweaverDiagnosticDialogReturn = {
  diagnosticOpen: boolean
  diagnosticActionLoading: boolean
  diagnosticActionError: string | null
  setDiagnosticActionLoading: (value: boolean) => void
  setDiagnosticActionError: (value: string | null) => void
  openDiagnosticDialog: () => void
  closeDiagnosticDialog: () => void
  resetDiagnosticState: () => void
}

export function useDreamweaverDiagnosticDialog(): UseDreamweaverDiagnosticDialogReturn {
  const [diagnosticOpen, setDiagnosticOpen] = useState(false)
  const [diagnosticActionLoading, setDiagnosticActionLoading] = useState(false)
  const [diagnosticActionError, setDiagnosticActionError] = useState<string | null>(null)

  const openDiagnosticDialog = useCallback(() => {
    setDiagnosticActionError(null)
    setDiagnosticOpen(true)
  }, [])

  const closeDiagnosticDialog = useCallback(() => {
    setDiagnosticOpen(false)
  }, [])

  const resetDiagnosticState = useCallback(() => {
    setDiagnosticOpen(false)
    setDiagnosticActionLoading(false)
    setDiagnosticActionError(null)
  }, [])

  return {
    diagnosticOpen,
    diagnosticActionLoading,
    diagnosticActionError,
    setDiagnosticActionLoading,
    setDiagnosticActionError,
    openDiagnosticDialog,
    closeDiagnosticDialog,
    resetDiagnosticState,
  }
}
