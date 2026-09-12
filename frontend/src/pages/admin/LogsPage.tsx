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
import HistoryIcon from '@mui/icons-material/History'
import LoginIcon from '@mui/icons-material/Login'
import { useFormats } from '@/i18n'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
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

const buildOperationTypes = (t: TFunction) => [
  { value: '', label: t('admin.logs.operations.all') },
  { value: 'create', label: t('admin.logs.operations.create') },
  { value: 'update', label: t('admin.logs.operations.update') },
  { value: 'delete', label: t('admin.logs.operations.delete') },
  { value: 'login', label: t('admin.logs.operations.login') },
  { value: 'logout', label: t('admin.logs.operations.logout') },
]

const buildResourceTypes = (t: TFunction) => [
  { value: '', label: t('admin.logs.resources.all') },
  { value: 'user', label: t('admin.logs.resources.user') },
  { value: 'role', label: t('admin.logs.resources.role') },
  { value: 'project', label: t('admin.logs.resources.project') },
  { value: 'chapter', label: t('admin.logs.resources.chapter') },
  { value: 'audiobook', label: t('admin.logs.resources.audiobook') },
]

const buildLoginStatuses = (t: TFunction) => [
  { value: '', label: t('admin.logs.statuses.all') },
  { value: 'success', label: t('admin.logs.statuses.success') },
  { value: 'failed', label: t('admin.logs.statuses.failed') },
]

export default function LogsPage() {
  // 审计日志与登录日志都要保留到秒：同一分钟内的连续操作、暴力登录尝试，
  // 少了秒就没法排序也没法定位。
  const { t } = useTranslation()
  const { formatDateTimeWithSeconds } = useFormats()
  const operationTypeOptions = buildOperationTypes(t)
  const resourceTypeOptions = buildResourceTypes(t)
  const loginStatusOptions = buildLoginStatuses(t)
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
      setError(err.response?.data?.detail || t('admin.logs.messages.fetchOperationFailed'))
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
      setError(err.response?.data?.detail || t('admin.logs.messages.fetchLoginFailed'))
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
        {t('admin.logs.title')}
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Card>
        <Tabs value={tabValue} onChange={handleTabChange} sx={{ borderBottom: 1, borderColor: 'divider' }}>
          <Tab icon={<HistoryIcon />} label={t('admin.logs.tabs.operation')} iconPosition="start" />
          <Tab icon={<LoginIcon />} label={t('admin.logs.tabs.login')} iconPosition="start" />
        </Tabs>

        <CardContent>
          {tabValue === 0 && (
            <>
              <Box sx={{ display: 'flex', gap: 2, mb: 3, flexWrap: 'wrap' }}>
                <FormControl size="small" sx={{ width: 150 }}>
                  <InputLabel>{t('admin.logs.filters.operationType')}</InputLabel>
                  <Select
                    value={opFilters.operation_type}
                    label={t('admin.logs.filters.operationType')}
                    onChange={(e) => setOpFilters({ ...opFilters, operation_type: e.target.value })}
                  >
                    {operationTypeOptions.map((type) => (
                      <MenuItem key={type.value} value={type.value}>{type.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <FormControl size="small" sx={{ width: 150 }}>
                  <InputLabel>{t('admin.logs.filters.resourceType')}</InputLabel>
                  <Select
                    value={opFilters.resource_type}
                    label={t('admin.logs.filters.resourceType')}
                    onChange={(e) => setOpFilters({ ...opFilters, resource_type: e.target.value })}
                  >
                    {resourceTypeOptions.map((type) => (
                      <MenuItem key={type.value} value={type.value}>{type.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label={t('admin.logs.filters.startDate')}
                  type="date"
                  size="small"
                  value={opFilters.start_date}
                  onChange={(e) => setOpFilters({ ...opFilters, start_date: e.target.value })}
                  InputLabelProps={{ shrink: true }}
                />
                <TextField
                  label={t('admin.logs.filters.endDate')}
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
                      <TableCell>{t('admin.logs.columns.operator')}</TableCell>
                      <TableCell>{t('admin.logs.columns.operationType')}</TableCell>
                      <TableCell>{t('admin.logs.columns.resourceType')}</TableCell>
                      <TableCell>{t('admin.logs.columns.resourceId')}</TableCell>
                      <TableCell>{t('admin.logs.columns.detail')}</TableCell>
                      <TableCell>{t('admin.logs.columns.ipAddress')}</TableCell>
                      <TableCell>{t('admin.logs.columns.time')}</TableCell>
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
                          {formatDateTimeWithSeconds(log.created_at)}
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
                  <InputLabel>{t('admin.logs.filters.loginStatus')}</InputLabel>
                  <Select
                    value={loginFilters.login_status}
                    label={t('admin.logs.filters.loginStatus')}
                    onChange={(e) => setLoginFilters({ ...loginFilters, login_status: e.target.value })}
                  >
                    {loginStatusOptions.map((status) => (
                      <MenuItem key={status.value} value={status.value}>{status.label}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
                <TextField
                  label={t('admin.logs.filters.startDate')}
                  type="date"
                  size="small"
                  value={loginFilters.start_date}
                  onChange={(e) => setLoginFilters({ ...loginFilters, start_date: e.target.value })}
                  InputLabelProps={{ shrink: true }}
                />
                <TextField
                  label={t('admin.logs.filters.endDate')}
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
                      <TableCell>{t('admin.logs.columns.user')}</TableCell>
                      <TableCell>{t('admin.logs.columns.loginType')}</TableCell>
                      <TableCell>{t('admin.logs.columns.status')}</TableCell>
                      <TableCell>{t('admin.logs.columns.ipAddress')}</TableCell>
                      <TableCell>{t('admin.logs.columns.failureReason')}</TableCell>
                      <TableCell>{t('admin.logs.columns.time')}</TableCell>
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
                            label={log.login_status === 'success' ? t('admin.logs.statuses.success') : t('admin.logs.statuses.failed')}
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
                          {formatDateTimeWithSeconds(log.created_at)}
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
            labelRowsPerPage={t('admin.logs.pagination.rowsPerPage')}
            labelDisplayedRows={({ from, to, count }) => t('admin.logs.pagination.displayedRows', { from, to, count })}
          />
        </CardContent>
      </Card>
    </Box>
  )
}
