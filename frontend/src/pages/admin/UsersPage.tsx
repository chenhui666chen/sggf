import { useEffect, useState } from 'react'
import {
  Box,
  Card,
  CardContent,
  Typography,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  Paper,
  Button,
  IconButton,
  TextField,
  InputAdornment,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
  Alert,
} from '@mui/material'
import {
  Search as SearchIcon,
  Edit as EditIcon,
  Block as BlockIcon,
  CheckCircle as CheckCircleIcon,
  Delete as DeleteIcon,
  Add as AddIcon,
} from '@mui/icons-material'
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

export default function AdminUsersPage() {
  const [users, setUsers] = useState<User[]>([])
  const [roles, setRoles] = useState<Role[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(10)
  const [total, setTotal] = useState(0)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('')
  
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [selectedUser, setSelectedUser] = useState<User | null>(null)
  const [selectedRoleIds, setSelectedRoleIds] = useState<number[]>([])

  useEffect(() => {
    fetchUsers()
    fetchRoles()
  }, [page, rowsPerPage, search, statusFilter])

  const fetchUsers = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams({
        page: (page + 1).toString(),
        page_size: rowsPerPage.toString(),
      })
      if (search) params.append('search', search)
      if (statusFilter) params.append('is_active', statusFilter)
      
      const response = await apiClient.get(`/api/v1/admin/users?${params}`)
      const data: UserListResponse = response.data
      setUsers(data.items)
      setTotal(data.total)
    } catch (err: any) {
      setError(err.response?.data?.detail || '获取用户列表失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchRoles = async () => {
    try {
      const response = await apiClient.get('/api/v1/admin/roles')
      setRoles(response.data.items)
    } catch (err) {
      console.error('获取角色列表失败', err)
    }
  }

  const handleToggleStatus = async (user: User) => {
    try {
      await apiClient.patch(`/api/v1/admin/users/${user.id}/status`, {
        is_active: !user.is_active
      })
      fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || '操作失败')
    }
  }

  const handleDelete = async () => {
    if (!selectedUser) return
    try {
      await apiClient.delete(`/api/v1/admin/users/${selectedUser.id}`)
      setDeleteDialogOpen(false)
      setSelectedUser(null)
      fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || '删除失败')
    }
  }

  const handleEditRoles = async () => {
    if (!selectedUser) return
    try {
      await apiClient.post(`/api/v1/admin/users/${selectedUser.id}/roles`, {
        role_ids: selectedRoleIds
      })
      setEditDialogOpen(false)
      setSelectedUser(null)
      setSelectedRoleIds([])
      fetchUsers()
    } catch (err: any) {
      setError(err.response?.data?.detail || '分配角色失败')
    }
  }

  const openEditDialog = (user: User) => {
    setSelectedUser(user)
    setSelectedRoleIds(user.roles.map(r => r.id))
    setEditDialogOpen(true)
  }

  const openDeleteDialog = (user: User) => {
    setSelectedUser(user)
    setDeleteDialogOpen(true)
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

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Card>
        <CardContent>
          <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
            <TextField
              placeholder="搜索用户名、邮箱、手机号"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              size="small"
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <SearchIcon />
                  </InputAdornment>
                ),
              }}
              sx={{ width: 300 }}
            />
            <FormControl size="small" sx={{ width: 150 }}>
              <InputLabel>状态</InputLabel>
              <Select
                value={statusFilter}
                label="状态"
                onChange={(e) => setStatusFilter(e.target.value)}
              >
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
                          sx={{ mr: 0.5 }}
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
                    <TableCell>
                      {new Date(user.created_at).toLocaleDateString('zh-CN')}
                    </TableCell>
                    <TableCell>
                      <IconButton size="small" onClick={() => openEditDialog(user)} title="编辑角色">
                        <EditIcon />
                      </IconButton>
                      <IconButton 
                        size="small" 
                        onClick={() => handleToggleStatus(user)}
                        title={user.is_active ? '禁用' : '启用'}
                      >
                        {user.is_active ? <BlockIcon /> : <CheckCircleIcon />}
                      </IconButton>
                      <IconButton size="small" onClick={() => openDeleteDialog(user)} title="删除">
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
            onPageChange={(e, newPage) => setPage(newPage)}
            rowsPerPage={rowsPerPage}
            onRowsPerPageChange={(e) => {
              setRowsPerPage(parseInt(e.target.value, 10))
              setPage(0)
            }}
            labelRowsPerPage="每页行数："
            labelDisplayedRows={({ from, to, count }) => `${from}-${to} 共 ${count} 条`}
          />
        </CardContent>
      </Card>

      <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)}>
        <DialogTitle>编辑用户角色</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>
            用户: {selectedUser?.username}
          </Typography>
          <FormControl fullWidth>
            <InputLabel>角色</InputLabel>
            <Select
              multiple
              value={selectedRoleIds}
              onChange={(e) => setSelectedRoleIds(e.target.value as number[])}
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
          <Button onClick={handleEditRoles} variant="contained">保存</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>确认删除</DialogTitle>
        <DialogContent>
          <Typography>
            确定要删除用户 "{selectedUser?.username}" 吗？此操作不可恢复。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>取消</Button>
          <Button onClick={handleDelete} variant="contained" color="error">删除</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
