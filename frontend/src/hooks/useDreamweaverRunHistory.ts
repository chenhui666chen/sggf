import { useState, useCallback, useMemo } from 'react'
import { apiClient, extractApiErrorMessage } from '../services/api'

export interface DreamweaverRunSummary {
  id: number
  run_id: string
  status: string
  created_at?: string
  updated_at?: string
  state?: string | null
  stage?: string | null
  progress?: number | null
  error?: string | null
}

export interface UseDreamweaverRunHistoryReturn {
  historyOpen: boolean
  setHistoryOpen: (open: boolean) => void
  historyLoading: boolean
  historyError: string | null
  historyRuns: DreamweaverRunSummary[]
  historyStatusFilters: string[]
  setHistoryStatusFilters: (filters: string[]) => void
  historyStatusCounts: Record<string, number>
  filteredHistoryRuns: DreamweaverRunSummary[]
  fetchRunHistory: (projectId: number) => Promise<void>
  clearHistoryError: () => void
}

export function useDreamweaverRunHistory(): UseDreamweaverRunHistoryReturn {
  const [historyOpen, setHistoryOpen] = useState(false)
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyError, setHistoryError] = useState<string | null>(null)
  const [historyRuns, setHistoryRuns] = useState<DreamweaverRunSummary[]>([])
  const [historyStatusFilters, setHistoryStatusFilters] = useState<string[]>([])

  const fetchRunHistory = useCallback(async (projectId: number) => {
    setHistoryLoading(true)
    setHistoryError(null)
    try {
      const res = await apiClient.listDreamweaverRuns(projectId, 100)
      const runs = Array.isArray(res.data) ? (res.data as DreamweaverRunSummary[]) : []
      setHistoryRuns(runs)
    } catch (e: any) {
      setHistoryError(await extractApiErrorMessage(e, '加载历史任务失败'))
    } finally {
      setHistoryLoading(false)
    }
  }, [])

  const historyStatusCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const run of historyRuns) {
      const statusRaw = String(run.status || '').trim().toLowerCase() || 'unknown'
      counts[statusRaw] = (counts[statusRaw] || 0) + 1
    }
    return counts
  }, [historyRuns])

  const filteredHistoryRuns = useMemo(() => {
    if (!historyStatusFilters.length) return historyRuns
    const enabled = new Set(historyStatusFilters.map((s) => String(s || '').trim().toLowerCase()).filter(Boolean))
    if (!enabled.size) return historyRuns
    return historyRuns.filter((run) => enabled.has(String(run.status || '').trim().toLowerCase() || 'unknown'))
  }, [historyRuns, historyStatusFilters])

  const clearHistoryError = useCallback(() => {
    setHistoryError(null)
  }, [])

  return {
    historyOpen,
    setHistoryOpen,
    historyLoading,
    historyError,
    historyRuns,
    historyStatusFilters,
    setHistoryStatusFilters,
    historyStatusCounts,
    filteredHistoryRuns,
    fetchRunHistory,
    clearHistoryError,
  }
}
