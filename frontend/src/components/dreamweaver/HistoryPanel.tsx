import { useMemo } from 'react'
import {
  Box,
  Chip,
  Drawer,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Stack,
  Typography,
  Button,
  Checkbox,
  Alert,
  LinearProgress,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/Delete'
import HistoryIcon from '@mui/icons-material/History'
import { useFormats } from '@/i18n'
import { useTranslation } from 'react-i18next'
import type { DreamweaverRunSummary } from '@/types/dreamweaver'
import { getStageDisplayName } from '@/utils/timeEstimate'

interface HistoryPanelProps {
  open: boolean
  onClose: () => void
  runs: DreamweaverRunSummary[]
  loading: boolean
  error: string | null
  selectedIds: string[]
  onToggleSelect: (runId: string) => void
  onSelectAll: () => void
  onClearSelection: () => void
  onDeleteSelected: () => Promise<void>
  onLoadRun: (runId: string) => void
  bulkDeleting: boolean
  bulkDeleteProgress: { current: number; total: number } | null
}

function getStatusColor(status: string): 'success' | 'error' | 'warning' | 'default' {
  switch (status.toLowerCase()) {
    case 'done':
    case 'completed':
      return 'success'
    case 'failed':
    case 'error':
      return 'error'
    case 'running':
    case 'processing':
      return 'warning'
    default:
      return 'default'
  }
}

export function HistoryPanel({
  open,
  onClose,
  runs,
  loading,
  error,
  selectedIds,
  onToggleSelect,
  onSelectAll,
  onClearSelection,
  onDeleteSelected,
  onLoadRun,
  bulkDeleting,
  bulkDeleteProgress,
}: HistoryPanelProps) {
  const { formatMonthDayTime } = useFormats()
  const { t } = useTranslation()
  const allSelected = runs.length > 0 && selectedIds.length === runs.length

  const sortedRuns = useMemo(() => {
    return [...runs].sort((a, b) => {
      const timeA = a.updated_at ? new Date(a.updated_at).getTime() : 0
      const timeB = b.updated_at ? new Date(b.updated_at).getTime() : 0
      return timeB - timeA
    })
  }, [runs])

  // 原本在模块级，依赖当前语言之后只能待进组件内。两条兜底刻意保留：空值给 '-'，
  // 解析不出来就把后端原串显示出来——那串东西至少能让人看出后端返回了什么。
  const formatRunTime = (value: string | null | undefined): string => {
    if (!value) return '-'
    return formatMonthDayTime(value) || value
  }

  return (
    <Drawer anchor="right" open={open} onClose={onClose}>
      <Box sx={{ width: 400, height: '100%', display: 'flex', flexDirection: 'column' }}>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}
        >
          <Stack direction="row" alignItems="center" spacing={1}>
            <HistoryIcon />
            <Typography variant="h6">{t('dreamweaverHistory.title')}</Typography>
            <Chip size="small" label={runs.length} />
          </Stack>
          <IconButton onClick={onClose}>
            <CloseIcon />
          </IconButton>
        </Stack>

        {selectedIds.length > 0 && (
          <Box sx={{ p: 1.5, bgcolor: 'grey.100' }}>
            <Stack direction="row" alignItems="center" justifyContent="space-between">
              <Stack direction="row" alignItems="center" spacing={1}>
                <Checkbox
                  checked={allSelected}
                  indeterminate={selectedIds.length > 0 && selectedIds.length < runs.length}
                  onChange={allSelected ? onClearSelection : onSelectAll}
                  size="small"
                />
                <Typography variant="body2">{t('dreamweaverHistory.selectedCount', { count: selectedIds.length })}</Typography>
              </Stack>
              <Button
                size="small"
                color="error"
                startIcon={<DeleteIcon />}
                onClick={onDeleteSelected}
                disabled={bulkDeleting}
              >
                {bulkDeleting ? t('dreamweaverDelete.deleting') : t('common.delete')}
              </Button>
            </Stack>
            {bulkDeleting && bulkDeleteProgress && (
              <Box sx={{ mt: 1 }}>
                <LinearProgress
                  variant="determinate"
                  value={(bulkDeleteProgress.current / bulkDeleteProgress.total) * 100}
                />
                <Typography variant="caption" color="text.secondary">
                  {t('dreamweaverHistory.deletingProgress', { current: bulkDeleteProgress.current, total: bulkDeleteProgress.total })}
                </Typography>
              </Box>
            )}
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ m: 1 }}>
            {error}
          </Alert>
        )}

        <Box sx={{ flex: 1, overflow: 'auto' }}>
          {loading ? (
            <Box sx={{ p: 2, textAlign: 'center' }}>
              <Typography color="text.secondary">{t('dreamweaverHistory.loading')}</Typography>
            </Box>
          ) : sortedRuns.length === 0 ? (
            <Box sx={{ p: 2, textAlign: 'center' }}>
              <Typography color="text.secondary">{t('dreamweaverHistory.empty')}</Typography>
            </Box>
          ) : (
            <List dense>
              {sortedRuns.map((run) => (
                <ListItem
                  key={run.run_id}
                  secondaryAction={
                    <Checkbox
                      checked={selectedIds.includes(run.run_id)}
                      onChange={() => onToggleSelect(run.run_id)}
                      size="small"
                    />
                  }
                  disablePadding
                >
                  <ListItemButton onClick={() => onLoadRun(run.run_id)}>
                    <ListItemText
                      primary={
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                            {run.run_id.slice(0, 8)}...
                          </Typography>
                          <Chip
                            size="small"
                            label={run.status}
                            color={getStatusColor(run.status)}
                          />
                        </Stack>
                      }
                      secondary={
                        <Stack direction="row" spacing={1} alignItems="center" sx={{ mt: 0.5 }}>
                          <Typography variant="caption" color="text.secondary">
                            {formatRunTime(run.updated_at)}
                          </Typography>
                          {run.stage && (
                            <Chip
                              size="small"
                              label={getStageDisplayName(run.stage, t)}
                              variant="outlined"
                            />
                          )}
                          {run.camera_count != null && (
                            <Typography variant="caption" color="text.secondary">
                              {run.camera_count} {t('dreamweaverHistory.cameraCount')}
                            </Typography>
                          )}
                        </Stack>
                      }
                    />
                  </ListItemButton>
                </ListItem>
              ))}
            </List>
          )}
        </Box>
      </Box>
    </Drawer>
  )
}
