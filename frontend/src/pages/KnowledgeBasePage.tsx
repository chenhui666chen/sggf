import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Box,
  Tabs,
  Tab,
  Card,
  CardContent,
  CardActions,
  Button,
  TextField,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Typography,
  Grid,
  Badge,
  InputAdornment,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import SearchIcon from '@mui/icons-material/Search'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import UploadIcon from '@mui/icons-material/Upload'
import DownloadIcon from '@mui/icons-material/Download'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Snackbar from '@mui/material/Snackbar'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import { RootState, AppDispatch } from '@/store/store'
import {
  fetchKnowledgeBase,
  addWorldSetting,
  addCharacter,
  addPlotOutline,
  deleteKnowledgeBase,
} from '@/store/slices/knowledgeBaseSlice'
import { logger } from '@/utils/logger'

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props
  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  )
}

export default function KnowledgeBasePage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { worldSettings, characters, plotOutline } = useSelector(
    (state: RootState) => state.knowledgeBase
  )
  const [tabValue, setTabValue] = useState(0)
  const [openDialog, setOpenDialog] = useState(false)
  const [dialogType, setDialogType] = useState<'world' | 'character' | 'plot'>('world')
  const [formData, setFormData] = useState({ name: '', content: '' })
  const [searchQuery, setSearchQuery] = useState('')
  
  // 删除确认对话框状态
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [itemToDelete, setItemToDelete] = useState<number | null>(null)
  
  // 🆕 向量搜索相关状态
  const [searchMode, setSearchMode] = useState<'local' | 'vector'>('local')
  const [vectorSearchResults, setVectorSearchResults] = useState<any[]>([])
  const [isVectorSearching, setIsVectorSearching] = useState(false)
  const [vectorSearchError, setVectorSearchError] = useState<string | null>(null)
  
  // 🆕 批量导入相关状态
  const [showImportDialog, setShowImportDialog] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [isImporting, setIsImporting] = useState(false)
  const [importMessage, setImportMessage] = useState('')
  const [importSeverity, setImportSeverity] = useState<'success' | 'error'>('success')
  const [showImportSnackbar, setShowImportSnackbar] = useState(false)
  
  // 🆕 导出相关状态
  const [exportMenuAnchor, setExportMenuAnchor] = useState<null | HTMLElement>(null)
  const [isExporting, setIsExporting] = useState(false)

  useEffect(() => {
    if (projectId) {
      dispatch(fetchKnowledgeBase(parseInt(projectId)))
    }
  }, [dispatch, projectId])

  const handleAddItem = async () => {
    if (formData.name.trim() && projectId) {
      const data = { name: formData.name, content: formData.content }
      if (dialogType === 'world') {
        await dispatch(addWorldSetting({ projectId: parseInt(projectId), data }))
      } else if (dialogType === 'character') {
        await dispatch(addCharacter({ projectId: parseInt(projectId), data }))
      } else {
        await dispatch(addPlotOutline({ projectId: parseInt(projectId), data }))
      }
      setFormData({ name: '', content: '' })
      setOpenDialog(false)
    }
  }

  const handleDeleteItem = (kbId: number) => {
    setItemToDelete(kbId)
    setDeleteDialogOpen(true)
  }

  const handleConfirmDelete = () => {
    if (projectId && itemToDelete !== null) {
      dispatch(deleteKnowledgeBase({ projectId: parseInt(projectId), kbId: itemToDelete }))
      setDeleteDialogOpen(false)
      setItemToDelete(null)
    }
  }

  const handleCancelDelete = () => {
    setDeleteDialogOpen(false)
    setItemToDelete(null)
  }

  // 🆕 向量搜索功能
  const handleVectorSearch = async () => {
    if (!searchQuery.trim() || !projectId) return

    setIsVectorSearching(true)
    setVectorSearchError(null)

    try {
      logger.log('🔍 执行向量搜索:', searchQuery)
      
      // 根据当前tab确定搜索类型
      const filterTypeMap = ['world_setting', 'character', 'plot_outline']
      const filterType = filterTypeMap[tabValue]

      const response = await fetch('/api/v1/knowledge/search', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          query: searchQuery,
          k: 10,
          filter_type: filterType,
          project_id: parseInt(projectId),
        }),
      })

      if (response.ok) {
        const data = await response.json()
        logger.log('✅ 向量搜索结果:', data)
        setVectorSearchResults(data.results || [])
      } else {
        const errorData = await response.json()
        logger.error('❌ 向量搜索失败:', errorData)
        setVectorSearchError(errorData.error || '搜索失败')
      }
    } catch (error) {
      logger.error('❌ 向量搜索异常:', error)
      setVectorSearchError('搜索失败，请重试')
    } finally {
      setIsVectorSearching(false)
    }
  }

  // 搜索模式切换时重置结果
  const handleSearchModeChange = (_event: React.MouseEvent<HTMLElement>, newMode: 'local' | 'vector' | null) => {
    if (newMode !== null) {
      setSearchMode(newMode)
      setVectorSearchResults([])
      setVectorSearchError(null)
      
      // 如果切换到向量搜索且有搜索词，自动搜索
      if (newMode === 'vector' && searchQuery.trim()) {
        handleVectorSearch()
      }
    }
  }

  // 🆕 批量导入功能
  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (files && files.length > 0) {
      setImportFile(files[0])
    }
  }

  const handleBatchImport = async () => {
    if (!importFile || !projectId) return

    setIsImporting(true)

    try {
      const formData = new FormData()
      formData.append('file', importFile)

      // 根据当前tab确定类型
      const typeMap = ['world', 'character', 'plot']
      const kbType = typeMap[tabValue]

      const response = await fetch(
        `/api/v1/projects/${projectId}/knowledge-base/batch-import?kb_type=${kbType}`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
          body: formData,
        }
      )

      if (response.ok) {
        const data = await response.json()
        logger.log('✅ 批量导入成功:', data)
        
        setImportMessage(`✅ 成功导入 ${data.imported} 条记录`)
        setImportSeverity('success')
        setShowImportSnackbar(true)
        
        // 关闭对话框
        setShowImportDialog(false)
        setImportFile(null)
        
        // 重新加载知识库
        dispatch(fetchKnowledgeBase(parseInt(projectId)))
      } else {
        const errorData = await response.json()
        logger.error('❌ 批量导入失败:', errorData)
        
        setImportMessage(errorData.detail || '导入失败')
        setImportSeverity('error')
        setShowImportSnackbar(true)
      }
    } catch (error) {
      logger.error('❌ 批量导入异常:', error)
      setImportMessage('导入失败，请重试')
      setImportSeverity('error')
      setShowImportSnackbar(true)
    } finally {
      setIsImporting(false)
    }
  }

  // 🆕 导出功能
  const handleExport = async (format: 'json' | 'markdown' | 'csv') => {
    if (!projectId) return

    setIsExporting(true)
    setExportMenuAnchor(null)

    try {
      // 根据当前tab确定类型（可选）
      const typeMap = ['world', 'character', 'plot']
      const kbType = typeMap[tabValue]

      const response = await fetch(
        `/api/v1/projects/${projectId}/knowledge-base/export?format=${format}&kb_type=${kbType}`,
        {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        }
      )

      if (response.ok) {
        // 获取文件内容
        const blob = await response.blob()
        
        // 创建下载链接
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `knowledge_base_${kbType}.${format === 'markdown' ? 'md' : format}`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        window.URL.revokeObjectURL(url)

        setImportMessage(`✅ 导出成功`)
        setImportSeverity('success')
        setShowImportSnackbar(true)
      } else {
        const errorData = await response.json()
        logger.error('❌ 导出失败:', errorData)
        
        setImportMessage(errorData.detail || '导出失败')
        setImportSeverity('error')
        setShowImportSnackbar(true)
      }
    } catch (error) {
      logger.error('❌ 导出异常:', error)
      setImportMessage('导出失败，请重试')
      setImportSeverity('error')
      setShowImportSnackbar(true)
    } finally {
      setIsExporting(false)
    }
  }
  const filterItems = (items: any[]) => {
    if (!searchQuery.trim()) return items
    const query = searchQuery.toLowerCase()
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(query) ||
        item.content.toLowerCase().includes(query)
    )
  }

  // 渲染向量搜索结果
  const renderVectorSearchResults = () => {
    if (vectorSearchResults.length === 0) {
      return (
        <Alert severity="info" sx={{ mt: 2 }}>
          没有找到相关结果，请尝试其他关键词
        </Alert>
      )
    }

    return (
      <Grid container spacing={2} sx={{ mt: 1 }}>
        {vectorSearchResults.map((result, index) => (
          <Grid item xs={12} sm={6} md={4} key={index}>
            <Card sx={{ position: 'relative' }}>
              {/* 相似度分数 */}
              <Chip
                label={`相似度: ${(result.score * 100).toFixed(1)}%`}
                color="primary"
                size="small"
                sx={{ position: 'absolute', top: 8, right: 8 }}
              />
              <CardContent>
                <Typography variant="h6" gutterBottom>
                  {result.metadata?.name || '无标题'}
                </Typography>
                <Typography variant="body2" color="textSecondary">
                  {result.content?.substring(0, 100)}...
                </Typography>
                <Chip
                  label={result.metadata?.type || '未知类型'}
                  size="small"
                  sx={{ mt: 1 }}
                />
              </CardContent>
              <CardActions>
                <Button
                  size="small"
                  onClick={() => {
                    // 点击后跳转到对应的tab
                    const typeMap: Record<string, number> = {
                      'world_setting': 0,
                      'character': 1,
                      'plot_outline': 2,
                    }
                    const targetTab = typeMap[result.metadata?.type] ?? 0
                    setTabValue(targetTab)
                    setSearchMode('local')
                    setSearchQuery(result.metadata?.name || '')
                  }}
                >
                  查看详情
                </Button>
              </CardActions>
            </Card>
          </Grid>
        ))}
      </Grid>
    )
  }

  const renderItems = (items: any[]) => (
    <Grid container spacing={2}>
      {items.map((item) => (
        <Grid item xs={12} sm={6} md={4} key={item.id}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                {item.name}
              </Typography>
              <Typography variant="body2" color="textSecondary">
                {item.content.substring(0, 100)}...
              </Typography>
            </CardContent>
            <CardActions>
              <Button
                size="small"
                color="error"
                startIcon={<DeleteIcon />}
                onClick={() => handleDeleteItem(item.id)}
              >
                Delete
              </Button>
            </CardActions>
          </Card>
        </Grid>
      ))}
    </Grid>
  )

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/dashboard')}
        >
          Back
        </Button>
        <Typography variant="h5">Knowledge Base</Typography>
      </Box>

      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 2 }}>
        <Tabs value={tabValue} onChange={(_e, newValue) => setTabValue(newValue)}>
          <Tab
            label={
              <Badge badgeContent={worldSettings.length} color="primary" max={99}>
                <span style={{ marginRight: '8px' }}>World Settings</span>
              </Badge>
            }
          />
          <Tab
            label={
              <Badge badgeContent={characters.length} color="primary" max={99}>
                <span style={{ marginRight: '8px' }}>Characters</span>
              </Badge>
            }
          />
          <Tab
            label={
              <Badge badgeContent={plotOutline.length} color="primary" max={99}>
                <span style={{ marginRight: '8px' }}>Plot Outline</span>
              </Badge>
            }
          />
        </Tabs>
      </Box>

      {/* 🆕 搜索框和模式切换 */}
      <Box sx={{ mb: 3 }}>
        <Grid container spacing={2} alignItems="center">
          <Grid item xs={12} md={8}>
            <TextField
              fullWidth
              placeholder={
                searchMode === 'local'
                  ? '本地搜索...（匹配名称和内容）'
                  : '语义搜索...（例如：能量操控、时空穿越）'
              }
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyPress={(e) => {
                if (e.key === 'Enter' && searchMode === 'vector') {
                  handleVectorSearch()
                }
              }}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    {searchMode === 'local' ? <SearchIcon /> : <TravelExploreIcon />}
                  </InputAdornment>
                ),
                endAdornment: isVectorSearching ? (
                  <InputAdornment position="end">
                    <CircularProgress size={20} />
                  </InputAdornment>
                ) : null,
              }}
              size="small"
            />
          </Grid>
          <Grid item xs={12} md={4}>
            <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
              {/* 搜索模式切换 */}
              <ToggleButtonGroup
                value={searchMode}
                exclusive
                onChange={handleSearchModeChange}
                size="small"
              >
                <ToggleButton value="local">
                  <SearchIcon sx={{ mr: 0.5 }} />
                  本地搜索
                </ToggleButton>
                <ToggleButton value="vector">
                  <TravelExploreIcon sx={{ mr: 0.5 }} />
                  语义搜索
                </ToggleButton>
              </ToggleButtonGroup>
              
              {/* 向量搜索按钮 */}
              {searchMode === 'vector' && (
                <Button
                  variant="contained"
                  onClick={handleVectorSearch}
                  disabled={!searchQuery.trim() || isVectorSearching}
                >
                  搜索
                </Button>
              )}
            </Box>
          </Grid>
        </Grid>

        {/* 搜索模式提示 */}
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          {searchMode === 'local'
            ? '🔍 本地搜索：匹配标题和内容中的关键词'
            : '🧠 语义搜索：基于AI理解的智能搜索，可找到相关含义的内容'}
        </Typography>

        {/* 错误提示 */}
        {vectorSearchError && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {vectorSearchError}
          </Alert>
        )}
      </Box>

      {/* 🆕 向量搜索结果展示 */}
      {searchMode === 'vector' && vectorSearchResults.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Typography variant="h6" gutterBottom>
            搜索结果 ({vectorSearchResults.length}条)
          </Typography>
          {renderVectorSearchResults()}
        </Box>
      )}

      <TabPanel value={tabValue} index={0}>
        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              setDialogType('world')
              setOpenDialog(true)
            }}
          >
            Add World Setting
          </Button>
          <Button
            variant="outlined"
            startIcon={<UploadIcon />}
            onClick={() => setShowImportDialog(true)}
          >
            Batch Import
          </Button>
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={(e) => setExportMenuAnchor(e.currentTarget)}
            disabled={isExporting}
          >
            Export
          </Button>
        </Box>
        {renderItems(filterItems(worldSettings))}
      </TabPanel>

      <TabPanel value={tabValue} index={1}>
        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              setDialogType('character')
              setOpenDialog(true)
            }}
          >
            Add Character
          </Button>
          <Button
            variant="outlined"
            startIcon={<UploadIcon />}
            onClick={() => setShowImportDialog(true)}
          >
            Batch Import
          </Button>
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={(e) => setExportMenuAnchor(e.currentTarget)}
            disabled={isExporting}
          >
            Export
          </Button>
        </Box>
        {renderItems(filterItems(characters))}
      </TabPanel>

      <TabPanel value={tabValue} index={2}>
        <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => {
              setDialogType('plot')
              setOpenDialog(true)
            }}
          >
            Add Plot Outline
          </Button>
          <Button
            variant="outlined"
            startIcon={<UploadIcon />}
            onClick={() => setShowImportDialog(true)}
          >
            Batch Import
          </Button>
          <Button
            variant="outlined"
            startIcon={<DownloadIcon />}
            onClick={(e) => setExportMenuAnchor(e.currentTarget)}
            disabled={isExporting}
          >
            Export
          </Button>
        </Box>
        {renderItems(filterItems(plotOutline))}
      </TabPanel>

      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Add New Item
          </Typography>
          <TextField
            fullWidth
            label="Name"
            value={formData.name}
            onChange={(e) => setFormData({ ...formData, name: e.target.value })}
            margin="normal"
            required
          />
          <TextField
            fullWidth
            label="Content"
            value={formData.content}
            onChange={(e) => setFormData({ ...formData, content: e.target.value })}
            margin="normal"
            multiline
            rows={4}
            required
          />
          <Box sx={{ mt: 3, display: 'flex', gap: 2 }}>
            <Button
              variant="contained"
              color="primary"
              fullWidth
              onClick={handleAddItem}
            >
              Add
            </Button>
            <Button
              variant="outlined"
              fullWidth
              onClick={() => setOpenDialog(false)}
            >
              Cancel
            </Button>
          </Box>
        </Box>
      </Dialog>
      {/* 导出菜单 */}
      <Menu
        anchorEl={exportMenuAnchor}
        open={Boolean(exportMenuAnchor)}
        onClose={() => setExportMenuAnchor(null)}
      >
        <MenuItem onClick={() => handleExport('json')}>
          Export as JSON
        </MenuItem>
        <MenuItem onClick={() => handleExport('markdown')}>
          Export as Markdown
        </MenuItem>
        <MenuItem onClick={() => handleExport('csv')}>
          Export as CSV
        </MenuItem>
      </Menu>

      {/* 批量导入对话框 */}
      <Dialog open={showImportDialog} onClose={() => setShowImportDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Batch Import
          </Typography>
          
          <Alert severity="info" sx={{ mb: 2 }}>
            <Typography variant="body2" gutterBottom>
              <strong>Supported Formats:</strong>
            </Typography>
            <Typography variant="caption" component="div">
              • <strong>CSV:</strong> name,content<br />
              • <strong>JSON:</strong> {'[{"name": "...", "content": "..."}]'}<br />
              • <strong>Markdown:</strong> # Name\nContent...
            </Typography>
          </Alert>

          <input
            type="file"
            accept=".csv,.json,.md,.markdown"
            onChange={handleFileSelect}
            style={{ marginBottom: '16px', width: '100%' }}
          />
          
          {importFile && (
            <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
              Selected: {importFile.name}
            </Typography>
          )}

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Button
              variant="contained"
              color="primary"
              fullWidth
              onClick={handleBatchImport}
              disabled={!importFile || isImporting}
              startIcon={isImporting ? <CircularProgress size={20} /> : <UploadIcon />}
            >
              {isImporting ? 'Importing...' : 'Import'}
            </Button>
            <Button
              variant="outlined"
              fullWidth
              onClick={() => {
                setShowImportDialog(false)
                setImportFile(null)
              }}
              disabled={isImporting}
            >
              Cancel
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 导入结果提示 */}
      <Snackbar
        open={showImportSnackbar}
        autoHideDuration={3000}
        onClose={() => setShowImportSnackbar(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert severity={importSeverity} onClose={() => setShowImportSnackbar(false)}>
          {importMessage}
        </Alert>
      </Snackbar>

      {/* 删除确认对话框 */}
      <Dialog
        open={deleteDialogOpen}
        onClose={handleCancelDelete}
        aria-labelledby="delete-dialog-title"
        aria-describedby="delete-dialog-description"
      >
        <DialogTitle id="delete-dialog-title">
          确认删除
        </DialogTitle>
        <DialogContent>
          <DialogContentText id="delete-dialog-description">
            确定要删除这个项目吗？此操作无法撤销。
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelDelete} color="primary">
            取消
          </Button>
          <Button onClick={handleConfirmDelete} color="error" variant="contained" autoFocus>
            删除
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  )
}

