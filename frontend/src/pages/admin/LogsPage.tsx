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
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  CircularProgress,
  Alert,
  Tabs,
  Tab,
} from '@mui/material'
import {
  History as HistoryIcon,
  Login as LoginIcon,
} from '@mui/icons-material'
import { apiClient } from '@/services/api'

interface OperationLog {
  id: number
  user_id: number
  username: string
  operation_type: string
  resource_type: string
  resource_id: string | null
  detail: string | null
  ip_address: string | null
  user_agent: string | null
  created_at: string
}

interface LoginLog {
  id: number
  user_id: number
  username: string
  login_type: string
  login_status: string
  ip_address: string | null
  user_agent: string | null
  failure_reason: string | null
  created_at: string
}

interface LogListResponse {
  total: number
  page: number
  page_size: number
  total_pages: number
  items: OperationLog[] | LoginLog[]
}

const operationTypes = [
  { value: '', label: '全部操作' },
  { value: 'create', label: '创建' },
  { value: 'update', label: '更新' },
  { value: 'delete', label: '删除' },
  { value: 'login', label: '登录' },
  { value: 'logout', label: '登出' },
]

const resourceTypes = [
  { value: '', label: '全部资源' },
  { value: 'user', label: '用户' },
  { value: 'role', label: '角色' },
  { value: 'project', label: '项目' },
  { value: 'chapter', label: '章节' },
  { value: 'audiobook', label: '有声书' },
]

const loginStatuses = [
  { value: '', label: '全部状态' },
  { value: 'success', label: '成功' },
  { value: 'failed', label: '失败' },
]

export default function LogsPage() {
  const [tabValue, setTabValue] = useState(0)
  
  const [operationLogs, setOperationLogs] = useState<OperationLog[]>([])
  const [loginLogs, setLoginLogs] = useState<LoginLog[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(20)
  const [total, setTotal] = useState(0)
  
  const [opFilters, setOpFilters] = useState({
    operation_type: '',
    resource_type: '',
    start_date: '',
    end_date: '',
  })
  
  const [loginFilters, setLoginFilters] = useState({
    login_status: '',
    start_date: '',
    end_date: '',
  })

  useEffect(() => {
    if (tabValue === 0) {
      fetchOperationLogs()
    } else {
      fetchLoginLogs()
    }
  }, [tabValue, page, rowsPerPage, opFilters, loginFilters])

  const fetchOperationLogs = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams({
        page: (page + 1).toString(),
        page_size: rowsPerPage.toString(),
      })
      if (opFilters.operation_type) params.append('operation_type', opFilters.operation_type)
      if (opFilters.resource_type) params.append('resource_type', opFilters.resource_type)
      if (opFilters.start_date) params.append('start_date', opFilters.start_date)
      if (opFilters.end_date) params.append('end_date', opFilters.end_date)
      
      const response = await apiClient.get(`/api/v1/admin/logs/operations?${params}`)
      const data: LogListResponse = response.data
      setOperationLogs(data.items as OperationLog[])
      setTotal(data.total)
    } catch (err: any) {
      setError(err.response?.data?.detail || '获取操作日志失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchLoginLogs = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams({
        page: (page + 1).toString(),
        page_size: rowsPerPage.toString(),
      })
      if (loginFilters.login_status) params.append('login_status', loginFilters.login_status)
      if (loginFilters.start_date) params.append('start_date', loginFilters.start_date)
      if (loginFilters.end_date) params.append('end_date', loginFilters.end_date)
      
      const response = await apiClient.get(`/api/v1/admin/logs/logins?${params}`)
      const data: LogListResponse = response.data
      setLoginLogs(data.items as LoginLog[])
      setTotal(data.total)
    } catch (err: any) {
      setError(err.response?.data?.detail || '获取登录日志失败')
    } finally {
      setLoading(false)
    }
  }

  const handleTabChange = (_: any, newValue: number) => {
    setTabValue(newValue)
    setPage(0)
    setTotal(0)
  }

  const getOperationTypeColor = (type: string) => {
    const colors: Record<string, 'default' | 'primary' | 'success' | 'warning' | 'error'> = {
      create: 'success',
      update: 'primary',
      delete: 'error',
      login: 'primary',
      logout: 'default',
    }
    return colors[type] || 'default'
  }

  const getLoginStatusColor = (status: string) => {
    return status === 'success' ? 'success' : 'error'
  }

  if (loading && operationLogs.length === 0 && loginLogs.length === 0) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
        操作日志
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Card>
        <Tabs value={tabValue} onChange={handleTabChange} sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Tab icon={<HistoryIcon />} label="操作日志" iconPosition="start" />
          <Tab icon={<LoginIcon />} label="登录日志" iconPosition="start" />
        </Tabs>

        <CardContent>
          {tabValue === 0 && (
            <>
              <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                <FormControl size="small" sx={{ width: 150 }}>
                  <InputLabel>操作类型</InputLabel>
                  <Select
                    value={opFilters.operation_type}
                    label="操作类型"
                    onChange={(e) => setOpFilters({ ...opFilters, operation_type: e.target.value })}
                  >
                    {operationTypes.map((type) => (
                      <MenuItem key={type.value} value={type.value}>{type.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" sx={{ width: 150 }}>
                  <InputLabel>资源类型</InputLabel>
                  <Select
                    value={opFilters.resource_type}
                    label="资源类型"
                    onChange={(e) => setOpFilters({ ...opFilters, resource_type: e.target.value })}
                  >
                    {resourceTypes.map((type) => (
                      <MenuItem key={type.value} value={type.value}>{type.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="开始日期"
                  type="date"
                  size="small"
                  value={opFilters.start_date}
                  onChange={(e) => setOpFilters({ ...opFilters, start_date: e.target.value })}
                  InputLabelProps={{ shrink: true }}
                />
                <TextField
                  label="结束日期"
                  type="date"
                  size="small"
                  value={opFilters.end_date}
                  onChange={(e) => setOpFilters({ ...opFilters, end_date: e.target.value })}
                  InputLabelProps={{ shrink: true }}
                />
              </Box>

              <TableContainer component={Paper} variant="outlined">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableCell>ID</TableCell>
                      <TableCell>操作用户</TableCell>
                      <TableCell>操作类型</TableCell>
                      <TableCell>资源类型</TableCell>
                      <TableCell>资源ID</TableCell>
                      <TableCell>详情</TableCell>
                      <TableCell>IP地址</TableCell>
                      <TableCell>时间</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {operationLogs.map((log) => (
                      <TableRow key={log.id}>
                        <TableCell>{log.id}</TableCell>
                        <TableCell>{log.username}</TableCell>
                        <TableCell>
                          <Chip
                            label={log.operation_type}
                            size="small"
                            color={getOperationTypeColor(log.operation_type)}
                          />
                        </TableCell>
                        <TableCell>{log.resource_type}</TableCell>
                        <TableCell>{log.resource_id || '-'}</TableCell>
                        <TableCell>
                          <Typography variant="body2" sx={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {log.detail || '-'}
                          </Typography>
                        </TableCell>
                        <TableCell>{log.ip_address || '-'}</TableCell>
                        <TableCell>
                          {new Date(log.created_at).toLocaleString('zh-CN')}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}

          {tabValue === 1 && (
            <>
              <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                <FormControl size="small" sx={{ width: 150 }}>
                  <InputLabel>登录状态</InputLabel>
                  <Select
                    value={loginFilters.login_status}
                    label="登录状态"
                    onChange={(e) => setLoginFilters({ ...loginFilters, login_status: e.target.value })}
                  >
                    {loginStatuses.map((status) => (
                      <MenuItem key={status.value} value={status.value}>{status.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label="开始日期"
                  type="date"
                  size="small"
                  value={loginFilters.start_date}
                  onChange={(e) => setLoginFilters({ ...loginFilters, start_date: e.target.value })}
                  InputLabelProps={{ shrink: true }}
                />
                <TextField
                  label="结束日期"
                  type="date"
                  size="small"
                  value={loginFilters.end_date}
                  onChange={(e) => setLoginFilters({ ...loginFilters, end_date: e.target.value })}
                  InputLabelProps={{ shrink: true }}
                />
              </Box>

              <TableContainer component={Paper} variant="outlined">
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableCell>ID</TableCell>
                      <TableCell>用户</TableCell>
                      <TableCell>登录方式</TableCell>
                      <TableCell>状态</TableCell>
                      <TableCell>IP地址</TableCell>
                      <TableCell>失败原因</TableCell>
                      <TableCell>时间</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {loginLogs.map((log) => (
                      <TableRow key={log.id}>
                        <TableCell>{log.id}</TableCell>
                        <TableCell>{log.username}</TableCell>
                        <TableCell>{log.login_type}</TableCell>
                        <TableCell>
                          <Chip
                            label={log.login_status === 'success' ? '成功' : '失败'}
                            size="small"
                            color={getLoginStatusColor(log.login_status)}
                          />
                        </TableCell>
                        <TableCell>{log.ip_address || '-'}</TableCell>
                        <TableCell>
                          <Typography variant="body2" color={log.failure_reason ? 'error' : 'text.secondary'}>
                            {log.failure_reason || '-'}
                          </Typography>
                        </TableCell>
                        <TableCell>
                          {new Date(log.created_at).toLocaleString('zh-CN')}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </>
          )}

          <TablePagination
            component="div"
            count={total}
            page={page}
            onPageChange={(_, newPage) => setPage(newPage)}
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
    </Box>
  )
}
