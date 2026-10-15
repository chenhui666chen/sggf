import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Avatar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Container,
  Divider,
  FormControl,
  FormControlLabel,
  Grid,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
  alpha,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoStoriesIcon from '@mui/icons-material/AutoStories'
import DashboardCustomizeOutlinedIcon from '@mui/icons-material/DashboardCustomizeOutlined'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import LogoutIcon from '@mui/icons-material/Logout'
import MovieIcon from '@mui/icons-material/Movie'
import RefreshIcon from '@mui/icons-material/Refresh'
import SaveIcon from '@mui/icons-material/Save'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import SecurityOutlinedIcon from '@mui/icons-material/SecurityOutlined'
import { useFormats } from '@/i18n'
import { useTranslation } from 'react-i18next'
import { checkPasswordStrength } from '@/utils/passwordPolicy'
import { clearOAuthContext, generateOAuthState, getRequiredOAuthOrigin, storeOAuthContext, type OAuthProvider } from '@/utils/auth'
import { RootState, AppDispatch } from '@/store/store'
import { getCurrentUser, performLogout } from '@/store/slices/authSlice'
import { CONSENT_VERSIONS } from '@/constants/consent'
import {
  apiClient,
  extractApiErrorMessage,
  type UserCenterPointsOverviewResponse,
  type VideoApiApplication,
} from '@/services/api'
import { useUserCenterAssetConnectedOverviewRowsFromInput } from '@/hooks/useUserCenterAssetConnectedOverviewRowsFromInput'
import { useUserCenterOverviewTabMetrics } from '@/hooks/useUserCenterOverviewTabMetrics'
import UserAssetWorkspaceContent from '@/components/user-assets/UserAssetWorkspaceContent'
import { useUserAssetWorkspaceViewModel } from '@/hooks/useUserAssetWorkspaceViewModel'
import type { AudiobookProjectSummary, DeletedAudiobookProject } from '@/types/audiobook'

interface ProjectRecord {
  id: number
  title?: string
  description?: string
  genre?: string
  created_at?: string
  updated_at?: string | null
}

interface DeletedChapterRecord {
  id: number
  title: string
  content?: string
  word_count?: number
  project_id: number
  project_name?: string
  deleted_at?: string
  created_at?: string
}

interface DreamweaverRunSummary {
  run_id: string
  status?: string | null
  stage?: string | null
  created_at?: string | null
  updated_at?: string | null
}

type UserCenterTab = 'overview' | 'creation' | 'assets' | 'points' | 'records' | 'security' | 'video-api'

type FeedbackState = {
  type: 'success' | 'error'
  text: string
}

type ProjectAggregate = ProjectRecord & {
  audiobookCount: number
  dramaRunCount: number
}

const tabs: Array<{ value: UserCenterTab; label: string }> = [
  { value: 'overview', label: 'userCenter.tabs.overview' },
  { value: 'creation', label: 'userCenter.tabs.creation' },
  { value: 'assets', label: 'userCenter.tabs.assets' },
  { value: 'points', label: 'userCenter.tabs.points' },
  { value: 'records', label: 'userCenter.tabs.records' },
  { value: 'security', label: 'userCenter.tabs.security' },
  { value: 'video-api', label: '视频 API' },
]

const USER_CENTER_TAB_VALUES = new Set<UserCenterTab>(tabs.map((tab) => tab.value))
const USER_CENTER_POINTS_PATH = '/user-center?tab=points'

function normalizeUserCenterTab(value: string | null | undefined): UserCenterTab {
  if (!value) return 'overview'
  return USER_CENTER_TAB_VALUES.has(value as UserCenterTab) ? (value as UserCenterTab) : 'overview'
}

const runningStatuses = new Set(['queued', 'running', 'waiting', 'pending', 'processing'])
const failedStatuses = new Set(['failed', 'error', 'timeout'])

function getPointsEntryStatusMeta(status: string) {
  if (status === 'expired') {
    return { label: 'userCenter.status.expired', color: 'default' as const }
  }
  if (status === 'frozen') {
    return { label: 'userCenter.status.frozen', color: 'warning' as const }
  }
  return { label: 'userCenter.status.active', color: 'success' as const }
}

function getPointsEntryDirectionMeta(direction: string) {
  if (direction === 'expense') {
    return { label: 'userCenter.status.expense', color: 'error' as const }
  }
  if (direction === 'hold') {
    return { label: 'userCenter.status.hold', color: 'warning' as const }
  }
  return { label: 'userCenter.status.income', color: 'success' as const }
}

function getPointsRuleSourceLabel(source?: string | null) {
  return source === 'admin_log' ? 'userCenter.points.sourceAdmin' : 'userCenter.points.sourceDefault'
}

function getPricingBasisLabel(basis?: string | null) {
  return basis === 'standard_price_table' ? 'userCenter.points.basisInternal' : 'userCenter.points.basisPublic'
}

function formatPercentRate(value?: number | null) {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '--'
  return `${(amount * 100).toFixed(amount === 1 ? 0 : 2)}%`
}

function getTaskBillingPricingStatusMeta(status: string) {
  if (status === 'actual') {
    return { label: 'userCenter.billing.actual', color: 'success' as const }
  }
  if (status === 'estimated') {
    return { label: 'userCenter.billing.estimated', color: 'warning' as const }
  }
  return { label: 'userCenter.billing.pending', color: 'default' as const }
}

function getProjectTimestamp(project: ProjectRecord) {
  return new Date(project.updated_at || project.created_at || 0).getTime()
}

function MetricCard(props: { title: string; value: string | number; helper: string; color: string }) {
  const { title, value, helper, color } = props
  return (
    <Card variant="outlined" sx={{ height: '100%', borderRadius: 3, borderColor: 'divider' }}>
      <CardContent>
        <Typography variant="body2" color="text.secondary">
          {title}
        </Typography>
        <Typography variant="h4" sx={{ mt: 1, fontWeight: 700, color }}>
          {value}
        </Typography>
        <Typography variant="body2" sx={{ mt: 1, color: 'text.secondary' }}>
          {helper}
        </Typography>
      </CardContent>
    </Card>
  )
}

export default function UserCenterPage() {
  const { t } = useTranslation()
  const {
    formatDateTime: localizeDateTime,
    formatCurrency: localizeCurrency,
    formatNumber,
  } = useFormats()

  // 下面这四个 helper 原本在模块级，依赖当前语言之后只能待进组件内。它们会被
  // useUserCenterAssetConnectedOverviewRowsFromInput 与 useUserCenterOverviewTabMetrics
  // 放进 useMemo 依赖，因此必须 useCallback 保持引用稳定，否则每次渲染都会重算。
  const formatDateTime = useCallback((value?: string | null) => {
    if (!value) return t('userCenter.common.noTime')
    const timestamp = new Date(value).getTime()
    if (!Number.isFinite(timestamp) || timestamp <= 0) return t('userCenter.common.noTime')
    return localizeDateTime(value)
  }, [localizeDateTime, t])

  const formatCurrency = useCallback((value?: number | null) => {
    const amount = Number(value || 0)
    if (!Number.isFinite(amount)) return '¥0.00'
    return localizeCurrency(amount)
  }, [localizeCurrency])

  /** 账户指标：整数不带小数点，最多两位小数。 */
  const formatAccountMetric = useCallback((value?: number | null) => {
    const amount = Number(value)
    if (!Number.isFinite(amount)) return '--'
    return formatNumber(amount, { maxFractionDigits: 2 })
  }, [formatNumber])

  const formatPointsDelta = useCallback((value?: number | null, direction: 'income' | 'expense' | 'hold' = 'income') => {
    const amount = Number(value)
    if (!Number.isFinite(amount)) return '--'

    const normalized = formatNumber(Math.abs(amount), { maxFractionDigits: 2 })

    if (direction === 'hold') return `${normalized} ${t('userCenter.status.hold')}`
    if (amount > 0) return `+${normalized}`
    if (amount < 0) return `-${normalized}`
    return normalized
  }, [formatNumber])

  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const dispatch = useDispatch<AppDispatch>()
  const { user } = useSelector((state: RootState) => state.auth)

  const [projects, setProjects] = useState<ProjectRecord[]>([])
  const [audiobookMap, setAudiobookMap] = useState<Record<number, AudiobookProjectSummary[]>>({})
  const [dreamweaverMap, setDreamweaverMap] = useState<Record<number, DreamweaverRunSummary[]>>({})
  const [deletedChapters, setDeletedChapters] = useState<DeletedChapterRecord[]>([])
  const [deletedAudiobookProjects, setDeletedAudiobookProjects] = useState<DeletedAudiobookProject[]>([])
  const [pointsOverview, setPointsOverview] = useState<UserCenterPointsOverviewResponse | null>(null)
  const [videoApplications, setVideoApplications] = useState<VideoApiApplication[]>([])
  const [videoApplicationName, setVideoApplicationName] = useState('')
  const [videoApplicationPlan, setVideoApplicationPlan] = useState('standard')
  const [videoApiKey, setVideoApiKey] = useState<string | null>(null)
  const [videoApplicationBusy, setVideoApplicationBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<FeedbackState | null>(null)
  const [restoringKey, setRestoringKey] = useState<string | null>(null)
  const [passwordSubmitting, setPasswordSubmitting] = useState(false)
  const [passwordData, setPasswordData] = useState({ old_password: '', new_password: '', confirm_password: '' })
  // P2-4.2：第三方登录绑定/解绑
  const [bindingProvider, setBindingProvider] = useState<OAuthProvider | null>(null)
  const [unbindingProvider, setUnbindingProvider] = useState<OAuthProvider | null>(null)
  // 手机号绑定：先查占用，未占用直绑；已占用需短信验证码主张所有权（抢占）
  const PHONE_PATTERN = /^1[3-9]\d{9}$/
  const [phoneValue, setPhoneValue] = useState('')
  const [phoneSubmitting, setPhoneSubmitting] = useState(false)
  const [phoneOccupied, setPhoneOccupied] = useState(false)
  const [phoneCode, setPhoneCode] = useState('')
  const [phoneCodeConsented, setPhoneCodeConsented] = useState(false)
  const [phoneCodeSending, setPhoneCodeSending] = useState(false)
  const [phoneResendSeconds, setPhoneResendSeconds] = useState(0)

  const hasAdminRole = user?.roles?.some((role) => role.code === 'admin' || role.code === 'super_admin') ?? false
  const userDisplayName = user?.full_name?.trim() || user?.username || t('userCenter.common.unnamedUser')
  const userIdentity = user?.email || user?.username || t('userCenter.common.noIdentity')
  const userAvatarFallback = userDisplayName.slice(0, 1).toUpperCase()
  const roleNames = (user?.roles || []).map((role) => role.name).filter(Boolean)
  const activeTab = normalizeUserCenterTab(searchParams.get('tab'))
  const assetWorkspaceEnabled = activeTab === 'assets'

  const handleTabChange = useCallback(
    (nextTab: UserCenterTab) => {
      const nextSearchParams = new URLSearchParams(searchParams)
      if (nextTab === 'overview') {
        nextSearchParams.delete('tab')
      } else {
        nextSearchParams.set('tab', nextTab)
      }
      setSearchParams(nextSearchParams, { replace: true })
    },
    [searchParams, setSearchParams],
  )

  useEffect(() => {
    const rawTab = searchParams.get('tab')
    if (!rawTab) return
    if (normalizeUserCenterTab(rawTab) === rawTab) return
    const nextSearchParams = new URLSearchParams(searchParams)
    nextSearchParams.delete('tab')
    setSearchParams(nextSearchParams, { replace: true })
  }, [searchParams, setSearchParams])

  const loadUserCenterData = useCallback(async (silent = false) => {
    if (silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError(null)

    try {
      const [projectsRes, deletedChaptersRes, deletedAudiobookRes, pointsOverviewRes, videoApplicationsRes] = await Promise.all([
        apiClient.getProjects(),
        apiClient.getDeletedChapters(0),
        apiClient.listDeletedProjects(),
        apiClient.getUserCenterPointsOverview(),
        apiClient.listVideoApiApplications().catch(() => ({ data: { items: [] as VideoApiApplication[] } })),
      ])

      const nextProjects = Array.isArray(projectsRes.data) ? (projectsRes.data as ProjectRecord[]) : []
      const nextDeletedChapters = Array.isArray(deletedChaptersRes.data)
        ? (deletedChaptersRes.data as DeletedChapterRecord[])
        : []
      const deletedAudiobookData = deletedAudiobookRes.data as any
      const nextDeletedAudiobookProjects = Array.isArray(deletedAudiobookData?.projects)
        ? (deletedAudiobookData.projects as DeletedAudiobookProject[])
        : Array.isArray(deletedAudiobookData)
          ? (deletedAudiobookData as DeletedAudiobookProject[])
          : []

      setProjects(nextProjects)
      setDeletedChapters(nextDeletedChapters)
      setDeletedAudiobookProjects(nextDeletedAudiobookProjects)
      setPointsOverview((pointsOverviewRes.data || null) as UserCenterPointsOverviewResponse | null)
      setVideoApplications(videoApplicationsRes.data.items || [])

      const details = await Promise.all(
        nextProjects.map(async (project) => {
          const [audiobookRes, dreamweaverRes] = await Promise.allSettled([
            apiClient.getAudiobookProjectsByProject(project.id),
            apiClient.listDreamweaverRuns(project.id, 20),
          ])
          return {
            projectId: project.id,
            audiobookProjects:
              audiobookRes.status === 'fulfilled' && Array.isArray(audiobookRes.value.data)
                ? (audiobookRes.value.data as AudiobookProjectSummary[])
                : [],
            dreamweaverRuns:
              dreamweaverRes.status === 'fulfilled' && Array.isArray(dreamweaverRes.value.data)
                ? (dreamweaverRes.value.data as DreamweaverRunSummary[])
                : [],
          }
        }),
      )

      const nextAudiobookMap: Record<number, AudiobookProjectSummary[]> = {}
      const nextDreamweaverMap: Record<number, DreamweaverRunSummary[]> = {}
      details.forEach((detail) => {
        nextAudiobookMap[detail.projectId] = detail.audiobookProjects
        nextDreamweaverMap[detail.projectId] = detail.dreamweaverRuns
      })
      setAudiobookMap(nextAudiobookMap)
      setDreamweaverMap(nextDreamweaverMap)
    } catch (loadError) {
      const message = await extractApiErrorMessage(loadError, t('userCenter.feedback.loadFailed'))
      if (silent) {
        setFeedback({ type: 'error', text: message })
      } else {
        setError(message)
      }
    } finally {
      if (silent) {
        setRefreshing(false)
      } else {
        setLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    void loadUserCenterData()
  }, [loadUserCenterData])

  const handleAssetWorkspaceFeedback = useCallback((nextFeedback: FeedbackState) => {
    setFeedback(nextFeedback)
  }, [])

  const projectAggregates = useMemo<ProjectAggregate[]>(() => {
    return [...projects]
      .map((project) => ({
        ...project,
        audiobookCount: (audiobookMap[project.id] || []).length,
        dramaRunCount: (dreamweaverMap[project.id] || []).length,
      }))
      .sort((a, b) => getProjectTimestamp(b) - getProjectTimestamp(a))
  }, [audiobookMap, dreamweaverMap, projects])

  const {
    assetFacade,
  } = useUserAssetWorkspaceViewModel({
    projects,
    pointsOverview,
    publishFeedback: handleAssetWorkspaceFeedback,
    refreshUserCenterData: loadUserCenterData,
    navigateToPath: navigate,
    fallbackPath: '/user-center',
    enabled: assetWorkspaceEnabled,
  })

  const overviewMetrics = useMemo(() => {
    let audiobookProjects = 0
    let dramaProjects = 0
    let runningTasks = 0
    let failedTasks = 0

    projectAggregates.forEach((project) => {
      const audiobookProjectsOfProject = audiobookMap[project.id] || []
      const dramaRunsOfProject = dreamweaverMap[project.id] || []
      audiobookProjects += audiobookProjectsOfProject.length
      if (dramaRunsOfProject.length > 0) dramaProjects += 1

      runningTasks += audiobookProjectsOfProject.filter((item) =>
        runningStatuses.has(String(item.status || '').trim().toLowerCase()),
      ).length
      runningTasks += dramaRunsOfProject.filter((item) =>
        runningStatuses.has(String(item.status || '').trim().toLowerCase()),
      ).length

      failedTasks += audiobookProjectsOfProject.filter((item) =>
        failedStatuses.has(String(item.status || '').trim().toLowerCase()),
      ).length
      failedTasks += dramaRunsOfProject.filter((item) =>
        failedStatuses.has(String(item.status || '').trim().toLowerCase()),
      ).length
    })

    return {
      novelProjects: projects.length,
      audiobookProjects,
      dramaProjects,
      runningTasks,
      failedTasks,
      deletedTotal: deletedChapters.length + deletedAudiobookProjects.length,
    }
  }, [audiobookMap, deletedAudiobookProjects.length, deletedChapters.length, dreamweaverMap, projectAggregates, projects.length])

  const recentProjects = projectAggregates.slice(0, 4)

  const connectedBenefitItems = pointsOverview?.benefits.connected_items ?? []
  const plannedBenefitItems = pointsOverview?.benefits.planned_items ?? []
  const audiobookBillingEntries =
    pointsOverview?.ledger.connected_entries.map((entry) => ({
      ...entry,
      moduleLabel: entry.module_label,
      eventLabel: entry.event_label,
      occurredAt: entry.occurred_at,
      projectLabel: entry.project_label,
      actionPath: entry.action_path,
      actionLabel: entry.action_label,
    })) ?? []
  const pendingLedgerSignals =
    pointsOverview?.ledger.pending_signals.map((signal) => ({
      ...signal,
      moduleLabel: signal.module_label,
      signalLabel: signal.signal_label,
      actionPath: signal.action_path,
      actionLabel: signal.action_label,
    })) ?? []

  const pointsEntries =
    pointsOverview?.points_entries.map((entry) => ({
      ...entry,
      occurredAt: entry.occurred_at,
      expiresAt: entry.expires_at,
      actionPath: entry.action_path,
      actionLabel: entry.action_label,
      statusMeta: getPointsEntryStatusMeta(entry.status),
      directionMeta: getPointsEntryDirectionMeta(entry.direction),
    })) ?? []
  const assetConnectedOverviewRows = useUserCenterAssetConnectedOverviewRowsFromInput({
    pointsOverview,
    projects,
    userAssetCount: assetFacade.userAssetCount,
    overviewMetrics,
    formatCurrencyLabel: formatCurrency,
    formatPointsValueLabel: formatAccountMetric,
    formatUpdatedAtLabel: formatDateTime,
    getSourceLabel: getPointsRuleSourceLabel,
    t,
  })
  const taskBillingOverview = pointsOverview?.task_billing ?? null
  const taskBillingItems =
    pointsOverview?.task_billing.items.map((item) => ({
      ...item,
      occurredAt: item.occurred_at,
      actionPath: item.action_path,
      actionLabel: item.action_label,
      pricingStatusMeta: getTaskBillingPricingStatusMeta(item.pricing_status),
    })) ?? []
  const activePointsEntryCount = pointsEntries.filter((entry) => entry.status === 'active').length
  const frozenPointsEntryCount = pointsEntries.filter((entry) => entry.status === 'frozen').length
  const expiredPointsEntryCount = pointsEntries.filter((entry) => entry.status === 'expired').length
  const overviewTabMetrics = useUserCenterOverviewTabMetrics({
    pointsOverview,
    pendingLedgerSignalCount: pendingLedgerSignals.length,
    getPricingBasisLabel,
    formatPercentRate,
    formatUpdatedAtLabel: formatDateTime,
    t,
  })
  const {
    connectedLedgerSourceCount,
    pendingLedgerSourceCount,
    pointsAccountBalance,
    pointsAccountFrozen,
    pointsAccountExpiringSoon,
    pointsAccountStatusMeta,
    pricingPolicyPresentation,
  } = overviewTabMetrics

  const handleRestoreChapter = async (chapterId: number) => {
    setRestoringKey(`chapter-${chapterId}`)
    try {
      await apiClient.restoreChapter(chapterId)
      setFeedback({ type: 'success', text: t('userCenter.feedback.chapterRestored') })
      await loadUserCenterData(true)
    } catch (restoreError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(restoreError, t('userCenter.feedback.chapterRestoreFailed')),
      })
    } finally {
      setRestoringKey(null)
    }
  }

  const handleRestoreAudiobookProject = async (audiobookProjectId: number) => {
    setRestoringKey(`audiobook-${audiobookProjectId}`)
    try {
      await apiClient.restoreAudiobookProject(audiobookProjectId)
      setFeedback({ type: 'success', text: t('userCenter.feedback.audiobookRestored') })
      await loadUserCenterData(true)
    } catch (restoreError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(restoreError, t('userCenter.feedback.audiobookRestoreFailed')),
      })
    } finally {
      setRestoringKey(null)
    }
  }

  const handleCreateVideoApplication = async () => {
    if (!videoApplicationName.trim()) return
    setVideoApplicationBusy(true)
    try {
      const response = await apiClient.createVideoApiApplication({
        name: videoApplicationName.trim(), plan_code: videoApplicationPlan,
      })
      setVideoApplications((items) => [response.data, ...items])
      setVideoApiKey(response.data.api_key || null)
      setVideoApplicationName('')
      setFeedback({ type: 'success', text: '申请已提交，等待超级管理员审核。请保存完整 API Key，批准后可调用。' })
    } catch (createError) {
      setFeedback({ type: 'error', text: await extractApiErrorMessage(createError, '创建 API 应用失败') })
    } finally {
      setVideoApplicationBusy(false)
    }
  }

  const handleRotateVideoApplicationKey = async (applicationId: number) => {
    setVideoApplicationBusy(true)
    try {
      const response = await apiClient.rotateVideoApiApplicationKey(applicationId)
      setVideoApplications((items) => items.map((item) => item.id === applicationId ? response.data : item))
      setVideoApiKey(response.data.api_key || null)
      setFeedback({ type: 'success', text: 'API Key 已轮换，旧 Key 已失效。请立即保存新 Key。' })
    } catch (rotateError) {
      setFeedback({ type: 'error', text: await extractApiErrorMessage(rotateError, '轮换 API Key 失败') })
    } finally {
      setVideoApplicationBusy(false)
    }
  }

  const handleRevokeVideoApplication = async (applicationId: number) => {
    setVideoApplicationBusy(true)
    try {
      const response = await apiClient.revokeVideoApiApplication(applicationId)
      setVideoApplications((items) => items.map((item) => item.id === applicationId ? response.data : item))
    } catch (revokeError) {
      setFeedback({ type: 'error', text: await extractApiErrorMessage(revokeError, '吊销 API 应用失败') })
    } finally {
      setVideoApplicationBusy(false)
    }
  }

  const videoApiContent = (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h5" sx={{ fontWeight: 800 }}>视频 API 应用</Typography>
        <Typography color="text.secondary" sx={{ mt: 0.5 }}>
          为自己的平台申请独立 API Key；审核批准后启用。配额按应用隔离，完整 Key 只在创建或轮换后显示一次。
        </Typography>
      </Box>
      <Card variant="outlined">
        <CardContent>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} alignItems={{ md: 'center' }}>
            <TextField label="应用名称" value={videoApplicationName} onChange={(event) => setVideoApplicationName(event.target.value)} fullWidth />
            <TextField select label="套餐" value={videoApplicationPlan} onChange={(event) => setVideoApplicationPlan(event.target.value)} SelectProps={{ native: true }} sx={{ minWidth: 180 }}>
              <option value="standard">标准：1 请求/秒，5 个活动任务</option>
              <option value="professional">专业：5 请求/秒，20 个活动任务</option>
              <option value="enterprise">企业：20 请求/秒，100 个活动任务</option>
            </TextField>
            <Button variant="contained" onClick={() => void handleCreateVideoApplication()} disabled={videoApplicationBusy || !videoApplicationName.trim()}>提交申请</Button>
          </Stack>
        </CardContent>
      </Card>
      {videoApiKey ? (
        <Alert severity="warning" action={<Button size="small" startIcon={<ContentCopyIcon />} onClick={() => void navigator.clipboard?.writeText(videoApiKey)}>复制</Button>}>
          <Typography variant="body2">请立即保存完整 API Key：</Typography>
          <Typography component="code" sx={{ wordBreak: 'break-all' }}>{videoApiKey}</Typography>
        </Alert>
      ) : null}
      {videoApplications.map((item) => (
        <Card key={item.id} variant="outlined">
          <CardContent>
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between" alignItems={{ md: 'center' }}>
              <Box>
                <Typography variant="h6">{item.name}</Typography>
                <Typography variant="body2" color="text.secondary">Key 前缀：{item.api_key_prefix} · {item.plan_code} · {item.rate_limit_per_second} 请求/秒 · {item.max_active_jobs} 个活动任务 · 累计任务额度 {item.lifetime_task_limit}</Typography>
                <Chip size="small" sx={{ mt: 1 }} label={item.status} color={item.status === 'active' ? 'success' : item.status === 'suspended' ? 'warning' : 'default'} />
              </Box>
              <Stack direction="row" spacing={1}>
                <Button size="small" variant="outlined" onClick={() => void handleRotateVideoApplicationKey(item.id)} disabled={videoApplicationBusy || item.status === 'revoked'}>轮换 Key</Button>
                <Button size="small" color="error" variant="outlined" onClick={() => void handleRevokeVideoApplication(item.id)} disabled={videoApplicationBusy || item.status === 'revoked'}>吊销</Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ))}
      {videoApplications.length === 0 ? <Alert severity="info">还没有 API 应用。提交申请并经超级管理员批准后，即可接入视频网关。</Alert> : null}
    </Stack>
  )

  // P2-4.6：改密/设密共用同一前端校验（与后端 password_policy 同规则）；密码强度错误文案走 i18n passwordPolicy.message，其余文案归 P3
  const validateNewPassword = (): boolean => {
    if (passwordData.new_password !== passwordData.confirm_password) {
      setFeedback({ type: 'error', text: t('userCenter.feedback.passwordMismatch') })
      return false
    }
    const policyError = checkPasswordStrength(passwordData.new_password)
    if (policyError) {
      setFeedback({ type: 'error', text: t('passwordPolicy.message') })
      return false
    }
    return true
  }

  const handleChangePassword = async () => {
    if (!validateNewPassword()) return

    setPasswordSubmitting(true)
    try {
      const response = await apiClient.changePassword({
        old_password: passwordData.old_password,
        new_password: passwordData.new_password,
      })
      setFeedback({ type: 'success', text: response.data?.message || t('userCenter.feedback.passwordUpdated') })
      setPasswordData({ old_password: '', new_password: '', confirm_password: '' })
    } catch (passwordError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(passwordError, t('userCenter.feedback.passwordUpdateFailed')),
      })
    } finally {
      setPasswordSubmitting(false)
    }
  }

  // P2-4.2：OAuth 用户首次设置本地密码（不要求旧密码）
  const handleSetPassword = async () => {
    if (!validateNewPassword()) return

    setPasswordSubmitting(true)
    try {
      const response = await apiClient.setPassword(passwordData.new_password)
      setPasswordData({ old_password: '', new_password: '', confirm_password: '' })
      // 评审 #11：设密已递增 token_version，当前会话（access + refresh）立即失效；
      // 不再调 loadUserCenterData（必然 401 触发自动登出），改为清凭证并引导重新登录
      setFeedback({ type: 'success', text: response.data?.message || t('userCenter.feedback.passwordSet') })
      dispatch(performLogout())
      navigate('/login')
    } catch (passwordError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(passwordError, t('userCenter.feedback.passwordSetFailed')),
      })
    } finally {
      setPasswordSubmitting(false)
    }
  }

  // P2-4.2：发起第三方绑定（intent=bind，走现有 OAuth + 登录态 bind/confirm）
  const handleStartOAuthBind = async (provider: OAuthProvider) => {
    if (bindingProvider) return
    // 绑定需登录态，而会话 Cookie 按主机隔离，无法跨域名跳转后继续，域名不匹配时直接提示
    const requiredOrigin = getRequiredOAuthOrigin(provider)
    if (requiredOrigin && window.location.origin !== requiredOrigin) {
      const host = requiredOrigin.replace('https://', '')
      setFeedback({ type: 'error', text: t('userCenter.feedback.domainNotSupported', { host }) })
      return
    }
    setBindingProvider(provider)
    try {
      clearOAuthContext()
      const state = generateOAuthState()
      const redirectUri = `${window.location.origin}/login/callback`
      const response =
        provider === 'alipay'
          ? await apiClient.getAlipayAuthUrl({ redirect_uri: redirectUri, state, intent: 'bind' })
          : await apiClient.getWechatAuthUrl({ redirect_uri: redirectUri, state, intent: 'bind' })
      const authUrl = response.data?.auth_url
      const serverState = response.data?.state
      if (!authUrl || !serverState) {
        setFeedback({ type: 'error', text: t('userCenter.feedback.oauthConfigInvalid') })
        return
      }
      storeOAuthContext(provider, serverState)
      window.location.href = authUrl
    } catch (bindError) {
      clearOAuthContext()
      setFeedback({ type: 'error', text: await extractApiErrorMessage(bindError, t('userCenter.feedback.bindFailed')) })
    } finally {
      setBindingProvider(null)
    }
  }

  // P2-4.2：解绑第三方登录
  const handleUnbindProvider = async (provider: OAuthProvider) => {
    if (unbindingProvider) return
    setUnbindingProvider(provider)
    try {
      const response = await apiClient.unbindProvider(provider)
      setFeedback({ type: 'success', text: response.data?.message || t('userCenter.feedback.unbindSuccess') })
      await loadUserCenterData(true)
    } catch (unbindError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(unbindError, t('userCenter.feedback.unbindFailed')),
      })
    } finally {
      setUnbindingProvider(null)
    }
  }

  const handleLogout = () => {
    dispatch(performLogout())
    navigate('/login')
  }

  // 短信码重发倒计时（与后端重发间隔对齐）
  useEffect(() => {
    if (phoneResendSeconds <= 0) return
    const timer = window.setTimeout(() => setPhoneResendSeconds((prev) => prev - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [phoneResendSeconds])

  const resetPhoneBindFlow = () => {
    setPhoneOccupied(false)
    setPhoneCode('')
    setPhoneCodeConsented(false)
    setPhoneResendSeconds(0)
  }

  // 提交前先查占用：未占用直接绑定（不发短信）；已占用进入短信验码流程，勾选同意后才可提交（换号场景同此逻辑）
  const handleBindPhone = async () => {
    const phone = phoneValue.trim()
    if (!PHONE_PATTERN.test(phone)) {
      setFeedback({ type: 'error', text: t('userCenter.feedback.phoneInvalid') })
      return
    }
    setPhoneSubmitting(true)
    try {
      if (!phoneOccupied) {
        const statusRes = await apiClient.phoneCheckStatus(phone)
        const occupied = statusRes.data?.occupied ?? false
        setPhoneOccupied(occupied)
        if (occupied) {
          setFeedback({
            type: 'error',
            text: t('userCenter.feedback.phoneOccupiedClaim'),
          })
          return
        }
      }

      if (phoneOccupied) {
        if (phoneCode.length !== 6) {
          setFeedback({ type: 'error', text: t('userCenter.feedback.phoneCodeInvalid') })
          return
        }
        if (!phoneCodeConsented) {
          setFeedback({ type: 'error', text: t('userCenter.feedback.phoneConsentRequired') })
          return
        }
      }

      const response = await apiClient.phoneBindConfirm({
        phone,
        ...(phoneOccupied ? { code: phoneCode, consent: { phone_collection: CONSENT_VERSIONS.phone_collection } } : {}),
      })
      setFeedback({ type: 'success', text: response.data?.message || t('userCenter.feedback.phoneBound') })
      setPhoneValue('')
      resetPhoneBindFlow()
      // 同步最新用户信息（含手机号与同意记录）
      await dispatch(getCurrentUser())
    } catch (bindError) {
      setFeedback({ type: 'error', text: await extractApiErrorMessage(bindError, t('userCenter.feedback.phoneBindFailed')) })
    } finally {
      setPhoneSubmitting(false)
    }
  }

  const handleSendBindPhoneCode = async () => {
    const phone = phoneValue.trim()
    if (!phoneOccupied || phoneCodeSending || phoneResendSeconds > 0) return
    setPhoneCodeSending(true)
    try {
      const response = await apiClient.phoneSendCode({ phone, purpose: 'bind' })
      setPhoneResendSeconds(response.data?.resend_in || 60)
      setFeedback({ type: 'success', text: response.data?.message || t('userCenter.feedback.phoneCodeSent') })
    } catch (sendError) {
      setFeedback({ type: 'error', text: await extractApiErrorMessage(sendError, t('userCenter.feedback.phoneCodeSendFailed')) })
    } finally {
      setPhoneCodeSending(false)
    }
  }

  const renderProjectGrid = (items: ProjectAggregate[]) => {
    if (!items.length) {
      return <Alert severity="info">{t('userCenter.projects.empty')}</Alert>
    }

    return (
      <Grid container spacing={2}>
        {items.map((project) => (
          <Grid item xs={12} md={6} key={`project-${project.id}`}>
            <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
              <CardContent>
                <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={2}>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="h6" sx={{ fontWeight: 700 }}>
                      {project.title?.trim() || t('userCenter.common.projectFallback', { id: project.id })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                      {project.description?.trim() || t('userCenter.projects.noDescription')}
                    </Typography>
                  </Box>
                  <Chip size="small" label={project.genre || t('userCenter.projects.unclassified')} />
                </Stack>

                <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
                  <Chip icon={<AutoStoriesIcon />} size="small" label={t('userCenter.projects.novelProject')} />
                  <Chip icon={<HeadphonesIcon />} size="small" label={t('userCenter.projects.audiobookCount', { count: project.audiobookCount })} />
                  <Chip icon={<MovieIcon />} size="small" label={t('userCenter.projects.dramaRunCount', { count: project.dramaRunCount })} />
                </Stack>

                <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', rowGap: 1 }}>
                  <Button size="small" variant="contained" onClick={() => navigate('/dashboard')}>
                    {t('userCenter.projects.openNovelWorkspace')}
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={() =>
                      navigate(project.audiobookCount > 0 ? `/audiobook/${project.id}` : '/audiobook-dashboard')
                    }
                  >
                    {t('userCenter.projects.viewAudiobooks')}
                  </Button>
                  {hasAdminRole ? (
                    <Button size="small" variant="outlined" onClick={() => navigate(`/drama/${project.id}`)}>
                      {t('userCenter.projects.viewDrama')}
                    </Button>
                  ) : null}
                </Stack>

                <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1.5 }}>
                  {t('userCenter.common.updatedAt', { time: formatDateTime(project.updated_at || project.created_at) })}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    )
  }

  const overviewContent = (
    <Stack spacing={3}>
      <Grid container spacing={2}>
        <Grid item xs={12} md={3}>
          <MetricCard
            title={t('userCenter.overview.novelProjects')}
            value={overviewMetrics.novelProjects}
            helper={t('userCenter.overview.novelProjectsHelper')}
            color="#2563eb" // sg-color-fixed: 指标卡身份色（颜色即数据）
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <MetricCard
            title={t('userCenter.overview.audiobookProjects')}
            value={overviewMetrics.audiobookProjects}
            helper={t('userCenter.overview.audiobookProjectsHelper')}
            color="#7c3aed" // sg-color-fixed: 指标卡身份色（颜色即数据）
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <MetricCard
            title={t('userCenter.overview.dramaProjects')}
            value={overviewMetrics.dramaProjects}
            helper={t('userCenter.overview.dramaProjectsHelper')}
            color="#f97316" // sg-color-fixed: 指标卡身份色（颜色即数据）
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <MetricCard
            title={t('userCenter.overview.pendingTrash')}
            value={overviewMetrics.deletedTotal}
            helper={t('userCenter.overview.pendingTrashHelper')}
            color="#0f766e" // sg-color-fixed: 指标卡身份色（颜色即数据）
          />
        </Grid>
      </Grid>
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.overview.currentState')}
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', rowGap: 1 }}>
                <Chip label={t('userCenter.overview.runningTasks', { count: overviewMetrics.runningTasks })} color="info" />
                <Chip label={t('userCenter.overview.failedTasks', { count: overviewMetrics.failedTasks })} color={overviewMetrics.failedTasks > 0 ? 'error' : 'default'} />
                <Chip label={t('userCenter.overview.pointsStatus', { status: t(pointsAccountStatusMeta.label) })} color={pointsAccountStatusMeta.color} variant="outlined" />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                {t('userCenter.overview.divisionNote')}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.overview.positioningTitle')}
              </Typography>
              <Stack spacing={1.25} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  {t('userCenter.overview.positioningIdentity')}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {t('userCenter.overview.positioningSummary')}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {t('userCenter.overview.positioningGovernance')}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Alert severity="info">
        {t('userCenter.overview.assetStrategyNote')}
      </Alert>

      <Box>
        <Typography variant="h6" sx={{ fontWeight: 700, mb: 2 }}>
          {t('userCenter.overview.recentProjects')}
        </Typography>
        {renderProjectGrid(recentProjects)}
      </Box>
    </Stack>
  )

  const creationContent = (
    <Stack spacing={3}>
      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <AutoStoriesIcon sx={{ color: '#2563eb', fontSize: 28 }} /> // sg-color-fixed: 入口卡身份色（颜色即数据）
              <Typography variant="h6" sx={{ mt: 1, fontWeight: 700 }}>
                {t('userCenter.creation.novelTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
                {t('userCenter.creation.novelDesc')}
              </Typography>
              <Button sx={{ mt: 2 }} variant="contained" onClick={() => navigate('/dashboard')}>
                {t('userCenter.creation.enterNovel')}
              </Button>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <HeadphonesIcon sx={{ color: '#7c3aed', fontSize: 28 }} /> // sg-color-fixed: 入口卡身份色（颜色即数据）
              <Typography variant="h6" sx={{ mt: 1, fontWeight: 700 }}>
                {t('userCenter.creation.audiobookTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
                {t('userCenter.creation.audiobookDesc')}
              </Typography>
              <Button sx={{ mt: 2 }} variant="contained" onClick={() => navigate('/audiobook-dashboard')}>
                {t('userCenter.creation.enterAudiobook')}
              </Button>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <MovieIcon sx={{ color: '#f97316', fontSize: 28 }} /> // sg-color-fixed: 入口卡身份色（颜色即数据）
              <Typography variant="h6" sx={{ mt: 1, fontWeight: 700 }}>
                {t('userCenter.creation.dramaTitle')}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
                {t('userCenter.creation.dramaDesc')}
              </Typography>
              <Button sx={{ mt: 2 }} variant="contained" onClick={() => navigate('/drama')}>
                {t('userCenter.creation.enterDrama')}
              </Button>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Box>
        <Typography variant="h6" sx={{ fontWeight: 700, mb: 2 }}>
          {t('userCenter.creation.myProjects')}
        </Typography>
        {renderProjectGrid(projectAggregates)}
      </Box>
    </Stack>
  )

  const assetsContent = <UserAssetWorkspaceContent {...assetFacade.workspaceContentProps} />

  const pointsContent = (
    <Stack spacing={3}>
      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }}>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              {t('userCenter.points.accountOverview')}
            </Typography>
            <Chip size="small" color={pointsAccountStatusMeta.color} label={pointsAccountStatusMeta.label} />
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
            {pointsAccountStatusMeta.description}
          </Typography>

          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard title={t('userCenter.points.balance')} value={formatAccountMetric(pointsAccountBalance)} helper={t('userCenter.points.balanceHelper')} color="#2563eb" /> // sg-color-fixed: 指标卡身份色（颜色即数据）
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard title={t('userCenter.points.frozen')} value={formatAccountMetric(pointsAccountFrozen)} helper={t('userCenter.points.frozenHelper')} color="#f97316" /> // sg-color-fixed: 指标卡身份色（颜色即数据）
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard title={t('userCenter.points.expiringSoon')} value={formatAccountMetric(pointsAccountExpiringSoon)} helper={t('userCenter.points.expiringSoonHelper')} color="#dc2626" /> // sg-color-fixed: 指标卡身份色（颜色即数据）
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard title={t('userCenter.points.ledgerSource')} value={`${connectedLedgerSourceCount} / ${pendingLedgerSourceCount}`} helper={t('userCenter.points.ledgerSourceHelper')} color="#0f766e" /> // sg-color-fixed: 指标卡身份色（颜色即数据）
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {assetConnectedOverviewRows.strategyRowSlot}

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.points.currentPricing')}
              </Typography>
              {pricingPolicyPresentation ? (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                    <Chip
                      size="small"
                      color={pricingPolicyPresentation.sourceColor}
                      label={pricingPolicyPresentation.sourceLabel}
                    />
                    <Chip size="small" variant="outlined" label={pricingPolicyPresentation.userPriceBasisLabel} />
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    {pricingPolicyPresentation.description}
                  </Typography>
                  <Box sx={{ display: 'grid', gap: 1.25, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                    {pricingPolicyPresentation.summaryItems.map((item) => (
                      <Box
                        key={item.label}
                        sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}
                      >
                        <Typography variant="caption" color="text.secondary">
                          {item.label}
                        </Typography>
                        <Typography sx={{ mt: 0.5, fontWeight: 600 }}>{item.value}</Typography>
                      </Box>
                    ))}
                  </Box>
                  <Typography variant="caption" color="text.secondary">
                    {pricingPolicyPresentation.updatedAtLabel}
                  </Typography>
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                  {t('userCenter.points.noPricingSnapshot')}
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                justifyContent="space-between"
                spacing={1.5}
                alignItems={{ xs: 'flex-start', sm: 'center' }}
              >
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  {t('userCenter.points.taskBillingOverview')}
                </Typography>
                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                  <Chip size="small" color="success" variant="outlined" label={t('userCenter.billing.settledCount', { count: taskBillingOverview?.actual_task_count ?? 0 })} />
                  <Chip size="small" color="warning" variant="outlined" label={t('userCenter.billing.estimatedCount', { count: taskBillingOverview?.estimated_task_count ?? 0 })} />
                  <Chip size="small" variant="outlined" label={t('userCenter.billing.pendingCount', { count: taskBillingOverview?.pending_task_count ?? 0 })} />
                </Stack>
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
                {t('userCenter.points.taskBillingOverviewHelper')}
              </Typography>
              <Grid container spacing={2} sx={{ mt: 0.5 }}>
                <Grid item xs={12} sm={6}>
                  <MetricCard
                    title={t('userCenter.billing.settledPoints')}
                    value={formatAccountMetric(taskBillingOverview?.actual_spend_points ?? 0)}
                    helper={t('userCenter.billing.actualYuan', { amount: formatCurrency(taskBillingOverview?.actual_spend_yuan ?? 0) })}
                    color="#16a34a" // sg-color-fixed: 指标卡身份色（颜色即数据）
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <MetricCard
                    title={t('userCenter.billing.runningEstimate')}
                    value={formatAccountMetric(taskBillingOverview?.estimated_running_spend_points ?? 0)}
                    helper={t('userCenter.billing.estimatedYuan', { amount: formatCurrency(taskBillingOverview?.estimated_running_spend_yuan ?? 0) })}
                    color="#d97706" // sg-color-fixed: 指标卡身份色（颜色即数据）
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <MetricCard
                    title={t('userCenter.billing.suggestedFrozen')}
                    value={formatAccountMetric(taskBillingOverview?.suggested_frozen_points ?? 0)}
                    helper={t('userCenter.billing.frozenBasisHelper')}
                    color="#ea580c" // sg-color-fixed: 指标卡身份色（颜色即数据）
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <MetricCard
                    title={t('userCenter.billing.taskItems')}
                    value={taskBillingItems.length}
                    helper={t('userCenter.billing.taskItemsHelper')}
                    color="#0f766e" // sg-color-fixed: 指标卡身份色（颜色即数据）
                  />
                </Grid>
              </Grid>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {t('userCenter.points.taskBillingDetail')}
          </Typography>
          {taskBillingItems.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('userCenter.points.taskBillingEmpty')}
            </Alert>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {taskBillingItems.map((item) => (
                <Box key={item.key} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                        <Chip size="small" variant="outlined" label={item.module_label} />
                        <Chip size="small" color={item.pricingStatusMeta.color} label={t(item.pricingStatusMeta.label)} />
                        <Chip size="small" variant="outlined" label={item.task_status === 'completed' ? t('userCenter.billing.taskCompleted') : t('userCenter.billing.taskRunning')} />
                      </Stack>
                      <Typography sx={{ mt: 1, fontWeight: 600 }}>{item.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {item.summary}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                        {t('userCenter.records.updatedAt', { time: formatDateTime(item.occurredAt) })}
                      </Typography>
                    </Box>
                    <Stack spacing={1} alignItems={{ xs: 'flex-start', sm: 'flex-end' }}>
                      {item.actual_points != null ? (
                        <Chip size="small" color="success" variant="outlined" label={t('userCenter.billing.actualPoints', { value: formatAccountMetric(item.actual_points) })} />
                      ) : null}
                      {item.estimated_points != null ? (
                        <Chip size="small" color="warning" variant="outlined" label={t('userCenter.billing.estimatedPoints', { value: formatAccountMetric(item.estimated_points) })} />
                      ) : null}
                      {item.suggested_frozen_points != null ? (
                        <Chip size="small" color="warning" label={t('userCenter.billing.suggestedFrozenPoints', { value: formatAccountMetric(item.suggested_frozen_points) })} />
                      ) : null}
                      {item.actionPath ? (
                        <Button size="small" variant="outlined" onClick={() => navigate(item.actionPath || USER_CENTER_POINTS_PATH)}>
                          {item.actionLabel || t('userCenter.common.viewSource')}
                        </Button>
                      ) : null}
                    </Stack>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.points.connectedBenefits')}
              </Typography>
              {connectedBenefitItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  {t('userCenter.points.connectedBenefitsEmpty')}
                </Typography>
              ) : (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {connectedBenefitItems.map((item) => (
                    <Box key={item.key} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2.5 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2}>
                        <Typography sx={{ fontWeight: 600 }}>{item.label}</Typography>
                        <Chip size="small" color="success" label={t('userCenter.points.connected')} />
                      </Stack>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {item.summary}
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.points.plannedBenefits')}
              </Typography>
              {plannedBenefitItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  {t('userCenter.points.plannedBenefitsEmpty')}
                </Typography>
              ) : (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {plannedBenefitItems.map((item) => (
                    <Box key={item.key} sx={{ p: 2, border: '1px dashed', borderColor: 'divider', borderRadius: 2.5 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2}>
                        <Typography sx={{ fontWeight: 600 }}>{item.label}</Typography>
                        <Chip size="small" color="warning" variant="outlined" label={t('userCenter.points.planned')} />
                      </Stack>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {item.summary}
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {t('userCenter.points.connectedLedger')}
          </Typography>
          {audiobookBillingEntries.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('userCenter.points.connectedLedgerEmpty')}
            </Alert>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {audiobookBillingEntries.map((entry) => (
                <Box key={entry.key} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                        <Chip size="small" color="warning" label={entry.moduleLabel} />
                        <Chip size="small" variant="outlined" label={entry.eventLabel} />
                        {entry.projectLabel ? <Chip size="small" variant="outlined" label={entry.projectLabel} /> : null}
                      </Stack>
                      <Typography sx={{ mt: 1, fontWeight: 600 }}>{entry.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {entry.summary}
                      </Typography>
                    </Box>
                    <Stack spacing={1} alignItems={{ xs: 'flex-start', sm: 'flex-end' }}>
                      <Chip color="warning" variant="outlined" label={formatCurrency(entry.amount)} />
                      {entry.actionPath ? (
                        <Button size="small" variant="outlined" onClick={() => navigate(entry.actionPath || USER_CENTER_POINTS_PATH)}>
                          {entry.actionLabel || t('userCenter.common.viewSource')}
                        </Button>
                      ) : null}
                    </Stack>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {t('userCenter.points.pendingLedger')}
          </Typography>
          {pendingLedgerSignals.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              {t('userCenter.points.pendingLedgerEmpty')}
            </Typography>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {pendingLedgerSignals.map((signal) => (
                <Box key={signal.key} sx={{ p: 2, border: '1px dashed', borderColor: 'divider', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                        <Chip size="small" variant="outlined" label={signal.moduleLabel} />
                        <Chip size="small" color="secondary" variant="outlined" label={signal.signalLabel} />
                      </Stack>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {signal.summary}
                      </Typography>
                    </Box>
                    {signal.actionPath ? (
                      <Button size="small" variant="outlined" onClick={() => navigate(signal.actionPath || USER_CENTER_POINTS_PATH)}>
                        {signal.actionLabel || t('userCenter.common.viewSource')}
                      </Button>
                    ) : null}
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>
    </Stack>
  )

  const enhancedPointsContent = (
    <Stack spacing={3}>
      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', sm: 'center' }}
          >
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              {t('userCenter.points.accountOverview')}
            </Typography>
            <Chip size="small" color={pointsAccountStatusMeta.color} label={pointsAccountStatusMeta.label} />
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
            {pointsAccountStatusMeta.description}
          </Typography>

          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard
                title={t('userCenter.points.balance')}
                value={formatAccountMetric(pointsAccountBalance)}
                helper={t('userCenter.points.balanceHelper')}
                color="#2563eb" // sg-color-fixed: 指标卡身份色（颜色即数据）
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard
                title={t('userCenter.points.frozen')}
                value={formatAccountMetric(pointsAccountFrozen)}
                helper={t('userCenter.points.frozenHelper')}
                color="#f97316" // sg-color-fixed: 指标卡身份色（颜色即数据）
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard
                title={t('userCenter.points.expiringSoon')}
                value={formatAccountMetric(pointsAccountExpiringSoon)}
                helper={t('userCenter.points.expiringSoonHelper')}
                color="#dc2626" // sg-color-fixed: 指标卡身份色（颜色即数据）
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard
                title={t('userCenter.points.ledgerSource')}
                value={`${connectedLedgerSourceCount} / ${pendingLedgerSourceCount}`}
                helper={t('userCenter.points.ledgerSourceHelper')}
                color="#0f766e" // sg-color-fixed: 指标卡身份色（颜色即数据）
              />
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      {assetConnectedOverviewRows.pointsRulesRowSlot}

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.points.connectedBenefits')}
              </Typography>
              {connectedBenefitItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  {t('userCenter.points.connectedBenefitsEmpty')}
                </Typography>
              ) : (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {connectedBenefitItems.map((item) => (
                    <Box key={item.key} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2.5 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2}>
                        <Typography sx={{ fontWeight: 600 }}>{item.label}</Typography>
                        <Chip size="small" color="success" label={t('userCenter.points.connected')} />
                      </Stack>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {item.summary}
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.points.plannedBenefits')}
              </Typography>
              {plannedBenefitItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  {t('userCenter.points.plannedBenefitsEmpty')}
                </Typography>
              ) : (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {plannedBenefitItems.map((item) => (
                    <Box key={item.key} sx={{ p: 2, border: '1px dashed', borderColor: 'divider', borderRadius: 2.5 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2}>
                        <Typography sx={{ fontWeight: 600 }}>{item.label}</Typography>
                        <Chip size="small" color="warning" variant="outlined" label={t('userCenter.points.planned')} />
                      </Stack>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {item.summary}
                      </Typography>
                    </Box>
                  ))}
                </Stack>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            justifyContent="space-between"
            spacing={1.5}
            alignItems={{ xs: 'flex-start', sm: 'center' }}
          >
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              {t('userCenter.points.entryDetail')}
            </Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
              <Chip size="small" color="success" variant="outlined" label={t('userCenter.points.activeChip', { count: activePointsEntryCount })} />
              <Chip size="small" color="warning" variant="outlined" label={t('userCenter.points.frozenChip', { count: frozenPointsEntryCount })} />
              <Chip size="small" variant="outlined" label={t('userCenter.points.expiredChip', { count: expiredPointsEntryCount })} />
            </Stack>
          </Stack>
          {pointsEntries.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('userCenter.points.entriesEmpty')}
            </Alert>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {pointsEntries.map((entry) => (
                <Box key={entry.key} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                        <Chip size="small" variant="outlined" label={entry.source_label} />
                        <Chip size="small" color={entry.directionMeta.color} label={t(entry.directionMeta.label)} />
                        <Chip
                          size="small"
                          color={entry.statusMeta.color}
                          variant={entry.status === 'active' ? 'filled' : 'outlined'}
                          label={t(entry.statusMeta.label)}
                        />
                      </Stack>
                      <Typography sx={{ mt: 1, fontWeight: 600 }}>{entry.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {entry.summary}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                        {t('userCenter.records.occurredAt', { time: formatDateTime(entry.occurredAt) })}
                      </Typography>
                      {entry.expiresAt ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          {t('userCenter.records.expiresAt', { time: formatDateTime(entry.expiresAt) })}
                        </Typography>
                      ) : null}
                    </Box>
                    <Stack spacing={1} alignItems={{ xs: 'flex-start', sm: 'flex-end' }}>
                      <Chip
                        color={entry.direction === 'expense' ? 'error' : entry.direction === 'hold' ? 'warning' : 'success'}
                        variant={entry.status === 'expired' ? 'outlined' : 'filled'}
                        label={formatPointsDelta(entry.amount, entry.direction)}
                      />
                      {entry.actionPath ? (
                        <Button size="small" variant="outlined" onClick={() => navigate(entry.actionPath || USER_CENTER_POINTS_PATH)}>
                          {entry.actionLabel || t('userCenter.common.viewSource')}
                        </Button>
                      ) : null}
                    </Stack>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {t('userCenter.points.connectedLedger')}
          </Typography>
          {audiobookBillingEntries.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('userCenter.points.connectedLedgerEmpty')}
            </Alert>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {audiobookBillingEntries.map((entry) => (
                <Box key={entry.key} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                        <Chip size="small" color="warning" label={entry.moduleLabel} />
                        <Chip size="small" variant="outlined" label={entry.eventLabel} />
                        {entry.projectLabel ? <Chip size="small" variant="outlined" label={entry.projectLabel} /> : null}
                      </Stack>
                      <Typography sx={{ mt: 1, fontWeight: 600 }}>{entry.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {entry.summary}
                      </Typography>
                    </Box>
                    <Stack spacing={1} alignItems={{ xs: 'flex-start', sm: 'flex-end' }}>
                      <Chip color="warning" variant="outlined" label={formatCurrency(entry.amount)} />
                      {entry.actionPath ? (
                        <Button size="small" variant="outlined" onClick={() => navigate(entry.actionPath || USER_CENTER_POINTS_PATH)}>
                          {entry.actionLabel || t('userCenter.common.viewSource')}
                        </Button>
                      ) : null}
                    </Stack>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {t('userCenter.points.pendingLedger')}
          </Typography>
          {pendingLedgerSignals.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              {t('userCenter.points.pendingLedgerEmpty')}
            </Typography>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {pendingLedgerSignals.map((signal) => (
                <Box key={signal.key} sx={{ p: 2, border: '1px dashed', borderColor: 'divider', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                        <Chip size="small" variant="outlined" label={signal.moduleLabel} />
                        <Chip size="small" color="secondary" variant="outlined" label={signal.signalLabel} />
                      </Stack>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                        {signal.summary}
                      </Typography>
                    </Box>
                    {signal.actionPath ? (
                      <Button size="small" variant="outlined" onClick={() => navigate(signal.actionPath || USER_CENTER_POINTS_PATH)}>
                        {signal.actionLabel || t('userCenter.common.viewSource')}
                      </Button>
                    ) : null}
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>
    </Stack>
  )

  const recordsContent = (
    <Stack spacing={3}>
      <Alert severity="warning">
        {t('userCenter.records.dramaCleanupNote')}
      </Alert>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {t('userCenter.records.deletedChapters')}
          </Typography>
          {deletedChapters.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
              {t('userCenter.records.deletedChaptersEmpty')}
            </Typography>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {deletedChapters.map((chapter) => (
                <Box key={chapter.id} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography sx={{ fontWeight: 600 }}>{chapter.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {t('userCenter.records.chapterLine', {
                          project: chapter.project_name || t('userCenter.records.projectFallback', { id: chapter.project_id }),
                          words: chapter.word_count || 0,
                          time: formatDateTime(chapter.deleted_at),
                        })}
                      </Typography>
                    </Box>
                    <Button variant="contained" onClick={() => void handleRestoreChapter(chapter.id)} disabled={restoringKey === `chapter-${chapter.id}`}>
                      {restoringKey === `chapter-${chapter.id}` ? t('userCenter.records.restoring') : t('userCenter.records.restoreChapter')}
                    </Button>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {t('userCenter.records.deletedAudiobooks')}
          </Typography>
          {deletedAudiobookProjects.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
              {t('userCenter.records.deletedAudiobooksEmpty')}
            </Typography>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {deletedAudiobookProjects.map((item) => (
                <Box key={item.id} sx={{ p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography sx={{ fontWeight: 600 }}>{item.project_title || t('userCenter.records.audiobookProjectFallback', { id: item.id })}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {t('userCenter.records.audiobookLine', {
                          time: formatDateTime(item.deleted_at),
                          count: item.affected_chapters ?? 0,
                          status: item.status || t('userCenter.records.unknown'),
                        })}
                      </Typography>
                    </Box>
                    <Button variant="contained" onClick={() => void handleRestoreAudiobookProject(item.id)} disabled={restoringKey === `audiobook-${item.id}`}>
                      {restoringKey === `audiobook-${item.id}` ? t('userCenter.records.restoring') : t('userCenter.records.restoreAudiobook')}
                    </Button>
                  </Stack>
                </Box>
              ))}
            </Stack>
          )}
        </CardContent>
      </Card>
    </Stack>
  )

  const securityContent = (
    <Stack spacing={3}>
      <Grid container spacing={2}>
        <Grid item xs={12} md={5}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <SecurityOutlinedIcon color="primary" />
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  {t('userCenter.security.accountInfo')}
                </Typography>
              </Stack>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    {t('userCenter.security.username')}
                  </Typography>
                  <Typography>{user?.username || t('userCenter.security.none')}</Typography>
                </Box>
                <Divider />
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    {t('userCenter.security.email')}
                  </Typography>
                  <Stack direction="row" spacing={1} alignItems="center">
                    <Typography>{user?.email || t('userCenter.security.none')}</Typography>
                    {/* P1-3.8：邮箱验证状态——注册即验证；OAuth 用户可不绑定邮箱 */}
                    {user?.email ? (
                      <Chip
                        size="small"
                        label={user.email_verified ? t('userCenter.security.verified') : t('userCenter.security.unverified')}
                        color={user.email_verified ? 'success' : 'warning'}
                      />
                    ) : null}
                  </Stack>
                  {user?.email && !user.email_verified ? (
                    <Typography variant="caption" color="warning.main" sx={{ mt: 0.5, display: 'block' }}>
                      {t('userCenter.security.unverifiedHint')}
                    </Typography>
                  ) : null}
                </Box>
                <Divider />
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    {t('userCenter.security.displayName')}
                  </Typography>
                  <Typography>{user?.full_name || t('userCenter.security.none')}</Typography>
                </Box>
                <Divider />
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    {t('userCenter.security.role')}
                  </Typography>
                  <Typography>{roleNames.join(' / ') || t('userCenter.security.noRole')}</Typography>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={7}>
          <Card variant="outlined" sx={{ borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t(user?.has_password ? 'userCenter.security.changePassword' : 'userCenter.security.setPassword')}
              </Typography>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                {user?.has_password ? (
                  <TextField
                    fullWidth
                    label={t('userCenter.security.currentPassword')}
                    type="password"
                    value={passwordData.old_password}
                    onChange={(event) => setPasswordData((prev) => ({ ...prev, old_password: event.target.value }))}
                  />
                ) : null}
                <TextField
                  fullWidth
                  label={t('userCenter.security.newPassword')}
                  type="password"
                  value={passwordData.new_password}
                  onChange={(event) => setPasswordData((prev) => ({ ...prev, new_password: event.target.value }))}
                />
                <TextField
                  fullWidth
                  label={t('userCenter.security.confirmPassword')}
                  type="password"
                  value={passwordData.confirm_password}
                  onChange={(event) => setPasswordData((prev) => ({ ...prev, confirm_password: event.target.value }))}
                />
                <Typography variant="caption" color="text.secondary">
                  {t('passwordPolicy.message')}
                </Typography>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                  <Button
                    variant="contained"
                    startIcon={passwordSubmitting ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
                    onClick={() => void (user?.has_password ? handleChangePassword() : handleSetPassword())}
                    disabled={passwordSubmitting}
                  >
                    {passwordSubmitting ? t('userCenter.security.submitting') : user?.has_password ? t('userCenter.security.updatePassword') : t('userCenter.security.setPassword')}
                  </Button>
                  <Button variant="outlined" onClick={() => navigate('/home')}>
                    {t('userCenter.security.backToHome')}
                  </Button>
                </Stack>
              </Stack>
            </CardContent>
          </Card>

          {/* P2-4.2：第三方登录绑定/解绑 */}
          <Card variant="outlined" sx={{ mt: 2, borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.security.oauthBinding')}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                {t('userCenter.security.oauthBindingHelper')}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                {t('userCenter.security.oauthBindingHint')}
              </Typography>
              <Stack spacing={1} sx={{ mt: 2 }}>
                {(
                  [
                    { key: 'alipay' as OAuthProvider, label: 'userCenter.security.alipay', bound: user?.alipay_bound },
                    { key: 'wechat' as OAuthProvider, label: 'userCenter.security.wechat', bound: user?.wechat_bound },
                  ] as Array<{ key: OAuthProvider; label: string; bound?: boolean }>
                ).map((entry) => (
                  <Stack key={entry.key} direction="row" alignItems="center" justifyContent="space-between">
                    <Stack direction="row" spacing={1} alignItems="center">
                      <Typography>{t(entry.label)}</Typography>
                      <Chip
                        size="small"
                        label={entry.bound ? t('userCenter.security.bound') : t('userCenter.security.unbound')}
                        color={entry.bound ? 'success' : 'default'}
                      />
                    </Stack>
                    {entry.bound ? (
                      <Button
                        size="small"
                        variant="outlined"
                        color="error"
                        disabled={unbindingProvider === entry.key}
                        onClick={() => void handleUnbindProvider(entry.key)}
                      >
                        {unbindingProvider === entry.key ? t('userCenter.security.processing') : t('userCenter.security.unbind')}
                      </Button>
                    ) : (
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={bindingProvider === entry.key}
                        onClick={() => void handleStartOAuthBind(entry.key)}
                      >
                        {bindingProvider === entry.key ? t('userCenter.security.authorizing') : t('userCenter.security.bind')}
                      </Button>
                    )}
                  </Stack>
                ))}
              </Stack>
            </CardContent>
          </Card>

          {/* 手机号绑定：未占用直绑；已占用走短信验码抢占（原账号手机号清空并收到邮件通知） */}
          <Card variant="outlined" sx={{ mt: 2, borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                {t('userCenter.security.phoneBinding')}
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                {user?.phone
                  ? t('userCenter.security.currentPhone', { phone: `${user.phone.slice(0, 3)}****${user.phone.slice(-4)}` })
                  : t('userCenter.security.phoneUnboundHelper')}
              </Typography>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                <TextField
                  fullWidth
                  label={t('userCenter.security.phoneLabel')}
                  type="tel"
                  value={phoneValue}
                  onChange={(event) => {
                    setPhoneValue(event.target.value)
                    if (phoneOccupied) {
                      resetPhoneBindFlow()
                    }
                  }}
                  placeholder={t('userCenter.security.phonePlaceholder')}
                />
                {phoneOccupied && (
                  <FormControl component="fieldset">
                    <Alert severity="info" sx={{ mb: 1 }}>
                      {t('userCenter.security.phoneOccupiedAlert')}
                    </Alert>
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                      <TextField
                        fullWidth
                        label={t('userCenter.security.smsCode')}
                        value={phoneCode}
                        onChange={(event) => setPhoneCode(event.target.value.replace(/\D/g, '').slice(0, 6))}
                        inputProps={{ inputMode: 'numeric', maxLength: 6 }}
                        helperText={t('userCenter.security.smsCodeHelper')}
                      />
                      <Button
                        variant="outlined"
                        onClick={() => void handleSendBindPhoneCode()}
                        disabled={phoneCodeSending || phoneResendSeconds > 0}
                        sx={{ whiteSpace: 'nowrap', minWidth: 140 }}
                      >
                        {phoneCodeSending ? t('userCenter.security.sending') : phoneResendSeconds > 0 ? t('userCenter.security.resendAfter', { seconds: phoneResendSeconds }) : t('userCenter.security.sendSmsCode')}
                      </Button>
                    </Stack>
                    <FormControlLabel
                      sx={{ mt: 1 }}
                      control={
                        <Checkbox
                          checked={phoneCodeConsented}
                          onChange={(event) => setPhoneCodeConsented(event.target.checked)}
                        />
                      }
                      label={t('userCenter.security.consentLabel')}
                    />
                  </FormControl>
                )}
                <Button
                  variant="contained"
                  onClick={() => void handleBindPhone()}
                  disabled={phoneSubmitting}
                  sx={{ alignSelf: 'flex-start' }}
                >
                  {phoneSubmitting ? t('userCenter.security.submitting') : phoneOccupied ? t('userCenter.security.verifyAndBind') : t('userCenter.security.bindPhone')}
                </Button>
              </Stack>
            </CardContent>
          </Card>

          <Card variant="outlined" sx={{ mt: 2, borderRadius: 3 }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <LogoutIcon color="error" />
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  {t('userCenter.security.sessionTitle')}
                </Typography>
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                {t('userCenter.security.sessionHelper')}
              </Typography>
              <Button variant="outlined" color="error" sx={{ mt: 2 }} onClick={handleLogout}>
                {t('userCenter.security.safeLogout')}
              </Button>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Stack>
  )

  return (
    <Box
      sx={{
        minHeight: '100vh',
        backgroundColor: 'background.default', // 页面画布走 bgDefault 反相（原为浅蓝渐变）
        py: { xs: 2, md: 4 },
      }}
    >
      <Container maxWidth="lg">
        <Paper
          elevation={0}
          sx={(theme) => ({
            p: { xs: 2, md: 3 },
            borderRadius: 4,
            color: 'primary.contrastText',
            // hero 深蓝渐变走 primary 双阶反相（hero playbook），阴影取 shadow3 档。
            background: `linear-gradient(135deg, ${theme.palette.primary.main} 0%, ${theme.palette.primary.dark} 58%, ${theme.palette.primary.main} 100%)`,
            boxShadow: 8,
          })}
        >
          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={3}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'flex-start', sm: 'center' }}>
              <Avatar
                src={user?.avatar_url || undefined}
                sx={(theme) => ({ width: 72, height: 72, fontSize: '1.5rem', fontWeight: 700, bgcolor: alpha(theme.palette.primary.contrastText, 0.18) })}
              >
                {userAvatarFallback}
              </Avatar>
              <Box>
                <Typography variant="overline" sx={{ letterSpacing: '0.18em', opacity: 0.82 }}>
                  User Center
                </Typography>
                <Typography variant="h4" sx={{ fontWeight: 800 }}>
                  {t('userCenter.security.userCenter')}
                </Typography>
                <Typography variant="h6" sx={{ mt: 0.5, fontWeight: 600 }}>
                  {userDisplayName}
                </Typography>
                <Typography variant="body2" sx={{ opacity: 0.86, mt: 0.5 }}>
                  {userIdentity}
                </Typography>
                <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
                  <Chip size="small" label={hasAdminRole ? t('userCenter.security.adminAccount') : t('userCenter.security.creatorAccount')} sx={(theme) => ({ color: 'primary.contrastText', bgcolor: alpha(theme.palette.primary.contrastText, 0.14) })} />
                  {roleNames.length > 0 ? (
                    <Chip size="small" label={roleNames.join(' / ')} sx={(theme) => ({ color: 'primary.contrastText', bgcolor: alpha(theme.palette.primary.contrastText, 0.14) })} />
                  ) : null}
                  <Chip size="small" label={t('userCenter.security.pointsLedgerExpanding')} sx={(theme) => ({ color: 'primary.contrastText', bgcolor: alpha(theme.palette.primary.contrastText, 0.14) })} />
                </Stack>
              </Box>
            </Stack>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} alignItems={{ xs: 'stretch', sm: 'flex-start' }}>
              <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/home')} sx={(theme) => ({ color: 'primary.contrastText', borderColor: alpha(theme.palette.primary.contrastText, 0.35) })} variant="outlined">
                {t('userCenter.security.backToHome')}
              </Button>
              {hasAdminRole ? (
                <Button
                  startIcon={<DashboardCustomizeOutlinedIcon />}
                  onClick={() => navigate('/admin')}
                  sx={(theme) => ({ color: 'primary.contrastText', borderColor: alpha(theme.palette.primary.contrastText, 0.35) })}
                  variant="outlined"
                >
                  {t('userCenter.security.console')}
                </Button>
              ) : null}
              <Button
                startIcon={refreshing ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                onClick={assetFacade.refreshUserCenterAssets}
                disabled={refreshing}
                variant="contained"
                sx={(theme) => ({ bgcolor: alpha(theme.palette.primary.contrastText, 0.16), boxShadow: 'none' })}
              >
                {refreshing ? t('userCenter.security.refreshing') : t('userCenter.security.refreshUserCenter')}
              </Button>
            </Stack>
          </Stack>
        </Paper>

        {error ? (
          <Alert severity="error" sx={{ mt: 3 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        ) : null}
        {feedback ? (
          <Alert severity={feedback.type} sx={{ mt: 3 }} onClose={() => setFeedback(null)}>
            {feedback.text}
          </Alert>
        ) : null}

        <Paper sx={{ mt: 3, borderRadius: 4, overflow: 'hidden' }}>
          <Tabs
            value={activeTab}
            onChange={(_, value: UserCenterTab) => handleTabChange(value)}
            variant="scrollable"
            scrollButtons="auto"
            sx={{ px: 1.5, pt: 1.5, borderBottom: '1px solid', borderColor: 'divider' }}
          >
            {tabs.map((tab) => (
              <Tab key={tab.value} value={tab.value} label={t(tab.label)} />
            ))}
          </Tabs>

          <Box sx={{ p: { xs: 2, md: 3 } }}>
            {loading ? (
              <Box sx={{ py: 8, display: 'flex', justifyContent: 'center' }}>
                <CircularProgress />
              </Box>
            ) : null}

            {!loading && activeTab === 'overview' ? overviewContent : null}
            {!loading && activeTab === 'creation' ? creationContent : null}
            {!loading && activeTab === 'assets' ? assetsContent : null}
            {!loading && activeTab === 'points' ? (pointsOverview ? enhancedPointsContent : pointsContent) : null}
            {!loading && activeTab === 'records' ? recordsContent : null}
            {!loading && activeTab === 'security' ? securityContent : null}
            {!loading && activeTab === 'video-api' ? videoApiContent : null}
          </Box>
        </Paper>
      </Container>

    </Box>
  )
}
