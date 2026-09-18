import { useEffect, useState } from 'react'
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
  IconButton,
  InputAdornment,
  InputLabel,
  MenuItem,
  Paper,
  Select,
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
import BlockIcon from '@mui/icons-material/Block'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import SearchIcon from '@mui/icons-material/Search'
import StarsOutlinedIcon from '@mui/icons-material/StarsOutlined'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { useFormats } from '@/i18n'
import { apiClient } from '@/services/api'

interface User {
  id: number
  username: string
  email: string | null
  phone: string | null
  full_name: string | null
  is_active: boolean
  created_at: string
  roles: Array<{ id: number; code: string; name: string }>
}

interface UserListResponse {
  total: number
  page: number
  page_size: number
  total_pages: number
  items: User[]
}

interface Role {
  id: number
  code: string
  name: string
}

interface UserPointsAdjustment {
  id: number
  target_user_id: number
  operator_user_id: number
  operator_username: string
  delta: number
  reason: string
  adjustment_type: string
  expires_at?: string | null
  created_at: string
}

interface UserPointsAdjustmentListResponse {
  items: UserPointsAdjustment[]
}

interface UserPointsAccountEntry {
  key: string
  source_key: string
  source_label: string
  title: string
  summary: string
  amount: number
  direction: 'income' | 'expense' | 'hold'
  status: 'active' | 'expired' | 'frozen'
  occurred_at?: string | null
  expires_at?: string | null
  action_path?: string | null
  action_label?: string | null
}

interface UserPointsAccountOverview {
  target_user_id: number
  balance?: number | null
  frozen?: number | null
  available?: number | null
  expiring_soon?: number | null
  status: 'planned' | 'partial'
  connected_source_count: number
  entries: UserPointsAccountEntry[]
}

interface UserPointsBillingOperatingSnapshot {
  module_key: string
  module_label: string
  provider_key?: string | null
  user_basis_yuan: number
  user_billed_yuan: number
  supplier_list_price_yuan: number
  supplier_discount_rate: number
  supplier_discount_rate_source: string
  supplier_discounted_cost_yuan: number
  supplier_discount_yuan: number
  captured_discount_yuan: number
  shared_discount_yuan: number
  policy_target_user_billed_yuan: number
  policy_alignment_gap_yuan: number
  platform_gross_profit_yuan: number
  platform_margin_rate?: number | null
  margin_status: 'healthy' | 'warning' | 'negative'
  negative_margin_blocked: boolean
}

interface UserPointsBillingEvent {
  id: number
  target_user_id: number
  operator_user_id: number
  operator_username: string
  operation_type: string
  module_key: string
  module_label: string
  event_kind: 'freeze' | 'settle' | 'release'
  event_label: string
  billing_key: string
  title: string
  summary: string
  amount_points: number
  amount_yuan?: number | null
  pricing_status?: string | null
  task_status?: string | null
  project_id?: number | null
  audiobook_project_id?: number | null
  run_id?: string | null
  stage?: string | null
  action_path?: string | null
  action_label?: string | null
  created_at: string
  operating_snapshot?: UserPointsBillingOperatingSnapshot | null
}

interface UserPointsBillingEventListResponse {
  items: UserPointsBillingEvent[]
}

function formatAdjustmentType(type: string, t?: TFunction) {
  if (type === 'manual_grant') return t ? t('admin.users.adjustmentType.manualGrant') : '手工补发'
  if (type === 'recharge') return t ? t('admin.users.adjustmentType.recharge') : '充值入账'
  if (type === 'manual_deduction') return t ? t('admin.users.adjustmentType.manualDeduction') : '人工扣减'
  if (type === 'compensation') return t ? t('admin.users.adjustmentType.compensation') : '补偿调整'
  if (t) return type || t('admin.users.adjustmentType.unknown')
  return type || '未分类'
}

function formatBillingEventKind(kind: UserPointsBillingEvent['event_kind'], t?: TFunction) {
  if (kind === 'freeze') return t ? t('admin.users.eventKind.freeze') : '正式冻结'
  if (kind === 'settle') return t ? t('admin.users.eventKind.settle') : '正式结算'
  if (kind === 'release') return t ? t('admin.users.eventKind.release') : '冻结释放'
  return kind
}

function formatPricingStatus(status?: string | null, t?: TFunction) {
  if (status === 'actual') return t ? t('admin.pointsBilling.status.actual') : '实际计费'
  if (status === 'estimated') return t ? t('admin.pointsBilling.status.estimated') : '预估计费'
  if (status === 'pending') return t ? t('admin.pointsBilling.status.pending') : '待计费'
  if (t) return status || t('admin.users.statusNotMarked')
  return status || '未标记'
}

function formatTaskStatus(status?: string | null, t?: TFunction) {
  if (status === 'running') return t ? t('admin.pointsBilling.status.running') : '运行中'
  if (status === 'completed') return t ? t('admin.pointsBilling.status.completed') : '已完成'
  if (t) return status || t('admin.users.statusNotMarked')
  return status || '未标记'
}

function getBillingEventColor(kind: UserPointsBillingEvent['event_kind']): 'warning' | 'primary' | 'success' {
  if (kind === 'freeze') return 'warning'
  if (kind === 'release') return 'success'
  return 'primary'
}

function getMarginStatusColor(status: UserPointsBillingOperatingSnapshot['margin_status']): 'success' | 'warning' | 'error' {
  if (status === 'negative') return 'error'
  if (status === 'warning') return 'warning'
  return 'success'
}

function formatMarginStatus(status: UserPointsBillingOperatingSnapshot['margin_status'], t?: TFunction) {
  if (status === 'negative') return t ? t('admin.pointsBilling.status.negative') : '负毛利'
  if (status === 'warning') return t ? t('admin.pointsBilling.status.warning') : '低毛利预警'
  return t ? t('admin.pointsBilling.status.healthy') : '毛利健康'
}

function formatCurrency(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return `CNY ${value.toFixed(2)}`
}

function formatPoints(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return value.toFixed(2)
}

function formatPointsEntryStatus(status: UserPointsAccountEntry['status'], t?: TFunction) {
  if (status === 'expired') return t ? t('admin.users.entryStatus.expired') : '已过期'
  if (status === 'frozen') return t ? t('admin.users.entryStatus.frozen') : '冻结中'
  return t ? t('admin.users.entryStatus.active') : '有效'
}

function getPointsEntryColor(direction: UserPointsAccountEntry['direction']): 'success' | 'warning' | 'primary' {
  if (direction === 'income') return 'success'
  if (direction === 'expense') return 'warning'
  return 'primary'
}

function formatPercent(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return '-'
  }
  return `${(value * 100).toFixed(value === 1 ? 0 : 2)}%`
}

export default function AdminUsersPage() {
  const { t } = useTranslation()
  // 只解构用得上的两个：本文件另有 formatCurrency / formatPercent 等本地 helper，
  // 它们的展示约定（"CNY 12.34"）与 useFormats 的同名函数不同，不能被遮蔽。
  // 积分调整与计费事件属账务流水，保留到秒才排得出同一分钟内的先后。
  const { formatDate, formatDateTimeWithSeconds } = useFormats()
  const [users, setUsers] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(10)
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')

  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [pointsDialogOpen, setPointsDialogOpen] = useState(false)
  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [selectedRoleIds, setSelectedRoleIds] = useState<number[]>([])
  const [pointsSubmitting, setPointsSubmitting] = useState(false)
  const [pointsLoading, setPointsLoading] = useState(false)
  const [pointsAccount, setPointsAccount] = useState<UserPointsAccountOverview | null>(null)
  const [pointsAdjustments, setPointsAdjustments] = useState<UserPointsAdjustment[]>([])
  const [pointsBillingEvents, setPointsBillingEvents] = useState<UserPointsBillingEvent[]>([])
  const [pointsForm, setPointsForm] = useState({
    delta: '',
    reason: '',
    adjustmentType: 'manual_grant',
    expiresAt: '',
  })

  useEffect(() => {
    void fetchUsers()
  }, [page, rowsPerPage, search, statusFilter])

  useEffect(() => {
    void fetchRoles()
  }, [])

  const fetchUsers = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams({
        page: (page + 1).toString(),
        page_size: rowsPerPage.toString(),
      })
      if (search.trim()) params.append('search', search.trim())
      if (statusFilter) params.append('is_active', statusFilter)

      const response = await apiClient.get(`/api/v1/admin/users?${params}`)
      const data: UserListResponse = response.data
      setUsers(Array.isArray(data.items) ? data.items : [])
      setTotal(Number(data.total) || 0)
      setError(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || t('admin.users.messages.fetchUsersFailed'))
    } finally {
      setLoading(false)
    }
  }

  const fetchRoles = async () => {
    try {
      const response = await apiClient.get('/api/v1/admin/roles')
      setRoles(Array.isArray(response.data?.items) ? response.data.items : [])
    } catch {
      // 获取角色列表失败
    }
  }

  const fetchUserPointsDialogData = async (userId: number) => {
    try {
      setPointsLoading(true)

      const [accountResult, adjustmentsResult, billingEventsResult] = await Promise.allSettled([
        apiClient.get(`/api/v1/admin/users/${userId}/points-account`),
        apiClient.get(`/api/v1/admin/users/${userId}/points-adjustments?limit=10`),
        apiClient.get(`/api/v1/admin/users/${userId}/points-billing-events?limit=10`),
      ])

      let nextError: string | null = null

      if (accountResult.status === 'fulfilled') {
        const data: UserPointsAccountOverview = accountResult.value.data
        setPointsAccount(data && typeof data === 'object' ? data : null)
      } else {
        setPointsAccount(null)
        nextError = t('admin.users.messages.fetchBalanceFailed')
      }

      if (adjustmentsResult.status === 'fulfilled') {
        const data: UserPointsAdjustmentListResponse = adjustmentsResult.value.data
        setPointsAdjustments(Array.isArray(data.items) ? data.items : [])
      } else {
        setPointsAdjustments([])
        nextError = t('admin.users.messages.fetchAdjustmentsFailed')
      }

      if (billingEventsResult.status === 'fulfilled') {
        const data: UserPointsBillingEventListResponse = billingEventsResult.value.data
        setPointsBillingEvents(Array.isArray(data.items) ? data.items : [])
      } else {
        setPointsBillingEvents([])
        nextError = nextError || t('admin.users.messages.fetchBillingFailed')
      }

      if (nextError) {
        setError(nextError)
      } else {
        setError(null)
      }
    } finally {
      setPointsLoading(false)
    }
  }

  const handleToggleStatus = async (user: User) => {
    try {
      await apiClient.patch(`/api/v1/admin/users/${user.id}/status`, {
        is_active: !user.is_active,
      })
      setSuccessMessage(
        user.is_active
          ? t('admin.users.messages.userDisabled', { name: user.username })
          : t('admin.users.messages.userEnabled', { name: user.username }),
      )
      await fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('admin.users.messages.updateStatusFailed'))
    }
  }

  const handleDelete = async () => {
    if (!selectedUser) return
    try {
      await apiClient.delete(`/api/v1/admin/users/${selectedUser.id}`)
      setDeleteDialogOpen(false)
      setSuccessMessage(t('admin.users.messages.userDeleted', { name: selectedUser.username }))
      setSelectedUser(null)
      await fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('admin.users.messages.deleteFailed'))
    }
  }

  const handleEditRoles = async () => {
    if (!selectedUser) return
    try {
      await apiClient.post(`/api/v1/admin/users/${selectedUser.id}/roles`, {
        role_ids: selectedRoleIds,
      })
      setEditDialogOpen(false)
      setSuccessMessage(t('admin.users.messages.rolesUpdated', { name: selectedUser.username }))
      setSelectedUser(null)
      setSelectedRoleIds([])
      await fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('admin.users.messages.assignRolesFailed'))
    }
  }

  const handleSubmitPointsAdjustment = async () => {
    if (!selectedUser) return

    const delta = Number(pointsForm.delta)
    if (!Number.isFinite(delta) || delta === 0) {
      setError(t('admin.users.messages.zeroDelta'))
      return
    }
    if (!pointsForm.reason.trim()) {
      setError(t('admin.users.messages.missingReason'))
      return
    }

    try {
      setPointsSubmitting(true)
      await apiClient.post(`/api/v1/admin/users/${selectedUser.id}/points-adjustments`, {
        delta,
        reason: pointsForm.reason.trim(),
        adjustment_type: pointsForm.adjustmentType,
        expires_at: pointsForm.expiresAt ? new Date(pointsForm.expiresAt).toISOString() : null,
      })
      setSuccessMessage(t('admin.users.messages.adjustmentSubmitted', { name: selectedUser.username }))
      setPointsForm({
        delta: '',
        reason: '',
        adjustmentType: 'manual_grant',
        expiresAt: '',
      })
      await fetchUserPointsDialogData(selectedUser.id)
    } catch (err: any) {
      setError(err.response?.data?.detail || t('admin.users.messages.submitFailed'))
    } finally {
      setPointsSubmitting(false)
    }
  }

  const openEditDialog = (user: User) => {
    setSelectedUser(user)
    setSelectedRoleIds(user.roles.map((role) => role.id))
    setEditDialogOpen(true)
  }

  const openDeleteDialog = (user: User) => {
    setSelectedUser(user)
    setDeleteDialogOpen(true)
  }

  const openPointsDialog = (user: User) => {
    setSelectedUser(user)
    setPointsDialogOpen(true)
    setPointsAdjustments([])
    setPointsAccount(null)
    setPointsBillingEvents([])
    setPointsForm({
      delta: '',
      reason: '',
      adjustmentType: 'manual_grant',
      expiresAt: '',
    })
    void fetchUserPointsDialogData(user.id)
  }

  if (loading && users.length === 0) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
        {t('admin.users.title')}
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}

      {successMessage ? (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccessMessage(null)}>
          {successMessage}
        </Alert>
      ) : null}

      <Card>
        <CardContent>
          <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
            <TextField
              placeholder={t('admin.users.searchPlaceholder')}
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              size="small"
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon />
                  </InputAdornment>
                ),
              }}
              sx={{ width: { xs: '100%', sm: 320 } }}
            />
            <FormControl size="small" sx={{ width: 160 }}>
              <InputLabel>{t('admin.users.status')}</InputLabel>
              <Select value={statusFilter} label={t('admin.users.status')} onChange={(event) => setStatusFilter(event.target.value)}>
                <MenuItem value="">{t('admin.users.all')}</MenuItem>
                <MenuItem value="true">{t('admin.users.enabled')}</MenuItem>
                <MenuItem value="false">{t('admin.users.disabled')}</MenuItem>
              </Select>
            </FormControl>
          </Box>

          <TableContainer component={Paper} variant="outlined">
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>{t('admin.users.colId')}</TableCell>
                  <TableCell>{t('admin.users.colUsername')}</TableCell>
                  <TableCell>{t('admin.users.colEmail')}</TableCell>
                  <TableCell>{t('admin.users.colPhone')}</TableCell>
                  <TableCell>{t('admin.users.colRoles')}</TableCell>
                  <TableCell>{t('admin.users.colStatus')}</TableCell>
                  <TableCell>{t('admin.users.colRegisteredAt')}</TableCell>
                  <TableCell>{t('admin.users.colActions')}</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>{user.id}</TableCell>
                    <TableCell>{user.username}</TableCell>
                    <TableCell>{user.email || '-'}</TableCell>
                    <TableCell>{user.phone || '-'}</TableCell>
                    <TableCell>
                      {user.roles.map((role) => (
                        <Chip
                          key={role.id}
                          label={role.name}
                          size="small"
                          sx={{ mr: 0.5, mb: 0.5 }}
                          color={role.code === 'super_admin' ? 'error' : role.code === 'admin' ? 'primary' : 'default'}
                        />
                      ))}
                    </TableCell>
                    <TableCell>
                      <Chip
                        label={user.is_active ? t('admin.users.enabled') : t('admin.users.disabled')}
                        size="small"
                        color={user.is_active ? 'success' : 'error'}
                      />
                    </TableCell>
                    <TableCell>{formatDate(user.created_at)}</TableCell>
                    <TableCell>
                      <IconButton size="small" onClick={() => openEditDialog(user)} title={t('admin.users.editRolesTitle')}>
                        <EditIcon />
                      </IconButton>
                      <IconButton size="small" onClick={() => openPointsDialog(user)} title={t('admin.users.adjustPointsTitle')}>
                        <StarsOutlinedIcon />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={() => handleToggleStatus(user)}
                        title={user.is_active ? t('admin.users.disableUser') : t('admin.users.enableUser')}
                      >
                        {user.is_active ? <BlockIcon /> : <CheckCircleIcon />}
                      </IconButton>
                      <IconButton size="small" onClick={() => openDeleteDialog(user)} title={t('admin.users.deleteUserTitle')}>
                        <DeleteIcon />
                      </IconButton>
                    </TableCell>
                  </TableRow>
                ))}
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
            labelRowsPerPage={t('admin.users.rowsPerPage')}
            labelDisplayedRows={({ from, to, count }) =>
              t('admin.users.displayedRows', { from, to, count })
            }
          />
        </CardContent>
      </Card>

      <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>{t('admin.users.editDialogTitle')}</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>{t('admin.users.userPrefix', { name: selectedUser?.username })}</Typography>
          <FormControl fullWidth>
            <InputLabel>{t('admin.users.role')}</InputLabel>
            <Select
              multiple
              value={selectedRoleIds}
              onChange={(event) => setSelectedRoleIds(event.target.value as number[])}
              label={t('admin.users.role')}
            >
              {roles.map((role) => (
                <MenuItem key={role.id} value={role.id}>
                  {role.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditDialogOpen(false)}>{t('action.cancel')}</Button>
          <Button onClick={handleEditRoles} variant="contained">
            {t('action.save')}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={pointsDialogOpen} onClose={() => setPointsDialogOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>{t('admin.users.pointsDialogTitle')}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            {t('admin.users.targetUser', { name: selectedUser?.username })}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {t('admin.users.pointsHint')}
          </Typography>

          <Paper variant="outlined" sx={{ mt: 2, p: 2 }}>
            <Box sx={{ display: 'grid', gap: 1.5, gridTemplateColumns: { xs: '1fr 1fr', sm: 'repeat(4, 1fr)' } }}>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('admin.users.balance')}
                </Typography>
                <Typography variant="h6">{formatPoints(pointsAccount?.balance)}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('admin.users.frozen')}
                </Typography>
                <Typography variant="h6">{formatPoints(pointsAccount?.frozen)}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('admin.users.available')}
                </Typography>
                <Typography variant="h6">{formatPoints(pointsAccount?.available)}</Typography>
              </Box>
              <Box>
                <Typography variant="caption" color="text.secondary">
                  {t('admin.users.expiringSoon')}
                </Typography>
                <Typography variant="h6">{formatPoints(pointsAccount?.expiring_soon)}</Typography>
              </Box>
            </Box>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1.5 }}>
              <Chip
                size="small"
                color={pointsAccount?.status === 'partial' ? 'success' : 'default'}
                label={
                  pointsAccount?.status === 'partial' ? t('admin.users.statusPartial') : t('admin.users.statusNoSource')
                }
              />
              <Chip
                size="small"
                variant="outlined"
                label={t('admin.users.sourceCount', { count: pointsAccount?.connected_source_count ?? 0 })}
              />
            </Box>
            {pointsAccount?.entries?.length ? (
              <Box sx={{ mt: 2, display: 'grid', gap: 1 }}>
                {pointsAccount.entries.slice(0, 5).map((entry) => (
                  <Box
                    key={entry.key}
                    sx={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      gap: 1.5,
                      flexWrap: 'wrap',
                      alignItems: 'center',
                    }}
                  >
                    <Box sx={{ minWidth: 0 }}>
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {entry.title}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {entry.source_label} · {formatPointsEntryStatus(entry.status, t)}
                      </Typography>
                    </Box>
                    <Chip
                      size="small"
                      color={getPointsEntryColor(entry.direction)}
                      label={`${entry.direction === 'income' ? '+' : entry.direction === 'expense' ? '-' : ''}${formatPoints(Math.abs(entry.amount))}`}
                    />
                  </Box>
                ))}
              </Box>
            ) : null}
          </Paper>

          <Box sx={{ display: 'grid', gap: 2, mt: 2, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
            <TextField
              label={t('admin.users.adjustValue')}
              value={pointsForm.delta}
              onChange={(event) => setPointsForm((prev) => ({ ...prev, delta: event.target.value }))}
              placeholder={t('admin.users.adjustValuePlaceholder')}
              fullWidth
            />
            <FormControl fullWidth>
              <InputLabel>{t('admin.users.adjustType')}</InputLabel>
              <Select
                value={pointsForm.adjustmentType}
                label={t('admin.users.adjustType')}
                onChange={(event) => setPointsForm((prev) => ({ ...prev, adjustmentType: event.target.value }))}
              >
                <MenuItem value="manual_grant">{t('admin.users.adjustmentType.manualGrant')}</MenuItem>
                <MenuItem value="recharge">{t('admin.users.adjustmentType.recharge')}</MenuItem>
                <MenuItem value="manual_deduction">{t('admin.users.adjustmentType.manualDeduction')}</MenuItem>
                <MenuItem value="compensation">{t('admin.users.adjustmentType.compensation')}</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label={t('admin.users.expiresAt')}
              type="datetime-local"
              value={pointsForm.expiresAt}
              onChange={(event) => setPointsForm((prev) => ({ ...prev, expiresAt: event.target.value }))}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <Box />
          </Box>

          <TextField
            label={t('admin.users.adjustReason')}
            value={pointsForm.reason}
            onChange={(event) => setPointsForm((prev) => ({ ...prev, reason: event.target.value }))}
            placeholder={t('admin.users.adjustReasonPlaceholder')}
            fullWidth
            multiline
            minRows={2}
            sx={{ mt: 2 }}
          />

          <Typography variant="subtitle2" sx={{ mt: 3, fontWeight: 700 }}>
            {t('admin.users.recentAdjustments')}
          </Typography>

          {pointsLoading ? (
            <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
              <CircularProgress size={24} />
            </Box>
          ) : pointsAdjustments.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('admin.users.noAdjustments')}
            </Alert>
          ) : (
            <Box sx={{ mt: 2, display: 'grid', gap: 1.5 }}>
              {pointsAdjustments.map((item) => (
                <Paper key={item.id} variant="outlined" sx={{ p: 2 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
                    <Box>
                      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                        <Chip
                          size="small"
                          color={item.delta >= 0 ? 'success' : 'warning'}
                          label={`${item.delta >= 0 ? '+' : ''}${item.delta}`}
                        />
                        <Chip size="small" variant="outlined" label={formatAdjustmentType(item.adjustment_type, t)} />
                      </Box>
                      <Typography sx={{ mt: 1 }}>{item.reason}</Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                        {t('admin.users.operatorCreatedAt', {
                          name: item.operator_username,
                          time: formatDateTimeWithSeconds(item.created_at),
                        })}
                      </Typography>
                      {item.expires_at ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          {t('admin.users.expiresTime', { time: formatDateTimeWithSeconds(item.expires_at) })}
                        </Typography>
                      ) : null}
                    </Box>
                  </Box>
                </Paper>
              ))}
            </Box>
          )}

          <Typography variant="subtitle2" sx={{ mt: 3, fontWeight: 700 }}>
            {t('admin.users.billingEvents')}
          </Typography>

          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {t('admin.users.billingEventsHint')}
          </Typography>

          {pointsLoading ? null : pointsBillingEvents.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('admin.users.noBillingEvents')}
            </Alert>
          ) : (
            <Box sx={{ mt: 2, display: 'grid', gap: 1.5 }}>
              {pointsBillingEvents.map((item) => (
                <Paper key={item.id} variant="outlined" sx={{ p: 2 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                        <Chip size="small" variant="outlined" label={item.module_label} />
                        <Chip size="small" color={getBillingEventColor(item.event_kind)} label={formatBillingEventKind(item.event_kind, t)} />
                        <Chip size="small" variant="outlined" label={t('admin.users.pointsSuffix', { points: item.amount_points.toFixed(2) })} />
                        {item.amount_yuan != null ? (
                          <Chip size="small" variant="outlined" label={formatCurrency(item.amount_yuan)} />
                        ) : null}
                        {item.pricing_status ? (
                          <Chip size="small" variant="outlined" label={formatPricingStatus(item.pricing_status, t)} />
                        ) : null}
                        {item.task_status ? (
                          <Chip size="small" variant="outlined" label={formatTaskStatus(item.task_status, t)} />
                        ) : null}
                      </Box>

                      <Typography sx={{ mt: 1, fontWeight: 600 }}>{item.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {item.summary}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
                        {t('admin.users.billingKeyLine', {
                          key: item.billing_key,
                          name: item.operator_username,
                          time: formatDateTimeWithSeconds(item.created_at),
                        })}
                      </Typography>

                      {item.project_id || item.audiobook_project_id || item.run_id ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          {t('admin.users.projectId', { id: item.project_id ?? '-' })}
                          {item.audiobook_project_id ? t('admin.users.audiobookProject', { id: item.audiobook_project_id }) : ''}
                          {item.run_id ? t('admin.users.runId', { id: item.run_id }) : ''}
                          {item.stage ? t('admin.users.stagePrefix', { stage: item.stage }) : ''}
                        </Typography>
                      ) : null}

                      {item.action_path ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          {t('admin.users.actionEntry', {
                            label: item.action_label || item.action_path,
                            path: item.action_path,
                          })}
                        </Typography>
                      ) : null}

                      {item.operating_snapshot ? (
                        <Box
                          sx={{
                            mt: 1.5,
                            p: 1.5,
                            border: '1px solid',
                            borderColor: 'divider',
                            borderRadius: 2,
                            bgcolor: 'grey.50',
                          }}
                        >
                          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
                            <Typography variant="subtitle2">{t('admin.users.snapshotTitle')}</Typography>
                            <Chip
                              size="small"
                              color={getMarginStatusColor(item.operating_snapshot.margin_status)}
                              label={formatMarginStatus(item.operating_snapshot.margin_status, t)}
                            />
                          </Box>
                          <Box sx={{ mt: 1, display: 'grid', gap: 0.5 }}>
                            <Typography variant="body2" color="text.secondary">
                              {t('admin.users.userBilledCost', {
                                billed: formatCurrency(item.operating_snapshot.user_billed_yuan),
                                cost: formatCurrency(item.operating_snapshot.supplier_discounted_cost_yuan),
                              })}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {t('admin.users.profitRate', {
                                profit: formatCurrency(item.operating_snapshot.platform_gross_profit_yuan),
                                rate: formatPercent(item.operating_snapshot.platform_margin_rate),
                              })}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {t('admin.users.discountSource', {
                                rate: formatPercent(item.operating_snapshot.supplier_discount_rate),
                                source: item.operating_snapshot.supplier_discount_rate_source,
                              })}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {t('admin.users.discountAlloc', {
                                captured: formatCurrency(item.operating_snapshot.captured_discount_yuan),
                                shared: formatCurrency(item.operating_snapshot.shared_discount_yuan),
                              })}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {t('admin.users.blockStatus', {
                                status: item.operating_snapshot.negative_margin_blocked
                                  ? t('admin.users.blocked')
                                  : t('admin.users.notBlocked'),
                              })}
                            </Typography>
                          </Box>
                        </Box>
                      ) : null}
                    </Box>
                  </Box>
                </Paper>
              ))}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPointsDialogOpen(false)}>{t('action.close')}</Button>
          <Button variant="contained" onClick={() => void handleSubmitPointsAdjustment()} disabled={pointsSubmitting}>
            {pointsSubmitting ? t('admin.users.submitting') : t('admin.users.submitAdjustment')}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>{t('admin.users.confirmDeleteTitle')}</DialogTitle>
        <DialogContent>
          <Typography>{t('admin.users.confirmDeleteBody', { name: selectedUser?.username })}</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>{t('action.cancel')}</Button>
          <Button onClick={handleDelete} variant="contained" color="error">
            {t('admin.common.delete')}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
