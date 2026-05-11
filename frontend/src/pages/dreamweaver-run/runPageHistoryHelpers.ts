import { formatDateTime } from './runPageFormatUtils'

export type HistoryStatusColor = 'default' | 'primary' | 'success' | 'error' | 'warning' | 'info'

export type HistoryStatusMeta = {
  label: string
  color: HistoryStatusColor
}

export function getHistoryStatusMeta(status: string): HistoryStatusMeta {
  const normalized = String(status || '').trim().toLowerCase()
  if (normalized === 'completed') return { label: '已完成', color: 'success' }
  if (normalized === 'waiting') return { label: '待审核', color: 'warning' }
  if (normalized === 'failed') return { label: '失败', color: 'error' }
  if (normalized === 'timeout') return { label: '超时', color: 'warning' }
  if (normalized === 'running') return { label: '运行中', color: 'info' }
  if (normalized === 'queued') return { label: '排队中', color: 'info' }
  return { label: normalized || '未知', color: 'default' }
}

export const HISTORY_FILTER_STATUSES = ['running', 'queued', 'waiting', 'failed', 'timeout', 'completed'] as const

export function buildHistoryStatusCounts(runs: Array<{ status?: string }>): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const run of runs) {
    const statusRaw = String(run.status || '').trim().toLowerCase() || 'unknown'
    counts[statusRaw] = (counts[statusRaw] || 0) + 1
  }
  return counts
}

export function filterHistoryRuns<T extends { status?: string }>(runs: T[], filters: string[]): T[] {
  if (!filters.length) return runs
  const enabled = new Set(filters.map((s) => String(s || '').trim().toLowerCase()).filter(Boolean))
  if (!enabled.size) return runs
  return runs.filter((run) => enabled.has(String(run.status || '').trim().toLowerCase() || 'unknown'))
}

export function collectBulkDeleteTargets<T extends { status?: string }>(filteredRuns: T[]): T[] {
  return filteredRuns.filter((run) => {
    const statusRaw = String(run.status || '').trim().toLowerCase()
    return statusRaw !== 'running' && statusRaw !== 'queued'
  })
}

export interface HistoryFilterItem {
  key: string
  label: string
  count: number
  color: HistoryStatusColor | 'default'
  selected: boolean
  onClick: () => void
}

export function buildHistoryFilterItems(params: {
  totalRuns: number
  statusFilters: string[]
  statusCounts: Record<string, number>
  onClearFilters: () => void
  onToggleFilter: (status: string) => void
}): HistoryFilterItem[] {
  return [
    {
      key: 'all',
      label: '全部',
      count: params.totalRuns,
      color: 'default',
      selected: params.statusFilters.length === 0,
      onClick: params.onClearFilters,
    },
    ...HISTORY_FILTER_STATUSES.map((status) => {
      const enabled = params.statusFilters.includes(status)
      const count = params.statusCounts[status] || 0
      const { label, color } = getHistoryStatusMeta(status)
      return {
        key: status,
        label,
        count,
        color,
        selected: enabled,
        onClick: () => params.onToggleFilter(status),
      }
    }),
  ]
}

export interface HistoryRunItem {
  run_id: string
  progress?: number | null
  status?: string | null
  stage?: string | null
  camera_tree_mode?: string | null
  camera_count?: number | null
  camera_states_count?: number | null
  camera_scenes_count?: number | null
  updated_at?: string | null
  created_at?: string | null
  error_message?: string | null
}

export interface MappedHistoryRunItem {
  runId: string
  statusLabel: string
  statusColor: HistoryStatusColor
  progressValue: number | null
  stage: string | null
  cameraTreeMode: string | null
  cameraCount: number | null
  cameraStatesCount: number | null
  cameraScenesCount: number | null
  timeText: string | null
  errorMessage: string | null
}

export function mapHistoryRunsToItems(runs: HistoryRunItem[]): MappedHistoryRunItem[] {
  return runs.map((run) => {
    const progressValue =
      typeof run.progress === 'number' ? Math.max(0, Math.min(100, Math.round(run.progress))) : null
    const statusRaw = String(run.status || '').trim().toLowerCase()
    const { label: statusLabel, color: statusColor } = getHistoryStatusMeta(statusRaw)
    return {
      runId: run.run_id,
      statusLabel,
      statusColor,
      progressValue,
      stage: run.stage ?? null,
      cameraTreeMode: run.camera_tree_mode ?? null,
      cameraCount: run.camera_count ?? null,
      cameraStatesCount: run.camera_states_count ?? null,
      cameraScenesCount: run.camera_scenes_count ?? null,
      timeText: formatDateTime(run.updated_at || run.created_at),
      errorMessage: run.error_message ?? null,
    }
  })
}
