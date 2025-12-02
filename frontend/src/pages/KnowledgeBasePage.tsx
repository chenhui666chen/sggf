import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Container,
  Box,
  Tabs,
  Tab,
  Button,
  Typography,
  CircularProgress,
  Alert,
  Snackbar,
  Paper,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  Chip,
  Grid,
  Divider,
  Select,
  FormControl,
  InputLabel,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import SaveIcon from '@mui/icons-material/Save'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import FolderIcon from '@mui/icons-material/Folder'
import ArticleIcon from '@mui/icons-material/Article'
import { logger } from '@/utils/logger'
import MarkdownRenderer from '@/components/MarkdownRenderer'
import VditorEditor from '@/components/VditorEditor'
import { apiClient } from '@/services/api'

// ==================== 接口定义 ====================

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

interface SettingCollection {
  id: number
  name: string
  category: string
  description?: string
  max_depth?: number
  hierarchy_config?: string
  order: number
  created_at: string
}

interface SettingItem {
  id: number
  collection_id: number
  name: string
  code?: string
  level?: number
  tags?: string[]
  content?: string
  depth?: number
  node_type?: string
  is_leaf?: boolean
  path?: string
  summary?: string
  order: number
  created_at: string
}

// ==================== 组件定义 ====================

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props
  return (
    <div role="tabpanel" hidden={value !== index} {...other}>
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  )
}

// Category 中文名称映射（完整版 - 27种体系）
const CATEGORY_NAME_MAP: Record<string, string> = {
  // 地理与世界观
  map_system: '地图体系',
  
  // 修仙/玄幻体系
  cultivation_realm_system: '修仙境界体系',
  martial_realm_system: '武道境界体系',
  technique_system: '功法体系',
  pill_system: '丹药体系',
  formation_system: '阵法体系',
  talisman_system: '符箓体系',
  weapon_system: '武器与法宝体系',
  resource_system: '资源体系',
  force_system: '势力体系',
  
  // 都市异能体系
  ability_realm_system: '异能境界体系',
  ability_awakening_growth_system: '异能体系',
  hidden_organization_force_system: '组织势力体系',
  network_social_relationship_system: '人脉关系体系',
  special_artifact_relic_system: '道具遗物体系',
  wealth_business_empire_system: '财富商业体系',
  
  // 西幻/魔法体系
  magic_realm_system: '魔法境界体系',
  magic_system: '魔法体系',
  race_bloodline_system: '种族血脉体系',
  profession_class_system: '职业体系',
  
  // 科幻体系
  interstellar_travel_exploration_system: '星际航行体系',
  ai_robot_system: 'AI机器人体系',
  
  // 末世废土体系
  survivor_settlement_order_system: '聚落秩序体系',
  mutation_infection_aberration_system: '变异感染体系',
  
  // 游戏系统体系
  game_skill_talent_system: '技能天赋体系',
  skill_talent_system: '技能天赋体系',
  
  // 角色体系
  character_system: '角色体系',
  
  // 特殊
  candidate: '候选集合',
  organization_system: '组织体系',
  artifact_system: '法宝体系',
}

// ==================== 主组件 ====================

export default function KnowledgeBasePage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  // 主 Tab 状态 (0=文本内容, 1=类型设定)
  const [mainTabValue, setMainTabValue] = useState(1)

  // ==================== 文本内容相关状态 ====================
  const [textTabValue, setTextTabValue] = useState(0)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [worldSetting, setWorldSetting] = useState('')
  const [characters, setCharacters] = useState('')
  const [plotOutline, setPlotOutline] = useState('')

  const [isEditing, setIsEditing] = useState(false)
  const [editedContent, setEditedContent] = useState('')

  // ==================== 类型设定相关状态 ====================
  const [collections, setCollections] = useState<SettingCollection[]>([])
  const [selectedCollection, setSelectedCollection] = useState<SettingCollection | null>(null)
  const [settingItems, setSettingItems] = useState<SettingItem[]>([])
  const [selectedItem, setSelectedItem] = useState<SettingItem | null>(null)
  const [loadingCollections, setLoadingCollections] = useState(false)
  const [loadingItems, setLoadingItems] = useState(false)

  // 快速添加体系
  const [selectedCategoryToAdd, setSelectedCategoryToAdd] = useState<string>('')

  // 对话框状态
  const [createCollectionDialog, setCreateCollectionDialog] = useState(false)
  const [createItemDialog, setCreateItemDialog] = useState(false)
  const [editItemDialog, setEditItemDialog] = useState(false)
  const [templateDialog, setTemplateDialog] = useState(false)

  // 表单数据
  const [newCollectionName, setNewCollectionName] = useState('')
  const [newCollectionCategory, setNewCollectionCategory] = useState('')
  const [newCollectionDescription, setNewCollectionDescription] = useState('')
  const [selectedTemplate, setSelectedTemplate] = useState('')

  const [newItemName, setNewItemName] = useState('')
  const [newItemCode, setNewItemCode] = useState('')
  const [newItemLevel, setNewItemLevel] = useState(1)
  const [newItemContent, setNewItemContent] = useState('')
  const [newItemTags, setNewItemTags] = useState('')

  // 提示消息
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')

  // ==================== 生命周期 ====================

  useEffect(() => {
    if (mainTabValue === 0) {
      loadWorkflowData()
    } else {
      loadSettingCollections()
    }
  }, [projectId, mainTabValue])

  useEffect(() => {
    if (selectedCollection) {
      loadSettingItems(selectedCollection.id)
    } else {
      setSettingItems([])
      setSelectedItem(null)
    }
  }, [selectedCollection])

  // ==================== 文本内容相关函数 ====================

  const loadWorkflowData = async () => {
    if (!projectId) return

    setLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const stages = data.stages || {}
        setWorldSetting(parseContent(stages.world_setting))
        setCharacters(parseContent(stages.characters))
        setPlotOutline(parseContent(stages.plot_outline))
      } else {
        const errorData = await response.json()
        setError(errorData.detail || '加载失败')
      }
    } catch (err) {
      logger.error('❌ 加载工作流数据失败:', err)
      setError('加载失败，请重试')
    } finally {
      setLoading(false)
    }
  }

  const parseContent = (content: any): string => {
    if (!content) return ''
    if (typeof content === 'string') {
      try {
        if (content.startsWith('"') || content.startsWith('[')) {
          const parsed = JSON.parse(content)
          if (Array.isArray(parsed)) {
            return parsed.map(item =>
              typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)
            ).join('\n\n')
          }
          return String(parsed)
        }
      } catch {}
      return content
    }
    if (Array.isArray(content)) {
      return content.map(item =>
        typeof item === 'object' ? JSON.stringify(item, null, 2) : String(item)
      ).join('\n\n')
    }
    if (typeof content === 'object') {
      return JSON.stringify(content, null, 2)
    }
    return String(content)
  }

  const getCurrentContent = (): string => {
    switch (textTabValue) {
      case 0: return worldSetting
      case 1: return characters
      case 2: return plotOutline
      default: return ''
    }
  }

  const getCurrentStage = (): string => {
    switch (textTabValue) {
      case 0: return 'world_builder'
      case 1: return 'character_designer'
      case 2: return 'structure'
      default: return ''
    }
  }

  const handleStartEdit = () => {
    setEditedContent(getCurrentContent())
    setIsEditing(true)
  }

  const handleCancelEdit = () => {
    setIsEditing(false)
    setEditedContent('')
  }

  const handleSaveEdit = async () => {
    if (!projectId) return

    setSaving(true)

    try {
      const stage = getCurrentStage()
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/${stage}/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        switch (textTabValue) {
          case 0: setWorldSetting(editedContent); break
          case 1: setCharacters(editedContent); break
          case 2: setPlotOutline(editedContent); break
        }

        setIsEditing(false)
        showSnackbar('✅ 保存成功', 'success')
      } else {
        const errorData = await response.json()
        showSnackbar(errorData.detail || '保存失败', 'error')
      }
    } catch (err) {
      logger.error('❌ 保存失败:', err)
      showSnackbar('保存失败，请重试', 'error')
    } finally {
      setSaving(false)
    }
  }

  const getTabTitle = (): string => {
    switch (textTabValue) {
      case 0: return '世界观设定'
      case 1: return '人物设定'
      case 2: return '剧情大纲'
      default: return ''
    }
  }

  // ==================== 类型设定相关函数 ====================

  const loadSettingCollections = async () => {
    if (!projectId) return

    setLoadingCollections(true)

    try {
      const response = await apiClient.getSettingCollections(Number(projectId))
      setCollections(response.data || [])
      if (response.data && response.data.length > 0 && !selectedCollection) {
        setSelectedCollection(response.data[0])
      }
    } catch (err) {
      logger.error('❌ 加载设定集合失败:', err)
      showSnackbar('加载设定集合失败', 'error')
    } finally {
      setLoadingCollections(false)
    }
  }

  const loadSettingItems = async (collectionId: number) => {
    setLoadingItems(true)

    try {
      const response = await apiClient.getSettingItems(collectionId)
      const items = response.data || []
      // 按 depth 和 order 排序
      items.sort((a: SettingItem, b: SettingItem) => {
        if (a.depth !== b.depth) return (a.depth || 0) - (b.depth || 0)
        return a.order - b.order
      })
      setSettingItems(items)
    } catch (err) {
      logger.error('❌ 加载设定项失败:', err)
      showSnackbar('加载设定项失败', 'error')
    } finally {
      setLoadingItems(false)
    }
  }

  const handleCreateCollection = async () => {
    if (!projectId || !newCollectionName || !newCollectionCategory) {
      showSnackbar('请填写必填项', 'error')
      return
    }

    try {
      const response = await apiClient.createSettingCollection(Number(projectId), {
        name: newCollectionName,
        category: newCollectionCategory,
        description: newCollectionDescription,
        order: collections.length,
      })

      setCollections([...collections, response.data])
      setSelectedCollection(response.data)
      setCreateCollectionDialog(false)
      resetCollectionForm()
      showSnackbar('✅ 创建成功', 'success')
    } catch (err) {
      logger.error('❌ 创建集合失败:', err)
      showSnackbar('创建失败', 'error')
    }
  }

  const handleApplyTemplate = async () => {
    if (!projectId || !selectedTemplate) {
      showSnackbar('请选择模板', 'error')
      return
    }

    try {
      const response = await fetch(`/api/v1/projects/${projectId}/setting-collections/from-template`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          template_name: selectedTemplate,
          replace_existing: false,
        }),
      })

      if (response.ok) {
        await loadSettingCollections()
        setTemplateDialog(false)
        setSelectedTemplate('')
        showSnackbar('✅ 模板应用成功', 'success')
      } else {
        const errorData = await response.json()
        showSnackbar(errorData.detail || '应用模板失败', 'error')
      }
    } catch (err) {
      logger.error('❌ 应用模板失败:', err)
      showSnackbar('应用模板失败', 'error')
    }
  }

  const handleDeleteCollection = async (collectionId: number) => {
    if (!confirm('确定要删除这个设定集合吗？')) return

    try {
      await apiClient.deleteSettingCollection(collectionId)
      const newCollections = collections.filter(c => c.id !== collectionId)
      setCollections(newCollections)
      if (selectedCollection?.id === collectionId) {
        setSelectedCollection(newCollections[0] || null)
      }
      showSnackbar('✅ 删除成功', 'success')
    } catch (err) {
      logger.error('❌ 删除集合失败:', err)
      showSnackbar('删除失败', 'error')
    }
  }

  const handleCreateItem = async () => {
    if (!selectedCollection || !newItemName) {
      showSnackbar('请填写设定项名称', 'error')
      return
    }

    try {
      await apiClient.createSettingItem(selectedCollection.id, {
        name: newItemName,
        code: newItemCode,
        level: newItemLevel,
        content: newItemContent,
        tags: newItemTags ? newItemTags.split(',').map(t => t.trim()) : [],
        order: settingItems.length,
        depth: newItemLevel,
        is_leaf: true,
      })

      await loadSettingItems(selectedCollection.id)
      setCreateItemDialog(false)
      resetItemForm()
      showSnackbar('✅ 创建成功', 'success')
    } catch (err) {
      logger.error('❌ 创建设定项失败:', err)
      showSnackbar('创建失败', 'error')
    }
  }

  const handleEditItem = () => {
    if (!selectedItem) return

    setNewItemName(selectedItem.name)
    setNewItemCode(selectedItem.code || '')
    setNewItemLevel(selectedItem.level || 1)
    setNewItemContent(selectedItem.content || '')
    setNewItemTags(selectedItem.tags?.join(', ') || '')
    setEditItemDialog(true)
  }

  const handleSaveItemEdit = async () => {
    if (!selectedItem || !newItemName) return

    try {
      await apiClient.updateSettingItem(selectedItem.id, {
        name: newItemName,
        code: newItemCode,
        level: newItemLevel,
        content: newItemContent,
        tags: newItemTags ? newItemTags.split(',').map(t => t.trim()) : [],
      })

      await loadSettingItems(selectedItem.collection_id)
      setEditItemDialog(false)
      resetItemForm()
      showSnackbar('✅ 保存成功', 'success')
    } catch (err) {
      logger.error('❌ 保存设定项失败:', err)
      showSnackbar('保存失败', 'error')
    }
  }

  const handleDeleteItem = async (itemId: number) => {
    if (!confirm('确定要删除这个设定项吗？')) return

    try {
      await apiClient.deleteSettingItem(itemId)
      await loadSettingItems(selectedCollection!.id)
      if (selectedItem?.id === itemId) {
        setSelectedItem(null)
      }
      showSnackbar('✅ 删除成功', 'success')
    } catch (err) {
      logger.error('❌ 删除设定项失败:', err)
      showSnackbar('删除失败', 'error')
    }
  }

  const handleDuplicateItem = async (item: SettingItem) => {
    if (!selectedCollection) return

    try {
      await apiClient.createSettingItem(selectedCollection.id, {
        name: `${item.name} (副本)`,
        code: item.code,
        level: item.level,
        content: item.content,
        tags: item.tags,
        order: settingItems.length,
        depth: item.depth,
        is_leaf: item.is_leaf,
      })

      await loadSettingItems(selectedCollection.id)
      showSnackbar('✅ 复制成功', 'success')
    } catch (err) {
      logger.error('❌ 复制设定项失败:', err)
      showSnackbar('复制失败', 'error')
    }
  }

  const resetCollectionForm = () => {
    setNewCollectionName('')
    setNewCollectionCategory('')
    setNewCollectionDescription('')
  }

  const resetItemForm = () => {
    setNewItemName('')
    setNewItemCode('')
    setNewItemLevel(1)
    setNewItemContent('')
    setNewItemTags('')
  }

  const showSnackbar = (message: string, severity: 'success' | 'error') => {
    setSnackbarMessage(message)
    setSnackbarSeverity(severity)
    setSnackbarOpen(true)
  }

  // ==================== 辅助函数 ====================

  const getCategoryDisplayName = (category: string): string => {
    return CATEGORY_NAME_MAP[category] || category
  }

  const getIndentForItem = (item: SettingItem): number => {
    return ((item.depth || 1) - 1) * 24
  }

  const getAvailableCategoriesToAdd = (): string[] => {
    const existingCategories = new Set(collections.map(c => c.category))
    return Object.keys(CATEGORY_NAME_MAP).filter(key => !existingCategories.has(key)).sort()
  }

  const handleQuickAddCategory = async (category: string) => {
    if (!projectId || !category) return

    try {
      const collectionName = getCategoryDisplayName(category)
      const response = await apiClient.createSettingCollection(Number(projectId), {
        name: collectionName,
        category: category,
        description: `${collectionName}设定`,
        order: collections.length,
      })

      setCollections([...collections, response.data])
      setSelectedCollection(response.data)
      showSnackbar(`✅ 已添加「${collectionName}」`, 'success')
      setSelectedCategoryToAdd('')
    } catch (err) {
      logger.error('✅ 快速添加体系失败:', err)
      showSnackbar('添加体系失败', 'error')
    }
  }

  // ==================== 渲染 ====================

  return (
    <Container maxWidth="xl" sx={{ py: 4 }}>
      {/* 页面标题栏 */}
      <Box sx={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        mb: 3,
        pb: 2,
        borderBottom: '2px solid',
        borderColor: 'primary.light'
      }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/dashboard')}
          sx={{ fontWeight: 500 }}
        >
          ← 返回
        </Button>
        <Typography variant="h5" sx={{
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 1
        }}>
          🌍 世界观设定文档
        </Typography>
      </Box>

      {/* 主 Tab 导航 */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs
          value={mainTabValue}
          onChange={(_, newValue) => setMainTabValue(newValue)}
          sx={{
            '& .MuiTab-root': {
              fontWeight: 600,
              fontSize: '1rem',
              minHeight: 56,
            }
          }}
        >
          <Tab label="📝 文本内容" />
          <Tab label="🎨 类型设定" />
        </Tabs>
      </Box>

      {/* ==================== Tab 0: 文本内容 ==================== */}
      <TabPanel value={mainTabValue} index={0}>
        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
            <CircularProgress />
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 3 }}>
            {error}
            <Button size="small" onClick={loadWorkflowData} sx={{ ml: 2 }}>
              重试
            </Button>
          </Alert>
        )}

        {!loading && !error && (
          <>
            <Box sx={{
              borderBottom: 1,
              borderColor: 'divider',
              mb: 2,
              bgcolor: 'grey.50',
              borderRadius: '8px 8px 0 0'
            }}>
              <Tabs
                value={textTabValue}
                onChange={(_, newValue) => {
                  if (isEditing) {
                    setIsEditing(false)
                    setEditedContent('')
                  }
                  setTextTabValue(newValue)
                }}
                sx={{
                  '& .MuiTab-root': {
                    fontWeight: 500,
                    fontSize: '0.95rem',
                    minHeight: 56,
                  }
                }}
              >
                <Tab icon={<span style={{ marginRight: 8 }}>🌍</span>} iconPosition="start" label="世界观设定" />
                <Tab icon={<span style={{ marginRight: 8 }}>👥</span>} iconPosition="start" label="人物设定" />
                <Tab icon={<span style={{ marginRight: 8 }}>📋</span>} iconPosition="start" label="剧情大纲" />
              </Tabs>
            </Box>

            <Alert severity="info" sx={{ mb: 3 }}>
              📖 此页面展示工作流生成的设定数据，编辑后将同步到工作流中
            </Alert>

            <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
              {!isEditing ? (
                <Button
                  variant="contained"
                  startIcon={<EditIcon />}
                  onClick={handleStartEdit}
                  disabled={!getCurrentContent()}
                  sx={{ borderRadius: 2 }}
                >
                  编辑{getTabTitle()}
                </Button>
              ) : (
                <>
                  <Button
                    variant="contained"
                    color="primary"
                    startIcon={saving ? <CircularProgress size={20} /> : <SaveIcon />}
                    onClick={handleSaveEdit}
                    disabled={saving}
                    sx={{ borderRadius: 2 }}
                  >
                    {saving ? '保存中...' : '保存'}
                  </Button>
                  <Button
                    variant="outlined"
                    onClick={handleCancelEdit}
                    disabled={saving}
                    sx={{ borderRadius: 2 }}
                  >
                    取消
                  </Button>
                </>
              )}
            </Box>

            {[0, 1, 2].map(index => (
              <TabPanel key={index} value={textTabValue} index={index}>
                {isEditing ? (
                  <VditorEditor
                    value={editedContent}
                    onChange={(val) => setEditedContent(val)}
                    placeholder={`${getTabTitle()}内容（支持 Markdown 格式）...`}
                    height={500}
                  />
                ) : (
                  <Paper
                    elevation={0}
                    sx={{
                      bgcolor: 'background.paper',
                      p: 4,
                      borderRadius: 2,
                      minHeight: 400,
                      border: '1px solid',
                      borderColor: 'grey.200',
                    }}
                  >
                    {getCurrentContent() ? (
                      <MarkdownRenderer content={getCurrentContent()} />
                    ) : (
                      <Typography color="text.secondary" sx={{ textAlign: 'center', py: 8 }}>
                        📭 暂无{getTabTitle()}，请先在工作流中生成
                      </Typography>
                    )}
                  </Paper>
                )}
              </TabPanel>
            ))}
          </>
        )}
      </TabPanel>

      {/* ==================== Tab 1: 类型设定 ==================== */}
      <TabPanel value={mainTabValue} index={1}>
        <Grid container spacing={3}>
          {/* 左侧：设定集合列表 */}
          <Grid item xs={12} md={4}>
            <Paper elevation={2} sx={{ p: 2, height: '70vh', display: 'flex', flexDirection: 'column' }}>
              {/* 操作按钮 */}
              <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<AddIcon />}
                  onClick={() => setTemplateDialog(true)}
                  fullWidth
                >
                  从模板创建
                </Button>
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<AddIcon />}
                  onClick={() => setCreateCollectionDialog(true)}
                  fullWidth
                >
                  新建
                </Button>
              </Box>

              {/* 快速添加体系下拉框 */}
              {getAvailableCategoriesToAdd().length > 0 && (
                <FormControl size="small" fullWidth sx={{ mb: 2 }}>
                  <InputLabel>快速添加体系</InputLabel>
                  <Select
                    value={selectedCategoryToAdd}
                    label="快速添加体系"
                    onChange={(e) => {
                      const category = e.target.value
                      setSelectedCategoryToAdd(category)
                      if (category) {
                        handleQuickAddCategory(category)
                      }
                    }}
                  >
                    <MenuItem value="">请选择要添加的体系...</MenuItem>
                    {getAvailableCategoriesToAdd().map(cat => (
                      <MenuItem key={cat} value={cat}>
                        {getCategoryDisplayName(cat)}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}

              <Divider sx={{ mb: 2 }} />

              {/* 集合列表 */}
              {loadingCollections ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                  <CircularProgress />
                </Box>
              ) : collections.length === 0 ? (
                <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
                  暂无设定集合
                </Typography>
              ) : (
                <List sx={{ flexGrow: 1, overflow: 'auto' }}>
                  {collections.map((collection) => (
                    <ListItem
                      key={collection.id}
                      disablePadding
                      secondaryAction={
                        <IconButton
                          edge="end"
                          size="small"
                          onClick={() => handleDeleteCollection(collection.id)}
                        >
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      }
                    >
                      <ListItemButton
                        selected={selectedCollection?.id === collection.id}
                        onClick={() => setSelectedCollection(collection)}
                        sx={{ pr: 6 }}
                      >
                        <FolderIcon sx={{ mr: 1, color: 'primary.main' }} />
                        <ListItemText
                          primary={collection.name}
                          secondary={getCategoryDisplayName(collection.category)}
                          primaryTypographyProps={{ fontWeight: 500 }}
                        />
                      </ListItemButton>
                    </ListItem>
                  ))}
                </List>
              )}
            </Paper>
          </Grid>

          {/* 右侧：设定项列表 */}
          <Grid item xs={12} md={8}>
            <Paper elevation={2} sx={{ p: 2, height: '70vh', display: 'flex', flexDirection: 'column' }}>
              {selectedCollection ? (
                <>
                  {/* 标题和操作按钮 */}
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                    <Box>
                      <Typography variant="h6" sx={{ fontWeight: 600 }}>
                        设定项
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {getCategoryDisplayName(selectedCollection.category)} • 共 {settingItems.length} 项
                      </Typography>
                    </Box>
                    <Button
                      variant="contained"
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={() => setCreateItemDialog(true)}
                    >
                      新建设定项
                    </Button>
                  </Box>

                  <Divider sx={{ mb: 2 }} />

                  {/* 设定项列表 */}
                  {loadingItems ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                      <CircularProgress />
                    </Box>
                  ) : settingItems.length === 0 ? (
                    <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
                      暂无设定项
                    </Typography>
                  ) : (
                    <List sx={{ flexGrow: 1, overflow: 'auto' }}>
                      {settingItems.map((item) => (
                        <ListItem
                          key={item.id}
                          disablePadding
                          secondaryAction={
                            <Box>
                              <IconButton
                                edge="end"
                                size="small"
                                onClick={() => handleDuplicateItem(item)}
                              >
                                <ContentCopyIcon fontSize="small" />
                              </IconButton>
                              <IconButton
                                edge="end"
                                size="small"
                                onClick={() => handleDeleteItem(item.id)}
                              >
                                <DeleteIcon fontSize="small" />
                              </IconButton>
                            </Box>
                          }
                        >
                          <ListItemButton
                            selected={selectedItem?.id === item.id}
                            onClick={() => setSelectedItem(item)}
                            sx={{ pr: 10, pl: `${getIndentForItem(item) + 8}px` }}
                          >
                            <ArticleIcon sx={{ mr: 1, fontSize: 18, color: 'text.secondary' }} />
                            <ListItemText
                              primary={
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                  <Typography component="span" sx={{ fontWeight: 500 }}>
                                    Lv.{item.level || 1} {item.name}
                                  </Typography>
                                  {item.code && (
                                    <Chip label={item.code} size="small" variant="outlined" sx={{ height: 20 }} />
                                  )}
                                </Box>
                              }
                              secondary={item.summary || item.content?.substring(0, 50)}
                            />
                          </ListItemButton>
                        </ListItem>
                      ))}
                    </List>
                  )}

                  {/* 设定项详情 */}
                  {selectedItem && (
                    <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
                      <Box sx={{ display: 'flex', justifyContent: 'between', alignItems: 'center', mb: 1 }}>
                        <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                          {selectedItem.name}
                        </Typography>
                        <Button size="small" startIcon={<EditIcon />} onClick={handleEditItem}>
                          编辑
                        </Button>
                      </Box>
                      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', color: 'text.secondary' }}>
                        {selectedItem.content || '暂无内容'}
                      </Typography>
                      {selectedItem.tags && selectedItem.tags.length > 0 && (
                        <Box sx={{ mt: 1, display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                          {selectedItem.tags.map((tag, idx) => (
                            <Chip key={idx} label={tag} size="small" />
                          ))}
                        </Box>
                      )}
                    </Box>
                  )}
                </>
              ) : (
                <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
                  请选择一个设定集合
                </Typography>
              )}
            </Paper>
          </Grid>
        </Grid>
      </TabPanel>

      {/* ==================== 对话框 ==================== */}

      {/* 创建设定集合对话框 */}
      <Dialog open={createCollectionDialog} onClose={() => setCreateCollectionDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>新建设定集合</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label="集合名称 *"
            fullWidth
            value={newCollectionName}
            onChange={(e) => setNewCollectionName(e.target.value)}
          />
          <FormControl fullWidth margin="dense">
            <InputLabel>分类 *</InputLabel>
            <Select
              value={newCollectionCategory}
              label="分类 *"
              onChange={(e) => setNewCollectionCategory(e.target.value)}
            >
              {Object.entries(CATEGORY_NAME_MAP).map(([key, name]) => (
                <MenuItem key={key} value={key}>{name}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            margin="dense"
            label="描述"
            fullWidth
            multiline
            rows={3}
            value={newCollectionDescription}
            onChange={(e) => setNewCollectionDescription(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setCreateCollectionDialog(false); resetCollectionForm() }}>取消</Button>
          <Button onClick={handleCreateCollection} variant="contained">创建</Button>
        </DialogActions>
      </Dialog>

      {/* 从模板创建对话框 */}
      <Dialog open={templateDialog} onClose={() => setTemplateDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>从模板创建设定集合</DialogTitle>
        <DialogContent>
          <FormControl fullWidth margin="dense">
            <InputLabel>选择模板</InputLabel>
            <Select
              value={selectedTemplate}
              label="选择模板"
              onChange={(e) => setSelectedTemplate(e.target.value)}
            >
              <MenuItem value="xianxia">修仙模板</MenuItem>
              <MenuItem value="xuanhuan">玄幻模板</MenuItem>
              <MenuItem value="wuxia">武侠模板</MenuItem>
              <MenuItem value="modern_fantasy">现代奇幻模板</MenuItem>
              <MenuItem value="scifi">科幻模板</MenuItem>
            </Select>
          </FormControl>
          <Alert severity="info" sx={{ mt: 2 }}>
            将根据所选模板自动创建多个设定集合和预设项
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setTemplateDialog(false); setSelectedTemplate('') }}>取消</Button>
          <Button onClick={handleApplyTemplate} variant="contained">应用</Button>
        </DialogActions>
      </Dialog>

      {/* 创建设定项对话框 */}
      <Dialog open={createItemDialog} onClose={() => setCreateItemDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>新建设定项</DialogTitle>
        <DialogContent>
          <Grid container spacing={2}>
            <Grid item xs={8}>
              <TextField
                autoFocus
                margin="dense"
                label="设定项名称 *"
                fullWidth
                value={newItemName}
                onChange={(e) => setNewItemName(e.target.value)}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label="代码"
                fullWidth
                value={newItemCode}
                onChange={(e) => setNewItemCode(e.target.value)}
                placeholder="TAL_FIRE"
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label="等级"
                type="number"
                fullWidth
                value={newItemLevel}
                onChange={(e) => setNewItemLevel(Number(e.target.value))}
                inputProps={{ min: 1, max: 10 }}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label="标签（逗号分隔）"
                fullWidth
                value={newItemTags}
                onChange={(e) => setNewItemTags(e.target.value)}
                placeholder="火系, 攻击型"
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label="内容"
                fullWidth
                multiline
                rows={6}
                value={newItemContent}
                onChange={(e) => setNewItemContent(e.target.value)}
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setCreateItemDialog(false); resetItemForm() }}>取消</Button>
          <Button onClick={handleCreateItem} variant="contained">创建</Button>
        </DialogActions>
      </Dialog>

      {/* 编辑设定项对话框 */}
      <Dialog open={editItemDialog} onClose={() => setEditItemDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>编辑设定项</DialogTitle>
        <DialogContent>
          <Grid container spacing={2}>
            <Grid item xs={8}>
              <TextField
                autoFocus
                margin="dense"
                label="设定项名称 *"
                fullWidth
                value={newItemName}
                onChange={(e) => setNewItemName(e.target.value)}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label="代码"
                fullWidth
                value={newItemCode}
                onChange={(e) => setNewItemCode(e.target.value)}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label="等级"
                type="number"
                fullWidth
                value={newItemLevel}
                onChange={(e) => setNewItemLevel(Number(e.target.value))}
                inputProps={{ min: 1, max: 10 }}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label="标签（逗号分隔）"
                fullWidth
                value={newItemTags}
                onChange={(e) => setNewItemTags(e.target.value)}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label="内容"
                fullWidth
                multiline
                rows={6}
                value={newItemContent}
                onChange={(e) => setNewItemContent(e.target.value)}
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setEditItemDialog(false); resetItemForm() }}>取消</Button>
          <Button onClick={handleSaveItemEdit} variant="contained">保存</Button>
        </DialogActions>
      </Dialog>

      {/* 提示消息 */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={3000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert severity={snackbarSeverity} onClose={() => setSnackbarOpen(false)}>
          {snackbarMessage}
        </Alert>
      </Snackbar>
    </Container>
  )
}
