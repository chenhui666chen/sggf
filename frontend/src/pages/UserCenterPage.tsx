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
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  Grid,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoStoriesIcon from '@mui/icons-material/AutoStories'
import DashboardCustomizeOutlinedIcon from '@mui/icons-material/DashboardCustomizeOutlined'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import LogoutIcon from '@mui/icons-material/Logout'
import MovieIcon from '@mui/icons-material/Movie'
import RefreshIcon from '@mui/icons-material/Refresh'
import SaveIcon from '@mui/icons-material/Save'
import SecurityOutlinedIcon from '@mui/icons-material/SecurityOutlined'
import StarsOutlinedIcon from '@mui/icons-material/StarsOutlined'
import { RootState, AppDispatch } from '@/store/store'
import { logout } from '@/store/slices/authSlice'
import {
  apiClient,
  extractApiErrorMessage,
  type UserAssetRecord,
  type UserCenterPointsOverviewResponse,
} from '@/services/api'
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

type UserCenterTab = 'overview' | 'creation' | 'assets' | 'points' | 'records' | 'security'
type AssetViewFilter = 'all' | 'favorites' | 'deliverable' | 'reusable'
type AssetArchiveFilter = 'active' | 'archived' | 'all'

type FeedbackState = {
  type: 'success' | 'error'
  text: string
}

type UserAssetUpdatePayload = {
  title?: string
  description?: string | null
  tags?: string[]
  asset_class?: string
  is_favorite?: boolean
  archived?: boolean
}

type UserAssetSourceInfo = {
  label: string
  summary: string
  traceLabel?: string | null
  projectLabel?: string | null
  backPath?: string | null
  backLabel?: string | null
}

type ProjectAggregate = ProjectRecord & {
  audiobookCount: number
  dramaRunCount: number
}

const tabs: Array<{ value: UserCenterTab; label: string }> = [
  { value: 'overview', label: '概览' },
  { value: 'creation', label: '我的创作' },
  { value: 'assets', label: '我的资产' },
  { value: 'points', label: '积分与权益' },
  { value: 'records', label: '记录与回收站' },
  { value: 'security', label: '账户与安全' },
]

const USER_CENTER_TAB_VALUES = new Set<UserCenterTab>(tabs.map((tab) => tab.value))
const USER_CENTER_POINTS_PATH = '/user-center?tab=points'

function normalizeUserCenterTab(value: string | null | undefined): UserCenterTab {
  if (!value) return 'overview'
  return USER_CENTER_TAB_VALUES.has(value as UserCenterTab) ? (value as UserCenterTab) : 'overview'
}

const runningStatuses = new Set(['queued', 'running', 'waiting', 'pending', 'processing'])
const failedStatuses = new Set(['failed', 'error', 'timeout'])

function formatDateTime(value?: string | null) {
  if (!value) return '暂无时间'
  const timestamp = new Date(value).getTime()
  if (!Number.isFinite(timestamp) || timestamp <= 0) return '暂无时间'
  return new Date(value).toLocaleString('zh-CN')
}

function formatCurrency(value?: number | null) {
  const amount = Number(value || 0)
  if (!Number.isFinite(amount)) return '¥0.00'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount)
}

function formatAccountMetric(value?: number | null) {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '--'
  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amount)
}

function formatPointsDelta(value?: number | null, direction: 'income' | 'expense' | 'hold' = 'income') {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '--'

  const normalized = new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(Math.abs(amount))

  if (direction === 'hold') return `${normalized} 冻结`
  if (amount > 0) return `+${normalized}`
  if (amount < 0) return `-${normalized}`
  return normalized
}

function getPointsEntryStatusMeta(status: string) {
  if (status === 'expired') {
    return { label: '已过期', color: 'default' as const }
  }
  if (status === 'frozen') {
    return { label: '冻结中', color: 'warning' as const }
  }
  return { label: '生效中', color: 'success' as const }
}

function getPointsEntryDirectionMeta(direction: string) {
  if (direction === 'expense') {
    return { label: '支出', color: 'error' as const }
  }
  if (direction === 'hold') {
    return { label: '冻结', color: 'warning' as const }
  }
  return { label: '收入', color: 'success' as const }
}

function getPointsRuleSourceLabel(source?: string | null) {
  return source === 'admin_log' ? '后台运营规则' : '系统默认规则'
}

function getPricingBasisLabel(basis?: string | null) {
  return basis === 'standard_price_table' ? '内部标准价' : '供应商公开价'
}

function formatPercentRate(value?: number | null) {
  const amount = Number(value)
  if (!Number.isFinite(amount)) return '--'
  return `${(amount * 100).toFixed(amount === 1 ? 0 : 2)}%`
}

function getTaskBillingPricingStatusMeta(status: string) {
  if (status === 'actual') {
    return { label: '已结算', color: 'success' as const }
  }
  if (status === 'estimated') {
    return { label: '预估中', color: 'warning' as const }
  }
  return { label: '待计价', color: 'default' as const }
}

function getProjectTimestamp(project: ProjectRecord) {
  return new Date(project.updated_at || project.created_at || 0).getTime()
}

function extractDreamweaverLibraryAssetId(asset: UserAssetRecord): number | null {
  if (asset.source_module !== 'dreamweaver_library') return null

  const payloadAssetId = Number.parseInt(String(asset.source_payload_json?.asset_id || ''), 10)
  if (Number.isFinite(payloadAssetId) && payloadAssetId > 0) {
    return payloadAssetId
  }

  const metadataAssetId = Number.parseInt(String(asset.metadata_json?.library_asset_id || ''), 10)
  if (Number.isFinite(metadataAssetId) && metadataAssetId > 0) {
    return metadataAssetId
  }

  return null
}

function extractDreamweaverMergedRunId(asset: UserAssetRecord): string | null {
  if (asset.source_module !== 'dreamweaver_run') return null

  const payloadRunId = String(asset.source_payload_json?.run_id || '').trim()
  if (payloadRunId) return payloadRunId

  const metadataRunId = String(asset.metadata_json?.run_id || '').trim()
  return metadataRunId || null
}

function formatDreamweaverViewLabel(view: string | null | undefined): string | null {
  const normalized = String(view || '').trim().toLowerCase()
  if (!normalized) return null
  if (normalized === 'front') return '正面'
  if (normalized === 'side') return '侧面'
  if (normalized === 'back') return '背面'
  if (normalized === 'bust_front') return '半身正面'
  if (normalized === 'bust_three_quarter') return '半身四分之三侧'
  if (normalized === 'bust_side') return '半身侧面'
  return normalized
}

function parseAssetTagsInput(value: string): string[] {
  const parts = String(value || '')
    .split(/[\n,，、]+/)
    .map((item) => item.trim())
    .filter(Boolean)

  const nextTags: string[] = []
  const seen = new Set<string>()

  parts.forEach((tag) => {
    const normalized = tag.slice(0, 30)
    const key = normalized.toLowerCase()
    if (!normalized || seen.has(key) || nextTags.length >= 12) return
    seen.add(key)
    nextTags.push(normalized)
  })

  return nextTags
}

function MetricCard(props: { title: string; value: string | number; helper: string; color: string }) {
  const { title, value, helper, color } = props
  return (
    <Card variant="outlined" sx={{ height: '100%', borderRadius: 3, borderColor: 'rgba(15, 23, 42, 0.08)' }}>
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
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [assetListError, setAssetListError] = useState<string | null>(null)
  const [assetListLoading, setAssetListLoading] = useState(false)
  const [userAssets, setUserAssets] = useState<UserAssetRecord[]>([])
  const [protectedAssetUrls, setProtectedAssetUrls] = useState<Record<number, string>>({})
  const [feedback, setFeedback] = useState<FeedbackState | null>(null)
  const [restoringKey, setRestoringKey] = useState<string | null>(null)
  const [assetActionKey, setAssetActionKey] = useState<string | null>(null)
  const [assetBatchSubmitting, setAssetBatchSubmitting] = useState(false)
  const [passwordSubmitting, setPasswordSubmitting] = useState(false)
  const [passwordData, setPasswordData] = useState({ old_password: '', new_password: '', confirm_password: '' })
  const [assetViewFilter, setAssetViewFilter] = useState<AssetViewFilter>('all')
  const [assetKindFilter, setAssetKindFilter] = useState<string>('all')
  const [assetArchiveFilter, setAssetArchiveFilter] = useState<AssetArchiveFilter>('active')
  const [assetSourceFilter, setAssetSourceFilter] = useState<string>('all')
  const [assetTagFilter, setAssetTagFilter] = useState<string>('all')
  const [assetEditorOpen, setAssetEditorOpen] = useState(false)
  const [editingAsset, setEditingAsset] = useState<UserAssetRecord | null>(null)
  const [assetEditorSubmitting, setAssetEditorSubmitting] = useState(false)
  const [selectedAssetIds, setSelectedAssetIds] = useState<number[]>([])
  const [assetEditorData, setAssetEditorData] = useState({ title: '', description: '', tagsText: '' })

  const hasAdminRole = user?.roles?.some((role) => role.code === 'admin' || role.code === 'super_admin') ?? false
  const userDisplayName = user?.full_name?.trim() || user?.username || '未命名用户'
  const userIdentity = user?.email || user?.username || '暂无账号标识'
  const userAvatarFallback = userDisplayName.slice(0, 1).toUpperCase()
  const roleNames = (user?.roles || []).map((role) => role.name).filter(Boolean)
  const activeTab = normalizeUserCenterTab(searchParams.get('tab'))

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

  const loadUserAssets = useCallback(async (silent = false) => {
    if (!silent) setAssetListLoading(true)
    try {
      const response = await apiClient.listUserAssets({ limit: 100, include_archived: true })
      setUserAssets(Array.isArray(response.data) ? response.data : [])
      setAssetListError(null)
    } catch (loadError) {
      setAssetListError(await extractApiErrorMessage(loadError, '加载用户资产失败'))
    } finally {
      if (!silent) setAssetListLoading(false)
    }
  }, [])

  const loadUserCenterData = useCallback(async (silent = false) => {
    if (silent) {
      setRefreshing(true)
    } else {
      setLoading(true)
    }
    setError(null)

    try {
      const [projectsRes, deletedChaptersRes, deletedAudiobookRes, pointsOverviewRes] = await Promise.all([
        apiClient.getProjects(),
        apiClient.getDeletedChapters(0),
        apiClient.listDeletedProjects(),
        apiClient.getUserCenterPointsOverview(),
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
      const message = await extractApiErrorMessage(loadError, '加载用户中心失败')
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

  useEffect(() => {
    void loadUserAssets()
  }, [loadUserAssets])

  const projectAggregates = useMemo<ProjectAggregate[]>(() => {
    return [...projects]
      .map((project) => ({
        ...project,
        audiobookCount: (audiobookMap[project.id] || []).length,
        dramaRunCount: (dreamweaverMap[project.id] || []).length,
      }))
      .sort((a, b) => getProjectTimestamp(b) - getProjectTimestamp(a))
  }, [audiobookMap, dreamweaverMap, projects])

  const projectTitleMap = useMemo(
    () => new Map(projects.map((project) => [project.id, project.title?.trim() || `项目 #${project.id}`] as const)),
    [projects],
  )

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
  const activeUserAssets = useMemo(() => userAssets.filter((asset) => !asset.archived_at), [userAssets])
  const archivedUserAssetCount = userAssets.length - activeUserAssets.length
  const favoriteAssetCount = activeUserAssets.filter((asset) => asset.is_favorite).length
  const deliverableAssetCount = activeUserAssets.filter((asset) => asset.asset_class === 'deliverable').length
  const reusableAssetCount = activeUserAssets.filter((asset) => asset.asset_class !== 'deliverable').length

  const totalAudiobookCost = pointsOverview?.connected_overview.audiobook_total_cost ?? 0
  const totalDreamweaverRuns = pointsOverview?.connected_overview.dreamweaver_run_count ?? 0
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

  const connectedLedgerSourceCount = pointsOverview?.points_account.connected_source_count ?? 0
  const pendingLedgerSourceCount =
    pointsOverview?.points_account.pending_source_count ?? pendingLedgerSignals.length
  const pointsAccountStatus = pointsOverview?.points_account.status ?? 'planned'
  const pointsAccountBalance = pointsOverview?.points_account.balance ?? null
  const pointsAccountFrozen = pointsOverview?.points_account.frozen ?? null
  const pointsAccountExpiringSoon = pointsOverview?.points_account.expiring_soon ?? null
  const pointsRules = pointsOverview?.points_rules ?? null
  const pricingPolicy = pointsOverview?.pricing_policy ?? null
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
  const pointsConnectedOverview = pointsOverview?.connected_overview ?? null
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
  const pointsRuleSummaryItems = pointsRules
    ? [
        { label: '复用资产奖励', value: `${formatAccountMetric(pointsRules.reusable_asset_reward)} 积分` },
        { label: '交付资产奖励', value: `${formatAccountMetric(pointsRules.deliverable_asset_reward)} 积分` },
        { label: '有声书完成奖励', value: `${formatAccountMetric(pointsRules.audiobook_completion_reward)} 积分` },
        { label: '短剧完成奖励', value: `${formatAccountMetric(pointsRules.dreamweaver_completion_reward)} 积分` },
        { label: '有声书运行冻结', value: `${formatAccountMetric(pointsRules.running_audiobook_frozen)} 积分` },
        { label: '短剧运行冻结', value: `${formatAccountMetric(pointsRules.running_dreamweaver_frozen)} 积分` },
        { label: '奖励有效期', value: `${pointsRules.reward_ttl_days} 天` },
        { label: '到期提醒窗口', value: `${pointsRules.expiring_notice_days} 天` },
      ]
    : []
  const pricingPolicySummaryItems = pricingPolicy
    ? [
        { label: '积分汇率', value: `1 元 = ${pricingPolicy.points_per_yuan} 积分` },
        { label: '用户计价基准', value: getPricingBasisLabel(pricingPolicy.user_price_basis) },
        { label: '用户计价系数', value: `${pricingPolicy.user_price_rate.toFixed(2)} ×` },
        { label: '冻结缓冲', value: formatPercentRate(pricingPolicy.freeze_buffer_rate) },
      ]
    : []

  const pointsAccountStatusMeta = useMemo(() => {
    if (pointsAccountStatus === 'partial') {
      return {
        label: '已接入账本',
        description: '已有真实积分账本与任务计费链路接入用户中心，后续会继续扩展更多消费和权益来源。',
        color: 'info' as const,
      }
    }
    return {
      label: '逐步扩展',
      description: '积分账户结构已就绪，当前已支持积分预检和部分任务计费，更多权益与消费来源会继续接入。',
      color: 'warning' as const,
    }
  }, [pointsAccountStatus])

  const assetKindOptions = useMemo(
    () =>
      Array.from(new Set(userAssets.map((asset) => String(asset.asset_kind || '').trim()).filter(Boolean))).sort(
        (left, right) => left.localeCompare(right),
      ),
    [userAssets],
  )

  const assetTagOptions = useMemo(
    () =>
      Array.from(
        new Set(
          userAssets.flatMap((asset) => asset.tags.map((tag) => String(tag || '').trim()).filter(Boolean)),
        ),
      ).sort((left, right) => left.localeCompare(right, 'zh-CN')),
    [userAssets],
  )

  const resolveUserAssetProjectId = useCallback((asset: UserAssetRecord) => {
    const directProjectId = Number(asset.project_id)
    if (Number.isFinite(directProjectId) && directProjectId > 0) return directProjectId

    const payloadProjectId = Number.parseInt(String(asset.source_payload_json?.project_id || ''), 10)
    if (Number.isFinite(payloadProjectId) && payloadProjectId > 0) return payloadProjectId

    const metadataProjectId = Number.parseInt(String(asset.metadata_json?.project_id || ''), 10)
    if (Number.isFinite(metadataProjectId) && metadataProjectId > 0) return metadataProjectId

    return null
  }, [])

  const getUserAssetSourceInfo = useCallback(
    (asset: UserAssetRecord): UserAssetSourceInfo => {
      const sourceModule = String(asset.source_module || '').trim().toLowerCase()
      const projectId = resolveUserAssetProjectId(asset)
      const projectLabel = projectId ? projectTitleMap.get(projectId) || `项目 #${projectId}` : null

      if (sourceModule === 'asset_studio') {
        return {
          label: '资产工坊',
          summary: projectLabel ? `来自资产工坊，关联项目：${projectLabel}。` : '来自资产工坊。',
          projectLabel,
          backPath: '/asset-studio',
          backLabel: '前往资产工坊',
        }
      }

      if (sourceModule === 'dreamweaver_library') {
        const entityType = String(
          asset.metadata_json?.entity_type || asset.source_payload_json?.entity_type || '',
        ).trim()
        const entityTypeLabel =
          entityType === 'character' ? '角色' : entityType === 'scene' ? '场景' : entityType === 'prop' ? '道具' : '素材'
        const viewLabel = formatDreamweaverViewLabel(
          String(asset.metadata_json?.view || asset.source_payload_json?.view || '').trim() || null,
        )
        return {
          label: '短剧素材库',
          summary: projectLabel ? `来自短剧素材库，沉淀于项目 ${projectLabel}。` : '来自短剧素材库。',
          traceLabel: viewLabel ? `${entityTypeLabel} · ${viewLabel}` : entityTypeLabel,
          projectLabel,
          backPath: projectId ? `/drama/${projectId}/library` : '/drama',
          backLabel: projectId ? '前往素材库' : '前往短剧模块',
        }
      }

      if (sourceModule === 'dreamweaver_run') {
        const runId = extractDreamweaverMergedRunId(asset)
        return {
          label: '短剧成片',
          summary: projectLabel ? `来自短剧运行结果，关联项目：${projectLabel}。` : '来自短剧运行结果。',
          traceLabel: runId ? `run_id ${runId}` : '运行结果',
          projectLabel,
          backPath: projectId ? `/drama/${projectId}` : '/drama',
          backLabel: projectId ? '回到短剧项目' : '前往短剧模块',
        }
      }

      return {
        label: asset.source_module || '未分类来源',
        summary: '该资产已进入用户中心统一治理，具体生产仍建议回到原模块处理。',
        projectLabel,
      }
    },
    [projectTitleMap, resolveUserAssetProjectId],
  )

  const assetSourceOptions = useMemo(
    () =>
      Array.from(
        new Map(
          userAssets
            .map((asset) => [String(asset.source_module || '').trim(), getUserAssetSourceInfo(asset).label] as const)
            .filter(([value]) => Boolean(value)),
        ).entries(),
      )
        .sort((left, right) => left[1].localeCompare(right[1], 'zh-CN'))
        .map(([value, label]) => ({ value, label })),
    [getUserAssetSourceInfo, userAssets],
  )

  const filteredUserAssets = useMemo(() => {
    let nextAssets = [...userAssets]
    if (assetArchiveFilter === 'active') nextAssets = nextAssets.filter((asset) => !asset.archived_at)
    if (assetArchiveFilter === 'archived') nextAssets = nextAssets.filter((asset) => Boolean(asset.archived_at))
    if (assetViewFilter === 'favorites') nextAssets = nextAssets.filter((asset) => asset.is_favorite)
    if (assetViewFilter === 'deliverable') nextAssets = nextAssets.filter((asset) => asset.asset_class === 'deliverable')
    if (assetViewFilter === 'reusable') nextAssets = nextAssets.filter((asset) => asset.asset_class !== 'deliverable')
    if (assetKindFilter !== 'all') nextAssets = nextAssets.filter((asset) => asset.asset_kind === assetKindFilter)
    if (assetSourceFilter !== 'all') nextAssets = nextAssets.filter((asset) => asset.source_module === assetSourceFilter)
    if (assetTagFilter !== 'all') nextAssets = nextAssets.filter((asset) => asset.tags.includes(assetTagFilter))
    return nextAssets
  }, [assetArchiveFilter, assetKindFilter, assetSourceFilter, assetTagFilter, assetViewFilter, userAssets])

  const selectedAssetIdSet = useMemo(() => new Set(selectedAssetIds), [selectedAssetIds])
  const selectedFilteredAssets = useMemo(
    () => filteredUserAssets.filter((asset) => selectedAssetIdSet.has(asset.id)),
    [filteredUserAssets, selectedAssetIdSet],
  )
  const allFilteredAssetsSelected =
    filteredUserAssets.length > 0 && filteredUserAssets.every((asset) => selectedAssetIdSet.has(asset.id))

  useEffect(() => {
    let revoked = false
    const objectUrls: string[] = []

    const loadProtectedAssetUrls = async () => {
      const protectedAssets = userAssets
        .map((asset) => {
          const libraryAssetId = extractDreamweaverLibraryAssetId(asset)
          if (libraryAssetId) return { assetId: asset.id, kind: 'dreamweaver_library' as const, libraryAssetId }
          const runId = extractDreamweaverMergedRunId(asset)
          if (runId) return { assetId: asset.id, kind: 'dreamweaver_run' as const, runId }
          return null
        })
        .filter(Boolean) as Array<
          | { assetId: number; kind: 'dreamweaver_library'; libraryAssetId: number }
          | { assetId: number; kind: 'dreamweaver_run'; runId: string }
        >

      if (!protectedAssets.length) {
        setProtectedAssetUrls({})
        return
      }

      const entries = await Promise.all(
        protectedAssets.map(async (item) => {
          try {
            const response =
              item.kind === 'dreamweaver_library'
                ? await apiClient.getDreamweaverLibraryAssetFile(item.libraryAssetId)
                : await apiClient.getDreamweaverMergedVideoFile(item.runId)
            const objectUrl = URL.createObjectURL(response.data)
            objectUrls.push(objectUrl)
            return [item.assetId, objectUrl] as const
          } catch {
            return [item.assetId, ''] as const
          }
        }),
      )

      if (revoked) return
      const nextUrls: Record<number, string> = {}
      entries.forEach(([assetId, url]) => {
        if (url) nextUrls[assetId] = url
      })
      setProtectedAssetUrls(nextUrls)
    }

    void loadProtectedAssetUrls()

    return () => {
      revoked = true
      objectUrls.forEach((url) => {
        try {
          URL.revokeObjectURL(url)
        } catch {
          // ignore
        }
      })
    }
  }, [userAssets])

  useEffect(() => {
    const visibleAssetIds = new Set(filteredUserAssets.map((asset) => asset.id))
    setSelectedAssetIds((prev) => {
      const next = prev.filter((assetId) => visibleAssetIds.has(assetId))
      return next.length === prev.length ? prev : next
    })
  }, [filteredUserAssets])

  const resolveUserAssetMediaUrl = useCallback(
    (asset: UserAssetRecord) => protectedAssetUrls[asset.id] || asset.preview_url || asset.file_url || '',
    [protectedAssetUrls],
  )

  const handleUpdateUserAsset = async (assetId: number, payload: UserAssetUpdatePayload) => {
    setAssetActionKey(`asset-${assetId}`)
    try {
      await apiClient.updateUserAsset(assetId, payload)
      await loadUserAssets(true)
      setFeedback({ type: 'success', text: '资产信息已更新' })
    } catch (updateError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(updateError, '更新用户资产失败'),
      })
    } finally {
      setAssetActionKey(null)
    }
  }

  const handleToggleAssetSelection = useCallback((assetId: number) => {
    setSelectedAssetIds((prev) =>
      prev.includes(assetId) ? prev.filter((currentId) => currentId !== assetId) : [...prev, assetId],
    )
  }, [])

  const handleToggleSelectAllFilteredAssets = useCallback(() => {
    if (allFilteredAssetsSelected) {
      setSelectedAssetIds([])
      return
    }
    setSelectedAssetIds(filteredUserAssets.map((asset) => asset.id))
  }, [allFilteredAssetsSelected, filteredUserAssets])

  const handleBatchUpdateUserAssets = async (payload: UserAssetUpdatePayload, actionLabel: string) => {
    if (!selectedFilteredAssets.length) return

    setAssetBatchSubmitting(true)
    try {
      const response = await apiClient.batchUpdateUserAssets({
        asset_ids: selectedFilteredAssets.map((asset) => asset.id),
        updates: payload,
      })
      const updatedIds = Array.isArray(response.data?.asset_ids)
        ? response.data.asset_ids
        : selectedFilteredAssets.map((asset) => asset.id)
      const updatedCount = Number(response.data?.updated_count) || updatedIds.length
      await loadUserAssets(true)
      setSelectedAssetIds((prev) => prev.filter((assetId) => !updatedIds.includes(assetId)))
      setFeedback({ type: 'success', text: `${actionLabel}，共处理 ${updatedCount} 项资产` })
    } catch (batchError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(batchError, `${actionLabel}失败`),
      })
    } finally {
      setAssetBatchSubmitting(false)
    }
  }

  const handleOpenAssetEditor = (asset: UserAssetRecord) => {
    setEditingAsset(asset)
    setAssetEditorData({
      title: asset.title || '',
      description: asset.description || '',
      tagsText: asset.tags.join(', '),
    })
    setAssetEditorOpen(true)
  }

  const handleCloseAssetEditor = () => {
    if (assetEditorSubmitting) return
    setAssetEditorOpen(false)
    setEditingAsset(null)
    setAssetEditorData({ title: '', description: '', tagsText: '' })
  }

  const handleSaveAssetEditor = async () => {
    if (!editingAsset) return
    const normalizedTitle = assetEditorData.title.trim()
    if (!normalizedTitle) {
      setFeedback({ type: 'error', text: '资产标题不能为空' })
      return
    }

    setAssetEditorSubmitting(true)
    try {
      await apiClient.updateUserAsset(editingAsset.id, {
        title: normalizedTitle,
        description: assetEditorData.description.trim() || null,
        tags: parseAssetTagsInput(assetEditorData.tagsText),
      })
      await loadUserAssets(true)
      setFeedback({ type: 'success', text: '资产内容已保存' })
      setAssetEditorOpen(false)
      setEditingAsset(null)
      setAssetEditorData({ title: '', description: '', tagsText: '' })
    } catch (saveError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(saveError, '保存资产失败'),
      })
    } finally {
      setAssetEditorSubmitting(false)
    }
  }

  const handleRestoreChapter = async (chapterId: number) => {
    setRestoringKey(`chapter-${chapterId}`)
    try {
      await apiClient.restoreChapter(chapterId)
      setFeedback({ type: 'success', text: '章节已恢复' })
      await loadUserCenterData(true)
    } catch (restoreError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(restoreError, '恢复章节失败'),
      })
    } finally {
      setRestoringKey(null)
    }
  }

  const handleRestoreAudiobookProject = async (audiobookProjectId: number) => {
    setRestoringKey(`audiobook-${audiobookProjectId}`)
    try {
      await apiClient.restoreAudiobookProject(audiobookProjectId)
      setFeedback({ type: 'success', text: '有声书项目已恢复' })
      await loadUserCenterData(true)
    } catch (restoreError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(restoreError, '恢复有声书项目失败'),
      })
    } finally {
      setRestoringKey(null)
    }
  }

  const handleChangePassword = async () => {
    if (passwordData.new_password !== passwordData.confirm_password) {
      setFeedback({ type: 'error', text: '两次输入的新密码不一致' })
      return
    }
    if (passwordData.new_password.length < 6) {
      setFeedback({ type: 'error', text: '新密码至少需要 6 位字符' })
      return
    }

    setPasswordSubmitting(true)
    try {
      const response = await apiClient.changePassword({
        old_password: passwordData.old_password,
        new_password: passwordData.new_password,
      })
      setFeedback({ type: 'success', text: response.data?.message || '密码已更新' })
      setPasswordData({ old_password: '', new_password: '', confirm_password: '' })
    } catch (passwordError) {
      setFeedback({
        type: 'error',
        text: await extractApiErrorMessage(passwordError, '修改密码失败'),
      })
    } finally {
      setPasswordSubmitting(false)
    }
  }

  const handleLogout = () => {
    dispatch(logout())
    navigate('/login')
  }

  const renderUserAssetPreview = (asset: UserAssetRecord) => {
    const previewUrl = resolveUserAssetMediaUrl(asset)
    const isProtectedAssetPending = asset.source_module === 'dreamweaver_library' && !previewUrl

    if (!previewUrl) {
      return (
        <Box
          sx={{
            height: 180,
            borderRadius: 2.5,
            bgcolor: 'rgba(15, 23, 42, 0.04)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <Typography variant="body2" color="text.secondary">
            {isProtectedAssetPending ? '受保护资源加载中...' : '暂无预览'}
          </Typography>
        </Box>
      )
    }

    if (asset.asset_kind === 'video') {
      return (
        <Box
          component="video"
          src={previewUrl}
          controls
          sx={{ width: '100%', height: 180, objectFit: 'cover', borderRadius: 2.5, bgcolor: 'black' }}
        />
      )
    }

    if (asset.asset_kind === 'audio') {
      return (
        <Box
          sx={{
            height: 180,
            borderRadius: 2.5,
            bgcolor: 'rgba(15, 23, 42, 0.04)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            p: 2,
          }}
        >
          <Box component="audio" src={previewUrl} controls sx={{ width: '100%' }} />
        </Box>
      )
    }

    return (
      <Box
        component="img"
        src={previewUrl}
        alt={asset.title}
        sx={{ width: '100%', height: 180, objectFit: 'cover', borderRadius: 2.5, bgcolor: 'black' }}
      />
    )
  }

  const renderProjectGrid = (items: ProjectAggregate[]) => {
    if (!items.length) {
      return <Alert severity="info">当前还没有可展示的项目，先从创作模块开始建立项目即可。</Alert>
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
                      {project.title?.trim() || `项目 #${project.id}`}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                      {project.description?.trim() || '暂无项目描述，可以在创作工作台内补充更多上下文。'}
                    </Typography>
                  </Box>
                  <Chip size="small" label={project.genre || '未分类'} />
                </Stack>

                <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
                  <Chip icon={<AutoStoriesIcon />} size="small" label="小说项目" />
                  <Chip icon={<HeadphonesIcon />} size="small" label={`有声书 ${project.audiobookCount}`} />
                  <Chip icon={<MovieIcon />} size="small" label={`短剧运行 ${project.dramaRunCount}`} />
                </Stack>

                <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', rowGap: 1 }}>
                  <Button size="small" variant="contained" onClick={() => navigate('/dashboard')}>
                    打开小说工作台
                  </Button>
                  <Button
                    size="small"
                    variant="outlined"
                    onClick={() =>
                      navigate(project.audiobookCount > 0 ? `/audiobook/${project.id}` : '/audiobook-dashboard')
                    }
                  >
                    查看有声书
                  </Button>
                  {hasAdminRole ? (
                    <Button size="small" variant="outlined" onClick={() => navigate(`/drama/${project.id}`)}>
                      查看短剧
                    </Button>
                  ) : null}
                </Stack>

                <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1.5 }}>
                  最近更新时间：{formatDateTime(project.updated_at || project.created_at)}
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
            title="小说项目"
            value={overviewMetrics.novelProjects}
            helper="统一从小说项目出发管理创作上下文。"
            color="#2563eb"
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <MetricCard
            title="有声书项目"
            value={overviewMetrics.audiobookProjects}
            helper="聚合现有有声书结果，不复制工作台。"
            color="#7c3aed"
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <MetricCard
            title="短剧项目"
            value={overviewMetrics.dramaProjects}
            helper="短剧仍保留在原模块内完成复杂生产流。"
            color="#f97316"
          />
        </Grid>
        <Grid item xs={12} md={3}>
          <MetricCard
            title="待处理回收"
            value={overviewMetrics.deletedTotal}
            helper="集中恢复章节与有声书项目。"
            color="#0f766e"
          />
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                当前运行态
              </Typography>
              <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', rowGap: 1 }}>
                <Chip label={`运行中任务 ${overviewMetrics.runningTasks}`} color="info" />
                <Chip label={`失败任务 ${overviewMetrics.failedTasks}`} color={overviewMetrics.failedTasks > 0 ? 'error' : 'default'} />
                <Chip label={`积分状态 ${pointsAccountStatusMeta.label}`} color={pointsAccountStatusMeta.color} variant="outlined" />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                用户中心负责身份、概览和治理入口；具体任务执行、结果修复和批量生产仍保留在对应模块内完成。
              </Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                用户中心定位
              </Typography>
              <Stack spacing={1.25} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  1. 身份层：承接头像、昵称、角色、账号与安全设置。
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  2. 汇总层：聚合小说、有声书、短剧和资产的结果态信息。
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  3. 治理层：承接资产分层、权益展示、消费账本与回收站。
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Alert severity="info">
        资产策略已经明确：过程态、强上下文资产继续留在生成模块；成品资产与跨模块复用素材进入用户中心统一检索、标记、归档和复用。
      </Alert>

      <Box>
        <Typography variant="h6" sx={{ fontWeight: 700, mb: 2 }}>
          最近项目
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
              <AutoStoriesIcon sx={{ color: '#2563eb', fontSize: 28 }} />
              <Typography variant="h6" sx={{ mt: 1, fontWeight: 700 }}>
                小说创作
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
                继续作为主项目工作台，负责章节、设定、审校与核心文本创作流程。
              </Typography>
              <Button sx={{ mt: 2 }} variant="contained" onClick={() => navigate('/dashboard')}>
                进入小说工作台
              </Button>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <HeadphonesIcon sx={{ color: '#7c3aed', fontSize: 28 }} />
              <Typography variant="h6" sx={{ mt: 1, fontWeight: 700 }}>
                有声书创作
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
                用户中心只汇总项目结果、回收与消费账本，脚本生成和音频调试仍回到原工作台处理。
              </Typography>
              <Button sx={{ mt: 2 }} variant="contained" onClick={() => navigate('/audiobook-dashboard')}>
                进入有声书工作台
              </Button>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <MovieIcon sx={{ color: '#f97316', fontSize: 28 }} />
              <Typography variant="h6" sx={{ mt: 1, fontWeight: 700 }}>
                短剧创作
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
                用户中心侧重成片、素材和积分信号汇总，不接管复杂生产链路。
              </Typography>
              <Button sx={{ mt: 2 }} variant="contained" onClick={() => navigate('/drama')}>
                进入短剧模块
              </Button>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Box>
        <Typography variant="h6" sx={{ fontWeight: 700, mb: 2 }}>
          我的项目
        </Typography>
        {renderProjectGrid(projectAggregates)}
      </Box>
    </Stack>
  )

  const assetsContent = (
    <Stack spacing={2.5}>
      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <MetricCard
            title="活跃资产"
            value={activeUserAssets.length}
            helper="用户中心负责汇总、筛选和归档，不替代模块内工作台。"
            color="#2563eb"
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <MetricCard
            title="可复用素材"
            value={`${reusableAssetCount} / ${deliverableAssetCount}`}
            helper="优先沉淀可跨项目复用的稳定素材。"
            color="#7c3aed"
          />
        </Grid>
        <Grid item xs={12} md={4}>
          <MetricCard
            title="重点 / 归档"
            value={`${favoriteAssetCount} / ${archivedUserAssetCount}`}
            helper="重点资产用于快速复用，归档资产用于沉淀历史成果。"
            color="#f97316"
          />
        </Grid>
      </Grid>

      {assetListError ? <Alert severity="warning">{assetListError}</Alert> : null}

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Stack direction={{ xs: 'column', lg: 'row' }} spacing={1.5} justifyContent="space-between">
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} flexWrap="wrap">
              <TextField
                select
                size="small"
                label="资产视角"
                value={assetViewFilter}
                onChange={(event) => setAssetViewFilter(event.target.value as AssetViewFilter)}
                sx={{ minWidth: { xs: '100%', sm: 180 } }}
              >
                <MenuItem value="all">全部资产</MenuItem>
                <MenuItem value="favorites">仅看重点</MenuItem>
                <MenuItem value="deliverable">仅看成品</MenuItem>
                <MenuItem value="reusable">仅看可复用</MenuItem>
              </TextField>
              <TextField
                select
                size="small"
                label="资产类型"
                value={assetKindFilter}
                onChange={(event) => setAssetKindFilter(event.target.value)}
                sx={{ minWidth: { xs: '100%', sm: 180 } }}
              >
                <MenuItem value="all">全部类型</MenuItem>
                {assetKindOptions.map((option) => (
                  <MenuItem key={`asset-kind-${option}`} value={option}>
                    {option}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                size="small"
                label="来源模块"
                value={assetSourceFilter}
                onChange={(event) => setAssetSourceFilter(event.target.value)}
                sx={{ minWidth: { xs: '100%', sm: 180 } }}
              >
                <MenuItem value="all">全部来源</MenuItem>
                {assetSourceOptions.map((option) => (
                  <MenuItem key={`asset-source-${option.value}`} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                size="small"
                label="归档范围"
                value={assetArchiveFilter}
                onChange={(event) => setAssetArchiveFilter(event.target.value as AssetArchiveFilter)}
                sx={{ minWidth: { xs: '100%', sm: 180 } }}
              >
                <MenuItem value="active">活跃资产</MenuItem>
                <MenuItem value="archived">已归档</MenuItem>
                <MenuItem value="all">全部</MenuItem>
              </TextField>
              <TextField
                select
                size="small"
                label="标签"
                value={assetTagFilter}
                onChange={(event) => setAssetTagFilter(event.target.value)}
                sx={{ minWidth: { xs: '100%', sm: 180 } }}
              >
                <MenuItem value="all">全部标签</MenuItem>
                {assetTagOptions.map((option) => (
                  <MenuItem key={`asset-tag-filter-${option}`} value={option}>
                    {option}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} alignItems={{ xs: 'stretch', sm: 'center' }}>
              <Chip size="small" color="primary" variant="outlined" label={`当前结果 ${filteredUserAssets.length}`} />
              <Button variant="outlined" startIcon={<RefreshIcon />} onClick={() => void loadUserAssets()} disabled={assetListLoading}>
                刷新资产
              </Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      {filteredUserAssets.length > 0 ? (
        <Card variant="outlined" sx={{ borderRadius: 3 }}>
          <CardContent>
            <Stack direction={{ xs: 'column', lg: 'row' }} spacing={1.5} justifyContent="space-between">
              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap">
                <Chip
                  size="small"
                  color={selectedFilteredAssets.length > 0 ? 'primary' : 'default'}
                  variant={selectedFilteredAssets.length > 0 ? 'filled' : 'outlined'}
                  label={`已选 ${selectedFilteredAssets.length}`}
                />
                <Chip size="small" variant="outlined" label={allFilteredAssetsSelected ? '当前结果已全选' : `可选 ${filteredUserAssets.length} 项`} />
              </Stack>

              <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} flexWrap="wrap">
                <Button size="small" variant="outlined" onClick={handleToggleSelectAllFilteredAssets} disabled={assetBatchSubmitting}>
                  {allFilteredAssetsSelected ? '取消全选' : '全选当前结果'}
                </Button>
                <Button size="small" variant="outlined" onClick={() => setSelectedAssetIds([])} disabled={assetBatchSubmitting || selectedFilteredAssets.length === 0}>
                  清空选择
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => void handleBatchUpdateUserAssets({ is_favorite: true }, '已批量设为重点')}
                  disabled={assetBatchSubmitting || selectedFilteredAssets.length === 0}
                >
                  设为重点
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => void handleBatchUpdateUserAssets({ archived: true }, '已批量归档')}
                  disabled={assetBatchSubmitting || selectedFilteredAssets.length === 0}
                >
                  归档
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => void handleBatchUpdateUserAssets({ archived: false }, '已批量恢复为活跃')}
                  disabled={assetBatchSubmitting || selectedFilteredAssets.length === 0}
                >
                  恢复活跃
                </Button>
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ) : null}

      {assetListLoading ? (
        <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
          <CircularProgress />
        </Box>
      ) : userAssets.length === 0 ? (
        <Alert severity="info">还没有收录到用户中心的资产，后续可以从各生成模块纳入稳定成果。</Alert>
      ) : filteredUserAssets.length === 0 ? (
        <Alert severity="info">当前筛选条件下没有匹配资产，可以切换筛选项查看其他结果。</Alert>
      ) : (
        <Grid container spacing={2}>
          {filteredUserAssets.map((asset) => {
            const sourceInfo = getUserAssetSourceInfo(asset)
            const isSubmitting = assetActionKey === `asset-${asset.id}`
            return (
              <Grid item xs={12} md={6} lg={4} key={`user-asset-${asset.id}`}>
                <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
                  <CardContent>
                    {renderUserAssetPreview(asset)}
                    <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
                      <Chip size="small" label={asset.asset_kind} />
                      <Chip size="small" color={asset.asset_class === 'deliverable' ? 'warning' : 'secondary'} label={asset.asset_class === 'deliverable' ? '成品资产' : '可复用素材'} />
                      <Chip size="small" variant="outlined" label={`来源：${sourceInfo.label}`} />
                      {asset.is_favorite ? <Chip size="small" color="primary" label="重点资产" /> : null}
                      {asset.archived_at ? <Chip size="small" variant="outlined" label="已归档" /> : null}
                    </Stack>

                    <Stack direction="row" justifyContent="flex-end" alignItems="center" sx={{ mt: 0.25 }}>
                      <Typography variant="caption" color="text.secondary">
                        纳入批量操作
                      </Typography>
                      <Checkbox
                        size="small"
                        checked={selectedAssetIdSet.has(asset.id)}
                        onChange={() => handleToggleAssetSelection(asset.id)}
                        disabled={assetBatchSubmitting}
                      />
                    </Stack>

                    <Typography variant="h6" sx={{ mt: 1.5, fontWeight: 700 }}>
                      {asset.title}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                      {asset.description?.trim() || '当前资产尚未补充说明，可以在用户中心内完善标题、描述和标签。'}
                    </Typography>
                    <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1 }}>
                      {sourceInfo.summary}
                    </Typography>

                    <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
                      {sourceInfo.projectLabel ? <Chip size="small" variant="outlined" label={sourceInfo.projectLabel} /> : null}
                      {sourceInfo.traceLabel ? <Chip size="small" variant="outlined" label={sourceInfo.traceLabel} /> : null}
                      {asset.tags.slice(0, 3).map((tag) => (
                        <Chip key={`asset-tag-${asset.id}-${tag}`} size="small" variant="outlined" label={tag} />
                      ))}
                    </Stack>

                    <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1.5 }}>
                      收录时间：{formatDateTime(asset.created_at)}
                    </Typography>

                    <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', rowGap: 1 }}>
                      {sourceInfo.backPath ? (
                        <Button size="small" variant="outlined" onClick={() => navigate(sourceInfo.backPath || '/user-center')}>
                          {sourceInfo.backLabel || '查看来源'}
                        </Button>
                      ) : null}
                      <Button size="small" variant="outlined" onClick={() => handleOpenAssetEditor(asset)}>
                        编辑信息
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={isSubmitting}
                        onClick={() => void handleUpdateUserAsset(asset.id, { is_favorite: !asset.is_favorite })}
                      >
                        {asset.is_favorite ? '取消重点' : '设为重点'}
                      </Button>
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={isSubmitting}
                        onClick={() => void handleUpdateUserAsset(asset.id, { archived: !asset.archived_at })}
                      >
                        {asset.archived_at ? '恢复活跃' : '归档'}
                      </Button>
                    </Stack>
                  </CardContent>
                </Card>
              </Grid>
            )
          })}
        </Grid>
      )}
    </Stack>
  )

  const pointsContent = (
    <Stack spacing={3}>
      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between" alignItems={{ xs: 'flex-start', sm: 'center' }}>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              积分账户概览
            </Typography>
            <Chip size="small" color={pointsAccountStatusMeta.color} label={pointsAccountStatusMeta.label} />
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
            {pointsAccountStatusMeta.description}
          </Typography>

          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard title="积分余额" value={formatAccountMetric(pointsAccountBalance)} helper="后续承接积分发放、抵扣与权益消费。" color="#2563eb" />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard title="冻结中" value={formatAccountMetric(pointsAccountFrozen)} helper="预留给结算中或待确认积分。" color="#f97316" />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard title="即将过期" value={formatAccountMetric(pointsAccountExpiringSoon)} helper="后续可补充到期提醒能力。" color="#dc2626" />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard title="账本来源" value={`${connectedLedgerSourceCount} / ${pendingLedgerSourceCount}`} helper="前者为已接入，后者为待接入。" color="#0f766e" />
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <StarsOutlinedIcon color="primary" />
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  已接入概览
                </Typography>
              </Stack>
              <Stack spacing={1.25} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  项目数：{pointsConnectedOverview?.project_count ?? projects.length}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  用户资产数：{pointsConnectedOverview?.user_asset_count ?? userAssets.length}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  有声书项目数：{pointsConnectedOverview?.audiobook_project_count ?? overviewMetrics.audiobookProjects}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  有声书累计成本：{formatCurrency(totalAudiobookCost)}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  短剧运行次数：{totalDreamweaverRuns}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                资产接入策略
              </Typography>
              <Stack spacing={1.25} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  1. 过程态资产继续保留在生成模块，避免用户中心承接复杂上下文操作。
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  2. 稳定素材、成片和跨模块复用结果进入用户中心，便于统一检索、标记和权益联动。
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  3. 不同类型资产采取不同策略，生成链路负责生产，用户中心负责汇总与治理。
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                当前消费定价
              </Typography>
              {pricingPolicy ? (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                    <Chip
                      size="small"
                      color={pricingPolicy.source === 'admin_log' ? 'primary' : 'default'}
                      label={pricingPolicy.source === 'admin_log' ? '后台定价快照' : '系统默认定价'}
                    />
                    <Chip size="small" variant="outlined" label={`用户按 ${getPricingBasisLabel(pricingPolicy.user_price_basis)} 计点`} />
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    用户侧按公开价或内部标准价折算积分，不额外加价；运行中任务会按当前缓冲比例预留建议冻结值。
                  </Typography>
                  <Box sx={{ display: 'grid', gap: 1.25, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                    {pricingPolicySummaryItems.map((item) => (
                      <Box
                        key={item.label}
                        sx={{ p: 1.5, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2 }}
                      >
                        <Typography variant="caption" color="text.secondary">
                          {item.label}
                        </Typography>
                        <Typography sx={{ mt: 0.5, fontWeight: 600 }}>{item.value}</Typography>
                      </Box>
                    ))}
                  </Box>
                  <Typography variant="caption" color="text.secondary">
                    最近调整：{pricingPolicy.updated_at ? formatDateTime(pricingPolicy.updated_at) : '尚未人工调整'}
                  </Typography>
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                  暂无可展示的消费定价快照。
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
                  任务计费总览
                </Typography>
                <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                  <Chip size="small" color="success" variant="outlined" label={`已结算 ${taskBillingOverview?.actual_task_count ?? 0}`} />
                  <Chip size="small" color="warning" variant="outlined" label={`预估中 ${taskBillingOverview?.estimated_task_count ?? 0}`} />
                  <Chip size="small" variant="outlined" label={`待计价 ${taskBillingOverview?.pending_task_count ?? 0}`} />
                </Stack>
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
                这里展示积分读模型聚合后的实际消耗、运行中预估和建议冻结，冻结、释放与结算事件会同步反映到账本视图。
              </Typography>
              <Grid container spacing={2} sx={{ mt: 0.5 }}>
                <Grid item xs={12} sm={6}>
                  <MetricCard
                    title="已结算积分"
                    value={formatAccountMetric(taskBillingOverview?.actual_spend_points ?? 0)}
                    helper={`对应金额 ${formatCurrency(taskBillingOverview?.actual_spend_yuan ?? 0)}`}
                    color="#16a34a"
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <MetricCard
                    title="运行中预估"
                    value={formatAccountMetric(taskBillingOverview?.estimated_running_spend_points ?? 0)}
                    helper={`预计金额 ${formatCurrency(taskBillingOverview?.estimated_running_spend_yuan ?? 0)}`}
                    color="#d97706"
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <MetricCard
                    title="建议冻结"
                    value={formatAccountMetric(taskBillingOverview?.suggested_frozen_points ?? 0)}
                    helper="按当前用户计价与冻结缓冲推导。"
                    color="#ea580c"
                  />
                </Grid>
                <Grid item xs={12} sm={6}>
                  <MetricCard
                    title="任务条目"
                    value={taskBillingItems.length}
                    helper="含已结算、预估中与待计价任务。"
                    color="#0f766e"
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
            任务计费明细
          </Typography>
          {taskBillingItems.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              暂无可展示的任务计费条目。后续当实际消耗或预估读模型产出后，会自动汇总到这里。
            </Alert>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {taskBillingItems.map((item) => (
                <Box key={item.key} sx={{ p: 2, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                        <Chip size="small" variant="outlined" label={item.module_label} />
                        <Chip size="small" color={item.pricingStatusMeta.color} label={item.pricingStatusMeta.label} />
                        <Chip size="small" variant="outlined" label={item.task_status === 'completed' ? '任务完成' : '任务运行中'} />
                      </Stack>
                      <Typography sx={{ mt: 1, fontWeight: 600 }}>{item.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {item.summary}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                        更新时间：{formatDateTime(item.occurredAt)}
                      </Typography>
                    </Box>
                    <Stack spacing={1} alignItems={{ xs: 'flex-start', sm: 'flex-end' }}>
                      {item.actual_points != null ? (
                        <Chip size="small" color="success" variant="outlined" label={`实际 ${formatAccountMetric(item.actual_points)} 积分`} />
                      ) : null}
                      {item.estimated_points != null ? (
                        <Chip size="small" color="warning" variant="outlined" label={`预估 ${formatAccountMetric(item.estimated_points)} 积分`} />
                      ) : null}
                      {item.suggested_frozen_points != null ? (
                        <Chip size="small" color="warning" label={`建议冻结 ${formatAccountMetric(item.suggested_frozen_points)} 积分`} />
                      ) : null}
                      {item.actionPath ? (
                        <Button size="small" variant="outlined" onClick={() => navigate(item.actionPath || USER_CENTER_POINTS_PATH)}>
                          {item.actionLabel || '查看来源'}
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
                已接入权益
              </Typography>
              {connectedBenefitItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  当前还没有已正式接入积分账户的权益项。
                </Typography>
              ) : (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {connectedBenefitItems.map((item) => (
                    <Box key={item.key} sx={{ p: 2, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2.5 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2}>
                        <Typography sx={{ fontWeight: 600 }}>{item.label}</Typography>
                        <Chip size="small" color="success" label="已接入" />
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
                规划中的权益
              </Typography>
              {plannedBenefitItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  当前没有新增的规划权益项。
                </Typography>
              ) : (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {plannedBenefitItems.map((item) => (
                    <Box key={item.key} sx={{ p: 2, border: '1px dashed rgba(15, 23, 42, 0.16)', borderRadius: 2.5 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2}>
                        <Typography sx={{ fontWeight: 600 }}>{item.label}</Typography>
                        <Chip size="small" color="warning" variant="outlined" label="规划中" />
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
            已接入账本
          </Typography>
          {audiobookBillingEntries.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              暂无已接入的真实金额消费记录。当前有声书 TTS 成本链路已打通，产生实际成本后会自动显示在这里。
            </Alert>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {audiobookBillingEntries.map((entry) => (
                <Box key={entry.key} sx={{ p: 2, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2.5 }}>
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
                          {entry.actionLabel || '查看来源'}
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
            待接入账本信号
          </Typography>
          {pendingLedgerSignals.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              当前没有待接入的账本信号。
            </Typography>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {pendingLedgerSignals.map((signal) => (
                <Box key={signal.key} sx={{ p: 2, border: '1px dashed rgba(15, 23, 42, 0.16)', borderRadius: 2.5 }}>
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
                        {signal.actionLabel || '查看来源'}
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
              积分账户概览
            </Typography>
            <Chip size="small" color={pointsAccountStatusMeta.color} label={pointsAccountStatusMeta.label} />
          </Stack>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
            {pointsAccountStatusMeta.description}
          </Typography>

          <Grid container spacing={2} sx={{ mt: 0.5 }}>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard
                title="积分余额"
                value={formatAccountMetric(pointsAccountBalance)}
                helper="后续承接积分发放、抵扣与权益消费。"
                color="#2563eb"
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard
                title="冻结中"
                value={formatAccountMetric(pointsAccountFrozen)}
                helper="预留给结算中或待确认积分。"
                color="#f97316"
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard
                title="即将过期"
                value={formatAccountMetric(pointsAccountExpiringSoon)}
                helper="后续可补充到期提醒能力。"
                color="#dc2626"
              />
            </Grid>
            <Grid item xs={12} sm={6} md={3}>
              <MetricCard
                title="账本来源"
                value={`${connectedLedgerSourceCount} / ${pendingLedgerSourceCount}`}
                helper="前者为已接入，后者为待接入。"
                color="#0f766e"
              />
            </Grid>
          </Grid>
        </CardContent>
      </Card>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <StarsOutlinedIcon color="primary" />
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  已接入概览
                </Typography>
              </Stack>
              <Stack spacing={1.25} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  项目数：{pointsConnectedOverview?.project_count ?? projects.length}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  用户资产数：{pointsConnectedOverview?.user_asset_count ?? userAssets.length}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  有声书项目数：{pointsConnectedOverview?.audiobook_project_count ?? overviewMetrics.audiobookProjects}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  有声书累计成本：{formatCurrency(totalAudiobookCost)}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  短剧运行次数：{totalDreamweaverRuns}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                当前积分规则
              </Typography>
              {pointsRules ? (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                    <Chip
                      size="small"
                      color={pointsRules.source === 'admin_log' ? 'primary' : 'default'}
                      label={getPointsRuleSourceLabel(pointsRules.source)}
                    />
                    <Chip
                      size="small"
                      variant="outlined"
                      label={pointsRules.updated_at ? `最近更新：${formatDateTime(pointsRules.updated_at)}` : '尚未人工调整'}
                    />
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    这里展示当前积分读模型实际采用的奖励、冻结和过期规则。
                  </Typography>
                  <Box sx={{ display: 'grid', gap: 1.25, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
                    {pointsRuleSummaryItems.map((item) => (
                      <Box
                        key={item.label}
                        sx={{ p: 1.5, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2 }}
                      >
                        <Typography variant="caption" color="text.secondary">
                          {item.label}
                        </Typography>
                        <Typography sx={{ mt: 0.5, fontWeight: 600 }}>{item.value}</Typography>
                      </Box>
                    ))}
                  </Box>
                  <Typography variant="caption" color="text.secondary">
                    最近操作人：{pointsRules.updated_by_username || '系统默认'}
                  </Typography>
                </Stack>
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                  暂无可展示的积分规则快照。
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                已接入权益
              </Typography>
              {connectedBenefitItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  当前还没有已正式接入积分账户的权益项。
                </Typography>
              ) : (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {connectedBenefitItems.map((item) => (
                    <Box key={item.key} sx={{ p: 2, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2.5 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2}>
                        <Typography sx={{ fontWeight: 600 }}>{item.label}</Typography>
                        <Chip size="small" color="success" label="已接入" />
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
                规划中的权益
              </Typography>
              {plannedBenefitItems.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                  当前没有新增的规划权益项。
                </Typography>
              ) : (
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  {plannedBenefitItems.map((item) => (
                    <Box key={item.key} sx={{ p: 2, border: '1px dashed rgba(15, 23, 42, 0.16)', borderRadius: 2.5 }}>
                      <Stack direction="row" justifyContent="space-between" spacing={2}>
                        <Typography sx={{ fontWeight: 600 }}>{item.label}</Typography>
                        <Chip size="small" color="warning" variant="outlined" label="规划中" />
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
              积分明细
            </Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
              <Chip size="small" color="success" variant="outlined" label={`生效中 ${activePointsEntryCount}`} />
              <Chip size="small" color="warning" variant="outlined" label={`冻结中 ${frozenPointsEntryCount}`} />
              <Chip size="small" variant="outlined" label={`已过期 ${expiredPointsEntryCount}`} />
            </Stack>
          </Stack>
          {pointsEntries.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              暂无可展示的积分明细。后续当真实奖励、扣减或冻结事件产生后，会自动汇总到这里。
            </Alert>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {pointsEntries.map((entry) => (
                <Box key={entry.key} sx={{ p: 2, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1 }}>
                        <Chip size="small" variant="outlined" label={entry.source_label} />
                        <Chip size="small" color={entry.directionMeta.color} label={entry.directionMeta.label} />
                        <Chip
                          size="small"
                          color={entry.statusMeta.color}
                          variant={entry.status === 'active' ? 'filled' : 'outlined'}
                          label={entry.statusMeta.label}
                        />
                      </Stack>
                      <Typography sx={{ mt: 1, fontWeight: 600 }}>{entry.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {entry.summary}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
                        发生时间：{formatDateTime(entry.occurredAt)}
                      </Typography>
                      {entry.expiresAt ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          到期时间：{formatDateTime(entry.expiresAt)}
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
                          {entry.actionLabel || '查看来源'}
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
            已接入账本
          </Typography>
          {audiobookBillingEntries.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              暂无已接入的真实金额消费记录。当前有声书 TTS 成本链路已打通，产生实际成本后会自动显示在这里。
            </Alert>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {audiobookBillingEntries.map((entry) => (
                <Box key={entry.key} sx={{ p: 2, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2.5 }}>
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
                          {entry.actionLabel || '查看来源'}
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
            待接入账本信号
          </Typography>
          {pendingLedgerSignals.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
              当前没有待接入的账本信号。
            </Typography>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {pendingLedgerSignals.map((signal) => (
                <Box key={signal.key} sx={{ p: 2, border: '1px dashed rgba(15, 23, 42, 0.16)', borderRadius: 2.5 }}>
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
                        {signal.actionLabel || '查看来源'}
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
        短剧生成内容的清理仍然保留在短剧模块内执行，用户中心当前只统一聚合小说章节与有声书项目回收站。
      </Alert>

      <Card variant="outlined" sx={{ borderRadius: 3 }}>
        <CardContent>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            已删除章节
          </Typography>
          {deletedChapters.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
              暂无已删除章节记录。
            </Typography>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {deletedChapters.map((chapter) => (
                <Box key={chapter.id} sx={{ p: 2, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography sx={{ fontWeight: 600 }}>{chapter.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        项目：{chapter.project_name || `项目 #${chapter.project_id}`} · 字数：{chapter.word_count || 0} · 删除时间：{formatDateTime(chapter.deleted_at)}
                      </Typography>
                    </Box>
                    <Button variant="contained" onClick={() => void handleRestoreChapter(chapter.id)} disabled={restoringKey === `chapter-${chapter.id}`}>
                      {restoringKey === `chapter-${chapter.id}` ? '恢复中...' : '恢复章节'}
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
            已删除有声书项目
          </Typography>
          {deletedAudiobookProjects.length === 0 ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
              暂无已删除有声书项目记录。
            </Typography>
          ) : (
            <Stack spacing={1.5} sx={{ mt: 2 }}>
              {deletedAudiobookProjects.map((item) => (
                <Box key={item.id} sx={{ p: 2, border: '1px solid rgba(15, 23, 42, 0.08)', borderRadius: 2.5 }}>
                  <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Typography sx={{ fontWeight: 600 }}>{item.project_title || `有声书项目 #${item.id}`}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        删除时间：{formatDateTime(item.deleted_at)} · 影响章节：{item.affected_chapters ?? 0} · 状态：{item.status || '未知'}
                      </Typography>
                    </Box>
                    <Button variant="contained" onClick={() => void handleRestoreAudiobookProject(item.id)} disabled={restoringKey === `audiobook-${item.id}`}>
                      {restoringKey === `audiobook-${item.id}` ? '恢复中...' : '恢复有声书项目'}
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
                  账户信息
                </Typography>
              </Stack>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    用户名
                  </Typography>
                  <Typography>{user?.username || '暂无'}</Typography>
                </Box>
                <Divider />
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    邮箱
                  </Typography>
                  <Typography>{user?.email || '暂无'}</Typography>
                </Box>
                <Divider />
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    显示名称
                  </Typography>
                  <Typography>{user?.full_name || '暂无'}</Typography>
                </Box>
                <Divider />
                <Box>
                  <Typography variant="caption" color="text.secondary">
                    角色
                  </Typography>
                  <Typography>{roleNames.join(' / ') || '未配置角色'}</Typography>
                </Box>
              </Stack>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={7}>
          <Card variant="outlined" sx={{ borderRadius: 3 }}>
            <CardContent>
              <Typography variant="h6" sx={{ fontWeight: 700 }}>
                修改密码
              </Typography>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                <TextField
                  fullWidth
                  label="当前密码"
                  type="password"
                  value={passwordData.old_password}
                  onChange={(event) => setPasswordData((prev) => ({ ...prev, old_password: event.target.value }))}
                />
                <TextField
                  fullWidth
                  label="新密码"
                  type="password"
                  value={passwordData.new_password}
                  onChange={(event) => setPasswordData((prev) => ({ ...prev, new_password: event.target.value }))}
                />
                <TextField
                  fullWidth
                  label="确认新密码"
                  type="password"
                  value={passwordData.confirm_password}
                  onChange={(event) => setPasswordData((prev) => ({ ...prev, confirm_password: event.target.value }))}
                />
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                  <Button
                    variant="contained"
                    startIcon={passwordSubmitting ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
                    onClick={() => void handleChangePassword()}
                    disabled={passwordSubmitting}
                  >
                    {passwordSubmitting ? '提交中...' : '更新密码'}
                  </Button>
                  <Button variant="outlined" onClick={() => navigate('/home')}>
                    返回创作中心
                  </Button>
                </Stack>
              </Stack>
            </CardContent>
          </Card>

          <Card variant="outlined" sx={{ mt: 2, borderRadius: 3 }}>
            <CardContent>
              <Stack direction="row" spacing={1} alignItems="center">
                <LogoutIcon color="error" />
                <Typography variant="h6" sx={{ fontWeight: 700 }}>
                  登录会话与退出
                </Typography>
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
                退出登录已经收纳为用户中心下的账户安全能力，不再作为首页独立主入口。后续如果接入设备管理与风控提醒，也会继续放在这里。
              </Typography>
              <Button variant="outlined" color="error" sx={{ mt: 2 }} onClick={handleLogout}>
                安全退出登录
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
        background: 'linear-gradient(180deg, #eff6ff 0%, #f8fafc 100%)',
        py: { xs: 2, md: 4 },
      }}
    >
      <Container maxWidth="lg">
        <Paper
          elevation={0}
          sx={{
            p: { xs: 2, md: 3 },
            borderRadius: 4,
            color: 'white',
            background: 'linear-gradient(135deg, #0f172a 0%, #1d4ed8 58%, #0ea5e9 100%)',
            boxShadow: '0 24px 48px rgba(37, 99, 235, 0.18)',
          }}
        >
          <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={3}>
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} alignItems={{ xs: 'flex-start', sm: 'center' }}>
              <Avatar
                src={user?.avatar_url || undefined}
                sx={{ width: 72, height: 72, fontSize: '1.5rem', fontWeight: 700, bgcolor: 'rgba(255,255,255,0.18)' }}
              >
                {userAvatarFallback}
              </Avatar>
              <Box>
                <Typography variant="overline" sx={{ letterSpacing: '0.18em', opacity: 0.82 }}>
                  User Center
                </Typography>
                <Typography variant="h4" sx={{ fontWeight: 800 }}>
                  用户中心
                </Typography>
                <Typography variant="h6" sx={{ mt: 0.5, fontWeight: 600 }}>
                  {userDisplayName}
                </Typography>
                <Typography variant="body2" sx={{ opacity: 0.86, mt: 0.5 }}>
                  {userIdentity}
                </Typography>
                <Stack direction="row" spacing={1} sx={{ mt: 1.5, flexWrap: 'wrap', rowGap: 1 }}>
                  <Chip size="small" label={hasAdminRole ? '管理员账号' : '创作者账号'} sx={{ color: 'white', bgcolor: 'rgba(255,255,255,0.14)' }} />
                  {roleNames.length > 0 ? (
                    <Chip size="small" label={roleNames.join(' / ')} sx={{ color: 'white', bgcolor: 'rgba(255,255,255,0.14)' }} />
                  ) : null}
                  <Chip size="small" label="积分账本持续扩展" sx={{ color: 'white', bgcolor: 'rgba(255,255,255,0.14)' }} />
                </Stack>
              </Box>
            </Stack>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25} alignItems={{ xs: 'stretch', sm: 'flex-start' }}>
              <Button startIcon={<ArrowBackIcon />} onClick={() => navigate('/home')} sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.35)' }} variant="outlined">
                返回创作中心
              </Button>
              {hasAdminRole ? (
                <Button
                  startIcon={<DashboardCustomizeOutlinedIcon />}
                  onClick={() => navigate('/admin')}
                  sx={{ color: 'white', borderColor: 'rgba(255,255,255,0.35)' }}
                  variant="outlined"
                >
                  控制台
                </Button>
              ) : null}
              <Button
                startIcon={refreshing ? <CircularProgress size={16} color="inherit" /> : <RefreshIcon />}
                onClick={() => {
                  void loadUserCenterData(true)
                  void loadUserAssets(true)
                }}
                disabled={refreshing}
                variant="contained"
                sx={{ bgcolor: 'rgba(255,255,255,0.16)', boxShadow: 'none' }}
              >
                {refreshing ? '刷新中...' : '刷新用户中心'}
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
            sx={{ px: 1.5, pt: 1.5, borderBottom: '1px solid rgba(15, 23, 42, 0.08)' }}
          >
            {tabs.map((tab) => (
              <Tab key={tab.value} value={tab.value} label={tab.label} />
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
          </Box>
        </Paper>
      </Container>

      <Dialog open={assetEditorOpen} onClose={handleCloseAssetEditor} fullWidth maxWidth="sm">
        <DialogTitle>编辑资产信息</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2} sx={{ pt: 1 }}>
            <TextField
              fullWidth
              required
              label="资产标题"
              value={assetEditorData.title}
              onChange={(event) => setAssetEditorData((prev) => ({ ...prev, title: event.target.value }))}
              disabled={assetEditorSubmitting}
            />
            <TextField
              fullWidth
              multiline
              minRows={3}
              maxRows={6}
              label="补充说明"
              value={assetEditorData.description}
              onChange={(event) => setAssetEditorData((prev) => ({ ...prev, description: event.target.value }))}
              disabled={assetEditorSubmitting}
            />
            <TextField
              fullWidth
              multiline
              minRows={2}
              maxRows={4}
              label="标签"
              placeholder="可使用逗号、中文逗号、顿号或换行分隔"
              value={assetEditorData.tagsText}
              onChange={(event) => setAssetEditorData((prev) => ({ ...prev, tagsText: event.target.value }))}
              helperText="最多保留 12 个标签，每个标签最多 30 个字符。"
              disabled={assetEditorSubmitting}
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, py: 2 }}>
          <Button onClick={handleCloseAssetEditor} disabled={assetEditorSubmitting}>
            取消
          </Button>
          <Button
            variant="contained"
            onClick={() => void handleSaveAssetEditor()}
            disabled={assetEditorSubmitting || !editingAsset}
            startIcon={assetEditorSubmitting ? <CircularProgress size={16} color="inherit" /> : <SaveIcon />}
          >
            {assetEditorSubmitting ? '保存中...' : '保存'}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
