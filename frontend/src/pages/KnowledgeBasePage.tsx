import { lazy, Suspense, useCallback, useEffect, useState } from 'react'
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
  Tooltip,
  alpha,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import SaveIcon from '@mui/icons-material/Save'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import FolderIcon from '@mui/icons-material/Folder'
import ArticleIcon from '@mui/icons-material/Article'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import SyncIcon from '@mui/icons-material/Sync'
import { useTranslation } from 'react-i18next'
import { logger } from '@/utils/logger'
import {
  estimateChapterCount,
  estimateCharacterCount,
} from '@/utils/workflowContentMetrics'
import { apiClient } from '@/services/api'
import BackToTopButton from '@/components/common/BackToTopButton'
import FormattedContent from '@/components/common/FormattedContent'
import { useKnowledgeBaseWorkflowContent } from '@/hooks/useKnowledgeBaseWorkflowContent'
import { useStoryExpansionController } from '@/hooks/useStoryExpansionController'
import { useStoryExpansionProjectRecommendation } from '@/hooks/useStoryExpansionProjectRecommendation'
import type {
  SettingCollection,
  SettingItem,
  SettingTemplateMetadata,
  SettingSmartExtractResponse,
  SettingSmartExtractRelatedContent,
  SettingTreeActionItem,
} from '@/types/settings'
import { useFormats } from '@/i18n'

const loadMarkdownRenderer = () => import('@/components/MarkdownRenderer')
const loadVditorEditor = () => import('@/components/VditorEditor')
const loadSettingTreeView = () => import('@/components/SettingTreeView')
const loadSettingRecommendations = () => import('@/components/SettingRecommendations')
const loadConflictDetector = () => import('@/components/ConflictDetector')
const loadRelationshipGraph = () => import('@/components/RelationshipGraph')
const loadCharacterCardManager = () => import('@/components/CharacterCardManager')
const loadStoryExpansionDialog = () => import('@/components/workflow/StoryExpansionDialog')
const loadStoryExpansionResultDialog = () => import('@/components/workflow/StoryExpansionResultDialog')

const LazyMarkdownRenderer = lazy(loadMarkdownRenderer)
const LazyVditorEditor = lazy(loadVditorEditor)
const LazySettingTreeView = lazy(loadSettingTreeView)
const LazySettingRecommendations = lazy(loadSettingRecommendations)
const LazyConflictDetector = lazy(loadConflictDetector)
const LazyRelationshipGraph = lazy(loadRelationshipGraph)
const LazyCharacterCardManager = lazy(loadCharacterCardManager)
const LazyStoryExpansionDialog = lazy(loadStoryExpansionDialog)
const LazyStoryExpansionResultDialog = lazy(loadStoryExpansionResultDialog)

// ==================== 局部懒加载资源 ====================

interface TabPanelProps {
  children?: React.ReactNode
  index: number
  value: number
}

// ==================== 缁勪欢瀹氫箟 ====================

function TabPanel(props: TabPanelProps) {
  const { children, value, index, ...other } = props
  return (
    <div role="tabpanel" hidden={value !== index} {...other}>
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  )
}

function LazySectionFallback({ minHeight = 240 }: { minHeight?: number }) {
  return (
    <Box
      sx={{
        minHeight,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <CircularProgress size={28} />
    </Box>
  )
}

function warmImport(loader: () => Promise<unknown>) {
  void loader()
}

// Category 中文名称映射（与后端 HIERARCHY_DEFAULTS 保持一致 - 33种体系）
const CATEGORY_NAME_MAP: Record<string, string> = {
  // 地理与世界观（通用）
  map_system: '地图体系',
  organization_force_system: '组织势力体系',
  resource_system: '资源体系',

  // 修仙/玄幻体系
  cultivation_realm_system: '修仙境界体系',
  technique_system: '功法体系',
  pill_system: '丹药体系',
  formation_system: '阵法体系',
  talisman_system: '符箓体系',
  weapon_system: '武器法宝体系',

  // 都市异能体系
  ability_system: '异能体系',
  network_social_relationship_system: '人脉关系体系',
  special_artifact_relic_system: '道具遗物体系',
  wealth_business_empire_system: '财富商业体系',

  // 西幻/魔法体系
  magic_realm_system: '魔法境界体系',
  magic_system: '魔法体系',
  race_bloodline_system: '种族血脉体系',
  profession_class_system: '职业体系',

  // 武侠体系
  martial_realm_system: '武道境界体系',

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

  // 权力政治体系（历史权谋）
  power_official_system: '权力与官制体系',
  military_warfare_system: '军事与战争体系',
  economy_taxation_system: '经济与财税体系',
  culture_etiquette_examination_system: '文化礼制体系',
  legal_criminal_system: '律法刑罚体系',
  communication_intelligence_system: '通讯情报体系',
  historical_event_legend_system: '历史与传说体系',
  lifestyle_custom_system: '民生风俗体系',

  // 特殊
  candidate: '候选集合',
}

// ==================== 主组件 ====================

export default function KnowledgeBasePage() {
  const { t } = useTranslation()
  const { formatDateTime } = useFormats()
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  // 主 Tab 状态 (0=世界观设定, 1=人物设定, 2=大纲设定, 3=设定中心, 4=冲突检测)
  const [mainTabValue, setMainTabValue] = useState(0)
  
  // 设定中心子 Tab 状态 (0=设定管理, 1=热门设定, 2=关系网络)
  const [settingSubTabValue, setSettingSubTabValue] = useState(0)
  
  // 人物设定子 Tab 状态 (0=人物文本, 1=人物卡管理)
  const [characterSubTabValue, setCharacterSubTabValue] = useState(0)

  // ==================== 文本内容相关状态 ====================
  const [saving, setSaving] = useState(false)
  const {
    loading,
    error,
    worldSetting,
    setWorldSetting,
    characters,
    setCharacters,
    plotOutline,
    setPlotOutline,
    loadWorkflowData,
  } = useKnowledgeBaseWorkflowContent(projectId)

  const [isEditing, setIsEditing] = useState(false)
  const [editedContent, setEditedContent] = useState('')

  // ==================== 类型设定相关状态 ====================
  const [collections, setCollections] = useState<SettingCollection[]>([])
  const [selectedCollection, setSelectedCollection] = useState<SettingCollection | null>(null)
  const [settingItems, setSettingItems] = useState<SettingItem[]>([])
  const [selectedItem, setSelectedItem] = useState<SettingItem | null>(null)
  const [selectedCategoryPath, setSelectedCategoryPath] = useState<string | null>(null)
  const [selectedCategoryItem, setSelectedCategoryItem] = useState<SettingItem | null>(null)  // 当前选中的分类项
  
  // 模板相关状态
  const [settingTemplates, setSettingTemplates] = useState<SettingTemplateMetadata[]>([])
  const [settingTemplatesLoading, setSettingTemplatesLoading] = useState(false)
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string | null>(null)
  const [clearExistingSettings, setClearExistingSettings] = useState(false)
  const [applyingTemplate, setApplyingTemplate] = useState(false)
  const [loadingCollections, setLoadingCollections] = useState(false)

  // 快速添加体系
  const [selectedCategoryToAdd, setSelectedCategoryToAdd] = useState<string>('')

  // 对话框状态
  const [createCollectionDialog, setCreateCollectionDialog] = useState(false)
  const [createItemDialog, setCreateItemDialog] = useState(false)
  const [editItemDialog, setEditItemDialog] = useState(false)
  const [templateDialog, setTemplateDialog] = useState(false)
  const [createChildItemDialog, setCreateChildItemDialog] = useState(false)
  const [parentItemPath, setParentItemPath] = useState<string>('')
  const [, setParentItemRef] = useState<SettingItem | null>(null)
  const [newItemIsLeaf, setNewItemIsLeaf] = useState<boolean>(true)
  const [treeRefreshTrigger, setTreeRefreshTrigger] = useState<number>(0)
  const [moveItemDialog, setMoveItemDialog] = useState(false)
  const [moveTargetPath, setMoveTargetPath] = useState<string>('')

  // 琛ㄥ崟鏁版嵁
  const [newCollectionName, setNewCollectionName] = useState('')
  const [newCollectionCategory, setNewCollectionCategory] = useState('')
  const [newCollectionDescription, setNewCollectionDescription] = useState('')

  const [newItemName, setNewItemName] = useState('')
  const [newItemCode, setNewItemCode] = useState('')
  const [newItemLevel, setNewItemLevel] = useState(1)
  const [newItemContent, setNewItemContent] = useState('')
  const [newItemTags, setNewItemTags] = useState('')

  // 智能提取相关状态
  const [smartExtractLoading, setSmartExtractLoading] = useState(false)
  const [smartExtractData, setSmartExtractData] = useState<SettingSmartExtractResponse | null>(null)

  // 设定同步到工作流状态
  const [syncingSettings, setSyncingSettings] = useState(false)

  // 候选设定合并状态
  const [mergingCandidates, setMergingCandidates] = useState(false)

  // 鎻愮ず娑堟伅
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')

  const showSnackbar = useCallback((message: string, severity: 'success' | 'error') => {
    setSnackbarMessage(message)
    setSnackbarSeverity(severity)
    setSnackbarOpen(true)
  }, [])

  // ==================== 大纲扩展相关状态 ====================
  const [outlineHistory, setOutlineHistory] = useState<Array<{timestamp: number, content: string, chapterCount: number}>>([])
  const [showHistoryDialog, setShowHistoryDialog] = useState(false)

  // 当前人物数
  const getCurrentCharacterCount = useCallback((): number => (
    estimateCharacterCount(characters)
  ), [characters])

  // 当前章节数
  const getCurrentChapterCount = useCallback((): number => (
    estimateChapterCount(plotOutline)
  ), [plotOutline])

  // 推荐相关状态
  const storyExpansionRecommendation = useStoryExpansionProjectRecommendation(projectId)
  const { recommendationReason } = storyExpansionRecommendation

  const {
    expandingStory,
    hasStoryExpansionResult,
    showStoryExpansionDialog,
    storyExpansionWaitInfo,
    openStoryExpansion,
    openStoryExpansionResultDialog,
    storyExpansionDialogProps,
    storyExpansionResultDialogProps,
  } = useStoryExpansionController({
    projectId,
    worldSetting,
    plotOutline,
    characters,
    getCurrentChapterCount,
    getCurrentCharacterCount,
    recommendation: storyExpansionRecommendation,
    refreshWorkflowData: loadWorkflowData,
    showSnackbar,
  })

  const currentCharacterCount = getCurrentCharacterCount()
  const hasCharacterText = Boolean((characters || '').trim())

  const preloadCharacterTabResources = (tabValue: number) => {
    if (tabValue === 1) {
      warmImport(loadCharacterCardManager)
      return
    }

    warmImport(loadMarkdownRenderer)
  }

  const preloadSettingTabResources = (tabValue: number) => {
    if (tabValue === 1) {
      warmImport(loadSettingRecommendations)
      return
    }

    if (tabValue === 2) {
      warmImport(loadRelationshipGraph)
      return
    }

    warmImport(loadSettingTreeView)
  }

  const preloadMainTabResources = (tabValue: number) => {
    if (tabValue <= 2) {
      warmImport(loadMarkdownRenderer)
      warmImport(loadStoryExpansionDialog)
    }

    if (tabValue === 1) {
      preloadCharacterTabResources(characterSubTabValue)
      return
    }

    if (tabValue === 3) {
      preloadSettingTabResources(settingSubTabValue)
      return
    }

    if (tabValue === 4) {
      warmImport(loadConflictDetector)
    }
  }

  // ==================== 鐢熷懡鍛ㄦ湡 ====================

  useEffect(() => {
    if (!projectId) return
    const numericProjectId = Number.parseInt(projectId, 10)
    if (!Number.isFinite(numericProjectId)) return

    let disposed = false
    let unsubscribeNotification: () => void = () => undefined

    import('@/services/websocket').then(({ workflowWebSocket }) => {
      if (disposed) {
        return
      }

      workflowWebSocket.connect()
        .then(() => {
          if (disposed) {
            return
          }
          workflowWebSocket.joinProject(numericProjectId)
        })
        .catch(() => undefined)

      unsubscribeNotification = workflowWebSocket.onNotification((data) => {
        const payload = (
          data.type === 'system_collections_created'
          && data.data
          && typeof data.data === 'object'
          && !Array.isArray(data.data)
        )
          ? data.data as { collections?: Array<{ name: string }> }
          : null

        if (payload?.collections?.length) {
          const collections = payload.collections
          const collectionNames = collections.map((c) => c.name).join(', ')
          showSnackbar(`${data.message}: ${collectionNames}`, 'success')
          if (mainTabValue === 3) {
            loadSettingCollections()
          }
          return
        }

        showSnackbar(data.message || '', data.type === 'success' ? 'success' : 'error')
      })
    })

    return () => {
      disposed = true
      unsubscribeNotification()
    }
  }, [projectId, mainTabValue])

  useEffect(() => {
    if (mainTabValue <= 2) {
      loadWorkflowData()
    } else {
      loadSettingCollections()
    }
  }, [projectId, mainTabValue])

  useEffect(() => {
    if (selectedCollection) {
      setSelectedItem(null)
      setSelectedCategoryPath(null)
      setSelectedCategoryItem(null)
      void loadSettingItems(selectedCollection.id)
    } else {
      setSettingItems([])
      setSelectedItem(null)
      setSelectedCategoryPath(null)
      setSelectedCategoryItem(null)
    }
  }, [selectedCollection])

  useEffect(() => {
    preloadMainTabResources(mainTabValue)

    if (isEditing) {
      warmImport(loadVditorEditor)
    }

    if (showStoryExpansionDialog) {
      warmImport(loadStoryExpansionDialog)
    }
  }, [mainTabValue, characterSubTabValue, settingSubTabValue, isEditing, showStoryExpansionDialog])


  // 状态同步
  useEffect(() => {
    const historyData = getHistory('outline')
    setOutlineHistory(historyData)
  }, [])
  // ==================== 当前编辑内容 ====================

  const getCurrentContent = (): string => {
    switch (mainTabValue) {
      case 0: return worldSetting
      case 1: return characters
      case 2: return plotOutline
      default: return ''
    }
  }

  const getCurrentStage = (): string => {
    switch (mainTabValue) {
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
      const response = await apiClient.updateWorkflowStageContent(Number(projectId), stage, {
        content: editedContent,
        continue_workflow: false,
      })

      if (response.status >= 200 && response.status < 300) {
        switch (mainTabValue) {
          case 0: setWorldSetting(editedContent); break
          case 1: setCharacters(editedContent); break
          case 2: setPlotOutline(editedContent); break
        }

        setIsEditing(false)
        showSnackbar(t('kb.snack.saveSuccess'), 'success')
      } else {
        showSnackbar(String(response.data?.detail || response.data?.error || t('kb.snack.saveFailedShort')), 'error')
      }
    } catch (err) {
      logger.error('保存失败:', err)
      showSnackbar(t('kb.snack.saveFailed'), 'error')
    } finally {
      setSaving(false)
    }
  }

  const getTabTitle = (): string => {
    switch (mainTabValue) {
      case 0: return t('kb.tabs.world')
      case 1: return t('kb.tabs.characters')
      case 2: return t('kb.tabs.outline')
      default: return ''
    }
  }

  // ==================== 绫诲瀷璁惧畾鐩稿叧鍑芥暟 ====================

  const loadSettingCollections = async (): Promise<SettingCollection[]> => {
    if (!projectId) return []

    setLoadingCollections(true)

    try {
      const response = await apiClient.getSettingCollections(Number(projectId))
      const nextCollections = response.data || []
      setCollections(nextCollections)
      if (nextCollections.length > 0 && !selectedCollection) {
        setSelectedCollection(nextCollections[0])
      }
      return nextCollections
    } catch (err) {
      logger.error('加载设定集合失败:', err)
      showSnackbar(t('kb.snack.loadCollectionsFailed'), 'error')
      return []
    } finally {
      setLoadingCollections(false)
    }
  }

  const loadSettingItems = async (collectionId: number): Promise<SettingItem[]> => {
    try {
      const response = await apiClient.getSettingItems(collectionId)
      const items = response.data || []
      // 按 depth 和 order 排序
      items.sort((a: SettingItem, b: SettingItem) => {
        if (a.depth !== b.depth) return (a.depth || 0) - (b.depth || 0)
        return a.order - b.order
      })
      setSettingItems(items)
      return items
    } catch (err) {
      logger.error('加载设定项失败:', err)
      showSnackbar(t('kb.snack.loadItemsFailed'), 'error')
      return []
    }
  }

  const focusSettingItem = async (itemId: number) => {
    try {
      const itemResponse = await apiClient.getSettingItem(itemId)
      const targetItem = itemResponse.data

      let targetCollection = collections.find(c => c.id === targetItem.collection_id) || null
      if (!targetCollection) {
        const loadedCollections = await loadSettingCollections()
        targetCollection = loadedCollections.find(c => c.id === targetItem.collection_id) || null
      }

      if (!targetCollection) {
        showSnackbar(t('kb.snack.noCollectionFound'), 'error')
        return null
      }

      setSelectedCollection(targetCollection)
      const items = await loadSettingItems(targetCollection.id)
      const fullItem = items.find(item => item.id === targetItem.id) || targetItem
      setSelectedItem(fullItem)
      setSelectedCategoryPath(null)
      setSelectedCategoryItem(null)
      return fullItem
    } catch (err) {
      logger.error('加载设定详情失败:', err)
      showSnackbar(t('kb.snack.loadItemDetailFailed'), 'error')
      return null
    }
  }

  const handleCreateCollection = async () => {
    if (!projectId || !newCollectionName || !newCollectionCategory) {
      showSnackbar(t('kb.snack.requiredFields'), 'error')
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
      showSnackbar(t('kb.snack.createSuccess'), 'success')
    } catch (err) {
      logger.error('创建集合失败:', err)
      showSnackbar(t('kb.snack.createFailed'), 'error')
    }
  }

  const loadSettingTemplates = async () => {
    setSettingTemplatesLoading(true)
    try {
      const response = await apiClient.getSettingTemplates()
      setSettingTemplates(response.data || [])
    } catch (error) {
      logger.error('获取设定模板列表失败:', error)
      showSnackbar(t('kb.snack.loadTemplatesFailed'), 'error')
    } finally {
      setSettingTemplatesLoading(false)
    }
  }

  const handleOpenTemplateDialog = () => {
    if (!projectId) {
      showSnackbar(t('kb.snack.selectProjectFirst'), 'error')
      return
    }

    setTemplateDialog(true)
    setSelectedTemplateKey(null)
    setClearExistingSettings(false)
    loadSettingTemplates()
  }

  const handleApplyTemplate = async () => {
    if (!projectId || !selectedTemplateKey) {
      showSnackbar(t('kb.snack.selectTemplate'), 'error')
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
      showSnackbar(t('kb.snack.templateApplied'), 'success')
    } catch (err) {
      logger.error('应用模板失败:', err)
      showSnackbar(t('kb.snack.templateApplyFailed'), 'error')
    } finally {
      setApplyingTemplate(false)
    }
  }

  const handleDeleteCollection = async (collectionId: number) => {
    if (!confirm(t('kb.snack.deleteCollectionConfirm'))) return

    try {
      await apiClient.deleteSettingCollection(collectionId)
      const newCollections = collections.filter(c => c.id !== collectionId)
      setCollections(newCollections)
      if (selectedCollection?.id === collectionId) {
        setSelectedCollection(newCollections[0] || null)
      }
      showSnackbar(t('kb.snack.deleteSuccess'), 'success')
    } catch (err) {
      logger.error('删除集合失败:', err)
      showSnackbar(t('kb.snack.deleteFailed'), 'error')
    }
  }

  const handleCreateItem = async () => {
    if (!selectedCollection || !newItemName) {
      showSnackbar(t('kb.snack.fillItemName'), 'error')
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
        is_leaf: true,
      })

      await loadSettingItems(selectedCollection.id)
      setCreateItemDialog(false)
      resetItemForm()
      showSnackbar(t('kb.snack.createSuccess'), 'success')
    } catch (err) {
      logger.error('创建设定项失败:', err)
      showSnackbar(t('kb.snack.createFailed'), 'error')
    }
  }

  const handleEditItem = (targetItem: SettingItem | null = selectedItem) => {
    if (!targetItem) return

    setSelectedItem(targetItem)
    setNewItemName(targetItem.name)
    setNewItemCode(targetItem.code || '')
    setNewItemLevel(targetItem.level || 1)
    setNewItemContent(targetItem.content || '')
    setNewItemTags(targetItem.tags?.join(', ') || '')
    setEditItemDialog(true)
  }

  const handleSaveItemEdit = async () => {
    if (!selectedItem || !newItemName) return

    try {
      const response = await apiClient.updateSettingItem(selectedItem.id, {
        name: newItemName,
        code: newItemCode,
        level: newItemLevel,
        content: newItemContent,
        tags: newItemTags ? newItemTags.split(',').map(t => t.trim()) : [],
      })

      setSelectedItem(response.data)
      await loadSettingItems(selectedItem.collection_id)
      setEditItemDialog(false)
      resetItemForm()
      showSnackbar(t('kb.snack.saveSuccess'), 'success')
    } catch (err) {
      logger.error('保存设定项失败:', err)
      showSnackbar(t('kb.snack.saveFailedShort'), 'error')
    }
  }

  const handleDeleteItem = async (itemId: number) => {
    if (!confirm(t('kb.snack.deleteItemConfirm'))) return

    try {
      await apiClient.deleteSettingItem(itemId)
      await loadSettingItems(selectedCollection!.id)
      if (selectedItem?.id === itemId) {
        setSelectedItem(null)
      }
      showSnackbar(t('kb.snack.deleteSuccess'), 'success')
    } catch (err) {
      logger.error('删除设定项失败:', err)
      showSnackbar(t('kb.snack.deleteFailed'), 'error')
    }
  }

  const handleDuplicateItem = async (item: SettingItem) => {
    if (!selectedCollection) return

    try {
      await apiClient.createSettingItem(selectedCollection.id, {
        name: `${item.name} ${t('kb.snack.copySuffix')}`,
        code: item.code,
        level: item.level,
        content: item.content,
        tags: item.tags,
        order: settingItems.length,
        is_leaf: item.is_leaf,
      })

      await loadSettingItems(selectedCollection.id)
      showSnackbar(t('kb.snack.duplicateSuccess'), 'success')
    } catch (err) {
      logger.error('复制设定项失败:', err)
      showSnackbar(t('kb.snack.duplicateFailed'), 'error')
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
    setSmartExtractData(null)  // 清空智能提取数据
    setNewItemIsLeaf(true)  // 重置为叶子节点
  }

  // 打开树节点创建弹窗
  const handleTreeAddItem = (parentPath: string, parentItem: SettingItem | null) => {
    setParentItemPath(parentPath)
    setParentItemRef(parentItem)
    resetItemForm()
    setCreateChildItemDialog(true)
  }

  // 删除树节点及其子项
  const handleTreeDeleteItem = async (item: SettingTreeActionItem) => {
    const isLeaf = item.is_leaf
    const itemPath = item.path
    const itemName = item.name

    if (isLeaf) {
      if (typeof item.id !== 'number') {
        showSnackbar(t('kb.snack.deleteNoId'), 'error')
        return
      }

      // 鍒犻櫎鍗曚釜鍙跺瓙鑺傜偣
      if (!confirm(t('kb.snack.deleteNodeConfirm', { name: itemName }))) return

      try {
        await apiClient.deleteSettingItem(item.id)
        await loadSettingItems(selectedCollection!.id)
        setTreeRefreshTrigger(prev => prev + 1)
        if (selectedItem?.id === item.id) {
          setSelectedItem(null)
        }
        setSelectedCategoryItem(null)
        showSnackbar(t('kb.snack.deleteSuccess'), 'success')
      } catch (err) {
        logger.error('删除设定项失败:', err)
        showSnackbar(t('kb.snack.deleteFailed'), 'error')
      }
    } else {
      const itemsToDelete = settingItems.filter(it => 
        it.path && (it.path === itemPath || it.path.startsWith(itemPath + '/'))
      )
      
      if (itemsToDelete.length === 0) {
        showSnackbar(t('kb.snack.noItemsToDelete'), 'error')
        return
      }

      if (!confirm(t('kb.snack.deleteNodeWithChildrenConfirm', { name: itemName, count: itemsToDelete.length }))) return

      try {
        if (typeof item.id === 'number') {
          await apiClient.deleteSettingItem(item.id)
        } else {
          for (const delItem of itemsToDelete) {
            await apiClient.deleteSettingItem(delItem.id)
          }
        }
        await loadSettingItems(selectedCollection!.id)
        setTreeRefreshTrigger(prev => prev + 1)
        setSelectedItem(null)
        setSelectedCategoryPath(null)
        setSelectedCategoryItem(null)
        showSnackbar(t('kb.snack.deletedCount', { count: itemsToDelete.length }), 'success')
      } catch (err) {
        logger.error('批量删除失败:', err)
        showSnackbar(t('kb.snack.deleteFailed'), 'error')
      }
    }
  }

  // 创建子分类或设定项
  const handleCreateChildItem = async () => {
    if (!selectedCollection || !newItemName) {
      showSnackbar(t('kb.snack.fillItemName'), 'error')
      return
    }

    try {
      // 拼接父级路径和当前名称
      const itemPath = parentItemPath ? `${parentItemPath}/${newItemName}` : `${selectedCollection.name}/${newItemName}`
      
      await apiClient.createSettingItem(selectedCollection.id, {
        name: newItemName,
        code: newItemCode,
        level: newItemLevel,
        content: newItemContent,  // 设定项正文内容
        tags: newItemTags ? newItemTags.split(',').map(t => t.trim()) : [],
        order: settingItems.length,
        is_leaf: newItemIsLeaf,
        path: itemPath,
      })

      await loadSettingItems(selectedCollection.id)
      setTreeRefreshTrigger(prev => prev + 1)
      setCreateChildItemDialog(false)
      resetItemForm()
      showSnackbar(t('kb.snack.childCreated', { type: t(newItemIsLeaf ? 'kb.itemTypeItem' : 'kb.categoryBadge') }), 'success')
    } catch (err) {
      logger.error('创建设定项失败:', err)
      showSnackbar(t('kb.snack.createFailed'), 'error')
    }
  }

  // 移动节点到新的父节点下
  const handleMoveItem = async () => {
    if (!selectedItem || !selectedCollection) {
      showSnackbar(t('kb.snack.selectItemToMove'), 'error')
      return
    }

    try {
      const response = await apiClient.setParentForItem(selectedItem.id, moveTargetPath)
      setSelectedItem(response.data)
      await loadSettingItems(selectedCollection.id)
      setTreeRefreshTrigger(prev => prev + 1)
      setMoveItemDialog(false)
      setMoveTargetPath('')
      showSnackbar(t('kb.snack.moveSuccess'), 'success')
    } catch (err) {
      logger.error('移动失败:', err)
      showSnackbar(t('kb.snack.moveFailed'), 'error')
    }
  }

  // 获取可用的移动目标（所有分类节点 + 根节点）
  const getAvailableMoveTargets = () => {
    if (!selectedItem || !selectedCollection) return []
    
    const targets: { path: string; label: string; depth: number }[] = [
      { path: '', label: t('kb.snack.rootSuffix', { name: selectedCollection.name }), depth: 0 }
    ]
    
    // 添加所有分类节点
    settingItems
      .filter(it => !it.is_leaf && it.id !== selectedItem.id)  // 排除当前节点
      .filter(it => !(it.path || '').startsWith((selectedItem.path || '') + '/'))  // 排除当前节点的子孙节点
      .forEach(it => {
        const depth = (it.path || '').split('/').length - 1
        const indent = '\u00A0\u00A0'.repeat(depth)
        targets.push({
          path: it.path || '',
          label: `${indent}${it.name}`,
          depth,
        })
      })
    
    return targets
  }

  // 智能提取设定项相关内容
  const handleSmartExtract = async () => {
    if (!selectedItem) return

    setSmartExtractLoading(true)
    setSmartExtractData(null)

    try {
      const response = await apiClient.getSettingItemSmartExtract(selectedItem.id)
      setSmartExtractData(response.data)
      showSnackbar(t('kb.snack.extractDone'), 'success')
    } catch (error) {
      logger.error('智能提取失败:', error)
      showSnackbar(t('kb.snack.extractFailed'), 'error')
    } finally {
      setSmartExtractLoading(false)
    }
  }

  // 应用推荐的标签
  const handleApplySuggestedTags = (tags: string[]) => {
    const currentTags = newItemTags ? newItemTags.split(',').map(t => t.trim()) : []
    const mergedTags = [...new Set([...currentTags, ...tags])]
    setNewItemTags(mergedTags.join(', '))
    showSnackbar(t('kb.snack.tagsAdded', { count: tags.length }), 'success')
  }

  // 应用提取的内容
  const handleApplyExtractedContent = (excerpt: string) => {
    if (newItemContent) {
      setNewItemContent(`${newItemContent}\n\n---\n${excerpt}`)
    } else {
      setNewItemContent(excerpt)
    }
    showSnackbar(t('kb.snack.contentAppended'), 'success')
  }

  // ==================== 澶х翰鎵╁睍鐩稿叧鍑芥暟 ====================

  // 鑾峰彇鍘嗗彶
  const getHistory = (type: 'outline'): Array<{timestamp: number, content: string, chapterCount: number}> => {
    const key = `${type}_history`
    return JSON.parse(localStorage.getItem(key) || '[]')
  }

  // ==================== 杈呭姪鍑芥暟 ====================
  const getCategoryDisplayName = (category: string): string => {
    return CATEGORY_NAME_MAP[category] || category
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
      showSnackbar(t('kb.snack.quickAddDone', { name: collectionName }), 'success')
      setSelectedCategoryToAdd('')
    } catch (err) {
      logger.error('快速添加体系失败:', err)
      showSnackbar(t('kb.snack.quickAddFailed'), 'error')
    }
  }

  // 同步设定到工作流摘要
  const handleSyncSettingsToWorkflow = async () => {
    if (!projectId) return

    setSyncingSettings(true)
    try {
      const response = await apiClient.syncSettingsToWorkflow(Number(projectId))
      showSnackbar(response.data.message, 'success')
      loadWorkflowData()
    } catch (err) {
      logger.error('同步设定到工作流失败:', err)
      showSnackbar(t('kb.snack.syncFailed'), 'error')
    } finally {
      setSyncingSettings(false)
    }
  }

  // 合并高置信候选设定（修复 P3-3：候选确认闭环）
  const handleMergeCandidates = async () => {
    if (!projectId) return

    setMergingCandidates(true)
    try {
      const response = await apiClient.autoMergeSettings(Number(projectId))
      const merged = response.data?.merged_count ?? 0
      const skipped = response.data?.skipped_count ?? 0
      showSnackbar(
        merged > 0
          ? t('kb.snack.mergedCount', { count: merged, skipped })
          : t('kb.snack.noMergeCandidates', { skipped }),
        'success',
      )
      if (merged > 0) {
        await loadSettingCollections()
        if (selectedCollection) {
          await loadSettingItems(selectedCollection.id)
        }
      }
    } catch (err) {
      logger.error('合并候选设定失败:', err)
      showSnackbar(t('kb.snack.mergeFailed'), 'error')
    } finally {
      setMergingCandidates(false)
    }
  }

  // ==================== 娓叉煋 ====================

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
          {t('action.back')}
        </Button>
        <Alert severity="info" sx={{ flex: 1, mx: 3, py: 0.5 }} icon={false}>
          {t('kb.pageHint')}
        </Alert>
        <Typography variant="h5" sx={{
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 1
        }}>
          {t('kb.title')}
        </Typography>
      </Box>

      {/* 主 Tab 导航 */}
      <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
        <Tabs
          value={mainTabValue}
          onChange={(_, newValue) => { preloadMainTabResources(newValue); setMainTabValue(newValue) }}
          sx={{
            '& .MuiTab-root': {
              fontWeight: 600,
              fontSize: '1rem',
              minHeight: 56,
            }
          }}
        >
          <Tab label={t('kb.tabs.world')} onMouseEnter={() => preloadMainTabResources(0)} onFocus={() => preloadMainTabResources(0)} />
          <Tab label={t('kb.tabs.characters')} onMouseEnter={() => preloadMainTabResources(1)} onFocus={() => preloadMainTabResources(1)} />
          <Tab label={t('kb.tabs.outline')} onMouseEnter={() => preloadMainTabResources(2)} onFocus={() => preloadMainTabResources(2)} />
          <Tab label={t('kb.tabs.settings')} onMouseEnter={() => preloadMainTabResources(3)} onFocus={() => preloadMainTabResources(3)} />
          <Tab label={t('kb.tabs.conflicts')} onMouseEnter={() => preloadMainTabResources(4)} onFocus={() => preloadMainTabResources(4)} />
        </Tabs>
      </Box>

      {/* ==================== Tab 0-2: 世界观 / 人物 / 大纲 ==================== */}
      {mainTabValue <= 2 && (
        <Box>
          {/* 人物页二级 Tab 导航 */}
          {mainTabValue === 1 && (
            <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
              <Tabs
                value={characterSubTabValue}
                onChange={(_, newValue) => { preloadCharacterTabResources(newValue); setCharacterSubTabValue(newValue) }}
              >
                <Tab label={t('kb.tabs.characterText')} onMouseEnter={() => preloadCharacterTabResources(0)} onFocus={() => preloadCharacterTabResources(0)} />
                <Tab label={t('kb.tabs.characterCards')} onMouseEnter={() => preloadCharacterTabResources(1)} onFocus={() => preloadCharacterTabResources(1)} />
              </Tabs>
            </Box>
          )}

          {loading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
              <CircularProgress />
            </Box>
          )}

          {error && (
            <Alert severity="error" sx={{ mb: 3 }}>
              {error}
              <Button size="small" onClick={loadWorkflowData} sx={{ ml: 2 }}>
                {t('action.retry')}
              </Button>
            </Alert>
          )}

          {!loading && !error && (
            <>
              {/* 世界观/人物页操作区，仅在对应标签显示 */}
              {(mainTabValue !== 1 || characterSubTabValue === 0) && (
              <>
              <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
                {!isEditing ? (
                  <>
                    <Button
                      variant="contained"
                      startIcon={<EditIcon />}
                      onClick={handleStartEdit}
                      onMouseEnter={() => warmImport(loadVditorEditor)}
                      onFocus={() => warmImport(loadVditorEditor)}
                      disabled={!getCurrentContent() || expandingStory}
                      sx={{ borderRadius: 2 }}
                    >
                      {t('kb.editTab', { tab: getTabTitle() })}
                    </Button>
                    {(mainTabValue === 2 || (mainTabValue === 1 && characterSubTabValue === 0)) && (
                      <>
                        <Tooltip
                          title={recommendationReason || t('kb.collab.expandTooltip')}
                          placement="top"
                          arrow
                        >
                          <span>
                            <Button
                              variant="contained"
                              color="secondary"
                              startIcon={expandingStory ? <CircularProgress size={20} /> : <AutoFixHighIcon />}
                              onMouseEnter={() => warmImport(loadStoryExpansionDialog)}
                              onFocus={() => warmImport(loadStoryExpansionDialog)}
                              onClick={() => {
                                void openStoryExpansion(mainTabValue === 1 ? 'character' : 'outline')
                              }}
                              disabled={expandingStory || !worldSetting || (!plotOutline && !characters)}
                              sx={{
                                borderRadius: 2,
                                // 协同拓展（teal 品牌 accent）走 info token：浅色深青、暗色雾青，文字钉 contrastText 随反相。
                                bgcolor: 'info.main',
                                color: 'info.contrastText',
                                '&:hover': {
                                  bgcolor: 'info.dark',
                                },
                              }}
                            >
                              {expandingStory ? t('kb.collab.expanding') : t('kb.collab.expand')}
                            </Button>
                          </span>
                        </Tooltip>
                        {hasStoryExpansionResult && !expandingStory && (
                          <Button
                            variant="text"
                            onClick={openStoryExpansionResultDialog}
                            onMouseEnter={() => warmImport(loadStoryExpansionResultDialog)}
                            onFocus={() => warmImport(loadStoryExpansionResultDialog)}
                            sx={{ borderRadius: 2 }}
                          >
                            {t('kb.collab.viewResult')}
                          </Button>
                        )}
                      </>
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
                      {saving ? t('kb.saving') : t('action.save')}
                    </Button>
                    <Button
                      variant="outlined"
                      onClick={handleCancelEdit}
                      disabled={saving}
                      sx={{ borderRadius: 2 }}
                    >
                      {t('action.cancel')}
                    </Button>
                  </>
                )}
              </Box>
              {expandingStory && storyExpansionWaitInfo && (
                <Alert severity="info" variant="outlined" sx={{ mb: 3 }}>
                  <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
                    {storyExpansionWaitInfo.summary}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {storyExpansionWaitInfo.detail}
                  </Typography>
                </Alert>
              )}
              </>
              )}

              {/* 人物主内容区域 */}
              {mainTabValue === 1 ? (
                <>
                  {/* 子标签 0: 人物设定 */}
                  {characterSubTabValue === 0 && (
                    <>
                      <Paper
                        elevation={0}
                        sx={(theme) => ({
                          mb: 3,
                          p: 2.5,
                          borderRadius: 2,
                          border: '1px solid',
                          borderColor: 'primary.light',
                          // 人物总览卡：teal 渐变底走 info token 反相（与协同拓展按钮同源）。
                          background: `linear-gradient(135deg, ${alpha(theme.palette.info.main, 0.08)} 0%, ${theme.palette.background.paper} 100%)`,
                        })}
                      >
                        <Box
                          sx={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            alignItems: { xs: 'flex-start', md: 'center' },
                            flexDirection: { xs: 'column', md: 'row' },
                            gap: 2,
                          }}
                        >
                          <Box>
                            <Typography variant="overline" sx={{ color: 'primary.dark', fontWeight: 700 }}>
                              {t('kb.characterOverview')}
                            </Typography>
                            <Typography variant="h5" sx={{ fontWeight: 700, mb: 0.5 }}>
                              {t('kb.characterCount', { count: currentCharacterCount })}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              {t('kb.characterCountHint')}
                            </Typography>
                          </Box>
                          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                            <Chip label={t('kb.characterTotal', { count: currentCharacterCount })} color="primary" variant="outlined" />
                            <Chip
                              label={hasCharacterText ? t('kb.characterEntered') : t('kb.characterPending')}
                              color={hasCharacterText ? 'success' : 'default'}
                              variant="outlined"
                            />
                          </Box>
                        </Box>
                      </Paper>
                      {isEditing ? (
                        <Suspense fallback={<LazySectionFallback minHeight={500} />}>
                          <LazyVditorEditor
                          value={editedContent}
                          onChange={(val) => setEditedContent(val)}
                          placeholder={t('kb.editorPlaceholder', { tab: getTabTitle() })}
                          height={500}
                          />
                        </Suspense>
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
                            <Suspense fallback={<LazySectionFallback minHeight={240} />}>
                              <LazyMarkdownRenderer content={getCurrentContent()}  />
                            </Suspense>
                          ) : (
                            <Typography color="text.secondary" sx={{ textAlign: 'center', py: 8 }}>
                              {t('kb.emptyContent', { tab: getTabTitle() })}
                            </Typography>
                          )}
                        </Paper>
                      )}
                    </>
                  )}

                  {/* 子 Tab 1: 人物卡管理 */}
                  {characterSubTabValue === 1 && (
                    <Suspense fallback={<LazySectionFallback minHeight={360} />}>
                      <LazyCharacterCardManager
                        projectId={Number(projectId)}
                      />
                    </Suspense>
                  )}

                  {/* 已移除“拓展人物”子页，改为顶部并排输入区与按钮，复用原有逻辑 */}
                </>
              ) : (
                // 世界观设定和大纲设定 Tab 的原有内容
                <>
                  {isEditing ? (
                <Suspense fallback={<LazySectionFallback minHeight={500} />}>
                  <LazyVditorEditor
                  value={editedContent}
                  onChange={(val) => setEditedContent(val)}
                  placeholder={t('kb.editorPlaceholder', { tab: getTabTitle() })}
                  height={500}
                  />
                </Suspense>
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
                    <Suspense fallback={<LazySectionFallback minHeight={240} />}>
                      <LazyMarkdownRenderer content={getCurrentContent()}  />
                    </Suspense>
                  ) : (
                    <Typography color="text.secondary" sx={{ textAlign: 'center', py: 8 }}>
                      {t('kb.emptyContent', { tab: getTabTitle() })}
                    </Typography>
                  )}
                </Paper>
              )}
                </>
              )}
            </>
          )}
        </Box>
      )}

      {/* ==================== Tab 3: 设定管理 ==================== */}
      <TabPanel value={mainTabValue} index={3}>
        {/* Tab 3 Nav */}
        <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
          <Tabs
            value={settingSubTabValue}
            onChange={(_, newValue) => { preloadSettingTabResources(newValue); setSettingSubTabValue(newValue) }}
          >
            <Tab label={t('kb.tabs.settingsManage')} onMouseEnter={() => preloadSettingTabResources(0)} onFocus={() => preloadSettingTabResources(0)} />
            <Tab label={t('kb.tabs.popularSettings')} onMouseEnter={() => preloadSettingTabResources(1)} onFocus={() => preloadSettingTabResources(1)} />
            <Tab label={t('kb.tabs.relationGraph')} onMouseEnter={() => preloadSettingTabResources(2)} onFocus={() => preloadSettingTabResources(2)} />
          </Tabs>
        </Box>

        {/* 子标签 0: 设定树 */}
        {settingSubTabValue === 0 && (
        <Grid container spacing={3}>
          {/* 左侧：设定集合列表 */}
          <Grid item xs={12} md={4}>
            <Paper elevation={2} sx={{ p: 2, height: '70vh', display: 'flex', flexDirection: 'column' }}>
              {/* 鎿嶄綔鎸夐挳 */}
              <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
                <Button
                  variant="outlined"
                  size="small"
                  startIcon={<AddIcon />}
                  onClick={handleOpenTemplateDialog}
                  fullWidth
                >
                  {t('kb.createFromTemplate')}
                </Button>
                <Button
                  variant="contained"
                  size="small"
                  startIcon={<AddIcon />}
                  onClick={() => setCreateCollectionDialog(true)}
                  fullWidth
                >
                  {t('kb.createNew')}
                </Button>
              </Box>

              {/* 快速添加常用分类 */}
              {getAvailableCategoriesToAdd().length > 0 && (
                <FormControl size="small" fullWidth sx={{ mb: 2 }}>
                  <InputLabel>{t('kb.quickAddSystem')}</InputLabel>
                  <Select
                    value={selectedCategoryToAdd}
                    label={t('kb.quickAddSystem')}
                    onChange={(e) => {
                      const category = e.target.value
                      setSelectedCategoryToAdd(category)
                      if (category) {
                        handleQuickAddCategory(category)
                      }
                    }}
                  >
                    <MenuItem value="">{t('kb.quickAddPlaceholder')}</MenuItem>
                    {getAvailableCategoriesToAdd().map(cat => (
                      <MenuItem key={cat} value={cat}>
                        {getCategoryDisplayName(cat)}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              )}

              <Divider sx={{ mb: 2 }} />

              {/* 闆嗗悎鍒楄〃 */}
              {loadingCollections ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
                  <CircularProgress />
                </Box>
              ) : collections.length === 0 ? (
                <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
                  {t('kb.noCollections')}
                </Typography>
              ) : (
                <>
                  <List sx={{ flexGrow: 1, overflow: 'auto', mb: 2 }}>
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
                          <Typography sx={{ fontWeight: 500 }}>{collection.name}</Typography>
                        </ListItemButton>
                      </ListItem>
                    ))}
                  </List>
                  
                  {/* 同步设定到工作流按钮 */}
                  <Tooltip
                    title={t('kb.syncTooltip')}
                    placement="top"
                    arrow
                  >
                    <span>
                      <Button
                        variant="outlined"
                        color="primary"
                        size="small"
                        fullWidth
                        startIcon={syncingSettings ? <CircularProgress size={16} /> : <SyncIcon />}
                        onClick={handleSyncSettingsToWorkflow}
                        disabled={syncingSettings || collections.length === 0}
                      >
                        {syncingSettings ? t('kb.validating') : t('kb.validateWorkflow')}
                      </Button>
                    </span>
                  </Tooltip>

                  {/* 合并高置信候选设定按钮（修复 P3-3：候选确认闭环） */}
                  <Tooltip
                    title={t('kb.mergeTooltip')}
                    placement="top"
                    arrow
                  >
                    <span>
                      <Button
                        variant="outlined"
                        color="secondary"
                        size="small"
                        fullWidth
                        sx={{ mt: 1 }}
                        startIcon={mergingCandidates ? <CircularProgress size={16} /> : <AutoFixHighIcon />}
                        onClick={handleMergeCandidates}
                        disabled={mergingCandidates}
                      >
                        {mergingCandidates ? t('kb.merging') : t('kb.mergeCandidates')}
                      </Button>
                    </span>
                  </Tooltip>
                </>
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
                        {t('kb.settingItems')}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {t('kb.categoryCount', { category: getCategoryDisplayName(selectedCollection.category || ''), count: settingItems.length })}
                      </Typography>
                    </Box>
                    <Button
                      variant="contained"
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={() => setCreateItemDialog(true)}
                    >
                      {t('kb.createItem')}
                    </Button>
                  </Box>

                  <Divider sx={{ mb: 2 }} />

                  <Box sx={{ display: 'flex', gap: 2, flex: 1, minHeight: 0 }}>
                    {/* 左侧分类树与右侧详情 */}
                    <Box sx={{ width: '60%', borderRight: '1px solid', borderColor: 'grey.200', pr: 1 }}>
                      <Suspense fallback={<LazySectionFallback minHeight={360} />}>
                        <LazySettingTreeView
                        collectionId={selectedCollection.id}
                        selectedItemId={selectedItem?.id}
                        refreshTrigger={treeRefreshTrigger}
                        onSelectCategory={(path, categoryItem) => {
                          setSelectedCategoryPath(path)
                          setSelectedCategoryItem(categoryItem)  // 记录当前分类项
                          setSelectedItem(null)
                        }}
                        onSelectInstance={(item) => {
                          setSelectedItem(item)
                          setSelectedCategoryPath(null)
                          setSelectedCategoryItem(null)
                        }}
                        onAddItem={handleTreeAddItem}
                        onDeleteItem={handleTreeDeleteItem}
                        title={t('kb.treeViewTitle')}
                        />
                      </Suspense>
                    </Box>

                    {/* 右侧：详情 / 列表（根据选择切换） */}
                    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                      {/* 分类描述区域，仅在选中分类时显示 */}
                      {!selectedItem && selectedCategoryPath && selectedCategoryItem && (
                        <Box sx={{ p: 2, bgcolor: 'primary.50', borderRadius: 1, mb: 2, border: '1px solid', borderColor: 'primary.200' }}>
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <FolderIcon sx={{ color: 'primary.main' }} />
                              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                {selectedCategoryItem.name}
                              </Typography>
                              <Chip label={t('kb.categoryBadge')} size="small" color="primary" variant="outlined" />
                            </Box>
                            <Box sx={{ display: 'flex', gap: 0.5 }}>
                              <Tooltip title={t('kb.editCategoryDesc')}>
                                <Button size="small" startIcon={<EditIcon />} onClick={() => {
                                  handleEditItem(selectedCategoryItem)
                                }}>
                                  {t('kb.edit')}
                                </Button>
                              </Tooltip>
                            </Box>
                          </Box>
                          {selectedCategoryItem.content ? (
                            <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                              {selectedCategoryItem.content}
                            </Typography>
                          ) : (
                            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', mb: 1 }}>
                              {t('kb.addCategoryDescHint')}
                            </Typography>
                          )}
                          <Typography variant="caption" color="text.secondary">
                            {t('kb.pathPrefix', { path: selectedCategoryPath })}
                          </Typography>
                        </Box>
                      )}

                      {/* 鍒嗙被涓嬬殑瀹炰緥鍒楄〃 */}
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
                                  onClick={() => {
                                    if (item.is_leaf) {
                                      setSelectedItem(item)
                                      setSelectedCategoryPath(null)
                                      setSelectedCategoryItem(null)
                                      return
                                    }
                                    setSelectedCategoryPath(item.path || "")
                                  }}
                                  sx={{ pr: 10 }}
                                >
                                  {item.is_leaf ? <ArticleIcon sx={{ mr: 1, fontSize: 18, color: 'text.secondary' }} /> : <FolderIcon sx={{ mr: 1, fontSize: 18, color: 'primary.main' }} />}
                                  <ListItemText
                                    primary={
                                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <Typography component="span" sx={{ fontWeight: 500 }}>
                                          {item.level != null ? `Lv.${item.level} ` : ''}{item.name}
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
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                {selectedItem.name}
                              </Typography>
                              {!selectedItem.is_leaf && (
                                <Chip label={t('kb.categoryBadge')} size="small" color="primary" variant="outlined" />
                              )}
                            </Box>
                            <Box sx={{ display: 'flex', gap: 0.5 }}>
                              <Tooltip title={t('kb.moveToOther')}>
                                <Button size="small" onClick={() => setMoveItemDialog(true)}>
                                  {t('kb.moveTo')}
                                </Button>
                              </Tooltip>
                              <Button size="small" startIcon={<EditIcon />} onClick={() => handleEditItem()}>
                                {t('kb.edit')}
                              </Button>
                            </Box>
                          </Box>
                          {selectedItem.path && (
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                              {t('kb.pathPrefix', { path: selectedItem.path })}
                            </Typography>
                          )}
                          {selectedItem.content ? (
                            <FormattedContent 
                              content={selectedItem.content} 
                              sx={{ color: 'text.secondary', fontSize: '0.875rem' }} 
                            />
                          ) : (
                            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                              {t('kb.addContentHint')}
                            </Typography>
                          )}
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
                          {t('kb.selectTreeItemHint')}
                        </Typography>
                      )}
                    </Box>
                  </Box>
                </>
              ) : (
                <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
                  {t('kb.selectCollectionHint')}
                </Typography>
              )}
            </Paper>
          </Grid>
        </Grid>
        )}

        {/* 子标签 1: 分类浏览 */}
        {settingSubTabValue === 1 && (
          <Box>
            <Suspense fallback={<LazySectionFallback minHeight={320} />}>
              <LazySettingRecommendations
              projectId={Number(projectId)}
              limit={50}
              showInsertButton={false}
              onSelectItem={(item) => {
                setSettingSubTabValue(0)
                void focusSettingItem(item.id)
              }}
              title={t('kb.popularSettingsTitle')}
              />
            </Suspense>
          </Box>
        )}

        {/* 子标签 2: 关系网络 */}
        {settingSubTabValue === 2 && (
          <Box>
            {selectedItem ? (
              <Suspense fallback={<LazySectionFallback minHeight={360} />}>
                <LazyRelationshipGraph
                itemId={selectedItem.id}
                itemName={selectedItem.name}
                onNodeClick={(nodeId) => {
                  setSettingSubTabValue(0)
                  void focusSettingItem(nodeId)
                }}
                />
              </Suspense>
            ) : (
              <Alert severity="info" sx={{ mt: 2 }}>
                {t('kb.relationGraphHint')}
              </Alert>
            )}
          </Box>
        )}
      </TabPanel>

      {/* ==================== Tab 4: 冲突检测 ==================== */}
      <TabPanel value={mainTabValue} index={4}>
        <Suspense fallback={<LazySectionFallback minHeight={360} />}>
          <LazyConflictDetector
          projectId={Number(projectId)}
          onSelectItem={(itemId) => {
            setMainTabValue(3)
            setSettingSubTabValue(0)  // 切回分类浏览 Tab
            void focusSettingItem(itemId)
          }}
          title={t('kb.conflictDetectTitle')}
          />
        </Suspense>
      </TabPanel>

      {/* ==================== 对话框 ==================== */}

      {/* 创建设定集合对话框 */}
      <Dialog open={createCollectionDialog} onClose={() => setCreateCollectionDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('kb.createCollectionTitle')}</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            margin="dense"
            label={t('kb.collectionNameLabel')}
            fullWidth
            value={newCollectionName}
            onChange={(e) => setNewCollectionName(e.target.value)}
          />
          <FormControl fullWidth margin="dense">
            <InputLabel>{t('kb.categoryLabel')}</InputLabel>
            <Select
              value={newCollectionCategory}
              label={t('kb.categoryLabel')}
              onChange={(e) => setNewCollectionCategory(e.target.value)}
            >
              {Object.entries(CATEGORY_NAME_MAP).map(([key, name]) => (
                <MenuItem key={key} value={key}>{name}</MenuItem>
              ))}
            </Select>
          </FormControl>
          <TextField
            margin="dense"
            label={t('kb.descriptionLabel')}
            fullWidth
            multiline
            rows={3}
            value={newCollectionDescription}
            onChange={(e) => setNewCollectionDescription(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setCreateCollectionDialog(false); resetCollectionForm() }}>{t('action.cancel')}</Button>
          <Button onClick={handleCreateCollection} variant="contained">{t('kb.create')}</Button>
        </DialogActions>
      </Dialog>

      {/* 应用模板弹窗 */}
      <Dialog
        open={templateDialog}
        onClose={() => !applyingTemplate && setTemplateDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>{t('kb.selectTemplateTitle')}</DialogTitle>
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
                    {t('kb.noTemplates')}
                  </Typography>
                </ListItem>
              ) : (
                settingTemplates.map((tpl: SettingTemplateMetadata) => (
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
                  {t('kb.clearExistingWarning')}
                </Typography>
              </Box>
            </FormControl>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setTemplateDialog(false)} disabled={applyingTemplate}>
            {t('action.cancel')}
          </Button>
          <Button
            onClick={handleApplyTemplate}
            variant="contained"
            disabled={!selectedTemplateKey || applyingTemplate}
            startIcon={applyingTemplate ? <CircularProgress size={20} /> : undefined}
          >
            {applyingTemplate ? t('kb.applying') : t('kb.applyTemplate')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 创建设定项弹窗 */}
      <Dialog open={createItemDialog} onClose={() => setCreateItemDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>{t('kb.createItemTitle')}</DialogTitle>
        <DialogContent>
          <Grid container spacing={2}>
            <Grid item xs={8}>
              <TextField
                autoFocus
                margin="dense"
                label={t('kb.itemNameLabel')}
                fullWidth
                value={newItemName}
                onChange={(e) => setNewItemName(e.target.value)}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label={t('kb.codeLabel')}
                fullWidth
                value={newItemCode}
                onChange={(e) => setNewItemCode(e.target.value)}
                placeholder="TAL_FIRE"
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label={t('kb.levelLabel')}
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
                label={t('kb.tagsLabel')}
                fullWidth
                value={newItemTags}
                onChange={(e) => setNewItemTags(e.target.value)}
                placeholder={t('kb.tagsPlaceholder')}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label={t('kb.contentLabel')}
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
          <Button onClick={() => { setCreateItemDialog(false); resetItemForm() }}>{t('action.cancel')}</Button>
          <Button onClick={handleCreateItem} variant="contained">{t('kb.create')}</Button>
        </DialogActions>
      </Dialog>

      {/* 层级视图创建子项对话框 */}
      <Dialog open={createChildItemDialog} onClose={() => setCreateChildItemDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          {t('kb.createChildTitle', { type: t(newItemIsLeaf ? 'kb.itemTypeItem' : 'kb.categoryBadge') })}
          {parentItemPath && (
            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              {t('kb.pathPrefix', { path: parentItemPath })}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={2}>
            {/* 绫诲瀷閫夋嫨 */}
            <Grid item xs={12}>
              <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                <Chip
                  label={t('kb.itemTypeItem')}
                  color={newItemIsLeaf ? 'primary' : 'default'}
                  variant={newItemIsLeaf ? 'filled' : 'outlined'}
                  onClick={() => setNewItemIsLeaf(true)}
                  sx={{ cursor: 'pointer' }}
                />
                <Chip
                  label={t('kb.itemTypeCategory')}
                  color={!newItemIsLeaf ? 'primary' : 'default'}
                  variant={!newItemIsLeaf ? 'filled' : 'outlined'}
                  onClick={() => setNewItemIsLeaf(false)}
                  sx={{ cursor: 'pointer' }}
                />
              </Box>
              <Typography variant="caption" color="text.secondary">
                {newItemIsLeaf ? t('kb.itemTypeHintItem') : t('kb.itemTypeHintCategory')}
              </Typography>
            </Grid>
            <Grid item xs={8}>
              <TextField
                autoFocus
                margin="dense"
                label={newItemIsLeaf ? t('kb.itemNameLabel') : t('kb.categoryNameLabel')}
                fullWidth
                value={newItemName}
                onChange={(e) => setNewItemName(e.target.value)}
                placeholder={newItemIsLeaf ? t('kb.itemNamePlaceholder') : t('kb.categoryNamePlaceholder')}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label={t('kb.codeLabel')}
                fullWidth
                value={newItemCode}
                onChange={(e) => setNewItemCode(e.target.value)}
                placeholder={t('kb.optionalPlaceholder')}
              />
            </Grid>
            {newItemIsLeaf && (
              <Grid item xs={12}>
                <TextField
                  margin="dense"
                  label={t('kb.tagsLabel')}
                  fullWidth
                  value={newItemTags}
                  onChange={(e) => setNewItemTags(e.target.value)}
                  placeholder={t('kb.tagsPlaceholder')}
                />
              </Grid>
            )}
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label={newItemIsLeaf ? t('kb.contentDescLabel') : t('kb.categoryDescLabel')}
                fullWidth
                multiline
                rows={newItemIsLeaf ? 6 : 3}
                value={newItemContent}
                onChange={(e) => setNewItemContent(e.target.value)}
                placeholder={newItemIsLeaf ? t('kb.contentDescPlaceholder') : t('kb.categoryDescPlaceholder')}
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setCreateChildItemDialog(false); resetItemForm() }}>{t('action.cancel')}</Button>
          <Button onClick={handleCreateChildItem} variant="contained">{t('kb.createWithType', { type: t(newItemIsLeaf ? 'kb.itemTypeItem' : 'kb.categoryBadge') })}</Button>
        </DialogActions>
      </Dialog>

      {/* 移动分类弹窗 */}
      <Dialog open={moveItemDialog} onClose={() => setMoveItemDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          {t('kb.moveTitle')}
          {selectedItem && (
            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              {t('kb.moveCurrent', { name: selectedItem.name })}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('kb.moveHint')}
          </Typography>
          <FormControl fullWidth margin="dense">
            <InputLabel>{t('kb.moveTargetLabel')}</InputLabel>
            <Select
              value={moveTargetPath}
              label={t('kb.moveTargetLabel')}
              onChange={(e) => setMoveTargetPath(e.target.value)}
            >
              {getAvailableMoveTargets().map((target) => (
                <MenuItem key={target.path || 'root'} value={target.path}>
                  {target.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          {selectedItem && moveTargetPath !== '' && (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('kb.moveNewPath', { path: `${moveTargetPath}/${selectedItem.name}` })}
            </Alert>
          )}
          {selectedItem && moveTargetPath === '' && selectedCollection && (
            <Alert severity="info" sx={{ mt: 2 }}>
              {t('kb.moveNewPath', { path: `${selectedCollection.name}/${selectedItem.name}` })}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setMoveItemDialog(false); setMoveTargetPath('') }}>{t('action.cancel')}</Button>
          <Button onClick={handleMoveItem} variant="contained">{t('kb.move')}</Button>
        </DialogActions>
      </Dialog>

      {/* 编辑设定项弹窗，支持智能提取 */}
      <Dialog open={editItemDialog} onClose={() => setEditItemDialog(false)} maxWidth="lg" fullWidth>
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          {t('kb.editItemTitle')}
          <Button
            variant="outlined"
            size="small"
            startIcon={smartExtractLoading ? <CircularProgress size={16} /> : <AutoFixHighIcon />}
            onClick={handleSmartExtract}
            disabled={smartExtractLoading}
          >
            {smartExtractLoading ? t('kb.extracting') : t('kb.smartExtract')}
          </Button>
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={3}>
            {/* 左侧：编辑表单 */}
            <Grid item xs={smartExtractData ? 6 : 12}>
              <Grid container spacing={2}>
                <Grid item xs={8}>
                  <TextField
                    autoFocus
                    margin="dense"
                    label={t('kb.itemNameLabel')}
                    fullWidth
                    value={newItemName}
                    onChange={(e) => setNewItemName(e.target.value)}
                  />
                </Grid>
                <Grid item xs={4}>
                  <TextField
                    margin="dense"
                    label={t('kb.codeLabel')}
                    fullWidth
                    value={newItemCode}
                    onChange={(e) => setNewItemCode(e.target.value)}
                  />
                </Grid>
                <Grid item xs={12}>
                  <TextField
                    margin="dense"
                    label={t('kb.levelLabel')}
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
                    label={t('kb.tagsLabel')}
                    fullWidth
                    value={newItemTags}
                    onChange={(e) => setNewItemTags(e.target.value)}
                  />
                </Grid>
                <Grid item xs={12}>
                  <TextField
                    margin="dense"
                    label={t('kb.contentLabel')}
                    fullWidth
                    multiline
                    rows={smartExtractData ? 10 : 6}
                    value={newItemContent}
                    onChange={(e) => setNewItemContent(e.target.value)}
                  />
                </Grid>
              </Grid>
            </Grid>

            {/* 右侧：智能提取结果 */}
            {smartExtractData && (
              <Grid item xs={6}>
                <Paper elevation={1} sx={{ p: 2, height: '100%', bgcolor: 'grey.50' }}>
                  <Typography variant="subtitle2" sx={{ mb: 2, fontWeight: 'bold', color: 'primary.main' }}>
                    {t('kb.aiExtractResult')}
                  </Typography>

                  {/* 推荐标签 */}
                  {smartExtractData.suggested_tags?.length > 0 && (
                    <Box sx={{ mb: 2 }}>
                      <Typography variant="caption" color="text.secondary">{t('kb.suggestedTags')}</Typography>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                        {smartExtractData.suggested_tags.map((tag: string, idx: number) => (
                          <Chip
                            key={idx}
                            label={tag}
                            size="small"
                            color="primary"
                            variant="outlined"
                            onClick={() => handleApplySuggestedTags([tag])}
                            sx={{ cursor: 'pointer' }}
                          />
                        ))}
                        {smartExtractData.suggested_tags.length > 1 && (
                          <Chip
                            label={t('kb.addAllTags')}
                            size="small"
                            color="success"
                            onClick={() => handleApplySuggestedTags(smartExtractData.suggested_tags)}
                            sx={{ cursor: 'pointer' }}
                          />
                        )}
                      </Box>
                    </Box>
                  )}

                  {/* 相关内容 */}
                  <Typography variant="caption" color="text.secondary">
                    {t('kb.relatedContentHint', { count: smartExtractData.related_contents?.length || 0 })}
                  </Typography>
                  <Box sx={{ mt: 1, maxHeight: 300, overflow: 'auto' }}>
                    {smartExtractData.related_contents?.length > 0 ? (
                      smartExtractData.related_contents.map((content: SettingSmartExtractRelatedContent, idx: number) => (
                        <Paper
                          key={idx}
                          elevation={0}
                          sx={{
                            p: 1.5,
                            mb: 1,
                            bgcolor: 'white',
                            border: '1px solid',
                            borderColor: content.ai_validated ? 'success.light' : 'grey.300',
                            borderRadius: 1,
                          }}
                        >
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                            <Typography variant="caption" color="text.secondary">
                              {t('kb.chapterRef', { number: content.chapter_number, title: content.chapter_title })}
                              {content.ai_validated && (
                                <Chip label={t('kb.aiValidated')} size="small" color="success" sx={{ ml: 1, height: 18 }} />
                              )}
                            </Typography>
                            <Button
                              size="small"
                              onClick={() => handleApplyExtractedContent(content.excerpt)}
                            >
                              {t('kb.append')}
                            </Button>
                          </Box>
                          <Typography variant="body2" sx={{ fontSize: '0.85rem', color: 'text.primary' }}>
                            {content.excerpt}
                          </Typography>
                        </Paper>
                      ))
                    ) : (
                      <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>
                        {t('kb.noRelatedContent')}
                      </Typography>
                    )}
                  </Box>
                </Paper>
              </Grid>
            )}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setEditItemDialog(false); resetItemForm() }}>{t('action.cancel')}</Button>
          <Button onClick={handleSaveItemEdit} variant="contained">{t('action.save')}</Button>
        </DialogActions>
      </Dialog>

      {/* 历史版本对话框 */}
      <Dialog 
        open={showHistoryDialog} 
        onClose={() => setShowHistoryDialog(false)} 
        maxWidth="md" 
        fullWidth
      >
        <DialogTitle>{t('kb.historyTitle')}</DialogTitle>
        <DialogContent dividers>
          {outlineHistory.length === 0 ? (
            <Typography color="text.secondary" sx={{ textAlign: 'center', py: 4 }}>
              {t('kb.noHistory')}
            </Typography>
          ) : (
            <List>
              {outlineHistory.slice().reverse().map((record, index) => (
                <ListItem key={index} sx={{ flexDirection: 'column', alignItems: 'flex-start' }}>
                  <Typography variant="caption" color="text.secondary">
                    {t('kb.historyItem', { time: formatDateTime(record.timestamp), count: record.chapterCount })}
                  </Typography>
                  <Typography variant="body2" sx={{ mt: 1, whiteSpace: 'pre-wrap' }}>
                    {(record.content || '').substring(0, 200)}...
                  </Typography>
                </ListItem>
              ))}
            </List>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowHistoryDialog(false)}>{t('kb.close')}</Button>
        </DialogActions>
      </Dialog>

      {hasStoryExpansionResult && (
        <Suspense fallback={null}>
          <LazyStoryExpansionResultDialog {...storyExpansionResultDialogProps} />
        </Suspense>
      )}

      {showStoryExpansionDialog && (
        <Suspense fallback={null}>
          <LazyStoryExpansionDialog {...storyExpansionDialogProps} />
        </Suspense>
      )}

      {/* 鎻愮ず娑堟伅 */}
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

      <BackToTopButton
        threshold={320}
        right={16}
        bottom="calc(env(safe-area-inset-bottom, 0px) + 24px)"
      />
    </Container>
  )
}
