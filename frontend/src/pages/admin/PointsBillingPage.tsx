import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
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
import RefreshIcon from '@mui/icons-material/Refresh'
import {
  type AdminPointsBillingModuleSummary,
  type AdminPointsBillingEvent,
  type AdminPointsBillingSummary,
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'
import { useFormats } from '@/i18n'

type FilterState = {
  userId: string
  moduleKey: string
  eventKind: string
  marginStatus: string
  keyword: string
}

function buildModuleOptions(t: TFunction): Array<{ value: string; label: string }> {
  return [
    { value: '', label: t('admin.pointsBilling.filters.allModules') },
    { value: 'audiobook', label: t('admin.pointsBilling.filters.audiobook') },
    { value: 'dreamweaver', label: t('admin.pointsBilling.filters.dreamweaver') },
  ]
}

function buildEventOptions(t: TFunction): Array<{ value: string; label: string }> {
  return [
    { value: '', label: t('admin.pointsBilling.filters.allEvents') },
    { value: 'freeze', label: t('admin.pointsBilling.filters.freeze') },
    { value: 'settle', label: t('admin.pointsBilling.filters.settle') },
    { value: 'release', label: t('admin.pointsBilling.filters.release') },
  ]
}

function buildMarginOptions(t: TFunction): Array<{ value: string; label: string }> {
  return [
    { value: '', label: t('admin.pointsBilling.filters.allMarginStatus') },
    { value: 'healthy', label: t('admin.pointsBilling.filters.marginHealthy') },
    { value: 'warning', label: t('admin.pointsBilling.filters.marginWarning') },
    { value: 'negative', label: t('admin.pointsBilling.filters.marginNegative') },
  ]
}

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

function formatPricingStatus(status?: string | null, t?: TFunction) {
  if (status === 'actual') return t ? t('admin.pointsBilling.status.actual') : '实际计费'
  if (status === 'estimated') return t ? t('admin.pointsBilling.status.estimated') : '预估计费'
  if (status === 'pending') return t ? t('admin.pointsBilling.status.pending') : '待计费'
  return status || '-'
}

function formatTaskStatus(status?: string | null, t?: TFunction) {
  if (status === 'running') return t ? t('admin.pointsBilling.status.running') : '运行中'
  if (status === 'completed') return t ? t('admin.pointsBilling.status.completed') : '已完成'
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

function formatMarginStatus(status?: string | null, t?: TFunction) {
  if (status === 'negative') return t ? t('admin.pointsBilling.status.negative') : '负毛利'
  if (status === 'warning') return t ? t('admin.pointsBilling.status.warning') : '低毛利预警'
  if (status === 'healthy') return t ? t('admin.pointsBilling.status.healthy') : '毛利健康'
  return '-'
}

function getSummaryAlertSeverity(summary: AdminPointsBillingSummary): 'success' | 'warning' | 'error' {
  if (summary.negative_event_count > 0) return 'error'
  if (summary.warning_event_count > 0) return 'warning'
  return 'success'
}

function getSummaryAlertMessage(summary: AdminPointsBillingSummary, t?: TFunction) {
  if (summary.negative_event_count > 0) {
    return t ? t('admin.pointsBilling.summaryAlert.negative', { count: summary.negative_event_count }) : `当前范围存在 ${summary.negative_event_count} 条负毛利结算，建议优先复核供应商折扣与用户计价策略。`
  }
  if (summary.warning_event_count > 0) {
    return t ? t('admin.pointsBilling.summaryAlert.warning', { count: summary.warning_event_count }) : `当前范围存在 ${summary.warning_event_count} 条低毛利结算，建议优先关注模块毛利分布和让利策略。`
  }
  return t ? t('admin.pointsBilling.summaryAlert.healthy') : '当前范围的结算毛利健康，暂未发现低毛利或负毛利结算。'
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

const STAGE_LABELS: Record<string, string> = {
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

const STAGE_LABEL_KEYS: Record<string, string> = {
  init: 'admin.pointsBilling.stages.init',
  strategy: 'admin.pointsBilling.stages.strategy',
  storyboard: 'admin.pointsBilling.stages.storyboard',
  delivery: 'admin.pointsBilling.stages.delivery',
  design: 'admin.pointsBilling.stages.design',
  script_adaptation: 'admin.pointsBilling.stages.scriptAdaptation',
  quality_review: 'admin.pointsBilling.stages.qualityReview',
  audio_prompt_review: 'admin.pointsBilling.stages.audioPromptReview',
  tts_synthesis: 'admin.pointsBilling.stages.ttsSynthesis',
  audio_mixing: 'admin.pointsBilling.stages.audioMixing',
  final_audio_review: 'admin.pointsBilling.stages.finalAudioReview',
  waiting_script_approval: 'admin.pointsBilling.stages.waitingScriptApproval',
  waiting_approval: 'admin.pointsBilling.stages.waitingApproval',
  waiting_video_confirmation: 'admin.pointsBilling.stages.waitingVideoConfirmation',
}

function formatStageLabel(stage?: string | null, t?: TFunction) {
  const normalized = String(stage || '').trim().toLowerCase()
  if (!normalized) return '-'
  if (t) {
    const key = STAGE_LABEL_KEYS[normalized]
    if (key) return t(key)
  }
  return STAGE_LABELS[normalized] || stage || '-'
}

function normalizeActionPath(actionPath?: string | null) {
  const raw = String(actionPath || '').trim()
  if (!raw) return null
  if (/^https?:\/\//i.test(raw)) return raw
  return raw.startsWith('/') ? raw : `/${raw.replace(/^\/+/, '')}`
}

function buildPolicyAlignmentMessage(gap?: number | null, t?: TFunction) {
  if (typeof gap !== 'number' || Number.isNaN(gap)) {
    return t ? t('admin.pointsBilling.policyGap.noData') : '当前没有可用的策略对齐差数据。'
  }

  if (Math.abs(gap) < 0.01) {
    return t ? t('admin.pointsBilling.policyGap.aligned') : '当前用户计费与策略目标基本一致。'
  }

  if (gap > 0) {
    return t
      ? t('admin.pointsBilling.policyGap.above', { amount: formatCurrency(gap) })
      : `当前用户实付高于策略目标 ${formatCurrency(gap)}，可能存在历史计价偏高或补差结算。`
  }

  return t
    ? t('admin.pointsBilling.policyGap.below', { amount: formatCurrency(Math.abs(gap)) })
    : `当前用户实付低于策略目标 ${formatCurrency(Math.abs(gap))}，说明本次结算存在额外让利。`
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
  // 只解构 formatDateTimeWithSeconds：本文件已有 formatCurrency / formatPercent 等本地
  // helper，它们的展示约定与 useFormats 的同名函数不同，不能被遮蔽。
  // 计费事件保留到秒：对账时同一分钟内的多笔扣费要排得出先后。
  const { t } = useTranslation()
  const { formatDateTimeWithSeconds } = useFormats()
  const navigate = useNavigate()
  const moduleOptions = buildModuleOptions(t)
  const eventOptions = buildEventOptions(t)
  const marginOptions = buildMarginOptions(t)
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
      setError(await extractApiErrorMessage(err, t('admin.pointsBilling.fetchFailed')))
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
          <Typography variant="h4">{t('admin.pointsBilling.title')}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
            {t('admin.pointsBilling.subtitle')}
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={refreshing ? <CircularProgress size={18} /> : <RefreshIcon />}
          onClick={() => void fetchEvents(true)}
          disabled={refreshing}
        >
          {t('admin.common.refresh')}
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
            <Typography variant="h6">{t('admin.pointsBilling.overview.title')}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
              {t('admin.pointsBilling.overview.subtitle')}
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
                {t('admin.pointsBilling.overview.recent7dTitle')}
              </Typography>
              <Typography variant="h4" sx={{ mt: 0.75 }}>
                {summary.recent_7d_settle_count}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                {t('admin.pointsBilling.overview.recent7dCaption')}
              </Typography>
            </Paper>

            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="overline" color="text.secondary">
                {t('admin.pointsBilling.overview.warningTitle')}
              </Typography>
              <Typography variant="h4" color={summary.warning_event_count > 0 ? 'warning.main' : 'text.primary'} sx={{ mt: 0.75 }}>
                {summary.warning_event_count}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                {t('admin.pointsBilling.overview.warningCaption')}
              </Typography>
            </Paper>

            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="overline" color="text.secondary">
                {t('admin.pointsBilling.overview.negativeTitle')}
              </Typography>
              <Typography variant="h4" color={summary.negative_event_count > 0 ? 'error.main' : 'text.primary'} sx={{ mt: 0.75 }}>
                {summary.negative_event_count}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                {t('admin.pointsBilling.overview.negativeCaption')}
              </Typography>
            </Paper>

            <Paper variant="outlined" sx={{ p: 2 }}>
              <Typography variant="overline" color="text.secondary">
                {t('admin.pointsBilling.overview.marginTitle')}
              </Typography>
              <Typography variant="h4" sx={{ mt: 0.75 }}>
                {formatPercent(summary.blended_margin_rate)}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                {t('admin.pointsBilling.overview.marginCaption', {
                  billed: formatCurrency(summary.total_user_billed_yuan),
                  profit: formatCurrency(summary.total_platform_gross_profit_yuan),
                })}
              </Typography>
            </Paper>
          </Box>

          <Alert severity={getSummaryAlertSeverity(summary)} sx={{ mt: 2 }}>
            {getSummaryAlertMessage(summary, t)}
          </Alert>

          <Box sx={{ mt: 3 }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.5 }}>
              {t('admin.pointsBilling.moduleDist.title')}
            </Typography>
            <TableContainer component={Paper} variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>{t('admin.pointsBilling.moduleDist.colModule')}</TableCell>
                    <TableCell>{t('admin.pointsBilling.moduleDist.colSettleEvents')}</TableCell>
                    <TableCell>{t('admin.pointsBilling.moduleDist.colRiskEvents')}</TableCell>
                    <TableCell>{t('admin.pointsBilling.moduleDist.colUserBilled')}</TableCell>
                    <TableCell>{t('admin.pointsBilling.moduleDist.colPlatformProfit')}</TableCell>
                    <TableCell>{t('admin.pointsBilling.moduleDist.colMarginRate')}</TableCell>
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
                          <Chip
                            size="small"
                            color="warning"
                            variant="outlined"
                            label={t('admin.pointsBilling.moduleDist.lowMargin', { count: item.warning_event_count })}
                          />
                          <Chip
                            size="small"
                            color="error"
                            variant="outlined"
                            label={t('admin.pointsBilling.moduleDist.negativeMargin', { count: item.negative_event_count })}
                          />
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
                        <Alert severity="info">{t('admin.pointsBilling.moduleDist.empty')}</Alert>
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
              label={t('admin.pointsBilling.filters.userIdLabel')}
              size="small"
              value={filters.userId}
              onChange={(event) => handleFilterChange('userId', event.target.value)}
              placeholder={t('admin.pointsBilling.filters.userIdPlaceholder')}
            />
            <FormControl size="small">
              <InputLabel>{t('admin.pointsBilling.filters.module')}</InputLabel>
              <Select
                value={filters.moduleKey}
                label={t('admin.pointsBilling.filters.module')}
                onChange={(event) => handleFilterChange('moduleKey', event.target.value)}
              >
                {moduleOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small">
              <InputLabel>{t('admin.pointsBilling.filters.eventKind')}</InputLabel>
              <Select
                value={filters.eventKind}
                label={t('admin.pointsBilling.filters.eventKind')}
                onChange={(event) => handleFilterChange('eventKind', event.target.value)}
              >
                {eventOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <FormControl size="small">
              <InputLabel>{t('admin.pointsBilling.filters.marginStatus')}</InputLabel>
              <Select
                value={filters.marginStatus}
                label={t('admin.pointsBilling.filters.marginStatus')}
                onChange={(event) => handleFilterChange('marginStatus', event.target.value)}
              >
                {marginOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              label={t('admin.pointsBilling.filters.keywordLabel')}
              size="small"
              value={filters.keyword}
              onChange={(event) => handleFilterChange('keyword', event.target.value)}
              placeholder={t('admin.pointsBilling.filters.keywordPlaceholder')}
            />
          </Box>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 2 }}>
            <Button variant="outlined" onClick={handleResetFilters}>
              {t('admin.pointsBilling.filters.reset')}
            </Button>
            <Button
              variant={!filters.eventKind && !filters.marginStatus ? 'contained' : 'outlined'}
              onClick={() => handleApplyQuickFilter('')}
            >
              {t('admin.pointsBilling.filters.allEvents')}
            </Button>
            <Button
              color="warning"
              variant={isQuickFilterActive(filters, 'warning') ? 'contained' : 'outlined'}
              onClick={() => handleApplyQuickFilter('warning')}
            >
              {t('admin.pointsBilling.filters.lowMarginSettle')}
            </Button>
            <Button
              color="error"
              variant={isQuickFilterActive(filters, 'negative') ? 'contained' : 'outlined'}
              onClick={() => handleApplyQuickFilter('negative')}
            >
              {t('admin.pointsBilling.filters.negativeMarginSettle')}
            </Button>
            <Typography variant="body2" color="text.secondary" sx={{ alignSelf: 'center' }}>
              {t('admin.pointsBilling.filters.totalLabel', { count: total })}
            </Typography>
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1.5 }}>
            {t('admin.pointsBilling.filters.hint')}
          </Typography>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <TableContainer component={Paper} variant="outlined">
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>{t('admin.pointsBilling.table.colTime')}</TableCell>
                  <TableCell>{t('admin.pointsBilling.table.colUser')}</TableCell>
                  <TableCell>{t('admin.pointsBilling.table.colModuleEvent')}</TableCell>
                  <TableCell>{t('admin.pointsBilling.table.colTitle')}</TableCell>
                  <TableCell>{t('admin.pointsBilling.table.colPointsAmount')}</TableCell>
                  <TableCell>{t('admin.pointsBilling.table.colTaskStatus')}</TableCell>
                  <TableCell>{t('admin.pointsBilling.table.colMarginStatus')}</TableCell>
                  <TableCell align="right">{t('admin.pointsBilling.table.colActions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.id} hover>
                    <TableCell>{formatDateTimeWithSeconds(item.created_at)}</TableCell>
                    <TableCell>
                      <Typography variant="body2">{item.operator_username}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {t('admin.pointsBilling.table.userIdSuffix', { id: item.target_user_id })}
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
                      <Typography variant="body2">{t('admin.pointsBilling.table.pointsSuffix', { points: item.amount_points.toFixed(2) })}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatCurrency(item.amount_yuan)}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Typography variant="body2">{formatTaskStatus(item.task_status, t)}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {formatPricingStatus(item.pricing_status, t)}
                      </Typography>
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={getMarginColor(item.operating_snapshot?.margin_status)}
                        label={formatMarginStatus(item.operating_snapshot?.margin_status, t)}
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Button size="small" onClick={() => setSelectedEvent(item)}>
                        {t('admin.common.viewDetail')}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!loading && items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8}>
                      <Alert severity="info">{t('admin.pointsBilling.table.empty')}</Alert>
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
            rowsPerPageOptions={[10, 20, 25, 50, 100]}
            onRowsPerPageChange={(event) => {
              setRowsPerPage(parseInt(event.target.value, 10))
              setPage(0)
            }}
            labelRowsPerPage={t('admin.pointsBilling.table.rowsPerPage')}
            labelDisplayedRows={({ from, to, count }) =>
              t('admin.pointsBilling.table.displayedRows', { from, to, count })
            }
          />
        </CardContent>
      </Card>

      <Dialog open={Boolean(selectedEvent)} onClose={() => setSelectedEvent(null)} fullWidth maxWidth="md">
        <DialogTitle>{t('admin.pointsBilling.detail.title')}</DialogTitle>
        <DialogContent dividers>
          {selectedEvent ? (
            <Stack spacing={2}>
              <Box>
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                  <Chip size="small" variant="outlined" label={selectedEvent.module_label} />
                  <Chip size="small" color={getEventColor(selectedEvent.event_kind)} label={selectedEvent.event_label} />
                  <Chip size="small" color={getTaskStatusColor(selectedEvent.task_status)} label={formatTaskStatus(selectedEvent.task_status, t)} />
                  <Chip
                    size="small"
                    color={getPricingStatusColor(selectedEvent.pricing_status)}
                    label={formatPricingStatus(selectedEvent.pricing_status, t)}
                  />
                  <Chip size="small" variant="outlined" label={t('admin.pointsBilling.detail.stagePrefix', { stage: formatStageLabel(selectedEvent.stage, t) })} />
                  <Chip
                    size="small"
                    color={getMarginColor(selectedEvent.operating_snapshot?.margin_status)}
                    label={formatMarginStatus(selectedEvent.operating_snapshot?.margin_status, t)}
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
                      {selectedEvent.action_label || t('admin.pointsBilling.detail.actionFallback')}
                    </Button>
                  ) : null}
                  <Button
                    variant="outlined"
                    onClick={() => handleApplyDialogFilters({ userId: String(selectedEvent.target_user_id) })}
                  >
                     {t('admin.pointsBilling.detail.onlyUser')}
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={() => handleApplyDialogFilters({ moduleKey: selectedEvent.module_key })}
                  >
                     {t('admin.pointsBilling.detail.onlyModule')}
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
                     {t('admin.pointsBilling.detail.sameBillingKey')}
                  </Button>
                </Stack>
              </Box>

              <Stack spacing={1.5}>
                {selectedEvent.operating_snapshot?.margin_status === 'negative' ? (
                  <Alert severity="error">
                    {t('admin.pointsBilling.detail.alertNegative')}
                  </Alert>
                ) : null}
                {selectedEvent.operating_snapshot?.margin_status === 'warning' ? (
                  <Alert severity="warning">
                    {t('admin.pointsBilling.detail.alertWarning')}
                  </Alert>
                ) : null}
                {selectedEvent.task_status === 'running' ? (
                  <Alert severity="info">{t('admin.pointsBilling.detail.alertTaskRunning')}</Alert>
                ) : null}
                {selectedEvent.pricing_status === 'estimated' ? (
                  <Alert severity="info">{t('admin.pointsBilling.detail.alertEstimated')}</Alert>
                ) : null}
                {selectedEvent.operating_snapshot && Math.abs(selectedEvent.operating_snapshot.policy_alignment_gap_yuan) >= 0.01 ? (
                  <Alert
                    severity={selectedEvent.operating_snapshot.policy_alignment_gap_yuan < 0 ? 'warning' : 'info'}
                  >
                    {buildPolicyAlignmentMessage(selectedEvent.operating_snapshot.policy_alignment_gap_yuan, t)}
                  </Alert>
                ) : null}
                {selectedEvent.operating_snapshot?.negative_margin_blocked ? (
                  <Alert severity="warning">{t('admin.pointsBilling.detail.alertBlocked')}</Alert>
                ) : null}
              </Stack>

              <Paper variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                  {t('admin.pointsBilling.detail.contextTitle')}
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
                    label={t('admin.pointsBilling.detail.context.billingKey')}
                    value={selectedEvent.billing_key || '-'}
                    caption={t('admin.pointsBilling.detail.context.billingKeyCaption')}
                  />
                  <DetailMetricCard
                    label={t('admin.pointsBilling.detail.context.userOperator')}
                    value={t('admin.pointsBilling.detail.context.userValue', { id: selectedEvent.target_user_id })}
                    caption={t('admin.pointsBilling.detail.context.operatorCaption', { name: selectedEvent.operator_username })}
                  />
                  <DetailMetricCard
                    label={t('admin.pointsBilling.detail.context.pointsAmount')}
                    value={t('admin.pointsBilling.detail.context.pointsValue', { points: selectedEvent.amount_points.toFixed(2) })}
                    caption={t('admin.pointsBilling.detail.context.amountCaption', { amount: formatCurrency(selectedEvent.amount_yuan) })}
                  />
                  <DetailMetricCard
                    label={t('admin.pointsBilling.detail.context.taskPricing')}
                    value={formatTaskStatus(selectedEvent.task_status, t)}
                    caption={t('admin.pointsBilling.detail.context.pricingCaption', {
                      status: formatPricingStatus(selectedEvent.pricing_status, t),
                    })}
                  />
                  <DetailMetricCard
                    label={t('admin.pointsBilling.detail.context.projectLoc')}
                    value={
                      selectedEvent.project_id
                        ? t('admin.pointsBilling.detail.context.projectValue', { id: selectedEvent.project_id })
                        : '-'
                    }
                    caption={t('admin.pointsBilling.detail.context.audiobookCaption', {
                      id: selectedEvent.audiobook_project_id || '-',
                    })}
                  />
                  <DetailMetricCard
                    label={t('admin.pointsBilling.detail.context.runLoc')}
                    value={selectedEvent.run_id || '-'}
                    caption={t('admin.pointsBilling.detail.context.stageCaption', {
                      stage: formatStageLabel(selectedEvent.stage, t),
                    })}
                  />
                  <DetailMetricCard
                    label={t('admin.pointsBilling.detail.context.createdAt')}
                    value={formatDateTimeWithSeconds(selectedEvent.created_at)}
                  />
                  <DetailMetricCard
                    label={t('admin.pointsBilling.detail.context.actionEntry')}
                    value={selectedEvent.action_label || t('admin.pointsBilling.detail.context.actionValue')}
                    caption={selectedEvent.action_path || t('admin.pointsBilling.detail.context.pathFallback')}
                  />
                </Box>
              </Paper>

              {selectedEvent.operating_snapshot ? (
                <Paper variant="outlined" sx={{ p: 2 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                    {t('admin.pointsBilling.detail.snapshotTitle')}
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
                      label={t('admin.pointsBilling.detail.snapshot.userBilled')}
                      value={formatCurrency(selectedEvent.operating_snapshot.user_billed_yuan)}
                      caption={t('admin.pointsBilling.detail.snapshot.policyTargetCaption', {
                        amount: formatCurrency(selectedEvent.operating_snapshot.policy_target_user_billed_yuan),
                      })}
                    />
                    <DetailMetricCard
                      label={t('admin.pointsBilling.detail.snapshot.supplierCost')}
                      value={formatCurrency(selectedEvent.operating_snapshot.supplier_discounted_cost_yuan)}
                      caption={t('admin.pointsBilling.detail.snapshot.supplierListCaption', {
                        amount: formatCurrency(selectedEvent.operating_snapshot.supplier_list_price_yuan),
                      })}
                    />
                    <DetailMetricCard
                      label={t('admin.pointsBilling.detail.snapshot.platformProfit')}
                      value={formatCurrency(selectedEvent.operating_snapshot.platform_gross_profit_yuan)}
                      caption={t('admin.pointsBilling.detail.snapshot.profitCaption')}
                      valueColor={
                        selectedEvent.operating_snapshot.platform_gross_profit_yuan < 0 ? 'error.main' : 'success.main'
                      }
                    />
                    <DetailMetricCard
                      label={t('admin.pointsBilling.detail.snapshot.marginRate')}
                      value={formatPercent(selectedEvent.operating_snapshot.platform_margin_rate)}
                      caption={t('admin.pointsBilling.detail.snapshot.marginStatusCaption', {
                        status: formatMarginStatus(selectedEvent.operating_snapshot.margin_status, t),
                      })}
                      valueColor={
                        selectedEvent.operating_snapshot.margin_status === 'negative'
                          ? 'error.main'
                          : selectedEvent.operating_snapshot.margin_status === 'warning'
                            ? 'warning.main'
                            : 'success.main'
                      }
                    />
                    <DetailMetricCard
                      label={t('admin.pointsBilling.detail.snapshot.alignmentGap')}
                      value={formatCurrency(selectedEvent.operating_snapshot.policy_alignment_gap_yuan)}
                      caption={buildPolicyAlignmentMessage(selectedEvent.operating_snapshot.policy_alignment_gap_yuan, t)}
                      valueColor={
                        selectedEvent.operating_snapshot.policy_alignment_gap_yuan < 0
                          ? 'warning.main'
                          : selectedEvent.operating_snapshot.policy_alignment_gap_yuan > 0
                            ? 'info.main'
                            : 'text.primary'
                      }
                    />
                    <DetailMetricCard
                      label={t('admin.pointsBilling.detail.snapshot.discountRate')}
                      value={formatPercent(selectedEvent.operating_snapshot.supplier_discount_rate)}
                      caption={selectedEvent.operating_snapshot.supplier_discount_rate_source}
                    />
                  </Box>

                  <Stack spacing={1} sx={{ mt: 2 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pointsBilling.detail.snapshot.capturedShared', {
                        captured: formatCurrency(selectedEvent.operating_snapshot.captured_discount_yuan),
                        shared: formatCurrency(selectedEvent.operating_snapshot.shared_discount_yuan),
                      })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pointsBilling.detail.snapshot.supplierDiscount', {
                        supplier: formatCurrency(selectedEvent.operating_snapshot.supplier_discount_yuan),
                        basis: formatCurrency(selectedEvent.operating_snapshot.user_basis_yuan),
                      })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pointsBilling.detail.snapshot.blockStatus', {
                        status: selectedEvent.operating_snapshot.negative_margin_blocked
                          ? t('admin.pointsBilling.detail.snapshot.blocked')
                          : t('admin.pointsBilling.detail.snapshot.notBlocked'),
                      })}
                    </Typography>
                  </Stack>
                </Paper>
              ) : (
                <Alert severity="info">{t('admin.pointsBilling.detail.noSnapshot')}</Alert>
              )}
            </Stack>
          ) : null}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSelectedEvent(null)}>{t('action.close')}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
