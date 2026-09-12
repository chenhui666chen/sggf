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
  CircularProgress,
  Alert,
  Checkbox,
  FormControlLabel,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import EditIcon from '@mui/icons-material/Edit'
import SecurityIcon from '@mui/icons-material/Security'
import { useSelector } from 'react-redux'
import { useTranslation } from 'react-i18next'
import { apiClient } from '@/services/api'
import { useFormats } from '@/i18n'
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
  const { t } = useTranslation()
  const { formatDate } = useFormats()
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
      setError(err.response?.data?.detail || t('admin.roles.messages.fetchFailed'))
    } finally {
      setLoading(false)
    }
  }

  const fetchPermissions = async () => {
    try {
      const response = await apiClient.get('/api/v1/admin/roles/permissions/all')
      setPermissions(response.data)
    } catch {
      // 获取权限列表失败
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
      setError(err.response?.data?.detail || t('admin.roles.messages.createFailed'))
    }
  }

  const handleUpdate = async () => {
    if (!selectedRole) return
    try {
      await apiClient.client.patch(`/api/v1/admin/roles/${selectedRole.id}`, {
        ...formData,
        permission_ids: selectedPermissionIds,
      })
      setEditDialogOpen(false)
      resetForm()
      fetchRoles()
    } catch (err: any) {
      setError(err.response?.data?.detail || t('admin.roles.messages.updateFailed'))
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
      setError(err.response?.data?.detail || t('admin.roles.messages.deleteFailed'))
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
          {t('admin.roles.title')}
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
            {t('admin.roles.createRole')}
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
                  <TableCell>{t('admin.roles.table.name')}</TableCell>
                  <TableCell>{t('admin.roles.table.code')}</TableCell>
                  <TableCell>{t('admin.roles.table.description')}</TableCell>
                  <TableCell>{t('admin.roles.table.permissionCount')}</TableCell>
                  <TableCell>{t('admin.roles.table.type')}</TableCell>
                  <TableCell>{t('admin.roles.table.createdAt')}</TableCell>
                  <TableCell>{t('admin.common.actions')}</TableCell>
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
                        <Chip label={t('admin.roles.roleType.system')} size="small" color="secondary" />
                      ) : (
                        <Chip label={t('admin.roles.roleType.custom')} size="small" />
                      )}
                    </TableCell>
                    <TableCell>
                      {formatDate(role.created_at)}
                    </TableCell>
                    <TableCell>
                      {isSuperAdmin && !role.is_system && (
                        <>
                          <IconButton size="small" onClick={() => openEditDialog(role)} title={t('admin.roles.editRole')}>
                            <EditIcon />
                          </IconButton>
                          <IconButton size="small" onClick={() => openDeleteDialog(role)} title={t('admin.common.delete')} color="error">
                            <DeleteIcon />
                          </IconButton>
                        </>
                      )}
                      {role.is_system && (
                        <Typography variant="body2" color="text.secondary">
                          {t('admin.roles.cannotModify')}
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
        <DialogTitle>{t('admin.roles.createRole')}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField
              label={t('admin.roles.fields.name')}
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              fullWidth
              required
            />
            <TextField
              label={t('admin.roles.fields.code')}
              value={formData.code}
              onChange={(e) => setFormData({ ...formData, code: e.target.value })}
              fullWidth
              required
              helperText={t('admin.roles.fields.codeHelp')}
            />
            <TextField
              label={t('admin.roles.fields.description')}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              fullWidth
              multiline
              rows={2}
            />
            
            <Typography variant="subtitle1" sx={{ mt: 2 }}>
              {t('admin.roles.fields.permissions')}
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
          <Button onClick={() => setCreateDialogOpen(false)}>{t('action.cancel')}</Button>
          <Button onClick={handleCreate} variant="contained" disabled={!formData.name || !formData.code}>
            {t('admin.roles.create')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 编辑角色对话框 */}
      <Dialog open={editDialogOpen} onClose={() => setEditDialogOpen(false)} maxWidth="md" fullWidth>
        <DialogTitle>{t('admin.roles.editRole')}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField
              label={t('admin.roles.fields.name')}
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              fullWidth
              required
            />
            <TextField
              label={t('admin.roles.fields.code')}
              value={formData.code}
              disabled
              fullWidth
              helperText={t('admin.roles.fields.codeLocked')}
            />
            <TextField
              label={t('admin.roles.fields.description')}
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              fullWidth
              multiline
              rows={2}
            />
            
            <Typography variant="subtitle1" sx={{ mt: 2 }}>
              {t('admin.roles.fields.permissions')}
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
          <Button onClick={() => setEditDialogOpen(false)}>{t('action.cancel')}</Button>
          <Button onClick={handleUpdate} variant="contained" disabled={!formData.name}>
            {t('action.save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 删除确认对话框 */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>{t('admin.roles.confirmDeleteTitle')}</DialogTitle>
        <DialogContent>
          <Typography>
            {t('admin.roles.deleteConfirmBody', { name: selectedRole?.name })}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>{t('action.cancel')}</Button>
          <Button onClick={handleDelete} variant="contained" color="error">{t('admin.common.delete')}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
