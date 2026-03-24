import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from '@mui/material'
import {
  Refresh as RefreshIcon,
} from '@mui/icons-material'
import {
  type AdminPointsBillingModuleSummary,
  type AdminPointsBillingEvent,
  type AdminPointsBillingSummary,
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'

type FilterState = {
  userId: string
  moduleKey: string
  eventKind: string
  marginStatus: string
  keyword: string
}

const MODULE_OPTIONS = [
  { value: '', label: '全部模块' },
  { value: 'audiobook', label: '有声书' },
  { value: 'dreamweaver', label: '短剧' },
]

const EVENT_OPTIONS = [
  { value: '', label: '全部事件' },
  { value: 'freeze', label: '冻结' },
  { value: 'settle', label: '结算' },
  { value: 'release', label: '释放' },
]

const MARGIN_OPTIONS = [
  { value: '', label: '全部毛利状态' },
  { value: 'healthy', label: '毛利健康' },
  { value: 'warning', label: '低毛利预警' },
  { value: 'negative', label: '负毛利' },
]

const EMPTY_FILTERS: FilterState = {
  userId: '',
  moduleKey: '',
  eventKind: '',
  marginStatus: '',
  keyword: '',
}

const EMPTY_SUMMARY: AdminPointsBillingSummary = {
  recent_7d_settle_count: 0,
  settle_event_count: 0,
  warning_event_count: 0,
  negative_event_count: 0,
  total_user_billed_yuan: 0,
  total_platform_gross_profit_yuan: 0,
  blended_margin_rate: null,
  module_summaries: [],
}

function formatCurrency(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return `CNY ${value.toFixed(2)}`
}

function formatPercent(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return `${(value * 100).toFixed(value === 1 ? 0 : 2)}%`
}

function formatPricingStatus(status?: string | null) {
  if (status === 'actual') return '实际计费'
  if (status === 'estimated') return '预估计费'
  if (status === 'pending') return '待计费'
  return status || '-'
}

function formatTaskStatus(status?: string | null) {
  if (status === 'running') return '运行中'
  if (status === 'completed') return '已完成'
  return status || '-'
}

function getEventColor(kind: AdminPointsBillingEvent['event_kind']): 'warning' | 'primary' | 'success' {
  if (kind === 'freeze') return 'warning'
  if (kind === 'release') return 'success'
  return 'primary'
}

function getMarginColor(status?: string | null): 'default' | 'success' | 'warning' | 'error' {
  if (status === 'negative') return 'error'
  if (status === 'warning') return 'warning'
  if (status === 'healthy') return 'success'
  return 'default'
}

function formatMarginStatus(status?: string | null) {
  if (status === 'negative') return '负毛利'
  if (status === 'warning') return '低毛利预警'
  if (status === 'healthy') return '毛利健康'
  return '-'
}

function getSummaryAlertSeverity(summary: AdminPointsBillingSummary): 'success' | 'warning' | 'error' {
  if (summary.negative_event_count > 0) return 'error'
  if (summary.warning_event_count > 0) return 'warning'
  return 'success'
}

function getSummaryAlertMessage(summary: AdminPointsBillingSummary) {
  if (summary.negative_event_count > 0) {
    return `当前范围存在 ${summary.negative_event_count} 条负毛利结算，建议优先复核供应商折扣与用户计价策略。`
  }
  if (summary.warning_event_count > 0) {
    return `当前范围存在 ${summary.warning_event_count} 条低毛利结算，建议优先关注模块毛利分布和让利策略。`
  }
  return '当前范围的结算毛利健康，暂未发现低毛利或负毛利结算。'
}

function isQuickFilterActive(filters: FilterState, marginStatus: 'warning' | 'negative') {
  return filters.eventKind === 'settle' && filters.marginStatus === marginStatus
}

function getTaskStatusColor(status?: string | null): 'default' | 'info' | 'success' {
  if (status === 'running') return 'info'
  if (status === 'completed') return 'success'
  return 'default'
}

function getPricingStatusColor(status?: string | null): 'default' | 'primary' | 'warning' {
  if (status === 'actual') return 'primary'
  if (status === 'estimated') return 'warning'
  return 'default'
}

function formatStageLabel(stage?: string | null) {
  const normalized = String(stage || '').trim().toLowerCase()
  if (!normalized) return '-'

  const labels: Record<string, string> = {
    init: '初始化',
    strategy: '策略',
    storyboard: '分镜',
    delivery: '交付',
    design: '设计',
    script_adaptation: '脚本改编',
    quality_review: '质量复核',
    audio_prompt_review: '提示词复核',
    tts_synthesis: '语音合成',
    audio_mixing: '音频混音',
    final_audio_review: '成品复核',
    waiting_script_approval: '待脚本确认',
    waiting_approval: '待确认',
    waiting_video_confirmation: '待视频确认',
  }

  return labels[normalized] || stage || '-'
}

function normalizeActionPath(actionPath?: string | null) {
  const raw = String(actionPath || '').trim()
  if (!raw) return null
  if (/^https?:\/\//i.test(raw)) return raw
  return raw.startsWith('/') ? raw : `/${raw.replace(/^\/+/, '')}`
}

function buildPolicyAlignmentMessage(gap?: number | null) {
  if (typeof gap !== 'number' || Number.isNaN(gap)) {
    return '当前没有可用的策略对齐差数据。'
  }

  if (Math.abs(gap) < 0.01) {
    return '当前用户计费与策略目标基本一致。'
  }

  if (gap > 0) {
    return `当前用户实付高于策略目标 ${formatCurrency(gap)}，可能存在历史计价偏高或补差结算。`
  }

  return `当前用户实付低于策略目标 ${formatCurrency(Math.abs(gap))}，说明本次结算存在额外让利。`
}

function DetailMetricCard(props: {
  label: string
  value: string
  caption?: string
  valueColor?: string
}) {
  const { label, value, caption, valueColor = 'text.primary' } = props

  return (
    <Paper variant="outlined" sx={{ p: 1.5, height: '100%' }}>
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="subtitle1" sx={{ mt: 0.75, color: valueColor, fontWeight: 700 }}>
        {value}
      </Typography>
      {caption ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
          {caption}
        </Typography>
      ) : null}
    </Paper>
  )
}

export default function PointsBillingPage() {
  const navigate = useNavigate()
  const [items, setItems] = useState<AdminPointsBillingEvent[]>([])
  const [summary, setSummary] = useState<AdminPointsBillingSummary>(EMPTY_SUMMARY)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState<FilterState>(EMPTY_FILTERS)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(20)
  const [total, setTotal] = useState(0)
  const [selectedEvent, setSelectedEvent] = useState<AdminPointsBillingEvent | null>(null)

  useEffect(() => {
    void fetchEvents()
  }, [page, rowsPerPage, filters])

  const fetchEvents = async (silent = false) => {
    try {
      if (silent) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }

      const userId = Number(filters.userId)
      const response = await apiClient.getAdminPointsBillingEvents({
        page: page + 1,
        page_size: rowsPerPage,
        user_id: Number.isInteger(userId) && userId > 0 ? userId : undefined,
        module_key: filters.moduleKey || undefined,
        event_kind: filters.eventKind || undefined,
        margin_status: filters.marginStatus || undefined,
        keyword: filters.keyword.trim() || undefined,
      })

      setItems(Array.isArray(response.data.items) ? response.data.items : [])
      setTotal(Number(response.data.total) || 0)
      setSummary(response.data.summary ?? EMPTY_SUMMARY)
      setError(null)
    } catch (err) {
      setError(await extractApiErrorMessage(err, '获取计费事件失败'))
      setItems([])
      setTotal(0)
      setSummary(EMPTY_SUMMARY)
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const handleFilterChange = (key: keyof FilterState, value: string) => {
    setPage(0)
    setFilters((prev) => ({
      ...prev,
      [key]: value,
    }))
  }

  const handleResetFilters = () => {
    setPage(0)
    setFilters(EMPTY_FILTERS)
  }

  const handleApplyQuickFilter = (marginStatus: '' | 'warning' | 'negative') => {
    setPage(0)
    if (!marginStatus) {
      setFilters((prev) => ({
        ...prev,
        eventKind: '',
        marginStatus: '',
      }))
      return
    }

    setFilters((prev) => ({
      ...prev,
      eventKind: 'settle',
      marginStatus,
    }))
  }

  const handleApplyDialogFilters = (patch: Partial<FilterState>) => {
    setPage(0)
    setSelectedEvent(null)
    setFilters((prev) => ({
      ...prev,
      ...patch,
    }))
  }

  const handleOpenEventAction = (event: AdminPointsBillingEvent) => {
    const actionPath = normalizeActionPath(event.action_path)
    if (!actionPath) return

    setSelectedEvent(null)
    if (/^https?:\/\//i.test(actionPath)) {
      window.open(actionPath, '_blank', 'noopener,noreferrer')
      return
    }
    navigate(actionPath)
  }

  if (loading && items.length === 0) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        justifyContent="space-between"
        alignItems={{ xs: 'stretch', md: 'center' }}
        spacing={2}
        sx={{ mb: 3 }}
      >
        <Box>
          <Typography variant="h4">计费事件</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
            统一查看正式积分冻结、结算、释放事件，并按毛利状态筛选经营风险。
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={refreshing ? <CircularProgress size={18} /> : <RefreshIcon />}
          onClick={() => void fetchEvents(true)}
          disabled={refreshing}
        >
          刷新
        </Button>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Box sx={{ mb: 2.5 }}>
            <Typography variant="h6">经营概览</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              基于当前用户、模块、关键词范围内的结算事件汇总，不受下方事件类型与毛利筛选影响。
            </Typography>
          </Box>

          <Box
            sx={{
              display: 'grid',
              gap: 2,
              gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', xl: 'repeat(4, minmax(0, 1fr))' },
            }}
          >
            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="overline" color="text.secondary">
                近 7 天结算事件
              </Typography>
              <Typography variant="h4" sx={{ mt: 0.75 }}>
                {summary.recent_7d_settle_count}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                用于判断近期消耗与结算活跃度
              </Typography>
            </Paper>

            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="overline" color="text.secondary">
                当前范围低毛利事件
              </Typography>
              <Typography variant="h4" color={summary.warning_event_count > 0 ? 'warning.main' : 'text.primary'} sx={{ mt: 0.75 }}>
                {summary.warning_event_count}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                需要关注折扣捕获与让利是否过多
              </Typography>
            </Paper>

            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="overline" color="text.secondary">
                当前范围负毛利事件
              </Typography>
              <Typography variant="h4" color={summary.negative_event_count > 0 ? 'error.main' : 'text.primary'} sx={{ mt: 0.75 }}>
                {summary.negative_event_count}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                建议优先复核供应商成本与策略对齐差
              </Typography>
            </Paper>

            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="overline" color="text.secondary">
                当前范围综合毛利率
              </Typography>
              <Typography variant="h4" sx={{ mt: 0.75 }}>
                {formatPercent(summary.blended_margin_rate)}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                用户计费 {formatCurrency(summary.total_user_billed_yuan)} / 平台毛利 {formatCurrency(summary.total_platform_gross_profit_yuan)}
              </Typography>
            </Paper>
          </Box>

          <Alert severity={getSummaryAlertSeverity(summary)} sx={{ mt: 2 }}>
            {getSummaryAlertMessage(summary)}
          </Alert>

          <Box sx={{ mt: 3 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
              按模块毛利分布
            </Typography>
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>模块</TableCell>
                    <TableCell>结算事件</TableCell>
                    <TableCell>风险事件</TableCell>
                    <TableCell>用户计费</TableCell>
                    <TableCell>平台毛利</TableCell>
                    <TableCell>综合毛利率</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {summary.module_summaries.map((item: AdminPointsBillingModuleSummary) => (
                    <TableRow key={item.module_key} hover>
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {item.module_label}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {item.module_key}
                        </Typography>
                      </TableCell>
                      <TableCell>{item.settle_event_count}</TableCell>
                      <TableCell>
                        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                          <Chip size="small" color="warning" variant="outlined" label={`低毛利 ${item.warning_event_count}`} />
                          <Chip size="small" color="error" variant="outlined" label={`负毛利 ${item.negative_event_count}`} />
                        </Stack>
                      </TableCell>
                      <TableCell>{formatCurrency(item.total_user_billed_yuan)}</TableCell>
                      <TableCell>{formatCurrency(item.total_platform_gross_profit_yuan)}</TableCell>
                      <TableCell>{formatPercent(item.blended_margin_rate)}</TableCell>
                    </TableRow>
                  ))}
                  {summary.module_summaries.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={6}>
                        <Alert severity="info">当前范围内暂无可汇总的结算事件。</Alert>
                      </TableCell>
                    </TableRow>
                  ) : null}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        </CardContent>
      </Card>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Box
            sx={{
              display: 'grid',
              gap: 2,
              gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', xl: 'repeat(5, minmax(0, 1fr))' },
            }}
          >
            <TextField
              label="用户 ID"
              size="small"
              value={filters.userId}
              onChange={(event) => handleFilterChange('userId', event.target.value)}
              placeholder="例如 12"
            />
            <FormControl size="small">
              <InputLabel>模块</InputLabel>
              <Select
                value={filters.moduleKey}
                label="模块"
                onChange={(event) => handleFilterChange('moduleKey', event.target.value)}
              >
                {MODULE_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small">
              <InputLabel>事件类型</InputLabel>
              <Select
                value={filters.eventKind}
                label="事件类型"
                onChange={(event) => handleFilterChange('eventKind', event.target.value)}
              >
                {EVENT_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small">
              <InputLabel>毛利状态</InputLabel>
              <Select
                value={filters.marginStatus}
                label="毛利状态"
                onChange={(event) => handleFilterChange('marginStatus', event.target.value)}
              >
                {MARGIN_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label="关键词"
              size="small"
              value={filters.keyword}
              onChange={(event) => handleFilterChange('keyword', event.target.value)}
              placeholder="用户名、计费键、标题、运行 ID"
            />
          </Box>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 2 }}>
            <Button variant="outlined" onClick={handleResetFilters}>
              重置筛选
            </Button>
            <Button
              variant={!filters.eventKind && !filters.marginStatus ? 'contained' : 'outlined'}
              onClick={() => handleApplyQuickFilter('')}
            >
              全部事件
            </Button>
            <Button
              color="warning"
              variant={isQuickFilterActive(filters, 'warning') ? 'contained' : 'outlined'}
              onClick={() => handleApplyQuickFilter('warning')}
            >
              低毛利结算
            </Button>
            <Button
              color="error"
              variant={isQuickFilterActive(filters, 'negative') ? 'contained' : 'outlined'}
              onClick={() => handleApplyQuickFilter('negative')}
            >
              负毛利结算
            </Button>
            <Typography variant="body2" color="text.secondary" sx={{ alignSelf: 'center' }}>
              当前共 {total} 条正式计费事件
            </Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
            快捷筛选会自动切换到结算事件，便于直接排查低毛利与负毛利风险。
          </Typography>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <TableContainer component={Paper} variant="outlined">
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>时间</TableCell>
                  <TableCell>用户</TableCell>
                  <TableCell>模块 / 事件</TableCell>
                  <TableCell>标题</TableCell>
                  <TableCell>积分 / 金额</TableCell>
                  <TableCell>任务状态</TableCell>
                  <TableCell>毛利状态</TableCell>
                  <TableCell align="right">操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.id} hover>
                    <TableCell>{new Date(item.created_at).toLocaleString('zh-CN')}</TableCell>
                    <TableCell>
                      <Typography variant="body2">{item.operator_username}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        用户 ID {item.target_user_id}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                        <Chip size="small" variant="outlined" label={item.module_label} />
                        <Chip size="small" color={getEventColor(item.event_kind)} label={item.event_label} />
                      </Stack>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {item.title}
                      </Typography>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{ display: 'block', maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                      >
                        {item.billing_key}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{item.amount_points.toFixed(2)} 积分</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatCurrency(item.amount_yuan)}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{formatTaskStatus(item.task_status)}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatPricingStatus(item.pricing_status)}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={getMarginColor(item.operating_snapshot?.margin_status)}
                        label={formatMarginStatus(item.operating_snapshot?.margin_status)}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Button size="small" onClick={() => setSelectedEvent(item)}>
                        查看详情
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!loading && items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8}>
                      <Alert severity="info">当前筛选条件下暂无计费事件。</Alert>
                    </TableCell>
                  </TableRow>
                ) : null}
              </TableBody>
            </Table>
          </TableContainer>

          <TablePagination
            component="div"
            count={total}
            page={page}
            onPageChange={(_, newPage) => setPage(newPage)}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={(event) => {
              setRowsPerPage(parseInt(event.target.value, 10))
              setPage(0)
            }}
            labelRowsPerPage="每页行数"
            labelDisplayedRows={({ from, to, count }) => `${from}-${to} / 共 ${count}`}
          />
        </CardContent>
      </Card>

      <Dialog open={Boolean(selectedEvent)} onClose={() => setSelectedEvent(null)} fullWidth maxWidth="md">
        <DialogTitle>计费事件详情</DialogTitle>
        <DialogContent dividers>
          {selectedEvent ? (
            <Stack spacing={2}>
              <Box>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip size="small" variant="outlined" label={selectedEvent.module_label} />
                  <Chip size="small" color={getEventColor(selectedEvent.event_kind)} label={selectedEvent.event_label} />
                  <Chip size="small" color={getTaskStatusColor(selectedEvent.task_status)} label={formatTaskStatus(selectedEvent.task_status)} />
                  <Chip
                    size="small"
                    color={getPricingStatusColor(selectedEvent.pricing_status)}
                    label={formatPricingStatus(selectedEvent.pricing_status)}
                  />
                  <Chip size="small" variant="outlined" label={`阶段：${formatStageLabel(selectedEvent.stage)}`} />
                  <Chip
                    size="small"
                    color={getMarginColor(selectedEvent.operating_snapshot?.margin_status)}
                    label={formatMarginStatus(selectedEvent.operating_snapshot?.margin_status)}
                  />
                </Stack>
                <Typography variant="h6" sx={{ mt: 1.5 }}>
                  {selectedEvent.title}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                  {selectedEvent.summary}
                </Typography>

                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mt: 2 }}>
                  {normalizeActionPath(selectedEvent.action_path) ? (
                    <Button variant="contained" onClick={() => handleOpenEventAction(selectedEvent)}>
                      {selectedEvent.action_label || '跳转到业务页面'}
                    </Button>
                  ) : null}
                  <Button
                    variant="outlined"
                    onClick={() => handleApplyDialogFilters({ userId: String(selectedEvent.target_user_id) })}
                  >
                    仅看该用户
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={() => handleApplyDialogFilters({ moduleKey: selectedEvent.module_key })}
                  >
                    仅看该模块
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={() =>
                      handleApplyDialogFilters({
                        keyword: selectedEvent.billing_key,
                        eventKind: '',
                        marginStatus: '',
                      })
                    }
                  >
                    查看同计费键链路
                  </Button>
                </Stack>
              </Box>

              <Stack spacing={1.5}>
                {selectedEvent.operating_snapshot?.margin_status === 'negative' ? (
                  <Alert severity="error">
                    本次结算为负毛利，建议优先复核供应商真实成本、折扣来源以及用户计价策略。
                  </Alert>
                ) : null}
                {selectedEvent.operating_snapshot?.margin_status === 'warning' ? (
                  <Alert severity="warning">
                    本次结算已进入低毛利预警区间，建议关注折扣捕获率、让利比例和模块近期毛利分布。
                  </Alert>
                ) : null}
                {selectedEvent.task_status === 'running' ? (
                  <Alert severity="info">任务仍在运行中，当前金额可能继续变化，适合结合冻结事件和后续结算事件一起追踪。</Alert>
                ) : null}
                {selectedEvent.pricing_status === 'estimated' ? (
                  <Alert severity="info">当前仍是预估计费口径，适合在任务完成后回看正式结算是否与冻结金额匹配。</Alert>
                ) : null}
                {selectedEvent.operating_snapshot && Math.abs(selectedEvent.operating_snapshot.policy_alignment_gap_yuan) >= 0.01 ? (
                  <Alert
                    severity={selectedEvent.operating_snapshot.policy_alignment_gap_yuan < 0 ? 'warning' : 'info'}
                  >
                    {buildPolicyAlignmentMessage(selectedEvent.operating_snapshot.policy_alignment_gap_yuan)}
                  </Alert>
                ) : null}
                {selectedEvent.operating_snapshot?.negative_margin_blocked ? (
                  <Alert severity="warning">负毛利拦截已触发，说明策略层已经识别到本次结算存在负毛利风险。</Alert>
                ) : null}
              </Stack>

              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  事件上下文
                </Typography>
                <Box
                  sx={{
                    mt: 1.5,
                    display: 'grid',
                    gap: 1.5,
                    gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(3, minmax(0, 1fr))' },
                  }}
                >
                  <DetailMetricCard
                    label="计费键"
                    value={selectedEvent.billing_key || '-'}
                    caption="用于串联冻结、结算、释放三类事件"
                  />
                  <DetailMetricCard
                    label="用户 / 操作人"
                    value={`用户 ${selectedEvent.target_user_id}`}
                    caption={`操作人：${selectedEvent.operator_username}`}
                  />
                  <DetailMetricCard
                    label="积分 / 金额"
                    value={`${selectedEvent.amount_points.toFixed(2)} 积分`}
                    caption={`金额：${formatCurrency(selectedEvent.amount_yuan)}`}
                  />
                  <DetailMetricCard
                    label="任务 / 计费状态"
                    value={formatTaskStatus(selectedEvent.task_status)}
                    caption={`计费状态：${formatPricingStatus(selectedEvent.pricing_status)}`}
                  />
                  <DetailMetricCard
                    label="项目定位"
                    value={selectedEvent.project_id ? `项目 ${selectedEvent.project_id}` : '-'}
                    caption={`有声书项目：${selectedEvent.audiobook_project_id || '-'}`}
                  />
                  <DetailMetricCard
                    label="运行定位"
                    value={selectedEvent.run_id || '-'}
                    caption={`阶段：${formatStageLabel(selectedEvent.stage)}`}
                  />
                  <DetailMetricCard
                    label="创建时间"
                    value={new Date(selectedEvent.created_at).toLocaleString('zh-CN')}
                  />
                  <DetailMetricCard
                    label="跳转入口"
                    value={selectedEvent.action_label || '暂无跳转入口'}
                    caption={selectedEvent.action_path || '未提供路径'}
                  />
                </Box>
              </Paper>

              {selectedEvent.operating_snapshot ? (
                <Paper variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                    经营快照
                  </Typography>
                  <Box
                    sx={{
                      mt: 1.5,
                      display: 'grid',
                      gap: 1.5,
                      gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))', lg: 'repeat(3, minmax(0, 1fr))' },
                    }}
                  >
                    <DetailMetricCard
                      label="用户计费"
                      value={formatCurrency(selectedEvent.operating_snapshot.user_billed_yuan)}
                      caption={`策略目标：${formatCurrency(selectedEvent.operating_snapshot.policy_target_user_billed_yuan)}`}
                    />
                    <DetailMetricCard
                      label="供应商折后成本"
                      value={formatCurrency(selectedEvent.operating_snapshot.supplier_discounted_cost_yuan)}
                      caption={`供应商公开价：${formatCurrency(selectedEvent.operating_snapshot.supplier_list_price_yuan)}`}
                    />
                    <DetailMetricCard
                      label="平台毛利"
                      value={formatCurrency(selectedEvent.operating_snapshot.platform_gross_profit_yuan)}
                      caption="用户计费减去供应商折后成本"
                      valueColor={
                        selectedEvent.operating_snapshot.platform_gross_profit_yuan < 0 ? 'error.main' : 'success.main'
                      }
                    />
                    <DetailMetricCard
                      label="综合毛利率"
                      value={formatPercent(selectedEvent.operating_snapshot.platform_margin_rate)}
                      caption={`毛利状态：${formatMarginStatus(selectedEvent.operating_snapshot.margin_status)}`}
                      valueColor={
                        selectedEvent.operating_snapshot.margin_status === 'negative'
                          ? 'error.main'
                          : selectedEvent.operating_snapshot.margin_status === 'warning'
                            ? 'warning.main'
                            : 'success.main'
                      }
                    />
                    <DetailMetricCard
                      label="策略对齐差"
                      value={formatCurrency(selectedEvent.operating_snapshot.policy_alignment_gap_yuan)}
                      caption={buildPolicyAlignmentMessage(selectedEvent.operating_snapshot.policy_alignment_gap_yuan)}
                      valueColor={
                        selectedEvent.operating_snapshot.policy_alignment_gap_yuan < 0
                          ? 'warning.main'
                          : selectedEvent.operating_snapshot.policy_alignment_gap_yuan > 0
                            ? 'info.main'
                            : 'text.primary'
                      }
                    />
                    <DetailMetricCard
                      label="供应商折扣率"
                      value={formatPercent(selectedEvent.operating_snapshot.supplier_discount_rate)}
                      caption={selectedEvent.operating_snapshot.supplier_discount_rate_source}
                    />
                  </Box>

                  <Stack spacing={1} sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      平台保留折扣：{formatCurrency(selectedEvent.operating_snapshot.captured_discount_yuan)} · 让利用户：
                      {formatCurrency(selectedEvent.operating_snapshot.shared_discount_yuan)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      供应商优惠额：{formatCurrency(selectedEvent.operating_snapshot.supplier_discount_yuan)} · 用户计价基准：
                      {formatCurrency(selectedEvent.operating_snapshot.user_basis_yuan)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      负毛利拦截：{selectedEvent.operating_snapshot.negative_margin_blocked ? '已触发' : '未触发'}
                    </Typography>
                  </Stack>
                </Paper>
              ) : (
                <Alert severity="info">该事件暂无经营快照，通常冻结或释放事件不会附带完整结算快照。</Alert>
              )}
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSelectedEvent(null)}>关闭</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
