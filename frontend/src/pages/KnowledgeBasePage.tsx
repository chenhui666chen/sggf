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
import DownloadIcon from '@mui/icons-material/Download'
import HistoryIcon from '@mui/icons-material/History'
import LinearProgress from '@mui/material/LinearProgress'
import Tooltip from '@mui/material/Tooltip'
import { logger } from '@/utils/logger'
import MarkdownRenderer from '@/components/MarkdownRenderer'
import VditorEditor from '@/components/VditorEditor'
import { apiClient } from '@/services/api'
import SettingTreeView from '@/components/SettingTreeView'

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
  skill_talent_system: '技能天赋体系',
  
  // 角色体系
  character_system: '角色体系',
  
  // 特殊
  candidate: '候选集合',
  organization_system: '组织体系',
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
  const [selectedCategoryPath, setSelectedCategoryPath] = useState<string | null>(null)
  
  // 模板相关状态
  const [settingTemplates, setSettingTemplates] = useState<any[]>([])
  const [settingTemplatesLoading, setSettingTemplatesLoading] = useState(false)
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string | null>(null)
  const [clearExistingSettings, setClearExistingSettings] = useState(false)
  const [applyingTemplate, setApplyingTemplate] = useState(false)
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

  const [newItemName, setNewItemName] = useState('')
  const [newItemCode, setNewItemCode] = useState('')
  const [newItemLevel, setNewItemLevel] = useState(1)
  const [newItemContent, setNewItemContent] = useState('')
  const [newItemTags, setNewItemTags] = useState('')

  // 提示消息
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')

  // ==================== 大纲扩展相关状态 ====================
  const [showExpandOutlineDialog, setShowExpandOutlineDialog] = useState(false)
  const [expandingOutline, setExpandingOutline] = useState(false)
  const [expandedOutlineData, setExpandedOutlineData] = useState<any>(null)
  const [currentChapterCount, setCurrentChapterCount] = useState(0)
  const [targetChapterCount, setTargetChapterCount] = useState<number>(100)
  const [expansionProgress, setExpansionProgress] = useState(0)
  const [expansionStartTime, setExpansionStartTime] = useState<number | null>(null)
  const [estimatedTimeRemaining, setEstimatedTimeRemaining] = useState<number | null>(null)
  const [editedExpansionContent, setEditedExpansionContent] = useState('')
  const [isEditingExpansion, setIsEditingExpansion] = useState(false)
  const [outlineHistory, setOutlineHistory] = useState<Array<{timestamp: number, content: string, chapterCount: number}>>([])
  const [showHistoryDialog, setShowHistoryDialog] = useState(false)

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

  // 加载历史记录
  useEffect(() => {
    const historyData = getHistory('outline')
    setOutlineHistory(historyData)
  }, [])

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

  const loadSettingTemplates = async () => {
    setSettingTemplatesLoading(true)
    try {
      const response = await apiClient.getSettingTemplates()
      setSettingTemplates(response.data || [])
    } catch (error) {
      logger.error('获取设定模板列表失败:', error)
      showSnackbar('获取设定模板列表失败', 'error')
    } finally {
      setSettingTemplatesLoading(false)
    }
  }

  const handleOpenTemplateDialog = () => {
    if (!projectId) {
      showSnackbar('请先选择一个项目', 'error')
      return
    }

    setTemplateDialog(true)
    setSelectedTemplateKey(null)
    setClearExistingSettings(false)
    loadSettingTemplates()
  }

  const handleApplyTemplate = async () => {
    if (!projectId || !selectedTemplateKey) {
      showSnackbar('请选择模板', 'error')
      return
    }

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    setApplyingTemplate(true)
    try {
      await apiClient.applySettingTemplate(projectIdNum, {
        template_key: selectedTemplateKey,
        clear_existing: clearExistingSettings,
      })

      await loadSettingCollections()
      setTemplateDialog(false)
      showSnackbar('✅ 模板应用成功', 'success')
    } catch (err) {
      logger.error('❌ 应用模板失败:', err)
      showSnackbar('应用模板失败', 'error')
    } finally {
      setApplyingTemplate(false)
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

  // ==================== 大纲扩展相关函数 ====================

  // 计算进度
  const calculateProgress = (current: number, total: number): number => {
    return Math.min(Math.round((current / total) * 100), 100)
  }

  // 估算剩余时间
  const estimateRemainingTime = (startTime: number, current: number, total: number): number => {
    const elapsed = Date.now() - startTime
    const avgTimePerIteration = elapsed / current
    return Math.round(avgTimePerIteration * (total - current) / 1000)
  }

  // 格式化剩余时间
  const formatRemainingTime = (seconds: number): string => {
    if (seconds < 60) return `${seconds}秒`
    const minutes = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${minutes}分${secs}秒`
  }

  // 保存历史
  const saveHistory = (type: 'outline', content: string, chapterCount: number) => {
    const key = `${type}_history`
    const history = JSON.parse(localStorage.getItem(key) || '[]')
    history.push({ timestamp: Date.now(), content, chapterCount })
    // 只保留最近20条记录
    if (history.length > 20) history.shift()
    localStorage.setItem(key, JSON.stringify(history))
  }

  // 获取历史
  const getHistory = (type: 'outline'): Array<{timestamp: number, content: string, chapterCount: number}> => {
    const key = `${type}_history`
    return JSON.parse(localStorage.getItem(key) || '[]')
  }

  // 大纲扩展主函数
  const handleExpandOutline = async () => {
    if (!projectId) return

    try {
      setExpandingOutline(true)
      setExpansionProgress(0)
      setExpansionStartTime(Date.now())
      setEstimatedTimeRemaining(null)
      setShowExpandOutlineDialog(true)
      setExpandedOutlineData(null)

      console.log('📖 开始渐进式扩展大纲...')

      // 从当前阶段获取数据
      let currentOutline = plotOutline || ''
      const worldSettingData = worldSetting || ''
      const charactersData = characters || ''

      if (!currentOutline) {
        showSnackbar('⚠️ 请先完成结构设计阶段，生成情节大纲', 'error')
        setExpandingOutline(false)
        setShowExpandOutlineDialog(false)
        return
      }

      let chapterCount = currentChapterCount
      let shouldContinue = true
      let totalIterations = 0
      const maxIterations = 10
      const targetChapters = targetChapterCount && targetChapterCount > 0 ? targetChapterCount : 100

      while (shouldContinue && totalIterations < maxIterations && chapterCount < targetChapters) {
        totalIterations++
        const remaining = targetChapters - chapterCount
        if (remaining <= 0) break

        let increment: number
        const gapRatio = remaining / targetChapters

        if (remaining <= 3) {
          increment = remaining
        } else if (targetChapters <= 40) {
          increment = Math.min(5, remaining)
        } else {
          if (gapRatio > 0.6) {
            increment = Math.min(15, Math.max(5, Math.round(remaining * 0.4)))
          } else if (gapRatio > 0.3) {
            increment = Math.min(10, Math.max(4, Math.round(remaining * 0.3)))
          } else {
            increment = Math.min(8, Math.max(3, Math.round(remaining * 0.2)))
          }
        }

        increment = Math.max(1, Math.min(increment, remaining))

        const progress = calculateProgress(totalIterations, maxIterations)
        setExpansionProgress(progress)

        if (expansionStartTime) {
          const remainingTime = estimateRemainingTime(expansionStartTime, totalIterations, maxIterations)
          setEstimatedTimeRemaining(remainingTime)
        }

        console.log(`🔄 第${totalIterations}次扩展：从 ${chapterCount} 章扩展 ${increment} 章（目标：${targetChapters} 章）... (进度: ${progress}%)`)

        const response = await fetch('/api/v1/workflow/expand-outline', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            project_id: parseInt(projectId),
            current_outline: currentOutline,
            world_setting: worldSettingData,
            characters: charactersData,
            current_chapter_count: chapterCount,
            increment: increment,
            target_total_chapters: targetChapters,
          }),
        })

        if (!response.ok) {
          throw new Error(`扩展大纲失败: ${response.status}`)
        }

        const data = await response.json()
        console.log(`✅ 第${totalIterations}次扩展完成，当前章节数: ${data.current_chapter_count}`)

        currentOutline = data.expanded_outline
        chapterCount = data.current_chapter_count
        shouldContinue = data.should_continue

        showSnackbar(`📝 已扩展到 ${chapterCount} 章${shouldContinue ? '，继续扩展...' : '，AI建议停止'}`, 'success')

        if (!shouldContinue) {
          console.log(`🛑 AI建议停止扩展：${data.continue_reason}`)
          setExpandedOutlineData({
            ...data,
            stop_reason: data.continue_reason
          })
          break
        }

        setExpandedOutlineData(data)
      }

      console.log('💾 开始保存扩展结果...')

      setPlotOutline(currentOutline)
      setCurrentChapterCount(chapterCount)

      const historyRecord = {
        timestamp: Date.now(),
        content: currentOutline,
        chapterCount: chapterCount
      }
      saveHistory('outline', currentOutline, chapterCount)
      setOutlineHistory(prev => [...prev, historyRecord])

      console.log('✅ 状态已更新')
      setExpansionProgress(100)

      showSnackbar(`✅ 大纲扩展完成！共 ${chapterCount} 章（${totalIterations}次扩展）`, 'success')
    } catch (error) {
      console.error('❌ 扩展大纲失败:', error)
      showSnackbar(`扩展大纲失败: ${error}`, 'error')
    } finally {
      setExpandingOutline(false)
      setExpansionProgress(0)
      setEstimatedTimeRemaining(null)
    }
  }

  // 开始编辑大纲
  const handleStartEditOutline = () => {
    setIsEditingExpansion(true)
    setEditedExpansionContent(expandedOutlineData?.expanded_outline || '')
  }

  // 保存编辑的大纲
  const handleSaveEditedOutline = () => {
    setPlotOutline(editedExpansionContent)
    setIsEditingExpansion(false)

    setExpandedOutlineData({
      ...expandedOutlineData,
      expanded_outline: editedExpansionContent
    })

    const historyRecord = {
      timestamp: Date.now(),
      content: editedExpansionContent,
      chapterCount: currentChapterCount
    }
    saveHistory('outline', editedExpansionContent, currentChapterCount)
    setOutlineHistory(prev => [...prev, historyRecord])

    showSnackbar('✅ 编辑已保存', 'success')
  }

  // 导出 Markdown
  const handleExportOutlineMarkdown = () => {
    if (!expandedOutlineData) return

    const markdown = `# 大纲扩展结果

**章节数**: ${currentChapterCount}

## 完整大纲

${expandedOutlineData.expanded_outline || ''}
`

    const blob = new Blob([markdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `大纲扩展_${currentChapterCount}章_${Date.now()}.md`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // 导出 CSV
  const handleExportChapterCSV = () => {
    if (!expandedOutlineData?.chapter_breakdown) return

    const csv = `章节号,标题,摘要\n${expandedOutlineData.chapter_breakdown}`

    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `章节分解_${currentChapterCount}章_${Date.now()}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  // 查看历史
  const handleShowHistory = () => {
    setShowHistoryDialog(true)
  }

  // 组件格式化显示
  const FormattedContent = ({ content, sx = {} }: { content: string, sx?: any }) => (
    <Box sx={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', ...sx }}>
      {content}
    </Box>
  )

  // ==================== 辅助函数 ====================

  const getCategoryDisplayName = (category: string): string => {
    return CATEGORY_NAME_MAP[category] || category
  }

  const getIndentForItem = (item: SettingItem): number => {
    return ((item.depth || 1) - 1) * 24
  }

  const getAvailableCategoriesToAdd = (): string[] => {
    const existingCategories = new Set(collections.map(c => c.category))
    return Object.keys(CATEGORY_NAME_MAP)
      .filter(key => key !== 'character_system' && !existingCategories.has(key))
      .sort()
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
                <>
                  <Button
                    variant="contained"
                    startIcon={<EditIcon />}
                    onClick={handleStartEdit}
                    disabled={!getCurrentContent()}
                    sx={{ borderRadius: 2 }}
                  >
                    编辑{getTabTitle()}
                  </Button>
                  
                  {/* 只在剧情大纲Tab显示扩展按钮 */}
                  {textTabValue === 2 && (
                    <Button
                      variant="outlined"
                      color="primary"
                      startIcon={expandingOutline ? <CircularProgress size={20} /> : <ArticleIcon />}
                      onClick={handleExpandOutline}
                      disabled={!plotOutline || !worldSetting || !characters || expandingOutline}
                      sx={{ borderRadius: 2 }}
                    >
                      {expandingOutline ? '扩展中...' : `📖 扩展大纲${currentChapterCount > 0 ? `(当前${currentChapterCount}章)` : ''}`}
                    </Button>
                  )}
                </>
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
                  onClick={handleOpenTemplateDialog}
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
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Typography sx={{ fontWeight: 500 }}>{collection.name}</Typography>
                          {getCategoryDisplayName(collection.category) !== collection.name && (
                            <Chip label={getCategoryDisplayName(collection.category)} size="small" variant="outlined" sx={{ height: 20 }} />
                          )}
                        </Box>
                      </ListItemButton>
                    </ListItem>
                  ))}
                </List>
              )}
            </Paper>
          </Grid>

          {/* 右侧：设定项树 + 列表 */}
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

                  <Box sx={{ display: 'flex', gap: 2, flex: 1, minHeight: 0 }}>
                    {/* 左：树形视图 */}
                    <Box sx={{ width: '60%', borderRight: '1px solid', borderColor: 'grey.200', pr: 1 }}>
                      <SettingTreeView
                        collectionId={selectedCollection.id}
                        selectedItemId={selectedItem?.id}
                        onSelectCategory={(path) => {
                          setSelectedCategoryPath(path)
                          setSelectedItem(null)
                        }}
                        onSelectInstance={(item) => {
                          setSelectedItem(item)
                          setSelectedCategoryPath(null)
                        }}
                        title="层级视图"
                      />
                    </Box>

                    {/* 右：详情/列表（根据选择切换） */}
                    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                      {/* 分类下的实例列表 */}
                      {!selectedItem && selectedCategoryPath && (
                        <List sx={{ flexGrow: 1, overflow: 'auto' }}>
                          {settingItems
                            .filter((it) => ((it.path || '').startsWith(selectedCategoryPath + '/')) && (it.is_leaf ?? true))
                            .map((item: SettingItem) => (
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
                                  selected={!!((selectedItem as any) && (selectedItem as any).id === item.id)}
                                  onClick={() => (item.is_leaf ? setSelectedItem(item) : setSelectedCategoryPath(item.path || ""))}
                                  sx={{ pr: 10 }}
                                >
                                  {item.is_leaf ? <ArticleIcon sx={{ mr: 1, fontSize: 18, color: 'text.secondary' }} /> : <FolderIcon sx={{ mr: 1, fontSize: 18, color: 'primary.main' }} />}
                                  <ListItemText
                                    primary={
                                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <Typography component="span" sx={{ fontWeight: 500 }}>
                                          Lv.{item.depth || item.level || 1} {item.name}
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
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
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

                      {/* 空态提示 */}
                      {!selectedItem && !selectedCategoryPath && (
                        <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
                          请选择左侧树中的分类或设定项
                        </Typography>
                      )}
                    </Box>
                  </Box>
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
      <Dialog
        open={templateDialog}
        onClose={() => !applyingTemplate && setTemplateDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>选择设定模板</DialogTitle>
        <DialogContent dividers>
          {settingTemplatesLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress size={24} />
            </Box>
          ) : (
            <List>
              {settingTemplates.length === 0 ? (
                <ListItem>
                  <Typography variant="body2" color="text.secondary">
                    暂无可用模板。
                  </Typography>
                </ListItem>
              ) : (
                settingTemplates.map((tpl: any) => (
                  <ListItem
                    key={tpl.key}
                    button
                    selected={selectedTemplateKey === tpl.key}
                    onClick={() => setSelectedTemplateKey(tpl.key)}
                  >
                    <Box>
                      <Typography variant="subtitle1">{tpl.name}</Typography>
                      <Typography variant="body2" color="text.secondary">
                        {tpl.description}
                      </Typography>
                    </Box>
                  </ListItem>
                ))
              )}
            </List>
          )}

          <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
            <FormControl component="fieldset">
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <input
                  type="checkbox"
                  checked={clearExistingSettings}
                  onChange={(e) => setClearExistingSettings(e.target.checked)}
                  style={{ width: 18, height: 18, cursor: 'pointer' }}
                />
                <Typography variant="body2" color="text.secondary">
                  清空当前项目下已有的设定集合（谨慎操作）
                </Typography>
              </Box>
            </FormControl>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTemplateDialog(false)} disabled={applyingTemplate}>
            取消
          </Button>
          <Button
            onClick={handleApplyTemplate}
            variant="contained"
            disabled={!selectedTemplateKey || applyingTemplate}
            startIcon={applyingTemplate ? <CircularProgress size={20} /> : undefined}
          >
            {applyingTemplate ? '应用中...' : '应用模板'}
          </Button>
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

      {/* 大纲扩展结果对话框 */}
      <Dialog 
        open={showExpandOutlineDialog} 
        onClose={() => !expandingOutline && setShowExpandOutlineDialog(false)} 
        maxWidth="lg" 
        fullWidth
      >
        <DialogTitle>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Box>
              <Typography variant="h6">
                📖 扩展大纲结果 - 已扩展至{currentChapterCount}章
              </Typography>
              {!expandingOutline && (
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
                  <TextField
                    label="目标章节数"
                    type="number"
                    size="small"
                    value={targetChapterCount}
                    onChange={(e) => {
                      const value = parseInt(e.target.value, 10)
                      setTargetChapterCount(Number.isNaN(value) ? 0 : value)
                    }}
                    inputProps={{ min: 1 }}
                    sx={{ width: 150 }}
                  />
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={handleExpandOutline}
                    disabled={expandingOutline}
                    startIcon={<ArticleIcon />}
                  >
                    继续扩展
                  </Button>
                </Box>
              )}
            </Box>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Tooltip title="编辑大纲">
                <IconButton
                  onClick={handleStartEditOutline}
                  color="primary"
                  disabled={expandingOutline || !expandedOutlineData}
                >
                  <EditIcon />
                </IconButton>
              </Tooltip>
              <Tooltip title="导出 Markdown">
                <IconButton
                  onClick={handleExportOutlineMarkdown}
                  color="primary"
                  disabled={expandingOutline || !expandedOutlineData}
                >
                  <DownloadIcon />
                </IconButton>
              </Tooltip>
              <Tooltip title="导出 CSV">
                <IconButton
                  onClick={handleExportChapterCSV}
                  color="primary"
                  disabled={expandingOutline || !expandedOutlineData?.chapter_breakdown}
                >
                  <DownloadIcon />
                </IconButton>
              </Tooltip>
              <Tooltip title="查看历史">
                <IconButton
                  onClick={handleShowHistory}
                  color="primary"
                >
                  <HistoryIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>
        </DialogTitle>
        <DialogContent dividers>
          {/* 进度条 */}
          {expandingOutline && (
            <Box sx={{ mb: 3 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  扩展进度：{expansionProgress}%
                </Typography>
                {estimatedTimeRemaining !== null && estimatedTimeRemaining > 0 && (
                  <Typography variant="body2" color="text.secondary">
                    预计剩余时间：{formatRemainingTime(estimatedTimeRemaining)}
                  </Typography>
                )}
              </Box>
              <LinearProgress variant="determinate" value={expansionProgress} sx={{ height: 8, borderRadius: 1 }} />
              <Box sx={{ mt: 3, textAlign: 'center', py: 4 }}>
                <CircularProgress size={60} />
                <Typography variant="h6" sx={{ mt: 2, color: 'text.secondary' }}>
                  🚀 正在扩展大纲...
                </Typography>
                <Typography variant="body2" sx={{ mt: 1, color: 'text.disabled' }}>
                  AI正在生成章节内容，请耐心等待
                </Typography>
              </Box>
            </Box>
          )}

          {/* 扩展结果 */}
          {!expandingOutline && expandedOutlineData && (
            <Box>
              {/* 完整大纲 */}
              <Paper elevation={2} sx={{ p: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                    📝 完整扩展大纲
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary">
                      {expandedOutlineData.expanded_outline?.length || 0} 字
                    </Typography>
                    <Button
                      size="small"
                      onClick={() => {
                        navigator.clipboard.writeText(expandedOutlineData.expanded_outline || '');
                        showSnackbar('✅ 已复制到剪贴板', 'success');
                      }}
                    >
                      📋 复制
                    </Button>
                  </Box>
                </Box>

                {isEditingExpansion ? (
                  <Box>
                    <TextField
                      fullWidth
                      multiline
                      minRows={12}
                      maxRows={20}
                      value={editedExpansionContent}
                      onChange={(e) => setEditedExpansionContent(e.target.value)}
                      sx={{ mb: 2 }}
                    />
                    <Box sx={{ display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
                      <Button
                        onClick={() => {
                          setIsEditingExpansion(false);
                          setEditedExpansionContent(expandedOutlineData?.expanded_outline || '');
                        }}
                        size="small"
                      >
                        取消
                      </Button>
                      <Button
                        variant="contained"
                        onClick={handleSaveEditedOutline}
                        size="small"
                        startIcon={<SaveIcon />}
                      >
                        保存编辑
                      </Button>
                    </Box>
                  </Box>
                ) : (
                  <Box sx={{
                    bgcolor: 'background.default',
                    p: 2,
                    borderRadius: 1,
                    maxHeight: 400,
                    overflow: 'auto',
                    border: '1px solid',
                    borderColor: 'divider'
                  }}>
                    <FormattedContent
                      content={expandedOutlineData.expanded_outline || '大纲内容为空'}
                      sx={{ fontSize: '0.9rem' }}
                    />
                  </Box>
                )}
              </Paper>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            variant="contained"
            onClick={() => setShowExpandOutlineDialog(false)}
            disabled={expandingOutline}
          >
            关闭
          </Button>
        </DialogActions>
      </Dialog>

      {/* 历史版本对话框 */}
      <Dialog 
        open={showHistoryDialog} 
        onClose={() => setShowHistoryDialog(false)} 
        maxWidth="md" 
        fullWidth
      >
        <DialogTitle>📜 历史版本</DialogTitle>
        <DialogContent dividers>
          {outlineHistory.length === 0 ? (
            <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              暂无历史记录
            </Typography>
          ) : (
            <List>
              {outlineHistory.slice().reverse().map((record, index) => (
                <ListItem key={index} sx={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                  <Typography variant="caption" color="text.secondary">
                    {new Date(record.timestamp).toLocaleString()} - {record.chapterCount}章
                  </Typography>
                  <Typography variant="body2" sx={{ mt: 1, whiteSpace: 'pre-wrap' }}>
                    {record.content.substring(0, 200)}...
                  </Typography>
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowHistoryDialog(false)}>关闭</Button>
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
