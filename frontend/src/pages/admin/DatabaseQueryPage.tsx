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
  IconButton,
  List,
  ListItem,
  ListItemText,
  Collapse,
  Accordion,
  AccordionSummary,
  AccordionDetails,
} from '@mui/material'
import {
  PlayArrow as PlayArrowIcon,
  Clear as ClearIcon,
  Refresh as RefreshIcon,
  TableChart as TableChartIcon,
  History as HistoryIcon,
  ExpandMore as ExpandMoreIcon,
  Code as CodeIcon,
} from '@mui/icons-material'
import { apiClient } from '../../services/api'

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
  const [tabValue, setTabValue] = useState(0)
  const [sqlQuery, setSqlQuery] = useState('SELECT * FROM users LIMIT 10;')
  const [description, setDescription] = useState('')
  const [queryResult, setQueryResult] = useState<QueryResult | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [tableSchema, setTableSchema] = useState<TableSchema | null>(null)
  const [history, setHistory] = useState<QueryHistory[]>([])
  const [expandedHistory, setExpandedHistory] = useState<number | false>(false)

  const queryTemplates: QueryTemplate[] = [
    {
      name: '用户列表',
      sql: 'SELECT id, username, email, created_at FROM users ORDER BY created_at DESC LIMIT 20;',
    },
    {
      name: '角色列表',
      sql: 'SELECT * FROM roles;',
    },
    {
      name: '项目统计',
      sql: 'SELECT status, COUNT(*) as count FROM projects GROUP BY status;',
    },
    {
      name: '最近操作日志',
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
        setQueryResult(response as QueryResult)
      }
    } catch (error: any) {
      setErrorMessage(error.response?.data?.detail || '查询执行失败')
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
    } catch (error) {
      console.error('加载表列表失败:', error)
    }
  }

  const loadTableSchema = async (tableName: string) => {
    setSelectedTable(tableName)
    try {
      const response = await apiClient.client.get(
        `/api/v1/admin/query/table-schema/${tableName}`,
      )
      if (response) {
        setTableSchema(response as TableSchema)
      }
    } catch (error) {
      console.error('加载表结构失败:', error)
    }
  }

  const loadHistory = async () => {
    try {
      const response = await apiClient.client.get('/api/v1/admin/query/history')
      if (response) {
        setHistory((response as any).items || [])
      }
    } catch (error) {
      console.error('加载历史失败:', error)
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
        数据库查询管理
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        安全的 SQL 查询工具 - 只读查询 | 自动脱敏 | 审计日志 | 查询限制
      </Typography>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs
          value={tabValue}
          onChange={(e, newValue) => setTabValue(newValue)}
          aria-label="database query tabs"
        >
          <Tab icon={<CodeIcon />} label="查询执行" iconPosition="start" />
          <Tab icon={<TableChartIcon />} label="表结构" iconPosition="start" />
          <Tab icon={<HistoryIcon />} label="历史记录" iconPosition="start" />
        </Tabs>
      </Box>

      {/* 查询执行标签页 */}
      {tabValue === 0 && (
        <Grid container spacing={3}>
          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  SQL 查询编辑器
                </Typography>

                {/* 快捷模板 */}
                <Box sx={{ mb: 2 }}>
                  <Typography variant="subtitle2" gutterBottom>
                    快捷模板:
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
                  placeholder="请输入 SQL 查询语句..."
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
                  placeholder="查询描述（可选，用于审计日志）"
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
                    执行查询
                  </Button>
                  <Button
                    variant="outlined"
                    startIcon={<ClearIcon />}
                    onClick={clearResult}
                    size="large"
                  >
                    清空
                  </Button>
                </Box>
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12}>
            <Card>
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  查询结果
                </Typography>

                {/* 错误信息 */}
                {errorMessage && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    <AlertTitle>查询失败</AlertTitle>
                    {errorMessage}
                  </Alert>
                )}

                {/* 查询结果 */}
                {queryResult && (
                  <Box>
                    {/* 统计信息 */}
                    <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
                      <Chip
                        label={`行数：${queryResult.row_count}`}
                        color="primary"
                        size="small"
                      />
                      <Chip
                        label={`执行时间：${queryResult.execution_time_ms}ms`}
                        color="success"
                        size="small"
                      />
                      {queryResult.masked_fields.length > 0 && (
                        <Chip
                          label="已脱敏"
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
                  <Typography variant="h6">数据库表</Typography>
                  <Button
                    startIcon={<RefreshIcon />}
                    onClick={loadTables}
                    size="small"
                  >
                    刷新
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
                            查看结构
                          </Button>
                        }
                      >
                        <ListItemText
                          primary={
                            <Typography variant="subtitle2" component="span">
                              {table.name}
                            </Typography>
                          }
                          secondary={`${table.row_count} 行`}
                        />
                      </ListItem>
                    ))}
                  </List>
                ) : (
                  <Typography color="text.secondary">点击刷新表列表加载</Typography>
                )}
              </CardContent>
            </Card>
          </Grid>

          <Grid item xs={12} md={6}>
            {tableSchema && (
              <Card>
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    表结构：{tableSchema.table_name}
                  </Typography>

                  <TableContainer component={Paper} sx={{ mb: 2 }}>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>列名</TableCell>
                          <TableCell>类型</TableCell>
                          <TableCell>可空</TableCell>
                          <TableCell>敏感度</TableCell>
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
                            <TableCell>{column.nullable ? '是' : '否'}</TableCell>
                            <TableCell>
                              {column.sensitive ? (
                                <Chip label="敏感" color="error" size="small" />
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
                      敏感字段：{tableSchema.sensitive_columns.join(', ')}
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
              <Typography variant="h6">查询历史</Typography>
              <Button
                startIcon={<RefreshIcon />}
                onClick={loadHistory}
                size="small"
              >
                刷新历史
              </Button>
            </Box>

            {history.length > 0 ? (
              <Accordion
                expanded={expandedHistory !== false}
                onChange={(e, isExpanded) =>
                  setExpandedHistory(isExpanded ? (e.target as any).value : false)
                }
              >
                {history.map((item) => (
                  <Accordion key={item.id} value={item.id}>
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
                          <strong>描述：</strong>{item.description || 'N/A'}
                        </Typography>
                        <Typography variant="body2">
                          <strong>行数：</strong>{item.row_count}
                        </Typography>
                        <Typography variant="body2">
                          <strong>执行时间：</strong>{item.execution_time_ms}ms
                        </Typography>
                        <Typography variant="body2" sx={{ fontFamily: 'monospace', wordBreak: 'break-all' }}>
                          <strong>完整 SQL:</strong> {item.sql}
                        </Typography>
                      </Box>
                    </AccordionDetails>
                  </Accordion>
                ))}
              </Accordion>
            ) : (
              <Typography color="text.secondary">暂无查询历史</Typography>
            )}
          </CardContent>
        </Card>
      )}
    </Box>
  )
}

export default DatabaseQueryPage
