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
import { apiClient } from '@/services/api'

interface User {
  id: number
  username: string
  email: string
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

function formatAdjustmentType(type: string) {
  if (type === 'manual_grant') return '手工补发'
  if (type === 'recharge') return '充值入账'
  if (type === 'manual_deduction') return '人工扣减'
  if (type === 'compensation') return '补偿调整'
  return type || '未分类'
}

function formatBillingEventKind(kind: UserPointsBillingEvent['event_kind']) {
  if (kind === 'freeze') return '正式冻结'
  if (kind === 'settle') return '正式结算'
  if (kind === 'release') return '冻结释放'
  return kind
}

function formatPricingStatus(status?: string | null) {
  if (status === 'actual') return '实际计费'
  if (status === 'estimated') return '预估计费'
  if (status === 'pending') return '待计费'
  return status || '未标记'
}

function formatTaskStatus(status?: string | null) {
  if (status === 'running') return '运行中'
  if (status === 'completed') return '已完成'
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

function formatMarginStatus(status: UserPointsBillingOperatingSnapshot['margin_status']) {
  if (status === 'negative') return '负毛利'
  if (status === 'warning') return '低毛利预警'
  return '毛利健康'
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

export default function AdminUsersPage() {
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
      setError(err.response?.data?.detail || '获取用户列表失败')
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

      const [adjustmentsResult, billingEventsResult] = await Promise.allSettled([
        apiClient.get(`/api/v1/admin/users/${userId}/points-adjustments?limit=10`),
        apiClient.get(`/api/v1/admin/users/${userId}/points-billing-events?limit=10`),
      ])

      let nextError: string | null = null

      if (adjustmentsResult.status === 'fulfilled') {
        const data: UserPointsAdjustmentListResponse = adjustmentsResult.value.data
        setPointsAdjustments(Array.isArray(data.items) ? data.items : [])
      } else {
        setPointsAdjustments([])
        nextError = '获取人工积分调整记录失败'
      }

      if (billingEventsResult.status === 'fulfilled') {
        const data: UserPointsBillingEventListResponse = billingEventsResult.value.data
        setPointsBillingEvents(Array.isArray(data.items) ? data.items : [])
      } else {
        setPointsBillingEvents([])
        nextError = nextError || '获取正式计费事件失败'
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
      setSuccessMessage(user.is_active ? `已禁用用户 ${user.username}` : `已启用用户 ${user.username}`)
      await fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || '更新用户状态失败')
    }
  }

  const handleDelete = async () => {
    if (!selectedUser) return
    try {
      await apiClient.delete(`/api/v1/admin/users/${selectedUser.id}`)
      setDeleteDialogOpen(false)
      setSuccessMessage(`已删除用户 ${selectedUser.username}`)
      setSelectedUser(null)
      await fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || '删除用户失败')
    }
  }

  const handleEditRoles = async () => {
    if (!selectedUser) return
    try {
      await apiClient.post(`/api/v1/admin/users/${selectedUser.id}/roles`, {
        role_ids: selectedRoleIds,
      })
      setEditDialogOpen(false)
      setSuccessMessage(`已更新用户 ${selectedUser.username} 的角色`)
      setSelectedUser(null)
      setSelectedRoleIds([])
      await fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || '分配角色失败')
    }
  }

  const handleSubmitPointsAdjustment = async () => {
    if (!selectedUser) return

    const delta = Number(pointsForm.delta)
    if (!Number.isFinite(delta) || delta === 0) {
      setError('积分调整值不能为 0')
      return
    }
    if (!pointsForm.reason.trim()) {
      setError('请填写积分调整原因')
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
      setSuccessMessage(`已为用户 ${selectedUser.username} 提交积分调整`)
      setPointsForm({
        delta: '',
        reason: '',
        adjustmentType: 'manual_grant',
        expiresAt: '',
      })
      await fetchUserPointsDialogData(selectedUser.id)
    } catch (err: any) {
      setError(err.response?.data?.detail || '提交积分调整失败')
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
        用户管理
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
              placeholder="搜索用户名、邮箱、手机号"
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
              <InputLabel>状态</InputLabel>
              <Select value={statusFilter} label="状态" onChange={(event) => setStatusFilter(event.target.value)}>
                <MenuItem value="">全部</MenuItem>
                <MenuItem value="true">已启用</MenuItem>
                <MenuItem value="false">已禁用</MenuItem>
              </Select>
            </FormControl>
          </Box>

          <TableContainer component={Paper} variant="outlined">
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>ID</TableCell>
                  <TableCell>用户名</TableCell>
                  <TableCell>邮箱</TableCell>
                  <TableCell>手机号</TableCell>
                  <TableCell>角色</TableCell>
                  <TableCell>状态</TableCell>
                  <TableCell>注册时间</TableCell>
                  <TableCell>操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {users.map((user) => (
                  <TableRow key={user.id}>
                    <TableCell>{user.id}</TableCell>
                    <TableCell>{user.username}</TableCell>
                    <TableCell>{user.email}</TableCell>
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
                        label={user.is_active ? '已启用' : '已禁用'}
                        size="small"
                        color={user.is_active ? 'success' : 'error'}
                      />
                    </TableCell>
                    <TableCell>{new Date(user.created_at).toLocaleDateString('zh-CN')}</TableCell>
                    <TableCell>
                      <IconButton size="small" onClick={() => openEditDialog(user)} title="编辑角色">
                        <EditIcon />
                      </IconButton>
                      <IconButton size="small" onClick={() => openPointsDialog(user)} title="调整积分">
                        <StarsOutlinedIcon />
                      </IconButton>
                      <IconButton
                        size="small"
                        onClick={() => handleToggleStatus(user)}
                        title={user.is_active ? '禁用用户' : '启用用户'}
                      >
                        {user.is_active ? <BlockIcon /> : <CheckCircleIcon />}
                      </IconButton>
                      <IconButton size="small" onClick={() => openDeleteDialog(user)} title="删除用户">
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
            labelRowsPerPage="每页行数"
            labelDisplayedRows={({ from, to, count }) => `${from}-${to} / 共 ${count} 条`}
          />
        </CardContent>
      </Card>

      <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>编辑用户角色</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>用户：{selectedUser?.username}</Typography>
          <FormControl fullWidth>
            <InputLabel>角色</InputLabel>
            <Select
              multiple
              value={selectedRoleIds}
              onChange={(event) => setSelectedRoleIds(event.target.value as number[])}
              label="角色"
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
          <Button onClick={() => setEditDialogOpen(false)}>取消</Button>
          <Button onClick={handleEditRoles} variant="contained">
            保存
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={pointsDialogOpen} onClose={() => setPointsDialogOpen(false)} fullWidth maxWidth="md">
        <DialogTitle>积分账户</DialogTitle>
        <DialogContent dividers>
          <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
            目标用户：{selectedUser?.username}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            正数表示补发或充值，负数表示扣减。提交后会直接反映到用户中心积分账户。
          </Typography>

          <Box sx={{ display: 'grid', gap: 2, mt: 2, gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' } }}>
            <TextField
              label="积分调整值"
              value={pointsForm.delta}
              onChange={(event) => setPointsForm((prev) => ({ ...prev, delta: event.target.value }))}
              placeholder="例如 20 或 -5"
              fullWidth
            />
            <FormControl fullWidth>
              <InputLabel>调整类型</InputLabel>
              <Select
                value={pointsForm.adjustmentType}
                label="调整类型"
                onChange={(event) => setPointsForm((prev) => ({ ...prev, adjustmentType: event.target.value }))}
              >
                <MenuItem value="manual_grant">手工补发</MenuItem>
                <MenuItem value="recharge">充值入账</MenuItem>
                <MenuItem value="manual_deduction">人工扣减</MenuItem>
                <MenuItem value="compensation">补偿调整</MenuItem>
              </Select>
            </FormControl>
            <TextField
              label="过期时间"
              type="datetime-local"
              value={pointsForm.expiresAt}
              onChange={(event) => setPointsForm((prev) => ({ ...prev, expiresAt: event.target.value }))}
              InputLabelProps={{ shrink: true }}
              fullWidth
            />
            <Box />
          </Box>

          <TextField
            label="调整原因"
            value={pointsForm.reason}
            onChange={(event) => setPointsForm((prev) => ({ ...prev, reason: event.target.value }))}
            placeholder="例如：补发活动积分、纠正重复奖励、充值入账"
            fullWidth
            multiline
            minRows={2}
            sx={{ mt: 2 }}
          />

          <Typography variant="subtitle2" sx={{ mt: 3, fontWeight: 700 }}>
            最近调整记录
          </Typography>

          {pointsLoading ? (
            <Box sx={{ py: 4, display: 'flex', justifyContent: 'center' }}>
              <CircularProgress size={24} />
            </Box>
          ) : pointsAdjustments.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              暂无人工积分调整记录。
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
                        <Chip size="small" variant="outlined" label={formatAdjustmentType(item.adjustment_type)} />
                      </Box>
                      <Typography sx={{ mt: 1 }}>{item.reason}</Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
                        操作人：{item.operator_username} · 创建时间：{new Date(item.created_at).toLocaleString('zh-CN')}
                      </Typography>
                      {item.expires_at ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          过期时间：{new Date(item.expires_at).toLocaleString('zh-CN')}
                        </Typography>
                      ) : null}
                    </Box>
                  </Box>
                </Paper>
              ))}
            </Box>
          )}

          <Typography variant="subtitle2" sx={{ mt: 3, fontWeight: 700 }}>
            正式计费事件
          </Typography>

          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            这里展示系统正式记账的冻结、结算、释放事件，以及对应的经营结算快照。
          </Typography>

          {pointsLoading ? null : pointsBillingEvents.length === 0 ? (
            <Alert severity="info" sx={{ mt: 2 }}>
              暂无正式计费事件记录。
            </Alert>
          ) : (
            <Box sx={{ mt: 2, display: 'grid', gap: 1.5 }}>
              {pointsBillingEvents.map((item) => (
                <Paper key={item.id} variant="outlined" sx={{ p: 2 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
                    <Box sx={{ minWidth: 0, flex: 1 }}>
                      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                        <Chip size="small" variant="outlined" label={item.module_label} />
                        <Chip size="small" color={getBillingEventColor(item.event_kind)} label={formatBillingEventKind(item.event_kind)} />
                        <Chip size="small" variant="outlined" label={`${item.amount_points.toFixed(2)} 积分`} />
                        {item.amount_yuan != null ? (
                          <Chip size="small" variant="outlined" label={formatCurrency(item.amount_yuan)} />
                        ) : null}
                        {item.pricing_status ? (
                          <Chip size="small" variant="outlined" label={formatPricingStatus(item.pricing_status)} />
                        ) : null}
                        {item.task_status ? (
                          <Chip size="small" variant="outlined" label={formatTaskStatus(item.task_status)} />
                        ) : null}
                      </Box>

                      <Typography sx={{ mt: 1, fontWeight: 600 }}>{item.title}</Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                        {item.summary}
                      </Typography>
                      <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.75 }}>
                        计费键：{item.billing_key} · 操作人：{item.operator_username} · 创建时间：{new Date(item.created_at).toLocaleString('zh-CN')}
                      </Typography>

                      {item.project_id || item.audiobook_project_id || item.run_id ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          {item.project_id ? `项目 ID：${item.project_id}` : '项目 ID：-'}
                          {item.audiobook_project_id ? ` · 有声书项目：${item.audiobook_project_id}` : ''}
                          {item.run_id ? ` · 运行 ID：${item.run_id}` : ''}
                          {item.stage ? ` · 阶段：${item.stage}` : ''}
                        </Typography>
                      ) : null}

                      {item.action_path ? (
                        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.25 }}>
                          跳转入口：{item.action_label || item.action_path} · {item.action_path}
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
                            <Typography variant="subtitle2">经营快照</Typography>
                            <Chip
                              size="small"
                              color={getMarginStatusColor(item.operating_snapshot.margin_status)}
                              label={formatMarginStatus(item.operating_snapshot.margin_status)}
                            />
                          </Box>
                          <Box sx={{ mt: 1, display: 'grid', gap: 0.5 }}>
                            <Typography variant="body2" color="text.secondary">
                              用户计费：{formatCurrency(item.operating_snapshot.user_billed_yuan)} · 供应商折后成本：{formatCurrency(item.operating_snapshot.supplier_discounted_cost_yuan)}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              平台毛利：{formatCurrency(item.operating_snapshot.platform_gross_profit_yuan)} · 毛利率：{formatPercent(item.operating_snapshot.platform_margin_rate)}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              供应商折扣：{formatPercent(item.operating_snapshot.supplier_discount_rate)} · 折扣来源：{item.operating_snapshot.supplier_discount_rate_source}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              折扣分配：平台保留 {formatCurrency(item.operating_snapshot.captured_discount_yuan)} · 让利用户 {formatCurrency(item.operating_snapshot.shared_discount_yuan)}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              负毛利拦截：{item.operating_snapshot.negative_margin_blocked ? '已触发' : '未触发'}
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
          <Button onClick={() => setPointsDialogOpen(false)}>关闭</Button>
          <Button variant="contained" onClick={() => void handleSubmitPointsAdjustment()} disabled={pointsSubmitting}>
            {pointsSubmitting ? '提交中...' : '提交调整'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)} fullWidth maxWidth="xs">
        <DialogTitle>确认删除</DialogTitle>
        <DialogContent>
          <Typography>确定要删除用户 “{selectedUser?.username}” 吗？此操作不可恢复。</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>取消</Button>
          <Button onClick={handleDelete} variant="contained" color="error">
            删除
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
