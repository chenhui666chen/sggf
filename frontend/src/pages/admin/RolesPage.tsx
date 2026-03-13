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
  Paper,
  Button,
  IconButton,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  CircularProgress,
  Alert,
  Tooltip,
  Checkbox,
  FormControlLabel,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material'
import {
  Add as AddIcon,
  Edit as EditIcon,
  Delete as DeleteIcon,
  ExpandMore as ExpandMoreIcon,
  Security as SecurityIcon,
} from '@mui/icons-material'
import { useSelector } from 'react-redux'
import { apiClient } from '@/services/api'
import { RootState } from '@/store/store'

interface Permission {
  id: number
  code: string
  name: string
  description: string | null
  parent_id: number | null
  children?: Permission[]
}

interface Role {
  id: number
  code: string
  name: string
  description: string | null
  is_system: boolean
  created_at: string
  permissions: Permission[]
  user_count?: number
}

interface RoleListResponse {
  total: number
  items: Role[]
}

export default function RolesPage() {
  const { user } = useSelector((state: RootState) => state.auth)
  const isSuperAdmin = (user as any)?.roles?.some((r: any) => r.code === 'super_admin')
  
  const [roles, setRoles] = useState<Role[]>([])
  const [permissions, setPermissions] = useState<Permission[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [selectedRole, setSelectedRole] = useState<Role | null>(null)
  
  const [formData, setFormData] = useState({
    name: '',
    code: '',
    description: '',
  })
  const [selectedPermissionIds, setSelectedPermissionIds] = useState<number[]>([])

  useEffect(() => {
    fetchRoles()
    fetchPermissions()
  }, [])

  const fetchRoles = async () => {
    try {
      setLoading(true)
      const response = await apiClient.get('/api/v1/admin/roles')
      const data: RoleListResponse = response.data
      setRoles(data.items)
    } catch (err: any) {
      setError(err.response?.data?.detail || '获取角色列表失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchPermissions = async () => {
    try {
      const response = await apiClient.get('/api/v1/admin/roles/permissions/all')
      setPermissions(response.data)
    } catch (err) {
      console.error('获取权限列表失败', err)
    }
  }

  const handleCreate = async () => {
    try {
      await apiClient.post('/api/v1/admin/roles', {
        ...formData,
        permission_ids: selectedPermissionIds,
      })
      setCreateDialogOpen(false)
      resetForm()
      fetchRoles()
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建角色失败')
    }
  }

  const handleUpdate = async () => {
    if (!selectedRole) return
    try {
      await apiClient.patch(`/api/v1/admin/roles/${selectedRole.id}`, {
        ...formData,
        permission_ids: selectedPermissionIds,
      })
      setEditDialogOpen(false)
      resetForm()
      fetchRoles()
    } catch (err: any) {
      setError(err.response?.data?.detail || '更新角色失败')
    }
  }

  const handleDelete = async () => {
    if (!selectedRole) return
    try {
      await apiClient.delete(`/api/v1/admin/roles/${selectedRole.id}`)
      setDeleteDialogOpen(false)
      setSelectedRole(null)
      fetchRoles()
    } catch (err: any) {
      setError(err.response?.data?.detail || '删除角色失败')
    }
  }

  const openEditDialog = (role: Role) => {
    setSelectedRole(role)
    setFormData({
      name: role.name,
      code: role.code,
      description: role.description || '',
    })
    setSelectedPermissionIds(role.permissions.map(p => p.id))
    setEditDialogOpen(true)
  }

  const openDeleteDialog = (role: Role) => {
    setSelectedRole(role)
    setDeleteDialogOpen(true)
  }

  const resetForm = () => {
    setFormData({ name: '', code: '', description: '' })
    setSelectedPermissionIds([])
    setSelectedRole(null)
  }

  const togglePermission = (permissionId: number) => {
    setSelectedPermissionIds(prev => 
      prev.includes(permissionId)
        ? prev.filter(id => id !== permissionId)
        : [...prev, permissionId]
    )
  }

  if (loading && roles.length === 0) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">
          角色权限管理
        </Typography>
        {isSuperAdmin && (
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              resetForm()
              setCreateDialogOpen(true)
            }}
          >
            新建角色
          </Button>
        )}
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Card>
        <CardContent>
          <TableContainer component={Paper} variant="outlined">
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>角色名称</TableCell>
                  <TableCell>角色代码</TableCell>
                  <TableCell>描述</TableCell>
                  <TableCell>权限数量</TableCell>
                  <TableCell>类型</TableCell>
                  <TableCell>创建时间</TableCell>
                  <TableCell>操作</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {roles.map((role) => (
                  <TableRow key={role.id}>
                    <TableCell>
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <SecurityIcon color="primary" />
                        {role.name}
                      </Box>
                    </TableCell>
                    <TableCell>
                      <Chip label={role.code} size="small" variant="outlined" />
                    </TableCell>
                    <TableCell>{role.description || '-'}</TableCell>
                    <TableCell>
                      <Chip label={role.permissions.length} size="small" color="primary" />
                    </TableCell>
                    <TableCell>
                      {role.is_system ? (
                        <Chip label="系统角色" size="small" color="secondary" />
                      ) : (
                        <Chip label="自定义" size="small" />
                      )}
                    </TableCell>
                    <TableCell>
                      {new Date(role.created_at).toLocaleDateString('zh-CN')}
                    </TableCell>
                    <TableCell>
                      {isSuperAdmin && !role.is_system && (
                        <>
                          <IconButton size="small" onClick={() => openEditDialog(role)} title="编辑">
                            <EditIcon />
                          </IconButton>
                          <IconButton size="small" onClick={() => openDeleteDialog(role)} title="删除" color="error">
                            <DeleteIcon />
                          </IconButton>
                        </>
                      )}
                      {role.is_system && (
                        <Typography variant="body2" color="text.secondary">
                          不可修改
                        </Typography>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </CardContent>
      </Card>

      {/* 创建角色对话框 */}
      <Dialog open={createDialogOpen} onClose={() => setCreateDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>新建角色</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField
              label="角色名称"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              fullWidth
              required
            />
            <TextField
              label="角色代码"
              value={formData.code}
              onChange={(e) => setFormData({ ...formData, code: e.target.value })}
              fullWidth
              required
              helperText="英文标识，如：content_manager"
            />
            <TextField
              label="描述"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              fullWidth
              multiline
              rows={2}
            />
            
            <Typography variant="subtitle1" sx={{ mt: 2 }}>
              权限配置
            </Typography>
            <Paper variant="outlined" sx={{ p: 2, maxHeight: 300, overflow: 'auto' }}>
              {permissions.map((permission) => (
                <Box key={permission.id} sx={{ mb: 1 }}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={selectedPermissionIds.includes(permission.id)}
                        onChange={() => togglePermission(permission.id)}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="body2" fontWeight="bold">
                          {permission.name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {permission.code} - {permission.description}
                        </Typography>
                      </Box>
                    }
                  />
                  {permission.children && permission.children.length > 0 && (
                    <Box sx={{ ml: 4 }}>
                      {permission.children.map((child) => (
                        <FormControlLabel
                          key={child.id}
                          control={
                            <Checkbox
                              size="small"
                              checked={selectedPermissionIds.includes(child.id)}
                              onChange={() => togglePermission(child.id)}
                            />
                          }
                          label={
                            <Typography variant="body2">
                              {child.name} ({child.code})
                            </Typography>
                          }
                        />
                      ))}
                    </Box>
                  )}
                </Box>
              ))}
            </Paper>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreateDialogOpen(false)}>取消</Button>
          <Button onClick={handleCreate} variant="contained" disabled={!formData.name || !formData.code}>
            创建
          </Button>
        </DialogActions>
      </Dialog>

      {/* 编辑角色对话框 */}
      <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>编辑角色</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField
              label="角色名称"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              fullWidth
              required
            />
            <TextField
              label="角色代码"
              value={formData.code}
              disabled
              fullWidth
              helperText="角色代码不可修改"
            />
            <TextField
              label="描述"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              fullWidth
              multiline
              rows={2}
            />
            
            <Typography variant="subtitle1" sx={{ mt: 2 }}>
              权限配置
            </Typography>
            <Paper variant="outlined" sx={{ p: 2, maxHeight: 300, overflow: 'auto' }}>
              {permissions.map((permission) => (
                <Box key={permission.id} sx={{ mb: 1 }}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={selectedPermissionIds.includes(permission.id)}
                        onChange={() => togglePermission(permission.id)}
                      />
                    }
                    label={
                      <Box>
                        <Typography variant="body2" fontWeight="bold">
                          {permission.name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {permission.code} - {permission.description}
                        </Typography>
                      </Box>
                    }
                  />
                  {permission.children && permission.children.length > 0 && (
                    <Box sx={{ ml: 4 }}>
                      {permission.children.map((child) => (
                        <FormControlLabel
                          key={child.id}
                          control={
                            <Checkbox
                              size="small"
                              checked={selectedPermissionIds.includes(child.id)}
                              onChange={() => togglePermission(child.id)}
                            />
                          }
                          label={
                            <Typography variant="body2">
                              {child.name} ({child.code})
                            </Typography>
                          }
                        />
                      ))}
                    </Box>
                  )}
                </Box>
              ))}
            </Paper>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditDialogOpen(false)}>取消</Button>
          <Button onClick={handleUpdate} variant="contained" disabled={!formData.name}>
            保存
          </Button>
        </DialogActions>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>确认删除</DialogTitle>
        <DialogContent>
          <Typography>
            确定要删除角色 "{selectedRole?.name}" 吗？此操作不可恢复。
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
