import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from '@mui/material'
import MonitorHeartIcon from '@mui/icons-material/MonitorHeart'
import RefreshIcon from '@mui/icons-material/Refresh'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import type {
  ContextObservation,
  ContextHealthResponse,
} from '@/types/contextHealth'
import {
  formatObservedBytes,
  getCacheChip,
  getConflictChipColor,
  getOnlineCallLabel,
  getOutputStatusChip,
  getRequestStatusChip,
} from '@/components/contextHealthPresentation'

interface ContextHealthPanelProps {
  projectId: number
  /** 历史观测返回条数，默认 20 */
  limit?: number
}

export default function ContextHealthPanel(props: ContextHealthPanelProps) {
  const { projectId, limit = 20 } = props

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [latest, setLatest] = useState<ContextObservation | null>(null)
  const [history, setHistory] = useState<ContextObservation[]>([])

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const response = await apiClient.getContextHealth(projectId, limit)
      const data = response.data as ContextHealthResponse
      setLatest(data.latest ?? null)
      setHistory(data.observations ?? [])
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '加载上下文观测失败'))
      // 接口失败：旧快照已失效，清空避免显示过期成功数据
      setLatest(null)
      setHistory([])
    } finally {
      setLoading(false)
    }
  }, [projectId, limit])

  useEffect(() => {
    if (projectId) {
      void load()
    }
  }, [projectId, load])

  // 失败请求（含锁定模型直接终止）需醒目展示，ok/旧数据不展示
  const requestStatusChip = latest ? getRequestStatusChip(latest) : null
  // 输出验收（②③）：调用成功但输出被拒/重试失败时独立提示，避免误读为成功
  const outputStatusChip = latest ? getOutputStatusChip(latest) : null

  return (
    <Card elevation={2}>
      <CardContent>
        <Box
          display="flex"
          alignItems="center"
          justifyContent="space-between"
          mb={2}
        >
          <Box display="flex" alignItems="center" gap={1}>
            <MonitorHeartIcon color="primary" />
            <Typography variant="h6" fontWeight={600}>
              上下文健康
            </Typography>
          </Box>
          <Tooltip title="刷新">
            <span>
              <IconButton
                size="small"
                onClick={load}
                disabled={loading}
              >
                <RefreshIcon fontSize="small" />
              </IconButton>
            </span>
          </Tooltip>
        </Box>

        {loading && (
          <Box display="flex" justifyContent="center" py={3}>
            <CircularProgress size={24} />
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {!loading && !error && !latest && (
          <Typography variant="body2" color="text.secondary">
            暂无观测数据，生成一章后将自动记录。
          </Typography>
        )}

        {latest && (
          <Box>
            {/* 阶段 A 观测为项目级全局最新快照，无 task_id/章节过滤，并发多任务时
                可能来自其他任务，故明确标注避免误读为“当前生成任务状态”。 */}
            <Typography variant="caption" color="text.secondary" display="block" mb={1}>
              项目级最近观测（非当前生成任务，多任务并发时可能来自其他任务）
            </Typography>
            {/* 关键指标 */}
            <Box display="flex" flexWrap="wrap" gap={1} mb={2}>
              <Chip
                size="small"
                label={`请求：${latest.request_kind}`}
                color="primary"
                variant="outlined"
              />
              {requestStatusChip ? (
                <Chip
                  size="small"
                  label={requestStatusChip.label}
                  color={requestStatusChip.color}
                />
              ) : null}
              {outputStatusChip ? (
                <Chip
                  size="small"
                  label={outputStatusChip.label}
                  color={outputStatusChip.color}
                />
              ) : null}
              <Chip size="small" label={`模型：${latest.model_id || '未知'}`} />
              <Chip
                size="small"
                label={`上下文上限：${latest.model_context_limit || '-'}`}
              />
              <Chip
                size="small"
                label={`安全预算：${latest.safe_input_budget || '未采集'}`}
                color={latest.safe_input_budget ? 'default' : 'warning'}
              />
              <Chip
                size="small"
                label={`输入 token：${latest.total_input_tokens}`}
                color={latest.remaining_budget < 0 ? 'error' : 'default'}
              />
              <Chip
                size="small"
                label={`剩余预算：${latest.safe_input_budget ? latest.remaining_budget : '未采集'}`}
                color={latest.remaining_budget < 0 ? 'error' : 'default'}
              />
              <Chip
                size="small"
                label={`完整请求：${formatObservedBytes(latest.prompt_request_bytes)}`}
              />
              <Chip
                size="small"
                label={`上下文载荷(估)：${formatObservedBytes(latest.context_payload_bytes)}`}
              />
              <Chip
                size="small"
                label={`DB：${latest.db_rows_read}行×${latest.db_columns_read}列`}
              />
              <Chip size="small" label={`RAG 命中：${latest.rag_hits}`} />
              <Chip
                size="small"
                label={getCacheChip(latest).label}
                color={getCacheChip(latest).color}
              />
              <Chip
                size="small"
                label={getOnlineCallLabel(latest)}
              />
              <Chip
                size="small"
                label={
                  latest.conflict_status
                    ? `冲突：${latest.conflict_status}（b${latest.blocking_conflict_count}/w${latest.warning_conflict_count}）`
                    : '冲突：未采集'
                }
                color={getConflictChipColor(latest)}
              />
              <Chip
                size="small"
                label={`细纲：${latest.outline_status || '未知'}`}
                color={latest.outline_status === 'available' ? 'success' : 'warning'}
              />
              <Chip
                size="small"
                label={`卷覆盖：${latest.volume_matched ? '命中' : '未命中'}`}
                color={latest.volume_matched ? 'success' : 'warning'}
              />
              {latest.task_id ? (
                <Chip size="small" variant="outlined" label={`任务：${latest.task_id.slice(0, 8)}`} />
              ) : null}
            </Box>

            {/* section 明细 */}
            <Table size="small" aria-label="context sections">
              <TableHead>
                <TableRow>
                  <TableCell>Section</TableCell>
                  <TableCell>层级</TableCell>
                  <TableCell align="right">原始 token</TableCell>
                  <TableCell align="right">最终 token</TableCell>
                  <TableCell>裁剪方式</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {latest.sections.map((section) => (
                  <TableRow key={section.section_id}>
                    <TableCell
                      sx={{
                        wordBreak: 'break-all',
                        fontSize: '0.78rem',
                      }}
                    >
                      {section.section_id}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={section.layer}
                        size="small"
                        variant="outlined"
                        sx={{ height: 20, fontSize: '0.68rem' }}
                      />
                    </TableCell>
                    <TableCell align="right" sx={{ fontSize: '0.78rem' }}>
                      {section.raw_tokens}
                    </TableCell>
                    <TableCell align="right" sx={{ fontSize: '0.78rem' }}>
                      {section.final_tokens}
                    </TableCell>
                    <TableCell sx={{ fontSize: '0.78rem' }}>
                      {section.trim_method}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            {history.length > 1 && (
              <Box mt={2}>
                <Divider sx={{ mb: 1 }} />
                <Typography variant="caption" color="text.secondary">
                  最近观测（{history.length} 条）：
                  {history
                    .slice()
                    .reverse()
                    .map(
                      (item) =>
                        `第${item.chapter_number}章/${item.request_kind}/${item.total_input_tokens}t`,
                    )
                    .join('；')}
                </Typography>
              </Box>
            )}
          </Box>
        )}
      </CardContent>
    </Card>
  )
}
