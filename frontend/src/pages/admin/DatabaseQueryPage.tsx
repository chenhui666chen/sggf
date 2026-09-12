/**
 * 数据库查询管理页面
 * 提供安全的 SQL 查询界面
 */
import React, { useState, useEffect } from 'react'
import {
  Box,
  Button,
  Card,
  CardContent,
  Typography,
  TextField,
  Grid,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Alert,
  AlertTitle,
  Tabs,
  Tab,
  List,
  ListItem,
  ListItemText,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material'
import ClearIcon from '@mui/icons-material/Clear'
import CodeIcon from '@mui/icons-material/Code'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import HistoryIcon from '@mui/icons-material/History'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'
import TableChartIcon from '@mui/icons-material/TableChart'
import { apiClient } from '../../services/api'
import { useTranslation } from 'react-i18next'

interface QueryResult {
  columns: string[]
  data: Record<string, any>[]
  row_count: number
  execution_time_ms: number
  masked_fields: string[]
  warning?: string
}

interface TableInfo {
  name: string
  row_count: number
}

interface TableSchema {
  table_name: string
  columns: {
    name: string
    type: string
    nullable: boolean
    sensitive: boolean
  }[]
  sensitive_columns: string[]
}

interface QueryHistory {
  id: number
  sql: string
  description: string
  status: string
  row_count: number
  execution_time_ms: number
  created_at: string
}

interface QueryTemplate {
  name: string
  sql: string
}

const DatabaseQueryPage: React.FC = () => {
  const { t } = useTranslation()
  const [tabValue, setTabValue] = useState(0)
  const [sqlQuery, setSqlQuery] = useState('SELECT * FROM users LIMIT 10;')
  const [description, setDescription] = useState('')
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [tables, setTables] = useState<TableInfo[]>([])
  const [tableSchema, setTableSchema] = useState<TableSchema | null>(null)
  const [history, setHistory] = useState<QueryHistory[]>([])
  const [expandedHistory, setExpandedHistory] = useState<number | false>(false)

  const queryTemplates: QueryTemplate[] = [
    {
      name: t('admin.queryPage.templates.userList'),
      sql: 'SELECT id, username, email, created_at FROM users ORDER BY created_at DESC LIMIT 20;',
    },
    {
      name: t('admin.queryPage.templates.roleList'),
      sql: 'SELECT * FROM roles;',
    },
    {
      name: t('admin.queryPage.templates.projectStats'),
      sql: 'SELECT status, COUNT(*) as count FROM projects GROUP BY status;',
    },
    {
      name: t('admin.queryPage.templates.recentLogs'),
      sql: 'SELECT * FROM admin_operation_logs ORDER BY created_at DESC LIMIT 20;',
    },
  ]

  const executeQuery = async () => {
    setIsLoading(true)
    setErrorMessage('')
    setQueryResult(null)

    try {
      const response = await apiClient.client.post('/api/v1/admin/query/execute', {
        sql: sqlQuery,
        description: description,
      })

      if (response) {
        setQueryResult(response.data as QueryResult)
      }
    } catch (error: any) {
      setErrorMessage(error.response?.data?.detail || t('admin.queryPage.messages.queryFailed'))
    } finally {
      setIsLoading(false)
    }
  }

  const loadTables = async () => {
    try {
      const response = await apiClient.client.get('/api/v1/admin/query/tables')
      if (response) {
        setTables((response as any).tables || [])
      }
    } catch {
      // 加载表列表失败
    }
  }

  const loadTableSchema = async (tableName: string) => {
    try {
      const response = await apiClient.client.get(
        `/api/v1/admin/query/table-schema/${tableName}`,
      )
      if (response) {
        setTableSchema(response.data as TableSchema)
      }
    } catch {
      // 加载表结构失败
    }
  }

  const loadHistory = async () => {
    try {
      const response = await apiClient.client.get('/api/v1/admin/query/history')
      if (response) {
        setHistory((response as any).items || [])
      }
    } catch {
      // 加载历史失败
    }
  }

  const handleTemplateClick = (templateSql: string) => {
    setSqlQuery(templateSql)
  }

  const clearResult = () => {
    setQueryResult(null)
    setErrorMessage('')
  }

  useEffect(() => {
    loadTables()
    loadHistory()
  }, [])

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h4" gutterBottom>
        {t('admin.queryPage.title')}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        {t('admin.queryPage.subtitle')}
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs
          value={tabValue}
          onChange={(_e, newValue) => setTabValue(newValue)}
          aria-label="database query tabs"
        >
          <Tab icon={<CodeIcon />} label={t('admin.queryPage.tabs.execute')} iconPosition="start" />
          <Tab icon={<TableChartIcon />} label={t('admin.queryPage.tabs.schema')} iconPosition="start" />
          <Tab icon={<HistoryIcon />} label={t('admin.queryPage.tabs.history')} iconPosition="start" />
        </Tabs>
      </Box>

      {/* 查询执行标签页 */}
      {tabValue === 0 && (
        <Grid container spacing={3}>
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  {t('admin.queryPage.editor.title')}
                </Typography>

                {/* 快捷模板 */}
                <Box sx={{ mb: 2 }}>
                  <Typography variant="subtitle2" gutterBottom>
                    {t('admin.queryPage.editor.templates')}
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    {queryTemplates.map((template) => (
                      <Chip
                        key={template.name}
                        label={template.name}
                        onClick={() => handleTemplateClick(template.sql)}
                        variant="outlined"
                        size="small"
                      />
                    ))}
                  </Box>
                </Box>

                {/* SQL 输入框 */}
                <TextField
                  fullWidth
                  multiline
                  rows={8}
                  value={sqlQuery}
                  onChange={(e) => setSqlQuery(e.target.value)}
                  placeholder={t('admin.queryPage.editor.sqlPlaceholder')}
                  variant="outlined"
                  sx={{
                    fontFamily: 'monospace',
                    fontSize: '14px',
                    '& textarea': {
                      fontFamily: 'monospace',
                      fontSize: '14px',
                    },
                  }}
                />

                {/* 查询描述 */}
                <TextField
                  fullWidth
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={t('admin.queryPage.editor.descPlaceholder')}
                  sx={{ mt: 2 }}
                  size="small"
                />

                {/* 执行按钮 */}
                <Box sx={{ mt: 2, display: 'flex', gap: 1 }}>
                  <Button
                    variant="contained"
                    color="primary"
                    startIcon={<PlayArrowIcon />}
                    onClick={executeQuery}
                    disabled={isLoading}
                    size="large"
                  >
                    {t('admin.queryPage.editor.execute')}
                  </Button>
                  <Button
                    variant="outlined"
                    startIcon={<ClearIcon />}
                    onClick={clearResult}
                    size="large"
                  >
                    {t('admin.queryPage.editor.clear')}
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  {t('admin.queryPage.result.title')}
                </Typography>

                {/* 错误信息 */}
                {errorMessage && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    <AlertTitle>{t('admin.queryPage.result.errorTitle')}</AlertTitle>
                    {errorMessage}
                  </Alert>
                )}

                {/* 查询结果 */}
                {queryResult && (
                  <Box>
                    {/* 统计信息 */}
                    <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
                      <Chip
                        label={t('admin.queryPage.result.rowCount', { count: queryResult.row_count })}
                        color="primary"
                        size="small"
                      />
                      <Chip
                        label={t('admin.queryPage.result.executionTime', { ms: queryResult.execution_time_ms })}
                        color="success"
                        size="small"
                      />
                      {queryResult.masked_fields.length > 0 && (
                        <Chip
                          label={t('admin.queryPage.result.masked')}
                          color="warning"
                          size="small"
                        />
                      )}
                    </Box>

                    {/* 警告信息 */}
                    {queryResult.warning && (
                      <Alert severity="warning" sx={{ mb: 2 }}>
                        {queryResult.warning}
                      </Alert>
                    )}

                    {/* 结果表格 */}
                    <TableContainer component={Paper} sx={{ maxHeight: 500, overflow: 'auto' }}>
                      <Table size="small" stickyHeader>
                        <TableHead>
                          <TableRow>
                            {queryResult.columns.map((column) => (
                              <TableCell key={column} sx={{ fontFamily: 'monospace', fontWeight: 'bold' }}>
                                {column}
                              </TableCell>
                            ))}
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {queryResult.data.map((row, index) => (
                            <TableRow key={index}>
                              {queryResult.columns.map((column) => (
                                <TableCell
                                  key={column}
                                  sx={{
                                    fontFamily: 'monospace',
                                    fontSize: '12px',
                                    maxWidth: 300,
                                    overflow: 'hidden',
                                    textOverflow: 'ellipsis',
                                  }}
                                >
                                  {row[column]}
                                </TableCell>
                              ))}
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  </Box>
                )}
              </CardContent>
            </Card>
          </Grid>
        </Grid>
      )}

      {/* 表结构标签页 */}
      {tabValue === 1 && (
        <Grid container spacing={3}>
          <Grid item xs={12} md={6}>
            <Card>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                  <Typography variant="h6">{t('admin.queryPage.schema.tables')}</Typography>
                  <Button
                    startIcon={<RefreshIcon />}
                    onClick={loadTables}
                    size="small"
                  >
                    {t('admin.common.refresh')}
                  </Button>
                </Box>

                {tables.length > 0 ? (
                  <List sx={{ maxHeight: 500, overflow: 'auto' }}>
                    {tables.map((table) => (
                      <ListItem
                        key={table.name}
                        secondaryAction={
                          <Button
                            size="small"
                            onClick={() => loadTableSchema(table.name)}
                          >
                            {t('admin.queryPage.schema.viewSchema')}
                          </Button>
                        }
                      >
                        <ListItemText
                          primary={
                            <Typography variant="subtitle2" component="span">
                              {table.name}
                            </Typography>
                          }
                          secondary={t('admin.queryPage.schema.rowCountSuffix', { count: table.row_count })}
                        />
                      </ListItem>
                    ))}
                  </List>
                ) : (
                  <Typography color="text.secondary">{t('admin.queryPage.schema.loadHint')}</Typography>
                )}
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} md={6}>
            {tableSchema && (
              <Card>
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    {t('admin.queryPage.schema.tableTitle', { name: tableSchema.table_name })}
                  </Typography>

                  <TableContainer component={Paper} sx={{ mb: 2 }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>{t('admin.queryPage.schema.columnName')}</TableCell>
                          <TableCell>{t('admin.queryPage.schema.columnType')}</TableCell>
                          <TableCell>{t('admin.queryPage.schema.nullable')}</TableCell>
                          <TableCell>{t('admin.queryPage.schema.sensitivity')}</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {tableSchema.columns.map((column) => (
                          <TableRow key={column.name}>
                            <TableCell sx={{ fontFamily: 'monospace', fontWeight: 'bold' }}>
                              {column.name}
                            </TableCell>
                            <TableCell>
                              <code>{column.type}</code>
                            </TableCell>
                            <TableCell>{column.nullable ? t('admin.queryPage.schema.yes') : t('admin.queryPage.schema.no')}</TableCell>
                            <TableCell>
                              {column.sensitive ? (
                                <Chip label={t('admin.queryPage.schema.sensitive')} color="error" size="small" />
                              ) : (
                                '-'
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>

                  {tableSchema.sensitive_columns.length > 0 && (
                    <Alert severity="warning">
                      {t('admin.queryPage.schema.sensitiveFields', { fields: tableSchema.sensitive_columns.join(', ') })}
                    </Alert>
                  )}
                </CardContent>
              </Card>
            )}
          </Grid>
        </Grid>
      )}

      {/* 历史记录标签页 */}
      {tabValue === 2 && (
        <Card>
          <CardContent>
            <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
              <Typography variant="h6">{t('admin.queryPage.history.title')}</Typography>
              <Button
                startIcon={<RefreshIcon />}
                onClick={loadHistory}
                size="small"
              >
                {t('admin.queryPage.history.refresh')}
              </Button>
            </Box>

            {history.length > 0 ? (
              <Box>
                {history.map((item) => (
                  <Accordion 
                    key={item.id} 
                    expanded={expandedHistory === item.id}
                    onChange={(_e, isExpanded) =>
                      setExpandedHistory(isExpanded ? item.id : false)
                    }
                  >
                    <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                      <Box sx={{ width: '100%', display: 'flex', alignItems: 'center', gap: 2 }}>
                        <Typography sx={{ flex: 1, fontFamily: 'monospace', fontSize: '13px' }} noWrap>
                          {item.sql.length > 100 ? item.sql.substring(0, 100) + '...' : item.sql}
                        </Typography>
                        <Chip
                          label={item.status}
                          color={
                            item.status === 'success'
                              ? 'success'
                              : item.status === 'error'
                                ? 'error'
                                : 'warning'
                          }
                          size="small"
                        />
                        <Typography variant="caption" color="text.secondary">
                          {item.created_at}
                        </Typography>
                      </Box>
                    </AccordionSummary>
                    <AccordionDetails>
                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <Typography variant="body2">
                          <strong>{t('admin.queryPage.history.desc')}</strong>{item.description || 'N/A'}
                        </Typography>
                        <Typography variant="body2">
                          <strong>{t('admin.queryPage.history.rowCount')}</strong>{item.row_count}
                        </Typography>
                        <Typography variant="body2">
                          <strong>{t('admin.queryPage.history.executionTime')}</strong>{item.execution_time_ms}ms
                        </Typography>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                          <strong>{t('admin.queryPage.history.fullSql')}</strong> {item.sql}
                        </Typography>
                      </Box>
                    </AccordionDetails>
                  </Accordion>
                ))}
              </Box>
            ) : (
              <Typography color="text.secondary">{t('admin.queryPage.history.empty')}</Typography>
            )}
          </CardContent>
        </Card>
      )}
    </Box>
  )
}

export default DatabaseQueryPage
