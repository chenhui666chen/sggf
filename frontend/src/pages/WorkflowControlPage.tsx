import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Box,
  Stepper,
  Step,
  StepLabel,
  Button,
  Card,
  CardContent,
  Typography,
  LinearProgress,
  Grid,
  Paper,
  Dialog,
  TextField,
  Alert,
  CircularProgress,
  Tooltip,
  IconButton,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  ListItemText,
  Tabs,
  Tab,
  MenuItem,
  FormControl,
  InputLabel,
  Select,
  Fab,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import PauseIcon from '@mui/icons-material/Pause'
import RefreshIcon from '@mui/icons-material/Refresh'
import SaveIcon from '@mui/icons-material/Save'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import DescriptionIcon from '@mui/icons-material/Description'
import ArticleIcon from '@mui/icons-material/Article'
import EditNoteIcon from '@mui/icons-material/EditNote'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import PublicIcon from '@mui/icons-material/Public'
import PeopleIcon from '@mui/icons-material/People'
import NavigateNextIcon from '@mui/icons-material/NavigateNext'
import EditIcon from '@mui/icons-material/Edit'
import DownloadIcon from '@mui/icons-material/Download'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'

import HistoryIcon from '@mui/icons-material/History'
import CompareArrowsIcon from '@mui/icons-material/CompareArrows'
import Checkbox from '@mui/material/Checkbox'
import FormControlLabel from '@mui/material/FormControlLabel'
import Chip from '@mui/material/Chip'
import Snackbar from '@mui/material/Snackbar'
import MuiAlert from '@mui/material/Alert'
import { RootState, AppDispatch, store } from '@/store/store'
import {
  startWorkflow,
  regenerateStage,
  setCurrentStage,
  setProjectId,
  updateStageOutput,
  updateStageStatus,
  updateAgentStatus,  // ✅ 添加导入
  resetFollowingStages,  // ✅ 导入新的 action
  StageType,
  // 🆕 生成下一章 actions
  startGenerateNextChapter,
  updateGenerateNextChapterProgress,
  appendGenerateNextChapterStream,
  clearGenerateNextChapterStream,
  completeGenerateNextChapter,
} from '@/store/slices/workflowSlice'
import { fetchProject } from '@/store/slices/projectSlice'
import { fetchChapters } from '@/store/slices/editorSlice'
import StageInfoPanel from '@/components/workflow/StageInfoPanel'
import OutputPreviewPanel from '@/components/workflow/OutputPreviewPanel'
import AgentStatusIndicator from '@/components/workflow/AgentStatusIndicator'
import { workflowWebSocket } from '@/services/websocket'
import { apiClient } from '@/services/api'  // ✅ 添加apiClient导入
import FormattedContent from '@/components/common/FormattedContent'
import {
  calculateProgress,
  estimateRemainingTime,
  formatRemainingTime,
  saveHistory,
  getHistory,
  clearHistory,
  exportToMarkdown,
  exportChapterBreakdownToCSV,
  downloadFile,
} from '@/utils/expansionHelpers'
import { ProgressEstimator, type StageDurations, type ProgressState } from '@/utils/progressEstimator'
import { statisticsService } from '@/services/statistics'


const stages: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
const stageNames = {
  concept: '概念开发',
  structure: '结构设计',
  content: '内容创作',
  review: '质量评审',
  iteration: '迭代优化',
}

type ItemRelationForm = {
  type: string
  targetId: number | null
}

const RELATION_TYPES = ['前置', '对立', '包含', '相关'] as const

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

export default function WorkflowControlPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const workflow = useSelector((state: RootState) => state.workflow)
  // 🎯 任务3：获取当前项目信息
  const currentProject = useSelector((state: RootState) => state.project.currentProject)
  const [openDialog, setOpenDialog] = useState(false)
  const [requirement, setRequirement] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const [isStarting, setIsStarting] = useState(false)  // 新增：标记是否正在启动工作流
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [chapterTitle, setChapterTitle] = useState('')

  // 🆕 保护机制：已有内容警告对话框
  const [showContentWarningDialog, setShowContentWarningDialog] = useState(false)
  const [existingChaptersCount, setExistingChaptersCount] = useState(0)

  // 故事概念对话框状态
  const [showConceptDialog, setShowConceptDialog] = useState(false)
  const [conceptContent, setConceptContent] = useState('')
  const [editedContent, setEditedContent] = useState('')
  const [conceptLoading, setConceptLoading] = useState(false)
  const [conceptSaving, setConceptSaving] = useState(false)

  // 情节大纲对话框状态
  const [showStructureDialog, setShowStructureDialog] = useState(false)
  const [structureContent, setStructureContent] = useState('')
  const [editedStructureContent, setEditedStructureContent] = useState('')
  const [structureLoading, setStructureLoading] = useState(false)
  const [structureSaving, setStructureSaving] = useState(false)

  // 章节初稿对话框状态
  const [showContentDialog, setShowContentDialog] = useState(false)
  const [contentDraftContent, setContentDraftContent] = useState('')
  const [editedContentDraftContent, setEditedContentDraftContent] = useState('')
  const [contentLoading, setContentLoading] = useState(false)
  const [contentSaving, setContentSaving] = useState(false)

  // 最终版本对话框状态（已移除finalVersionSaving，统一使用savingChapter）
  const [showFinalVersionDialog, setShowFinalVersionDialog] = useState(false)
  const [finalVersionContent, setFinalVersionContent] = useState('')
  const [editedFinalVersionContent, setEditedFinalVersionContent] = useState('')
  const [finalVersionLoading, setFinalVersionLoading] = useState(false)

  // 评审报告对话框状态
  const [showReviewDialog, setShowReviewDialog] = useState(false)
  const [reviewReportContent, setReviewReportContent] = useState('')
  const [editedReviewReportContent, setEditedReviewReportContent] = useState('')
  const [reviewLoading, setReviewLoading] = useState(false)
  const [reviewSaving, setReviewSaving] = useState(false)

  // 🆕 流式输出状态
  const [isStreaming, setIsStreaming] = useState(false)
  const [streamingStage, setStreamingStage] = useState<StageType | null>(null)

  // 世界观设定对话框状态
  const [showWorldDialog, setShowWorldDialog] = useState(false)

  // 类型化设定管理状态（世界观相关）
  const [worldSettingsTab, setWorldSettingsTab] = useState<'text' | 'settings'>('text')
  const [settingCollections, setSettingCollections] = useState<any[]>([])
  const [settingCollectionsLoading, setSettingCollectionsLoading] = useState(false)
  const [selectedCollectionId, setSelectedCollectionId] = useState<number | null>(null)
  const [settingItems, setSettingItems] = useState<any[]>([])
  const [settingTemplates, setSettingTemplates] = useState<any[]>([])
  const [settingTemplatesLoading, setSettingTemplatesLoading] = useState(false)
  const [showTemplateDialog, setShowTemplateDialog] = useState(false)
  const [selectedTemplateKey, setSelectedTemplateKey] = useState<string | null>(null)
  const [clearExistingSettings, setClearExistingSettings] = useState(false)
  const [applyingTemplate, setApplyingTemplate] = useState(false)
  const [settingItemsLoading, setSettingItemsLoading] = useState(false)
  const [selectedCategoryToAdd, setSelectedCategoryToAdd] = useState<string>('')  // 快速添加体系状态

  // 类型设定：集合/设定项编辑对话框 & 删除确认
  const [collectionDialogOpen, setCollectionDialogOpen] = useState(false)
  const [collectionDialogMode, setCollectionDialogMode] = useState<'create' | 'edit'>('create')
  const [editingCollection, setEditingCollection] = useState<any | null>(null)
  const [collectionForm, setCollectionForm] = useState({ name: '', category: '' })
  const [collectionDialogSaving, setCollectionDialogSaving] = useState(false)
  const [collectionDialogSubmitted, setCollectionDialogSubmitted] = useState(false)

  const [itemDialogOpen, setItemDialogOpen] = useState(false)
  const [itemDialogMode, setItemDialogMode] = useState<'create' | 'edit'>('create')
  const [editingItem, setEditingItem] = useState<any | null>(null)
  const [itemDialogSaving, setItemDialogSaving] = useState(false)
  const [itemDialogSubmitted, setItemDialogSubmitted] = useState(false)
  const [itemForm, setItemForm] = useState({
    name: '',
    level: '',
    code: '',
    content: '',
    tags: [] as string[],
    tagsInput: '',
    relations: [] as ItemRelationForm[],
  })

  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<{ type: 'collection' | 'item'; id: number } | null>(null)
  const [deleteLoading, setDeleteLoading] = useState(false)

  const [draggingCollectionId, setDraggingCollectionId] = useState<number | null>(null)
  const [draggingItemId, setDraggingItemId] = useState<number | null>(null)

  const [worldContent, setWorldContent] = useState('')
  const [editedWorldContent, setEditedWorldContent] = useState('')
  const [worldLoading, setWorldLoading] = useState(false)
  const [worldSaving, setWorldSaving] = useState(false)

  // 人物设定对话框状态
  const [showCharacterDialog, setShowCharacterDialog] = useState(false)
  const [characterContent, setCharacterContent] = useState('')
  const [editedCharacterContent, setEditedCharacterContent] = useState('')
  const [characterLoading, setCharacterLoading] = useState(false)
  const [characterSaving, setCharacterSaving] = useState(false)

  // 结构化人物管理状态
  const [characterTab, setCharacterTab] = useState<'text' | 'structured'>('text')
  const [structuredCharacters, setStructuredCharacters] = useState<any[]>([])
  const [structuredCharactersLoading, setStructuredCharactersLoading] = useState(false)

  const [showCharacterEditDialog, setShowCharacterEditDialog] = useState(false)
  const [characterFormData, setCharacterFormData] = useState<any>({})
  const [characterFormLoading, setCharacterFormLoading] = useState(false)
  const [characterFormSaving, setCharacterFormSaving] = useState(false)

  const [availableTechniques, setAvailableTechniques] = useState<any[]>([])
  const [availableRealms, setAvailableRealms] = useState<any[]>([])
  const [availableForces, setAvailableForces] = useState<any[]>([])
  const [availableProfessions, setAvailableProfessions] = useState<any[]>([])
  const [availableRaces, setAvailableRaces] = useState<any[]>([])
  const [characterTechniques, setCharacterTechniques] = useState<any[]>([])
  const [selectedTechniqueId, setSelectedTechniqueId] = useState<number | ''>('')

  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error' | 'warning' | 'info'>('success')

  // 生成下一章状态
  const [generatingNextChapter, setGeneratingNextChapter] = useState(false)

  // 保存章节状态（最终版本对话框统一使用此状态）
  const [savingChapter, setSavingChapter] = useState(false)
  const [chapterTitleInput, setChapterTitleInput] = useState('')

  // 🆕 异步任务状态
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null)
  const [taskPollingInterval, setTaskPollingInterval] = useState<NodeJS.Timeout | null>(null)
  const [taskProgress, setTaskProgress] = useState(0)

  // 🆕 标记是否是“生成下一章”流程（已经自动保存，不需要再次保存）
  const [isGenerateNextChapterFlow, setIsGenerateNextChapterFlow] = useState(false)

  // 🆕 生成下一章异步任务状态 - 从 Redux 读取
  const generateNextChapter = useSelector((state: RootState) => state.workflow.generateNextChapter)
  const generateNextChapterTaskId = generateNextChapter.taskId
  const generateNextChapterProgress = generateNextChapter.progress
  const generateNextChapterStreamContent = generateNextChapter.streamContent
  const generateNextChapterNumber = generateNextChapter.chapterNumber

  // 🆕 自动保存记忆状态（始终启用，UI 面板已隐藏）
  const autoSaveEnabled = true  // 🔧 简化：始终启用自动保存
  const [, setLastSaveTime] = useState<Date | null>(null)  // 仅用于更新，不显示
  // 🔧 修复：对话历史记录 - 收集工作流中的对话内容
  const [conversationHistory, setConversationHistory] = useState<Array<{role: string, content: string, stage?: string, timestamp?: string}>>([])

  // 🆕 大纲和人物扩展功能状态
  const [showExpandOutlineDialog, setShowExpandOutlineDialog] = useState(false)
  const [expandingOutline, setExpandingOutline] = useState(false)
  const [expandedOutlineData, setExpandedOutlineData] = useState<any>(null)
  const [currentChapterCount, setCurrentChapterCount] = useState(0)  // 🆕 当前章节数
  const [targetChapterCount, setTargetChapterCount] = useState<number>(100)  // 🆕 目标章节数（默认长篇：100章）


  const [showExpandCharactersDialog, setShowExpandCharactersDialog] = useState(false)
  const [expandingCharacters, setExpandingCharacters] = useState(false)
  const [expandedCharactersData, setExpandedCharactersData] = useState<any>(null)
  const [currentCharacterCount, setCurrentCharacterCount] = useState(0)  // 🆕 当前人物数
  const [targetCharacterCount, setTargetCharacterCount] = useState<number>(25)  // 🆕 目标人物数（默认长篇：25人）

  // 🆕 进度显示优化
  const [expansionProgress, setExpansionProgress] = useState(0)  // 扩展进度 0-100
  const [expansionStartTime, setExpansionStartTime] = useState<number | null>(null)  // 开始时间
  const [estimatedTimeRemaining, setEstimatedTimeRemaining] = useState<number | null>(null)  // 预计剩余时间（秒）

  // 🆕 历史版本管理
  const [outlineHistory, setOutlineHistory] = useState<Array<{timestamp: number, content: string, chapterCount: number}>>([])
  const [characterHistory, setCharacterHistory] = useState<Array<{timestamp: number, content: string, characterCount: number}>>([])
  const [showHistoryDialog, setShowHistoryDialog] = useState(false)
  const [historyType, setHistoryType] = useState<'outline' | 'character'>('outline')

  // 类型化设定管理：加载集合和设定项
  const loadSettingItems = async (collectionId: number) => {
    if (!collectionId) return

    setSettingItemsLoading(true)
    try {
      const response = await apiClient.getSettingItems(collectionId)
      const items = (response.data || []).slice().sort(
        (a: any, b: any) => (a.order ?? 0) - (b.order ?? 0),
      )
      setSettingItems(items)
    } catch (error) {
      console.error('获取设定项失败:', error)
      setSnackbarMessage('获取设定项失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setSettingItemsLoading(false)
    }
  }

  const loadSettingCollections = async (projectIdNum: number) => {
    setSettingCollectionsLoading(true)
    try {
      const response = await apiClient.getSettingCollections(projectIdNum)
      const collections = (response.data || []).slice().sort(
        (a: any, b: any) => (a.order ?? 0) - (b.order ?? 0),
      )
      setSettingCollections(collections)

      if (collections.length > 0) {
        const firstId = collections[0].id as number
        setSelectedCollectionId(firstId)
        await loadSettingItems(firstId)
      } else {
        setSelectedCollectionId(null)
        setSettingItems([])
      }
    } catch (error) {
      console.error('获取设定集合失败:', error)
      setSnackbarMessage('获取设定集合失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setSettingCollectionsLoading(false)
    }
  }

  // 辅助函数：Category 中文名称映射
  const getCategoryDisplayName = (category: string): string => {
    return CATEGORY_NAME_MAP[category] || category
  }

  // 辅助函数：层级缩进计算
  const getIndentForItem = (item: any): number => {
    return ((item.depth || 1) - 1) * 24
  }

  // 快速添加体系相关
  const getAvailableCategoriesToAdd = (): string[] => {
    const existingCategories = new Set(settingCollections.map((c: any) => c.category))
    return Object.keys(CATEGORY_NAME_MAP)
      .filter(key => key !== 'character_system' && !existingCategories.has(key))
      .sort()
  }

  const handleQuickAddCategory = async (category: string) => {
    if (!projectId || !category) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    try {
      const collectionName = getCategoryDisplayName(category)
      await apiClient.createSettingCollection(projectIdNum, {
        name: collectionName,
        category,
        description: `${collectionName}设定`,
      })
      await loadSettingCollections(projectIdNum)
      setSnackbarMessage(`✅ 已添加「${collectionName}」`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      setSelectedCategoryToAdd('')
    } catch (error) {
      console.error('快速添加体系失败:', error)
      setSnackbarMessage('添加体系失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  // 🧬 结构化人物：加载角色列表
  const loadStructuredCharacters = async () => {
    if (!projectId) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    setStructuredCharactersLoading(true)
    try {
      const response = await apiClient.getCharacters(projectIdNum)
      setStructuredCharacters(response.data || [])
    } catch (error) {
      console.error('获取角色列表失败:', error)
      setSnackbarMessage('获取角色列表失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setStructuredCharactersLoading(false)
    }
  }

  // 🧬 结构化人物：加载可用功法（来自项目功法体系）
  const loadAvailableTechniques = async () => {
    if (!projectId) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    try {
      const response = await apiClient.getProjectTechniques(projectIdNum)
      setAvailableTechniques(response.data || [])
    } catch (error) {
      console.error('获取功法列表失败:', error)
    }
  }

  // 🧬 结构化人物：加载可用境界（智能识别各种境界体系）
  const loadAvailableRealms = async () => {
    if (!projectId) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    try {
      const collectionsResponse = await apiClient.getSettingCollections(projectIdNum)
      const collections = collectionsResponse.data || []
      
      // 智能识别四种境界体系
      const realmCategories = [
        'cultivation_realm_system',
        'martial_realm_system', 
        'magic_realm_system',
        'ability_realm_system',
      ]
      
      const allRealms: any[] = []
      for (const category of realmCategories) {
        const realmCollection = collections.find((c: any) => c.category === category)
        if (realmCollection) {
          try {
            const itemsResponse = await apiClient.getSettingItems(realmCollection.id)
            const items = itemsResponse.data || []
            allRealms.push(...items)
          } catch (error) {
            console.error(`获取${category}境界列表失败:`, error)
          }
        }
      }
      
      setAvailableRealms(allRealms)
    } catch (error) {
      console.error('获取境界列表失败:', error)
    }
  }

  // 🧬 结构化人物：加载可用势力（从 force_system 体系）
  const loadAvailableForces = async () => {
    if (!projectId) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    try {
      const collectionsResponse = await apiClient.getSettingCollections(projectIdNum)
      const collections = collectionsResponse.data || []
      const forceCollection = collections.find((c: any) => c.category === 'force_system')
      if (forceCollection) {
        const itemsResponse = await apiClient.getSettingItems(forceCollection.id)
        setAvailableForces(itemsResponse.data || [])
      } else {
        setAvailableForces([])
      }
    } catch (error) {
      console.error('获取势力列表失败:', error)
    }
  }

  // 🧬 结构化人物：加载可用职业（从 profession_class_system 体系）
  const loadAvailableProfessions = async () => {
    if (!projectId) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    try {
      const collectionsResponse = await apiClient.getSettingCollections(projectIdNum)
      const collections = collectionsResponse.data || []
      const professionCollection = collections.find((c: any) => c.category === 'profession_class_system')
      if (professionCollection) {
        const itemsResponse = await apiClient.getSettingItems(professionCollection.id)
        setAvailableProfessions(itemsResponse.data || [])
      } else {
        setAvailableProfessions([])
      }
    } catch (error) {
      console.error('获取职业列表失败:', error)
    }
  }

  // 🧬 结构化人物：加载可用种族（从 race_bloodline_system 体系）
  const loadAvailableRaces = async () => {
    if (!projectId) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    try {
      const collectionsResponse = await apiClient.getSettingCollections(projectIdNum)
      const collections = collectionsResponse.data || []
      const raceCollection = collections.find((c: any) => c.category === 'race_bloodline_system')
      if (raceCollection) {
        const itemsResponse = await apiClient.getSettingItems(raceCollection.id)
        setAvailableRaces(itemsResponse.data || [])
      } else {
        setAvailableRaces([])
      }
    } catch (error) {
      console.error('获取种族列表失败:', error)
    }
  }

  const loadSettingTemplates = async () => {
    setSettingTemplatesLoading(true)
    try {
      const response = await apiClient.getSettingTemplates()
      setSettingTemplates(response.data || [])
    } catch (error) {
      console.error('获取设定模板列表失败:', error)
      setSnackbarMessage('获取设定模板列表失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setSettingTemplatesLoading(false)
    }
  }

  const handleOpenTemplateDialog = () => {
    if (!projectId) {
      setSnackbarMessage('请先选择一个项目')
      setSnackbarSeverity('warning')
      setSnackbarOpen(true)
      return
    }

    setShowTemplateDialog(true)
    setSelectedTemplateKey(null)
    setClearExistingSettings(false)
    loadSettingTemplates()
  }

  const handleApplyTemplate = async () => {
    if (!projectId || !selectedTemplateKey) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    setApplyingTemplate(true)
    try {
      await apiClient.applySettingTemplate(projectIdNum, {
        template_key: selectedTemplateKey,
        clear_existing: clearExistingSettings,
      })

      await loadSettingCollections(projectIdNum)

      setShowTemplateDialog(false)
      setSnackbarMessage('已应用设定模板')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      console.error('应用设定模板失败:', error)
      setSnackbarMessage('应用设定模板失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setApplyingTemplate(false)
    }
  }

  const handleCreateCollection = () => {
    if (!projectId) return

    setCollectionDialogMode('create')
    setEditingCollection(null)
    setCollectionForm({ name: '', category: '' })
    setCollectionDialogSubmitted(false)
    setCollectionDialogOpen(true)
  }

  const handleEditCollection = (collection: any) => {
    setCollectionDialogMode('edit')
    setEditingCollection(collection)
    setCollectionForm({
      name: collection.name || '',
      category: collection.category || '',
    })
    setCollectionDialogSubmitted(false)
    setCollectionDialogOpen(true)
  }

  const handleDeleteCollection = (collectionId: number) => {
    setDeleteTarget({ type: 'collection', id: collectionId })
    setDeleteDialogOpen(true)
  }

  const handleCreateItem = () => {
    if (!selectedCollectionId) return

    setItemDialogMode('create')
    setEditingItem(null)
    setItemForm({
      name: '',
      level: '',
      code: '',
      content: '',
      tags: [],
      tagsInput: '',
      relations: [],
    })
    setItemDialogSubmitted(false)
    setItemDialogOpen(true)
  }

  const handleEditItem = (item: any) => {
    setItemDialogMode('edit')
    setEditingItem(item)
    setItemForm({
      name: item.name || '',
      level: item.level != null ? String(item.level) : '',
      code: item.code || '',
      content: item.content || '',
      tags: item.tags || [],
      tagsInput: '',
      relations: parseRelationsFromApi(item.relations),
    })
    setItemDialogSubmitted(false)
    setItemDialogOpen(true)
  }

  const handleDeleteItem = (itemId: number) => {
    setDeleteTarget({ type: 'item', id: itemId })
    setDeleteDialogOpen(true)
  }



  // 🆕 编辑功能
  const [isEditingExpansion, setIsEditingExpansion] = useState(false)

  const parseRelationsFromApi = (value: any): ItemRelationForm[] => {
    if (!value || !Array.isArray(value.links)) return []
    return value.links.map((link: any) => ({
      type: link.type || '相关',
      targetId: typeof link.target_id === 'number' ? link.target_id : null,
    }))
  }

  const buildRelationsPayload = (relations: ItemRelationForm[]) => {
    const links = relations
      .filter((r) => r.targetId != null && r.type)
      .map((r) => ({ type: r.type, target_id: r.targetId }))
    return links.length > 0 ? { links } : null
  }

  const handleTagInputKeyDown = (event: any) => {
    if (event.key !== 'Enter' && event.key !== ' ') return
    event.preventDefault()
    const raw = (itemForm.tagsInput || '').trim()
    if (!raw) return
    if (!itemForm.tags.includes(raw)) {
      setItemForm((prev) => ({
        ...prev,
        tags: [...prev.tags, raw],
        tagsInput: '',
      }))
    } else {
      setItemForm((prev) => ({ ...prev, tagsInput: '' }))
    }
  }

  function handleRemoveTag(tag: string) {
    setItemForm((prev) => ({
      ...prev,
      tags: prev.tags.filter((t) => t !== tag),
    }))
  }

	  const handleAddRelation = () => {
	    setItemForm((prev) => ({
	      ...prev,
	      relations: [...prev.relations, { type: '相关', targetId: null }],
	    }))
	  }

	  const handleChangeRelation = (
	    index: number,
	    field: keyof ItemRelationForm,
	    value: any,
	  ) => {
	    setItemForm((prev) => {
	      const relations = [...prev.relations]
	      relations[index] = { ...relations[index], [field]: value }
	      return { ...prev, relations }
	    })
	  }

	  const handleRemoveRelationRow = (index: number) => {
	    setItemForm((prev) => ({
	      ...prev,
	      relations: prev.relations.filter((_, i) => i !== index),
	    }))
	  }


  const handleCloseCollectionDialog = () => {
    if (collectionDialogSaving) return
    setCollectionDialogOpen(false)
  }

  const handleSubmitCollectionDialog = async () => {
    if (!projectId) return
    setCollectionDialogSubmitted(true)
    if (!collectionForm.name.trim()) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    setCollectionDialogSaving(true)
    try {
      if (collectionDialogMode === 'create') {
        await apiClient.createSettingCollection(projectIdNum, {
          name: collectionForm.name.trim(),
          category: collectionForm.category.trim() || undefined,
          description: '',
          order: settingCollections.length,
        })
        setSnackbarMessage('创建设定集合成功')
      } else if (editingCollection) {
        await apiClient.updateSettingCollection(editingCollection.id, {
          name: collectionForm.name.trim(),
          category: collectionForm.category.trim() || undefined,
        })
        setSnackbarMessage('更新设定集合成功')
      }
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      await loadSettingCollections(projectIdNum)
      setCollectionDialogOpen(false)
    } catch (error) {
      console.error('保存设定集合失败:', error)
      setSnackbarMessage('保存设定集合失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCollectionDialogSaving(false)
    }
  }

  const handleCloseItemDialog = () => {
    if (itemDialogSaving) return
    setItemDialogOpen(false)
  }

  const handleSubmitItemDialog = async () => {
    if (!selectedCollectionId) return
    setItemDialogSubmitted(true)
    if (!itemForm.name.trim()) return

    const levelTrimmed = itemForm.level.trim()
    const levelValue = levelTrimmed ? Number(levelTrimmed) : undefined

    const payload: any = {
      name: itemForm.name.trim(),
      level:
        typeof levelValue === 'number' && !Number.isNaN(levelValue) ? levelValue : undefined,
      code: itemForm.code.trim() || undefined,
      content: itemForm.content || '',
      tags: itemForm.tags,
      relations: buildRelationsPayload(itemForm.relations),
    }

    setItemDialogSaving(true)
    try {
      if (itemDialogMode === 'create') {
        payload.order = settingItems.length
        await apiClient.createSettingItem(selectedCollectionId, payload)
        setSnackbarMessage('创建设定项成功')
      } else if (editingItem) {
        await apiClient.updateSettingItem(editingItem.id, payload)
        setSnackbarMessage('更新设定项成功')
      }
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      await loadSettingItems(selectedCollectionId)
      setItemDialogOpen(false)
    } catch (error) {
      console.error('保存设定项失败:', error)
      setSnackbarMessage('保存设定项失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setItemDialogSaving(false)
    }
  }

  const handleCopyItem = async (item: any) => {
    if (!selectedCollectionId) return
    try {
      await apiClient.createSettingItem(selectedCollectionId, {
        name: `${item.name} (副本)`,
        level: item.level,
        code: item.code,
        content: item.content,
        tags: item.tags || [],
        relations: item.relations || null,
        order: settingItems.length,
      })
      await loadSettingItems(selectedCollectionId)
      setSnackbarMessage('已复制设定项')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      console.error('复制设定项失败:', error)
      setSnackbarMessage('复制设定项失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return

    setDeleteLoading(true)
    try {
      if (deleteTarget.type === 'collection') {
        await apiClient.deleteSettingCollection(deleteTarget.id)
        if (projectId) {
          const projectIdNum = Number(projectId)
          if (!Number.isNaN(projectIdNum)) {
            await loadSettingCollections(projectIdNum)
          }
        }
      } else {
        await apiClient.deleteSettingItem(deleteTarget.id)
        if (selectedCollectionId) {
          await loadSettingItems(selectedCollectionId)
        }
      }
      setSnackbarMessage('删除成功')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      setDeleteDialogOpen(false)
      setDeleteTarget(null)
    } catch (error) {
      console.error('删除失败:', error)
      setSnackbarMessage('删除失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setDeleteLoading(false)
    }
  }

  const handleCancelDelete = () => {
    if (deleteLoading) return
    setDeleteDialogOpen(false)
    setDeleteTarget(null)
  }

  const handleDropCollection = async (targetCollectionId: number) => {
    if (!projectId || draggingCollectionId == null || draggingCollectionId === targetCollectionId) {
      return
    }

    const reordered = [...settingCollections]
    const fromIndex = reordered.findIndex((c) => c.id === draggingCollectionId)
    const toIndex = reordered.findIndex((c) => c.id === targetCollectionId)
    if (fromIndex === -1 || toIndex === -1) {
      setDraggingCollectionId(null)
      return
    }

    const [moved] = reordered.splice(fromIndex, 1)
    reordered.splice(toIndex, 0, moved)

    const withOrder = reordered.map((c, index) => ({
      ...c,
      order: index,
    }))
    setSettingCollections(withOrder)

    try {
      await Promise.all(
        withOrder.map((c, index) => apiClient.updateSettingCollection(c.id, { order: index })),
      )
      setSnackbarMessage('已更新集合顺序')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      console.error('更新集合排序失败:', error)
      setSnackbarMessage('更新集合排序失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      if (projectId) {
        const projectIdNum = Number(projectId)
        if (!Number.isNaN(projectIdNum)) {
          loadSettingCollections(projectIdNum)
        }
      }
    } finally {
      setDraggingCollectionId(null)
    }
  }

  const handleDropItem = async (targetItemId: number) => {
    if (!selectedCollectionId || draggingItemId == null || draggingItemId === targetItemId) {
      return
    }

    const reordered = [...settingItems]
    const fromIndex = reordered.findIndex((i) => i.id === draggingItemId)
    const toIndex = reordered.findIndex((i) => i.id === targetItemId)
    if (fromIndex === -1 || toIndex === -1) {
      setDraggingItemId(null)
      return
    }

    const [moved] = reordered.splice(fromIndex, 1)
    reordered.splice(toIndex, 0, moved)

    const withOrder = reordered.map((item, index) => ({
      ...item,
      order: index,
    }))
    setSettingItems(withOrder)

    try {
      await apiClient.reorderSettingItems(
        selectedCollectionId,
        withOrder.map((item, index) => ({ id: item.id, order: index })),
      )
      setSnackbarMessage('已更新设定项顺序')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      console.error('更新设定项排序失败:', error)
      setSnackbarMessage('更新设定项排序失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      await loadSettingItems(selectedCollectionId)
    } finally {
      setDraggingItemId(null)
    }
  }


  const [editedExpansionContent, setEditedExpansionContent] = useState('')

  // 🆕 进度估算器相关状态
  const [progressEstimator, setProgressEstimator] = useState<ProgressEstimator | null>(null)
  const [stageDurations, setStageDurations] = useState<StageDurations | null>(null)
  const [estimatedRemainingTime, setEstimatedRemainingTime] = useState(0)
  const [estimatedRemainingTimeMin, setEstimatedRemainingTimeMin] = useState(0)  // 🆕
  const [estimatedRemainingTimeMax, setEstimatedRemainingTimeMax] = useState(0)  // 🆕

  // 🆕 初始化进度估算器（自适应学习 + 置信区间）
  useEffect(() => {
    const initProgressEstimator = async () => {
      try {
        // 🆕 优先使用最近3次任务的平均耗时（自适应学习）
        let durations = await statisticsService.getStageDurations(
          projectId ? Number(projectId) : undefined,
          3  // 最近3次任务
        )

        // 检查是否有足够的数据
        const hasEnoughData = Object.values(durations).every(d => d > 0)

        if (!hasEnoughData) {
          // 如果最近3次任务数据不足，回退到全局平均
          console.log('⚠️ 最近3次任务数据不足，回退到全局平均耗时')
          durations = await statisticsService.getStageDurations(
            projectId ? Number(projectId) : undefined
          )
        }

        console.log('📊 最终使用的阶段耗时:', durations)
        setStageDurations(durations)

        // 🆕 获取置信区间
        const durationRanges = await statisticsService.getStageDurationRanges(
          projectId ? Number(projectId) : undefined
        )

        // 创建进度估算器（传入置信区间）
        const estimator = new ProgressEstimator(durations, durationRanges || undefined)
        setProgressEstimator(estimator)
      } catch (error) {
        console.error('初始化进度估算器失败:', error)
      }
    }

    initProgressEstimator()
  }, [projectId])

  useEffect(() => {
    if (projectId) {
      // 🔧 修复：不再从 localStorage 恢复阶段
      // 原因：localStorage 中的阶段可能与后端实际状态不一致
      // 改为从后端 API 获取实际的工作流状态

      // 🎯 任务2：项目切换时设置新的项目上下文
      dispatch(setProjectId(Number(projectId)))

      // 🎯 任务3：加载项目信息用于显示
      dispatch(fetchProject(Number(projectId)))
    }
  }, [projectId, dispatch])

  // 🔧 修复：移除 localStorage 阶段保存逻辑
  // 原因：localStorage 中的阶段可能与后端实际状态不一致
  // 改为完全依赖后端 API 返回的状态
  // useEffect(() => {
  //   if (projectId && workflow.currentStage) {
  //     localStorage.setItem(`project_${projectId}_currentStage`, workflow.currentStage)
  //     console.log(`💾 保存项目 ${projectId} 的当前阶段: ${workflow.currentStage}`)
  //   }
  // }, [projectId, workflow.currentStage])

  // 🔥 初始化加载历史记录
  useEffect(() => {
    const outlineHistoryData = getHistory('outline')
    const characterHistoryData = getHistory('character')
    setOutlineHistory(outlineHistoryData)
    setCharacterHistory(characterHistoryData)
    console.log(`💾 已加载历史记录: 大纲${outlineHistoryData.length}条, 人物${characterHistoryData.length}条`)
  }, [])

  // 🆕 页面加载时恢复记忆快照
  useEffect(() => {
    if (!projectId) return

    const loadLatestMemory = async () => {
      try {
        const token = localStorage.getItem('access_token')
        if (!token) return

        const response = await fetch(`/api/v1/projects/${projectId}/memories/latest`, {
          headers: {
            'Authorization': `Bearer ${token}`,
          },
        })

        if (response.ok) {
          const memory = await response.json()
          if (memory) {
            // 恢复对话历史
            if (memory.messages && Array.isArray(memory.messages)) {
              setConversationHistory(memory.messages)
              console.log(`🔄 已恢复对话历史: ${memory.messages.length} 条`)
            }
            // 恢复写作目标
            if (memory.writing_goal && !requirement) {
              setRequirement(memory.writing_goal)
              console.log(`🔄 已恢复写作目标: ${memory.writing_goal.substring(0, 50)}...`)
            }
            // 更新最后保存时间
            if (memory.updated_at) {
              setLastSaveTime(new Date(memory.updated_at))
            }
            console.log(`✅ 记忆快照已恢复，项目: ${projectId}`)
          }
        }
      } catch (error) {
        console.error('❌ 恢复记忆快照失败:', error)
      }
    }

    loadLatestMemory()
  }, [projectId])

  // 🆕 计算基于时间权重的总体进度
  useEffect(() => {
    if (!stageDurations) return

    // 计算总预估时间
    const totalDuration = Object.values(stageDurations).reduce((sum, duration) => sum + duration, 0)

    // 计算已完成阶段的时间
    let completedDuration = 0
    stages.forEach((stage) => {
      const stageStatus = workflow.stages[stage].status
      if (stageStatus === 'completed') {
        completedDuration += stageDurations[stage]
      } else if (stageStatus === 'active' && stage === workflow.currentStage) {
        // 当前阶段的进度
        completedDuration += (stageDurations[stage] * taskProgress) / 100
      }
    })

    // 计算总体进度
    const overallProgress = Math.round((completedDuration / totalDuration) * 100)

    // 更新 Redux 状态
    if (overallProgress !== workflow.overallProgress) {
      dispatch({ type: 'workflow/updateOverallProgress', payload: overallProgress })
    }
  }, [stageDurations, workflow.stages, workflow.currentStage, taskProgress, dispatch])

  // 🆕 处理 Redux 状态（从 DashboardPage 跳转过来时）
  useEffect(() => {
    if (generateNextChapterTaskId) {
      console.log(`📍 检测到生成下一章任务: taskId=${generateNextChapterTaskId}, chapterNumber=${generateNextChapterNumber}`)
      setGeneratingNextChapter(true)
      setIsGenerateNextChapterFlow(true)
    }
  }, [generateNextChapterTaskId, generateNextChapterNumber])

  // 🔌 WebSocket 连接管理
  useEffect(() => {
    if (!projectId) return

    console.log('🔌 初始化 WebSocket 连接...')

    // 连接 WebSocket （异步）
    workflowWebSocket.connect().then(() => {
      console.log('✅ WebSocket 连接就绪，加入项目房间')
      workflowWebSocket.joinProject(Number(projectId))
    }).catch((error) => {
      console.error('❌ WebSocket 连接失败:', error)
    })

    // 监听阶段更新
    workflowWebSocket.onStageUpdate((data) => {
      console.log('📊 收到阶段更新:', data)

      const stageType = data.stage as StageType

      // 更新 Redux 状态
      if (data.status === 'active') {
        dispatch(updateStageStatus({ stage: stageType, status: 'active' }))

        // ✅ 临时方案：将该阶段的所有 Agent 设置为工作中
        const agents = workflow.stages[stageType].agents
        agents.forEach(agent => {
          dispatch(updateAgentStatus({
            stage: stageType,
            agentId: agent.id,
            status: 'working',
            progress: 0,
            message: '执行中...'
          }))
        })
        console.log(`✅ 阶段 ${stageType} 开始，所有 Agent 设置为工作中`)
      } else if (data.status === 'completed') {
        dispatch(updateStageStatus({ stage: stageType, status: 'completed' }))

        // ✅ 临时方案：将该阶段的所有 Agent 设置为完成
        const agents = workflow.stages[stageType].agents
        agents.forEach(agent => {
          dispatch(updateAgentStatus({
            stage: stageType,
            agentId: agent.id,
            status: 'completed',
            progress: 100,
            message: '执行完成'
          }))
        })
        console.log(`✅ 阶段 ${stageType} 完成，所有 Agent 设置为完成`)

        if (data.output) {
          dispatch(updateStageOutput({ stage: stageType, output: data.output }))

          // 🔥 关键修复：同步更新组件本地状态
          if (stageType === 'iteration') {
            setFinalVersionContent(data.output)
            console.log(`🔄 迭代优化阶段完成，已同步 finalVersionContent，长度: ${data.output.length}`)
          } else if (stageType === 'review') {
            setReviewReportContent(data.output)
            console.log(`🔄 质量评审阶段完成，已同步 reviewReportContent，长度: ${data.output.length}`)
          } else if (stageType === 'content') {
            setContentDraftContent(data.output)
            console.log(`🔄 内容创作阶段完成，已同步 contentDraftContent，长度: ${data.output.length}`)
          }

          // 🆕 收集对话历史：将阶段输出添加到对话记录
          if (data.output) {
            const outputContent = data.output.substring(0, 2000) // 限制长度，避免数据过大
            setConversationHistory(prev => [
              ...prev,
              {
                role: 'assistant',
                content: outputContent,
                stage: stageType,
                timestamp: new Date().toISOString()
              }
            ])
            console.log(`💬 对话历史已更新，阶段: ${stageType}`)
          }
        }
      }

      // 更新进度
      if (data.progress !== undefined) {
        setTaskProgress(data.progress)

        // ✅ 临时方案：根据阶段进度更新 Agent 进度
        const agents = workflow.stages[stageType].agents
        agents.forEach(agent => {
          if (agent.status === 'working') {
            dispatch(updateAgentStatus({
              stage: stageType,
              agentId: agent.id,
              status: 'working',
              progress: data.progress || 0,  // ✅ 添加默认值
              message: `进度: ${data.progress}%`
            }))
          }
        })
      }
    })

    // 监听任务进度
    workflowWebSocket.onTaskProgress((data) => {
      console.log('📈 收到任务进度:', data)

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        console.log('📈 生成下一章任务进度:', data.progress, data.message)
        const progress = data.progress || 0

        // 🆕 根据进度计算当前步骤
        // 步骤1: 章节规划 (0-25%) -> structure
        // 步骤2: 内容创作 (25-50%) -> content
        // 步骤3: 质量评审 (50-75%) -> review
        // 步骤4: 迭代优化 (75-100%) -> iteration
        let currentStep = 1
        let targetStage: StageType = 'structure'
        if (progress < 25) {
          currentStep = 1
          targetStage = 'structure'
        } else if (progress < 50) {
          currentStep = 2
          targetStage = 'content'
        } else if (progress < 75) {
          currentStep = 3
          targetStage = 'review'
        } else {
          currentStep = 4
          targetStage = 'iteration'
        }

        // 使用 Redux action 更新进度和步骤
        dispatch(updateGenerateNextChapterProgress({ progress, currentStep }))

        // 切换工作流阶段
        dispatch(setCurrentStage(targetStage))
        console.log(`📍 生成下一章: 自动切换到 ${targetStage} 阶段 (进度: ${progress}%)`)

        return  // 不更新普通任务进度
      }

      // 🆕 更新进度估算器的真实进度
      if (progressEstimator) {
        progressEstimator.updateRealProgress(data.progress)
      } else {
        // 如果没有进度估算器，直接设置进度
        setTaskProgress(data.progress)
      }

      if (data.message) {
        setSnackbarMessage(data.message)
        setSnackbarSeverity('info' as any)
        setSnackbarOpen(true)
      }
    })

    // 监听任务完成
    workflowWebSocket.onTaskComplete((data) => {
      console.log('✅ 收到任务完成:', data)

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        console.log('✅ 生成下一章任务完成:', data.result)

        // 使用 Redux action 清除任务状态
        dispatch(completeGenerateNextChapter())
        setGeneratingNextChapter(false)

        // 提取章节信息
        const chapter = data.result?.chapter
        if (chapter) {
          setSnackbarMessage(`🎉 第${chapter.chapter_number}章已生成：${chapter.title} (${chapter.word_count}字)`)
        } else {
          setSnackbarMessage('✅ 章节生成完成！')
        }
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        // 刷新章节列表
        if (projectId) {
          dispatch(fetchChapters(parseInt(projectId)))
        }
        return
      }

      // 🆕 完成进度估算器
      if (progressEstimator) {
        progressEstimator.complete()
      }

      // 🆕 清除任务状态
      setCurrentTaskId(null)
      setTaskProgress(100)

      // 🆕 尝试从 data 中提取阶段信息并更新 Redux
      // 注意：需要后端在 send_task_complete 中传递 stage 和 output
      if (data.result && typeof data.result === 'object') {
        const result = data.result as any
        if (result.output) {
          console.log('✅ 任务结果包含输出内容，可能需要更新 Redux')
          // 如果后端传递了 stage 信息，可以在这里更新
          // dispatch(updateStageOutput({ stage: data.stage, output: result.output }))
        }
      }

      setSnackbarMessage('任务完成！')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      console.log('💡 WebSocket 任务完成通知已处理，无需轮询')
    })

    // 监听任务错误
    workflowWebSocket.onTaskError((data) => {
      console.log('❌ 收到任务错误:', data)

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 检查是否是"生成下一章"任务
      if (data.task_id && currentTaskId && data.task_id === currentTaskId) {
        console.log('❌ 生成下一章任务失败:', data.error)

        // 使用 Redux action 清除任务状态
        dispatch(completeGenerateNextChapter())
        setGeneratingNextChapter(false)

        setSnackbarMessage(`生成章节失败: ${data.error}`)
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      // 🆕 停止进度估算器
      if (progressEstimator) {
        progressEstimator.stop()
      }

      setCurrentTaskId(null)
      setTaskProgress(0)

      setSnackbarMessage(`任务失败: ${data.error}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)

      setIsRunning(false)
    })

    // 监听 Agent 状态
    workflowWebSocket.onAgentStatus((data) => {
      console.log('🤖 收到 Agent 状态:', data)

      // ✅ 更新 Redux 状态
      // 尝试从 agent_id 或 agent_name 推断阶段
      let stage: StageType | null = data.stage as StageType || null
      const agentId = data.agent_id || data.agent_name.toLowerCase().replace(/\s+/g, '-')

      // 如果没有阶段信息，尝试从 agent_id 推断
      if (!stage) {
        // 根据 agent_id 推断阶段
        if (agentId.includes('creative') || agentId.includes('worldview') || agentId.includes('character') || agentId.includes('world') || agentId.includes('创意') || agentId.includes('世界') || agentId.includes('人物')) {
          stage = 'concept'
        } else if (agentId.includes('plot') || agentId.includes('event') || agentId.includes('情节')) {
          stage = 'structure'
        } else if (agentId.includes('content') || agentId.includes('style') || agentId.includes('内容') || agentId.includes('文风')) {
          stage = 'content'
        } else if (agentId.includes('quality') || agentId.includes('review') || agentId.includes('质量') || agentId.includes('评审')) {
          stage = 'review'
        } else if (agentId.includes('iteration') || agentId.includes('迭代')) {
          stage = 'iteration'
        } else {
          // 默认使用当前阶段
          stage = workflow.currentStage
        }
      }

      if (stage) {
        dispatch(updateAgentStatus({
          stage: stage,
          agentId: agentId,
          status: data.status as any,  // 强制类型转换
          progress: data.progress || 0,
          message: data.message || ''
        }))
        console.log(`✅ Agent 状态已更新: ${agentId} (${stage}) -> ${data.status}`)
      }
    })

    // 🆕 监听流式输出开始（移除自动打开对话框，直接在主页面显示）
    workflowWebSocket.onStreamStart((data) => {
      console.log('🌊 流式输出开始:', data)
      setIsStreaming(true)
      setStreamingStage(data.stage as StageType)

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      // 🆕 如果是"生成下一章"任务，清空临时流式内容（为新步骤准备）
      if (currentTaskId) {
        dispatch(clearGenerateNextChapterStream())  // 清空临时内容，准备接收新步骤的流式输出
      }

      // 🔄 只清空对应阶段的内容，不再自动打开对话框
      const stageType = data.stage as StageType
      if (stageType === 'content') {
        setContentDraftContent('')  // 清空缓存
        setEditedContentDraftContent('')  // 清空编辑内容
      } else if (stageType === 'review') {
        setReviewReportContent('')
        setEditedReviewReportContent('')
      } else if (stageType === 'iteration') {
        setFinalVersionContent('')
        setEditedFinalVersionContent('')
      }

      setSnackbarMessage(data.message || `${data.stage} 阶段开始生成内容...`)
      setSnackbarSeverity('info')
      setSnackbarOpen(true)
    })

    // 🆕 监听流式输出块（打字机效果 - 直接在主页面的输出预览区显示）
    workflowWebSocket.onStreamChunk((data) => {
      const stageType = data.stage as StageType

      // 🆕 从 Redux store 直接读取最新状态（避免闭包问题）
      const currentState = store.getState()
      const currentTaskId = currentState.workflow.generateNextChapter.taskId

      console.log(`🌊 stream_chunk: stage=${stageType}, taskId=${currentTaskId}, chunkLen=${data.chunk?.length}`)

      // 🆕 如果是"生成下一章"任务，使用临时流式内容状态
      if (currentTaskId) {
        // 生成下一章模式：流式内容存入临时状态（不保存到数据库缓存）
        console.log(`📝 追加流式内容到 Redux, 当前总长度=${currentState.workflow.generateNextChapter.streamContent.length}`)
        dispatch(appendGenerateNextChapterStream(data.chunk))
        return
      }

      // 🔄 普通模式：实时更新对应阶段的内容显示（仅更新缓存，对话框打开时再同步）
      if (stageType === 'content') {
        setContentDraftContent(prev => prev + data.chunk)
      } else if (stageType === 'review') {
        setReviewReportContent(prev => prev + data.chunk)
      } else if (stageType === 'iteration') {
        setFinalVersionContent(prev => prev + data.chunk)
      }
    })

    // 🆕 监听流式输出结束
    workflowWebSocket.onStreamEnd((data) => {
      console.log('🌊 流式输出结束:', data)
      setIsStreaming(false)
      setStreamingStage(null)

      setSnackbarMessage(data.message || `${data.stage} 阶段内容生成完成，共 ${data.total_chars} 字`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    })

    // 🔔 组件卸载时：清除监听器，但不断开 WebSocket 连接
    return () => {
      console.log('🔌 清理 WebSocket 监听器（保持连接）...')
      // 🔔 修改：使用新方法，只移除监听器，不断开连接
      workflowWebSocket.removeEventListeners()  // ✅ 使用新方法
      // 🔔 不离开房间，以便在后台继续接收消息
      // if (projectId) {
      //   workflowWebSocket.leaveProject(Number(projectId))  // 🚫 删除此行
      // }
      console.log('✅ WebSocket 连接已保持，可在后台继续接收消息')
    }
  }, [projectId, dispatch])

  // 页面刷新时加载所有已保存的阶段内容和状态
  useEffect(() => {
    if (!projectId) return

    // 🔧 关键修复: 延迟执行，等待Token加载
    const timer = setTimeout(() => {
      const loadAllStageContents = async () => {
        try {
          // 🔧 关键修复: 确保Token存在才执行请求
          const token = localStorage.getItem('access_token')
          if (!token) {
            console.log('🔐 用户未登录，等待登录后自动加载内容')
            return
          }

          console.log('📍 开始加载所有阶段内容...')

          // 🔧 关键修复：使用局部变量跟踪恢复状态，避免异步状态更新问题
          let hasRestoredRunningTask = false
          let restoredStage: StageType | null = null

          // 🔔 步骤1：检查是否有正在运行的任务
          try {
            const runningTasksResponse = await fetch(
              `/api/v1/workflow/project/${projectId}/running-tasks`,
              {
                headers: {
                  'Authorization': `Bearer ${token}`,
                },
              }
            )

            if (runningTasksResponse.ok) {
              const runningTasksData = await runningTasksResponse.json()
              const runningTasks = runningTasksData.running_tasks || []
              const timeoutTasks = runningTasksData.timeout_tasks || []

              // 🔧 新增：显示超时任务提示
              if (timeoutTasks.length > 0) {
                console.log(`⏰ 检测到 ${timeoutTasks.length} 个超时任务已被自动清理`)
                setSnackbarMessage(`⏰ 检测到 ${timeoutTasks.length} 个超时任务已被自动清理`)
                setSnackbarSeverity('warning')
                setSnackbarOpen(true)
              }

              if (runningTasks.length > 0) {
                console.log(`🔍 发现 ${runningTasks.length} 个正在运行的任务，开始恢复...`)

                // 恢复最新的任务
                const latestTask = runningTasks[0]
                const taskType = latestTask.task_type

                // 从 task_type 提取 stage （例如："workflow_stage_concept" -> "concept"）
                const stageName = taskType.replace('workflow_stage_', '')
                const stageType = stageName as StageType

                // 🔧 验证 stageType 是否有效
                const validStages: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
                if (!validStages.includes(stageType)) {
                  console.warn(`⚠️  无效的阶段类型: ${stageType}，跳过恢复`)
                } else {
                  // 🔧 新增：显示任务运行时间
                  const ageMinutes = latestTask.age_minutes || 0
                  console.log(`📌 恢复任务: ${latestTask.task_id}, 阶段: ${stageType}, 已运行: ${ageMinutes.toFixed(1)}分钟`)

                  // 更新状态
                  setCurrentTaskId(latestTask.task_id)
                  setIsRunning(true)
                  // 🔧 关键修复：使用局部变量记录恢复状态，避免后续代码覆盖
                  hasRestoredRunningTask = true
                  restoredStage = stageType

                  dispatch(setCurrentStage(stageType))
                  dispatch(updateStageStatus({ stage: stageType, status: 'active' }))

                  // 🔔 关键：开始轮询任务状态（如果 WebSocket 未连接）
                  if (!workflowWebSocket.isConnected()) {
                    console.log('⚠️  WebSocket 未连接，启动轮询模式')
                    pollTaskStatus(latestTask.task_id, stageType)
                  } else {
                    console.log('✅ WebSocket 已连接，等待实时通知')
                  }

                  setSnackbarMessage(`✅ 工作流已恢复，继续执行 ${stageNames[stageType]}（已运行${ageMinutes.toFixed(0)}分钟）`)
                  setSnackbarSeverity('success')
                  setSnackbarOpen(true)
                }
              } else {
                console.log('✅ 没有正在运行的任务')
                // 🔧 修复：如果没有正在运行的任务，确保停止运行状态
                setIsRunning(false)
                setCurrentTaskId(null)
                // 清理可能存在的轮询定时器
                if (taskPollingInterval) {
                  clearInterval(taskPollingInterval)
                  setTaskPollingInterval(null)
                }
              }
            }
          } catch (error) {
            console.warn('⚠️  检查运行中任务失败:', error)
          }

          // ⚡ 步骤2：性能优化: 使用批量接口一次性获取所有阶段内容
          const batchResponse = await fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
            headers: {
              'Authorization': `Bearer ${token}`,
            },
          })

          if (batchResponse.ok) {
            const batchData = await batchResponse.json()
            const stages = batchData.stages

            // 设置所有按钮内容
            if (stages.concept) {
              setConceptContent(stages.concept)
              console.log(`✅ 故事概念已加载，内容长度: ${stages.concept.length}`)
            }
            if (stages.world_setting) {
              setWorldContent(stages.world_setting)
              console.log(`✅ 世界观设定已加载，内容长度: ${stages.world_setting.length}`)
            }
            if (stages.characters) {
              setCharacterContent(stages.characters)
              console.log(`✅ 人物设定已加载，内容长度: ${stages.characters.length}`)
            }
            if (stages.plot_outline) {
              setStructureContent(stages.plot_outline)
              console.log(`✅ 情节大纲已加载，内容长度: ${stages.plot_outline.length}`)
            }
            if (stages.chapter_draft) {
              setContentDraftContent(stages.chapter_draft)
              console.log(`✅ 章节初稿已加载，内容长度: ${stages.chapter_draft.length}`)
            }
            if (stages.final_version) {
              setFinalVersionContent(stages.final_version)
              console.log(`✅ 最终版本已加载，内容长度: ${stages.final_version.length}`)
            }
            if (stages.review_report) {
              setReviewReportContent(stages.review_report)
              console.log(`✅ 评审报告已加载，内容长度: ${stages.review_report.length}`)
            }

            // 更新Redux store的output字段，用于输出预览显示
            if (stages.concept) {
              dispatch(updateStageOutput({ stage: 'concept', output: stages.concept }))
            }
            if (stages.plot_outline) {
              dispatch(updateStageOutput({ stage: 'structure', output: stages.plot_outline }))
            }
            if (stages.chapter_draft) {
              dispatch(updateStageOutput({ stage: 'content', output: stages.chapter_draft }))
            }
            if (stages.review_report) {
              dispatch(updateStageOutput({ stage: 'review', output: stages.review_report }))
            }
            if (stages.final_version) {
              dispatch(updateStageOutput({ stage: 'iteration', output: stages.final_version }))
            }

            console.log('⚡ 批量加载完成，性能大幅提升！')
          } else {
            console.warn('⚠️  批量接口不可用，使用传统方式加载')
            // 备用方案: 使用原有的分别请求方式
            // 这里可以保留原有代码逻辑
          }

          // 加载阶段状态
          try {
            const statusResponse = await fetch(`/api/v1/workflow/${projectId}/stage-status`, {
              headers: {
                'Authorization': `Bearer ${token}`,
              },
            })

            if (statusResponse.ok) {
              const statusData = await statusResponse.json()
              console.log('📊 阶段状态数据:', statusData)

              // 更新Redux store中的阶段状态
              const stageStatusMap: Record<string, StageType> = {
                'stage_one_status': 'concept',
                'stage_two_status': 'structure',
                'stage_three_status': 'content',
                'stage_four_status': 'review',
                'stage_five_status': 'iteration'
              }

              // 🔧 修复：根据后端状态确定当前应该显示的阶段
              let lastCompletedStage: StageType | null = null
              const stageOrder: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']

              Object.entries(stageStatusMap).forEach(([dbField, stageName]) => {
                const status = statusData[dbField]
                if (status === 'completed') {
                  // 🔧 关键修复：如果该阶段正在运行，不要覆盖为 completed
                  if (hasRestoredRunningTask && stageName === restoredStage) {
                    console.log(`⚠️ 跳过更新阶段状态: ${stageName} (当前正在运行)`)
                    // 保持 active 状态，不更新为 completed
                  } else {
                    dispatch(updateStageStatus({ stage: stageName, status: 'completed' }))
                    console.log(`✅ 阶段状态已更新: ${stageName} = completed`)
                    lastCompletedStage = stageName
                  }
                }
              })

              // 🔧 关键修复：使用局部变量判断，避免 React 状态异步更新问题
              // 如果已经恢复了运行中的任务，就不要再设置当前阶段了
              if (hasRestoredRunningTask) {
                console.log(`🔒 跳过设置当前阶段，因为已恢复运行中的任务: ${restoredStage}`)
              } else {
                // 🆕 从 Redux 读取"生成下一章"任务状态（关键：避免闭包中的旧值）
                const reduxState = store.getState()
                const generateNextChapterTaskId = reduxState.workflow.generateNextChapter.taskId
                const isGeneratingNextChapter = reduxState.workflow.generateNextChapter.isRunning

                // 🆕 如果正在执行"生成下一章"任务，设置为 structure 阶段（章节规划从这里开始）
                if (generateNextChapterTaskId || isGeneratingNextChapter) {
                  dispatch(setCurrentStage('structure'))
                  console.log(`🔒 检测到"生成下一章"任务 (taskId=${generateNextChapterTaskId})，设置当前阶段为: structure`)
                } else if (lastCompletedStage) {
                  // 普通模式：根据完成状态设置当前阶段
                  const lastCompletedIndex = stageOrder.indexOf(lastCompletedStage)
                  if (lastCompletedIndex < stageOrder.length - 1) {
                    // 还有未完成的阶段,显示下一个阶段
                    const nextStage = stageOrder[lastCompletedIndex + 1]
                    dispatch(setCurrentStage(nextStage))
                    console.log(`📍 设置当前阶段为: ${nextStage} (最后完成阶段 ${lastCompletedStage} 的下一个)`)
                  } else {
                    // 所有阶段都完成了,显示最后一个阶段
                    dispatch(setCurrentStage(lastCompletedStage))
                    console.log(`📍 所有阶段已完成,显示最后阶段: ${lastCompletedStage}`)
                  }
                } else {
                  // 没有完成的阶段,显示第一个阶段
                  dispatch(setCurrentStage('concept'))
                  console.log(`📍 没有完成的阶段,显示第一个阶段: concept`)
                }
              }
            } else {
              console.warn('⚠️  无法加载阶段状态')
            }
          } catch (error) {
            console.warn('⚠️  加载阶段状态失败:', error)
          }

          console.log('✅ 所有阶段内容和状态加载完成')
        } catch (error) {
          console.error('❌ 加载阶段内容失败:', error)
          // 不显示错误提示，避免干扰用户体验
        }
      }

      loadAllStageContents()
    }, 100)  // 🔧 延迟100ms，等待localStorage初始化

    // 🔧 清理定时器
    return () => clearTimeout(timer)
  }, [projectId, dispatch])

  // 🆕 自动执行阶段的逻辑（异步模式）
  useEffect(() => {
    if (!isRunning || !projectId) return

    // 如果当前有异步任务正在执行，跳过
    if (currentTaskId) {
      console.log('⏳ 当前有异步任务正在执行，跳过自动执行')
      return
    }

    // 检查当前阶段是否已完成
    const currentStageData = workflow.stages[workflow.currentStage]

    if (currentStageData.status === 'pending') {
      console.log(`🚀 自动执行阶段（异步模式）: ${workflow.currentStage}`)
      executeStageAsync(workflow.currentStage)
    } else if (currentStageData.status === 'completed') {
      // 当前阶段已完成 - 检查是否需要执行下一阶段
      const currentIndex = stages.indexOf(workflow.currentStage)
      if (currentIndex < stages.length - 1) {
        // 移动到下一阶段
        const nextStage = stages[currentIndex + 1]
        console.log(`✅ 阶段 ${workflow.currentStage} 已完成，移动到下一阶段: ${nextStage}`)
        dispatch(setCurrentStage(nextStage))
        // 注意：不在这里执行，等待下次useEffect触发时执行
      } else {
        // 所有阶段都已完成
        console.log('🎉 所有阶段已完成！')
        setIsRunning(false)

        // 🔧 关键修复：只有在“非生成下一章”流程才自动保存
        if (isGenerateNextChapterFlow) {
          console.log('💾 跳过自动保存（生成下一章已经保存）')
          // 重置标记
          setIsGenerateNextChapterFlow(false)
          // 直接跳转
          console.log('📍 1.5秒后跳转到Dashboard...')
          setTimeout(() => {
            navigate(`/dashboard?projectId=${projectId}`)
          }, 1500)
        } else {
          // 普通工作流，需要自动保存
          console.log('💾 开始自动保存章节...')
          autoSaveChapter()
        }
      }
    }
  }, [isRunning, workflow.currentStage, workflow.stages, currentTaskId, projectId, dispatch])

  // 🆕 清理轮询定时器
  useEffect(() => {
    return () => {
      if (taskPollingInterval) {
        clearInterval(taskPollingInterval)
      }
    }
  }, [taskPollingInterval])

  // 🆕 自动保存记忆功能
  useEffect(() => {
    if (!autoSaveEnabled || !projectId) return

    // 每5分钟自动保存一次
    const interval = setInterval(() => {
      saveMemorySnapshot('auto')
    }, 5 * 60 * 1000) // 5分钟

    return () => {
      clearInterval(interval)
    }
  }, [autoSaveEnabled, projectId])

  // 🆕 页面卸载前保存记忆（使用 sendBeacon 确保请求完成）
  useEffect(() => {
    const handleBeforeUnload = () => {
      if (autoSaveEnabled && projectId && conversationHistory.length > 0) {
        // 使用 navigator.sendBeacon 确保页面卸载时请求能完成
        const memoryData = {
          messages: conversationHistory,
          current_chapter: workflow.stages.iteration.output ? 1 : null,
          current_scene: workflow.currentStage,
          active_characters: [],
          writing_goal: requirement || '创作小说',
        }

        const blob = new Blob([JSON.stringify(memoryData)], { type: 'application/json' })
        const token = localStorage.getItem('access_token')

        // sendBeacon 不支持自定义 headers，需要通过 URL 参数传递 token
        // 或者使用特殊的 endpoint 来处理
        const url = `/api/v1/projects/${projectId}/memories/auto-save?token=${token}`
        navigator.sendBeacon(url, blob)
        console.log('💾 [beforeunload] 使用 sendBeacon 保存记忆')
      }
    }

    window.addEventListener('beforeunload', handleBeforeUnload)

    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
    }
  }, [autoSaveEnabled, projectId, conversationHistory, workflow, requirement])

  // 🆕 保存记忆快照函数
  const saveMemorySnapshot = async (trigger: 'auto' | 'stage' | 'beforeUnload' | 'manual') => {
    if (!projectId) return

    // ⚠️  暂时禁用：后端尚未实现记忆保存API
    // console.log(`💾 [记忆快照] 功能已禁用，等待后端API实现`)
    // return

    try {
      console.log(`💾 保存记忆快照 [${trigger}]...`)

      // 收集当前工作流状态数据
      const memoryData = {
        messages: conversationHistory,
        current_chapter: workflow.stages.iteration.output ? 1 : null,
        current_scene: workflow.currentStage,
        active_characters: [],
        writing_goal: requirement || '创作小说',
      }

      const response = await fetch(`/api/v1/projects/${projectId}/memories/auto-save`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(memoryData),
      })

      if (response.ok) {
        const savedMemory = await response.json()
        setLastSaveTime(new Date(savedMemory.updated_at))
        console.log(`✅ 记忆快照已保存 [${trigger}]:`, savedMemory.id)

        // 仅在手动保存时显示提示
        if (trigger === 'manual') {
          setSnackbarMessage('✅ 记忆快照已保存')
          setSnackbarSeverity('success')
          setSnackbarOpen(true)
        }
      } else {
        console.error('❌ 保存记忆快照失败')
      }
    } catch (error) {
      console.error('❌ 保存记忆快照异常:', error)
    }
  }

  // 🆕 异步执行阶段函数
  const executeStageAsync = async (stage: StageType) => {
    if (!projectId) return

    try {
      console.log(`🚀 开始异步执行阶段: ${stage}`)

      // 🔧 立即更新阶段状态为 'active'，显示执行中的UI
      dispatch(updateStageStatus({ stage, status: 'active' }))

      // 🆕 收集用户输入到对话历史
      const stageNames: Record<string, string> = {
        concept: '概念开发',
        structure: '结构设计',
        content: '内容创作',
        review: '质量评审',
        iteration: '迭代优化'
      }
      setConversationHistory(prev => [
        ...prev,
        {
          role: 'user',
          content: `执行${stageNames[stage] || stage}阶段: ${requirement || '创作小说'}`,
          stage: stage,
          timestamp: new Date().toISOString()
        }
      ])

      // 🆕 阶段开始前保存记忆（确保意外关闭时写作目标不丢失）
      saveMemorySnapshot('stage')

      // 🆕 检查是否是支持流式输出的阶段
      const streamingStages = ['content', 'review', 'iteration']
      const enableStreaming = streamingStages.includes(stage)

      // 🆕 流式输出阶段：清空之前的内容，准备接收流式数据
      if (enableStreaming) {
        console.log(`🌊 阶段 ${stage} 支持流式输出，清空之前的内容`)
        if (stage === 'content') {
          setContentDraftContent('')
        } else if (stage === 'review') {
          setReviewReportContent('')
        } else if (stage === 'iteration') {
          setFinalVersionContent('')
        }
      }

      const response = await fetch('/api/v1/workflow/execute-stage-async', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          project_id: parseInt(projectId),
          stage: stage,
          requirement: requirement || `创作一部小说`,
          enable_streaming: enableStreaming,  // 🆕 启用流式输出
        }),
      })

      if (!response.ok) {
        throw new Error(`提交任务失败: ${response.status}`)
      }

      const data = await response.json()
      const taskId = data.task_id

      if (!taskId) {
        throw new Error('未返回task_id')
      }

      console.log(`✅ 任务已提交: ${taskId}`)
      setCurrentTaskId(taskId)
      setTaskProgress(0)

      // 🆕 启动进度估算器
      if (progressEstimator) {
        progressEstimator.startStage(stage, (state: ProgressState) => {
          setEstimatedRemainingTime(Math.round(state.remainingTime))
          setEstimatedRemainingTimeMin(Math.round(state.remainingTimeMin))  // 🆕
          setEstimatedRemainingTimeMax(Math.round(state.remainingTimeMax))  // 🆕
          setTaskProgress(Math.round(state.displayProgress))
        })
        console.log(`📊 进度估算器已启动: ${stage}`)
      }

      // 🆕 检查 WebSocket 是否连接
      if (workflowWebSocket.isConnected()) {
        console.log('💡 WebSocket 已连接，使用实时通知模式（不启动轮询）')
        console.log('   等待 task_complete 或 task_error 事件...')
        // 依赖 WebSocket 事件监听器，不启动轮询
      } else {
        console.log('⚠️  WebSocket 未连接，降级到 HTTP 轮询模式')
        // WebSocket 不可用时启动轮询
        pollTaskStatus(taskId, stage)
      }
    } catch (error) {
      console.error(`❌ 异步执行阶段失败:`, error)
      // 🔧 失败时重置状态
      dispatch(updateStageStatus({ stage, status: 'error' }))
      setSnackbarMessage(`执行${stageNames[stage]}失败，请重试`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }



  // 🆕 轮询任务状态函数
  const pollTaskStatus = (taskId: string, stage: StageType) => {
    let pollCount = 0
    const maxPolls = 180
    let consecutiveErrors = 0  // 🔧 记录连续错误次数
    const maxConsecutiveErrors = 5  // 连续5次404后停止轮询

    const interval = setInterval(async () => {
      try {
        pollCount++
        console.log(`🔄 轮询任务状态 [${pollCount}/${maxPolls}]: ${taskId}`)

        const response = await fetch(`/api/v1/workflow/task/${taskId}`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })

        if (!response.ok) {
          // 🔧 处理404错误
          if (response.status === 404) {
            consecutiveErrors++
            console.warn(`⚠️  任务不存在 (${consecutiveErrors}/${maxConsecutiveErrors}): ${taskId}`)

            if (consecutiveErrors >= maxConsecutiveErrors) {
              clearInterval(interval)
              setTaskPollingInterval(null)
              setTaskProgress(0)
              setCurrentTaskId(null)

              dispatch(updateStageStatus({ stage, status: 'error' }))

              setSnackbarMessage(`❌ 任务查询失败：后端未找到任务，请检查后端服务是否正常`)
              setSnackbarSeverity('error')
              setSnackbarOpen(true)

              console.error(`❌ 连续${maxConsecutiveErrors}次404错误，停止轮询`)
              return
            }
            // 继续轮询，等待后端任务初始化
            return
          }

          throw new Error(`查询任务状态失败: ${response.status}`)
        }

        // 🔧 成功响应，重置错误计数
        consecutiveErrors = 0

        const data = await response.json()
        console.log(`📊 任务状态:`, data)

        const progress = Math.min(95, pollCount * 3)
        setTaskProgress(progress)

        if (data.status === 'completed') {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(100)
          setCurrentTaskId(null)

          console.log(`✅ 任务完成:`, data.result)

          dispatch(updateStageStatus({ stage, status: 'completed' }))
          dispatch(updateStageOutput({ stage, output: data.result || '' }))

          // 🔥 关键修复：同步更新组件本地状态（轮询模式）
          const resultContent = data.result || ''
          if (stage === 'iteration' && resultContent) {
            setFinalVersionContent(resultContent)
            console.log(`🔄 [轮询] 迭代优化阶段完成，已同步 finalVersionContent，长度: ${resultContent.length}`)
          } else if (stage === 'review' && resultContent) {
            setReviewReportContent(resultContent)
            console.log(`🔄 [轮询] 质量评审阶段完成，已同步 reviewReportContent，长度: ${resultContent.length}`)
          } else if (stage === 'content' && resultContent) {
            setContentDraftContent(resultContent)
            console.log(`🔄 [轮询] 内容创作阶段完成，已同步 contentDraftContent，长度: ${resultContent.length}`)
          }

          setSnackbarMessage(`✅ ${stageNames[stage]}完成！`)
          setSnackbarSeverity('success')
          setSnackbarOpen(true)

          // 🆕 阶段完成后自动保存记忆
          if (autoSaveEnabled) {
            saveMemorySnapshot('stage')
          }

          if (isRunning) {
            const currentIndex = stages.indexOf(stage)
            if (currentIndex < stages.length - 1) {
              const nextStage = stages[currentIndex + 1]
              dispatch(setCurrentStage(nextStage))
              // 继续下一阶段
              setTimeout(() => {
                executeStageAsync(nextStage)
              }, 1000)
            } else {
              setIsRunning(false)

              // 🔧 关键修复：只有在“非生成下一章”流程才自动保存
              if (isGenerateNextChapterFlow) {
                console.log('💾 跳过自动保存（生成下一章已经保存）')
                // 重置标记
                setIsGenerateNextChapterFlow(false)
                // 直接跳转
                console.log('📍 1.5秒后跳转到Dashboard...')
                setTimeout(() => {
                  navigate(`/dashboard?projectId=${projectId}`)
                }, 1500)
              } else {
                // 普通工作流，需要自动保存
                console.log('💾 开始自动保存章节...')
                autoSaveChapter()
              }
            }
          }
        } else if (data.status === 'failed') {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(0)
          setCurrentTaskId(null)

          console.error(`❌ 任务失败:`, data.error)

          dispatch(updateStageStatus({ stage, status: 'error' }))

          setSnackbarMessage(`❌ ${stageNames[stage]}失败: ${data.error || '未知错误'}`)
          setSnackbarSeverity('error')
          setSnackbarOpen(true)

          setIsRunning(false)
        } else if (pollCount >= maxPolls) {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(0)
          setCurrentTaskId(null)

          console.error(`❌ 轮询超时`)

          dispatch(updateStageStatus({ stage, status: 'error' }))

          setSnackbarMessage(`❌ ${stageNames[stage]}超时，请重试`)
          setSnackbarSeverity('error')
          setSnackbarOpen(true)

          setIsRunning(false)
        }
      } catch (error) {
        console.error(`❌ 轮询任务状态失败:`, error)
        // 🔧 其他错误也计入连续错误
        consecutiveErrors++

        if (consecutiveErrors >= maxConsecutiveErrors) {
          clearInterval(interval)
          setTaskPollingInterval(null)
          setTaskProgress(0)
          setCurrentTaskId(null)

          dispatch(updateStageStatus({ stage, status: 'error' }))

          setSnackbarMessage(`❌ 轮询失败: ${error}`)
          setSnackbarSeverity('error')
          setSnackbarOpen(true)
        }
      }
    }, 2000)

    setTaskPollingInterval(interval)
  }

  // 🆕 渐进式扩展大纲函数（步长根据目标和差值动态调整，通常每次扩展3-15章）
  const handleExpandOutline = async () => {
    if (!projectId) return

    try {
      setExpandingOutline(true)
      setExpansionProgress(0)
      setExpansionStartTime(Date.now())
      setEstimatedTimeRemaining(null)

      // 🔥 关键修复：先打开对话框，再开始扩展
      setShowExpandOutlineDialog(true)
      setExpandedOutlineData(null)  // 清空旧数据

      console.log('📖 开始渐进式扩展大纲...')

      // 从当前阶段获取数据
      let currentOutline = structureContent || workflow.stages.structure.output || ''
      const worldSetting = worldContent || workflow.stages.concept.output?.world_setting || ''
      const characters = characterContent || workflow.stages.concept.output?.characters || ''

      if (!currentOutline) {
        setSnackbarMessage('⚠️ 请先完成结构设计阶段，生成情节大纲')
        setSnackbarSeverity('warning')
        setSnackbarOpen(true)
        setExpandingOutline(false)
        setShowExpandOutlineDialog(false)
        return
      }

      // 🆕 循环调用API，直到AI建议停止
      let chapterCount = currentChapterCount
      let shouldContinue = true
      let totalIterations = 0
      const maxIterations = 10  // 防止无限循环

      // 🆕 根据用户配置或默认值确定目标章节数（默认按长篇小说 100 章处理）
      const targetChapters = targetChapterCount && targetChapterCount > 0 ? targetChapterCount : 100

      while (shouldContinue && totalIterations < maxIterations && chapterCount < targetChapters) {
        totalIterations++
        const remaining = targetChapters - chapterCount
        if (remaining <= 0) {
          break
        }
        // 🆕 基于目标章节数和当前差值的动态扩展步长：自动在小步稳健和大步提速之间折中
        let increment: number
        const gapRatio = remaining / targetChapters

        if (remaining <= 3) {
          // 差值很小，直接补齐
          increment = remaining
        } else if (targetChapters <= 40) {
          // 短篇/中篇：更细腻的小步扩展
          increment = Math.min(5, remaining)
        } else {
          // 长篇：根据与目标的差值动态调整步长
          if (gapRatio > 0.6) {
            // 离目标还很远，步长稍大一些，但不要一次跳太多
            increment = Math.min(15, Math.max(5, Math.round(remaining * 0.4)))
          } else if (gapRatio > 0.3) {
            increment = Math.min(10, Math.max(4, Math.round(remaining * 0.3)))
          } else {
            // 接近目标时，收窄步长，避免大幅度震荡
            increment = Math.min(8, Math.max(3, Math.round(remaining * 0.2)))
          }
        }

        // 最后再做一次安全收敛，保证不超出剩余章节
        increment = Math.max(1, Math.min(increment, remaining))

        // 🔥 更新进度
        const progress = calculateProgress(totalIterations, maxIterations)
        setExpansionProgress(progress)

        // 🔥 估算剩余时间
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
            world_setting: worldSetting,
            characters: characters,
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

        // 更新状态
        currentOutline = data.expanded_outline
        chapterCount = data.current_chapter_count
        shouldContinue = data.should_continue

        // 显示进度
        setSnackbarMessage(`📝 已扩展到 ${chapterCount} 章${shouldContinue ? '，继续扩展...' : '，AI建议停止'}`)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 如果AI建议停止，显示原因
        if (!shouldContinue) {
          console.log(`🛑 AI庻议停止扩展：${data.continue_reason}`)
          setExpandedOutlineData({
            ...data,
            stop_reason: data.continue_reason
          })
          break
        }

        setExpandedOutlineData(data)
      }

      // 保存最终结果
      console.log('💾 开始保存扩展结果...')

      setStructureContent(currentOutline)
      setCurrentChapterCount(chapterCount)

      // 🔥 保存到历史记录
      const historyRecord = {
        timestamp: Date.now(),
        content: currentOutline,
        chapterCount: chapterCount
      }
      saveHistory('outline', currentOutline, chapterCount)
      setOutlineHistory(prev => [...prev, historyRecord])

      console.log('✅ 状态已更新，当前阶段:', workflow.currentStage)
      setExpansionProgress(100)

      setSnackbarMessage(`✅ 大纲扩展完成！共 ${chapterCount} 章（${totalIterations}次扩展）`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      console.error('❌ 扩展大纲失败:', error)
      setSnackbarMessage(`扩展大纲失败: ${error}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExpandingOutline(false)
      setExpansionProgress(0)
      setEstimatedTimeRemaining(null)
    }
  }

  // 🆕 渐进式扩展人物函数（步长根据目标和差值动态调整，通常每次扩展2-7人）
  const handleExpandCharacters = async () => {
    if (!projectId) return

    try {
      setExpandingCharacters(true)
      console.log('👥 开始渐进式扩展人物...')

      // 从当前阶段获取数据
      let mainCharacters = characterContent || workflow.stages.concept.output?.characters || ''
      const worldSetting = worldContent || workflow.stages.concept.output?.world_setting || ''
      const plotOutline = structureContent || workflow.stages.structure.output || ''

      if (!mainCharacters) {
        setSnackbarMessage('⚠️ 请先完成概念开发阶段，生成人物设定')
        setSnackbarSeverity('warning')
        setSnackbarOpen(true)
        return
      }

      if (!plotOutline) {
        setSnackbarMessage('⚠️ 建议先扩展大纲，再扩展人物')
        setSnackbarSeverity('warning')
        setSnackbarOpen(true)
        return
      }

      // 🆕 循环调用API，直到AI建议停止
      let characterCount = currentCharacterCount
      let shouldContinue = true
      let totalIterations = 0
      const maxIterations = 8  // 防止无限循环

      // 🆕 根据用户配置或默认值确定目标人物数（默认按长篇小说 25 人处理）
      const targetCharacters = targetCharacterCount && targetCharacterCount > 0 ? targetCharacterCount : 25

      while (shouldContinue && totalIterations < maxIterations && characterCount < targetCharacters) {
        totalIterations++
        const remaining = targetCharacters - characterCount
        if (remaining <= 0) {
          break
        }
        // 🆕 基于目标人物数和当前差值的动态扩展步长：在小步精修和中步提速之间折中
        let increment: number
        const gapRatio = remaining / targetCharacters

        if (remaining <= 2) {
          // 差值很小，直接补齐
          increment = remaining
        } else if (targetCharacters <= 12) {
          // 人物总目标较小：保持更细腻的小步扩展
          increment = Math.min(3, remaining)
        } else {
          // 长篇人物体系：根据差值动态调整步长
          if (gapRatio > 0.6) {
            // 离目标还比较远，适当放大步长
            increment = Math.min(7, Math.max(3, Math.round(remaining * 0.5)))
          } else if (gapRatio > 0.3) {
            increment = Math.min(5, Math.max(3, Math.round(remaining * 0.4)))
          } else {
            // 接近目标时收窄步长，避免一次性加太多人
            increment = Math.min(4, Math.max(2, Math.round(remaining * 0.3)))
          }
        }

        // 最后安全收敛，确保不超过剩余人数
        increment = Math.max(1, Math.min(increment, remaining))

        console.log(`🔄 第${totalIterations}次扩展：从 ${characterCount} 个扩展 ${increment} 个（目标：${targetCharacters} 个）...`)

        const response = await fetch('/api/v1/workflow/expand-characters', {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            project_id: parseInt(projectId),
            main_characters: mainCharacters,
            world_setting: worldSetting,
            plot_outline: plotOutline,
            current_character_count: characterCount,
            increment: increment,
            target_total_characters: targetCharacters,
          }),
        })

        if (!response.ok) {
          throw new Error(`扩展人物失败: ${response.status}`)
        }

        const data = await response.json()
        console.log(`✅ 第${totalIterations}次扩展完成，当前人物数: ${data.current_character_count}`)
        console.log('🔍 人物扩展响应数据:', {
          current_character_count: data.current_character_count,
          character_relationships_length: data.character_relationships?.length || 0,
          role_distribution: data.role_distribution,
          all_characters_length: typeof data.all_characters === 'string' ? data.all_characters.length : data.all_characters?.length || 0
        })

        // 更新状态
        mainCharacters = data.all_characters
        characterCount = data.current_character_count
        shouldContinue = data.should_continue

        // 显示进度
        setSnackbarMessage(`👥 已扩展到 ${characterCount} 个人物${shouldContinue ? '，继续扩展...' : '，AI建议停止'}`)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 如果AI建议停止，显示原因
        if (!shouldContinue) {
          console.log(`🛑 AI建议停止扩展：${data.continue_reason}`)
          setExpandedCharactersData({
            ...data,
            stop_reason: data.continue_reason
          })
          break
        }

        setExpandedCharactersData(data)
      }

      // 保存最终结果
      const charactersText = Array.isArray(mainCharacters)
        ? JSON.stringify(mainCharacters, null, 2)
        : mainCharacters

      setCharacterContent(charactersText)
      setCurrentCharacterCount(characterCount)

      // 打开结果对话框
      setShowExpandCharactersDialog(true)

      setSnackbarMessage(`✅ 人物扩展完成！共 ${characterCount} 个（${totalIterations}次扩展）`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
    } catch (error) {
      console.error('❌ 扩展人物失败:', error)
      setSnackbarMessage(`扩展人物失败: ${error}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setExpandingCharacters(false)
    }
  }

  // 🆕 检查项目是否已有内容
  const checkExistingContent = async () => {
    if (!projectId) return false

    try {
      // 获取项目的章节列表
      const response = await apiClient.getChapters(parseInt(projectId))
      const chapters = response.data || []
      const chapterCount = chapters.length

      // 检查是否有概念/大纲等内容（通过workflow状态判断）
      const hasCompletedStages =
        workflow.stages.concept.status === 'completed' ||
        workflow.stages.structure.status === 'completed' ||
        workflow.stages.content.status === 'completed'

      if (chapterCount > 0 || hasCompletedStages) {
        setExistingChaptersCount(chapterCount)
        return true
      }
      return false
    } catch (error) {
      console.error('检查项目内容失败:', error)
      return false
    }
  }

  // 🆕 点击"开始创作"按钮时的处理
  const handleStartButtonClick = async () => {
    const hasContent = await checkExistingContent()
    if (hasContent) {
      // 显示警告对话框
      setShowContentWarningDialog(true)
    } else {
      // 直接打开创作对话框
      setOpenDialog(true)
    }
  }

  // 🆕 标记是否是重新开始（需要清空旧数据）
  const [isRestartMode, setIsRestartMode] = useState(false)

  // 🆕 确认重新开始（覆盖现有内容）
  const handleConfirmRestart = () => {
    setShowContentWarningDialog(false)
    setIsRestartMode(true)  // 🆕 标记为重新开始模式
    setOpenDialog(true)
  }

  // 🆕 选择继续创作下一章
  const handleContinueNextChapter = () => {
    setShowContentWarningDialog(false)
    handleGenerateNextChapter()
  }

  const handleStartWorkflow = async () => {
    if (!projectId || !requirement.trim()) {
      // 使用 Snackbar 显示错误提示（取代 alert）
      setSnackbarMessage('请输入创作需求')
      setSnackbarSeverity('info')
      setSnackbarOpen(true)
      return
    }

    try {
      setIsStarting(true)  // 开始启动，显示加载状态
      await dispatch(
        startWorkflow({
          projectId: parseInt(projectId),
          requirement,
          targetChapterCount,
          clearExisting: isRestartMode,  // 🆕 传递清空标志
        })
      ).unwrap()
      setOpenDialog(false)
      setIsRunning(true)
      setIsStarting(false)  // 启动完成，隐藏加载状态
      setIsRestartMode(false)  // 🆕 重置重新开始标志

      // 🆕 如果是重新开始模式，刷新章节列表
      if (isRestartMode) {
        dispatch(fetchChapters(parseInt(projectId)))
        setSnackbarMessage('已清空旧内容，开始全新创作')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to start workflow:', error)
      setIsStarting(false)  // 启动失败，隐藏加载状态
      setIsRestartMode(false)  // 🆕 重置重新开始标志
      setSnackbarMessage('启动工作流失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  // 🔥 导出大纲为Markdown
  const handleExportOutlineMarkdown = () => {
    if (!expandedOutlineData) return

    const markdown = exportToMarkdown(
      expandedOutlineData.expanded_outline,
      `${currentProject?.title || '小说'} - 大纲扩展`,
      {
        '章节数': currentChapterCount,
        '扩展时间': new Date().toLocaleString(),
        '项目ID': projectId
      }
    )
    downloadFile(markdown, `大纲扩展_${currentChapterCount}章_${Date.now()}.md`, 'text/markdown')

    setSnackbarMessage('✅ 已导出为 Markdown')
    setSnackbarSeverity('success')
    setSnackbarOpen(true)
  }

  // 🔥 导出章节分解为CSV
  const handleExportChapterCSV = () => {
    if (!expandedOutlineData?.chapter_breakdown) return

    const chapterBreakdown = typeof expandedOutlineData.chapter_breakdown === 'string'
      ? expandedOutlineData.chapter_breakdown
      : JSON.stringify(expandedOutlineData.chapter_breakdown)

    const csv = exportChapterBreakdownToCSV(chapterBreakdown)
    downloadFile(csv, `章节分解_${currentChapterCount}章_${Date.now()}.csv`, 'text/csv')

    setSnackbarMessage('✅ 已导出为 Excel/CSV')
    setSnackbarSeverity('success')
    setSnackbarOpen(true)
  }

  // 🔥 开始编辑大纲
  const handleStartEditOutline = () => {
    setIsEditingExpansion(true)
    setEditedExpansionContent(expandedOutlineData?.expanded_outline || '')
    setHistoryType('outline')
  }

  // 🔥 保存编辑的大纲
  const handleSaveEditedOutline = () => {
    setStructureContent(editedExpansionContent)
    setIsEditingExpansion(false)

    // 更新当前对话框数据
    setExpandedOutlineData({
      ...expandedOutlineData,
      expanded_outline: editedExpansionContent
    })

    // 保存到历史
    const historyRecord = {
      timestamp: Date.now(),
      content: editedExpansionContent,
      chapterCount: currentChapterCount
    }
    saveHistory('outline', editedExpansionContent, currentChapterCount)
    setOutlineHistory(prev => [...prev, historyRecord])

    setSnackbarMessage('✅ 编辑已保存')
    setSnackbarSeverity('success')
    setSnackbarOpen(true)
  }

  // 🔥 查看历史记录
  const handleShowHistory = (type: 'outline' | 'character') => {
    setHistoryType(type)
    setShowHistoryDialog(true)
  }

  const handleRegenerateStage = async () => {
    if (!projectId) return

    try {
      await dispatch(
        regenerateStage({
          projectId: parseInt(projectId),
          stage: workflow.currentStage,
        })
      ).unwrap()
    } catch (error) {
      console.error('Failed to regenerate stage:', error)
    }
  }

  const handleNextStage = () => {
    const currentIndex = stages.indexOf(workflow.currentStage)
    if (currentIndex < stages.length - 1) {
      dispatch(setCurrentStage(stages[currentIndex + 1]))
    }
  }

  const handlePreviousStage = () => {
    const currentIndex = stages.indexOf(workflow.currentStage)
    if (currentIndex > 0) {
      dispatch(setCurrentStage(stages[currentIndex - 1]))
    }
  }

  const handleSaveAsChapter = async () => {
    if (!projectId) {
      console.error('❌ 项目ID不存在')
      setSnackbarMessage('项目ID不存在')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      return
    }

    // ✅ 设置保存状态
    setSavingChapter(true)

    try {
      console.log('📍 开始保存章节，projectId:', projectId)

      // 🔥 关键修复：从后端API获取最新的迭代阶段内容 - 使用apiClient
      console.log('📍 步骤1: 从后端获取最新的迭代阶段内容...')
      const getContentResponse = await apiClient.get(`/api/v1/workflow/${projectId}/stage/iteration/content`)

      const contentData = getContentResponse.data
      const content = contentData.content || ''

      if (!content || content.trim() === '') {
        console.error('❌ 章节内容为空')
        setSnackbarMessage('没有可保存的章节内容')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        setSavingChapter(false)  // ✅ 重置保存状态
        return
      }

      console.log('✅ 成功获取迭代阶段内容，长度:', content.length)


      // 如果用户没有输入标题，后端会自动生成
      const titleToSave = chapterTitle.trim() || ''
      console.log('📍 章节标题:', titleToSave || '(自动生成)')

      // 🔥 修复：直接创建章节记录 - 使用apiClient，URL末尾添加斜杠避免307重定向
      console.log('📍 步骤2: 创建章节记录...')
      const response = await apiClient.post('/api/v1/chapters/', {
        project_id: parseInt(projectId),
        content: content,
        title: titleToSave || undefined, // 如果为空则自动生成
      })

      // axios成功响应（2xx状态码）
      const data = response.data
      console.log('✅ 章节创建成功:', data)

      setSnackbarMessage(`✅ 章节已保存：${data.title} (${data.word_count} 字)`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // 关闭对话框，清空标题
      setShowSaveDialog(false)
      setChapterTitle('')

      // 🔧 修复：1.5秒后跳转到Dashboard页面，并自动展开章节列表
      console.log('📍 1.5秒后跳转到Dashboard并自动展开章节列表...')
      setTimeout(() => {
        console.log('📍 跳转到: /dashboard?projectId=' + projectId)
        navigate(`/dashboard?projectId=${projectId}`)  // 带projectId参数，自动展开章节列表
      }, 1500)
    } catch (error: any) {
      console.error('❌ 保存章节异常:', error)

      let errorMessage = '保存章节失败，请重试'

      if (error.response) {
        // 服务器返回错误响应
        errorMessage = error.response.data?.error || error.response.data?.detail || errorMessage
        console.error('❌ 服务器错误:', error.response.status, error.response.data)
      } else if (error.request) {
        // 请求已发送但无响应
        errorMessage = '无法连接到服务器，请检查后端服务是否启动'
        console.error('❌ 网络错误: 无响应')
      } else {
        // 其他错误
        errorMessage = error.message || errorMessage
        console.error('❌ 请求配置错误:', error.message)
      }

      setSnackbarMessage(errorMessage)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      // ✅ 确保一定会重置保存状态
      setSavingChapter(false)
      console.log('🛡️ [保存状态] savingChapter 已设置为 false')
    }
  }

  // 🆕 自动保存章节（无需用户输入标题）
  const autoSaveChapter = async () => {
    if (!projectId) {
      console.error('❌ 项目ID不存在')
      return
    }

    try {
      console.log('💾 开始自动保存章节，projectId:', projectId)

      // 获取最新的迭代阶段内容
      const getContentResponse = await apiClient.get(`/api/v1/workflow/${projectId}/stage/iteration/content`)
      const contentData = getContentResponse.data
      const content = contentData.content || ''

      if (!content || content.trim() === '') {
        console.error('❌ 章节内容为空，跳过自动保存')
        setSnackbarMessage('⚠️ 没有可保存的章节内容')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      console.log('✅ 获取内容成功，长度:', content.length)

      // 创建章节记录（标题自动生成）
      const response = await apiClient.post('/api/v1/chapters/', {
        project_id: parseInt(projectId),
        content: content,
        // 不传title，让后端自动生成
      })

      const data = response.data
      console.log('✅ 自动保存成功:', data)

      // 显示成功提示
      setSnackbarMessage(`✅ 章节已自动保存：${data.title} (${data.word_count} 字)`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // 1.5秒后跳转到Dashboard
      console.log('📍 1.5秒后跳转到Dashboard...')
      setTimeout(() => {
        navigate(`/dashboard?projectId=${projectId}`)
      }, 1500)

    } catch (error: any) {
      console.error('❌ 自动保存章节失败:', error)

      let errorMessage = '自动保存失败'

      if (error.response) {
        errorMessage = error.response.data?.error || error.response.data?.detail || errorMessage
      } else if (error.request) {
        errorMessage = '无法连接到服务器'
      }

      setSnackbarMessage(`❌ ${errorMessage}`)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }



  // 打开故事概念对话框
  const handleOpenConceptDialog = async () => {
    setShowConceptDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (conceptContent && conceptContent.trim() !== '') {
      console.log('⚡ 使用缓存的故事概念内容，长度:', conceptContent.length)
      setEditedContent(conceptContent)
      return
    }

    // 如果没有缓存，才从API获取
    setConceptLoading(true)

    try {
      console.log('📍 从API获取最新的故事概念内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/concept/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 故事概念已加载，长度:', content.length)
        setConceptContent(content)
        setEditedContent(content)
      } else {
        console.error('❌ 获取故事概念失败，状态码:', response.status)
        setSnackbarMessage('获取故事概念失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取故事概念异常:', error)
      setSnackbarMessage('获取故事概念失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setConceptLoading(false)
    }
  }

  // 关闭故事概念对话框
  const handleCloseConceptDialog = () => {
    setShowConceptDialog(false)
    // 不清空 conceptContent，保持已保存的内容
    setEditedContent('')  // 只清空编辑状态
  }

  // 保存并继续

  // 仅保存
  const handleSaveOnly = async () => {
    if (!projectId) return

    setConceptSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/concept/content`, {
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
        // ✅ 更新state，保持已保存的内容
        setConceptContent(editedContent)

        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        // 关闭对话框
        handleCloseConceptDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save concept:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setConceptSaving(false)
    }
  }

  // 打开情节大纲对话框
  const handleOpenStructureDialog = async () => {
    setShowStructureDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (structureContent && structureContent.trim() !== '') {
      console.log('⚡ 使用缓存的情节大纲内容，长度:', structureContent.length)
      setEditedStructureContent(structureContent)
      return
    }

    // 如果没有缓存，才从API获取
    setStructureLoading(true)

    try {
      console.log('📍 从API获取最新的情节大纲内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/structure/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setStructureContent(data.content || '')
        setEditedStructureContent(data.content || '')
      } else {
        console.error('❌ 获取情节大纲失败，状态码:', response.status)
        setSnackbarMessage('获取情节大纲失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取情节大纲异常:', error)
      setSnackbarMessage('获取情节大纲失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setStructureLoading(false)
    }
  }

  // 关闭情节大纲对话框
  const handleCloseStructureDialog = () => {
    setShowStructureDialog(false)
    // 不清空 structureContent，保持已保存的内容
    setEditedStructureContent('')  // 只清空编辑状态
  }

  // 保存并继续（情节大纲）

  // 仅保存（情节大纲）
  const handleSaveOnlyStructure = async () => {
    if (!projectId) return

    setStructureSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/structure/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedStructureContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setStructureContent(editedStructureContent)

        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseStructureDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save structure:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setStructureSaving(false)
    }
  }

  // 打开章节初稿对话框
  const handleOpenContentDialog = async () => {
    setShowContentDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (contentDraftContent && contentDraftContent.trim() !== '') {
      console.log('⚡ 使用缓存的章节初稿内容，长度:', contentDraftContent.length)
      setEditedContentDraftContent(contentDraftContent)
      return
    }

    // 如果没有缓存，才从API获取
    setContentLoading(true)

    try {
      console.log('📍 从API获取最新的章节初稿内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/content/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 章节初稿已加载，长度:', content.length)
        setContentDraftContent(content)
        setEditedContentDraftContent(content)
      } else {
        console.error('❌ 获取章节初稿失败，状态码:', response.status)
        setSnackbarMessage('获取章节初稿失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取章节初稿异常:', error)
      setSnackbarMessage('获取章节初稿失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentLoading(false)
    }
  }

  // 关闭章节初稿对话框
  const handleCloseContentDialog = () => {
    setShowContentDialog(false)
    // 不清空 contentDraftContent，保持已保存的内容
    setEditedContentDraftContent('')  // 只清空编辑状态
  }

  // 打开评审报告对话框
  const handleOpenReviewDialog = async () => {
    setShowReviewDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (reviewReportContent && reviewReportContent.trim() !== '') {
      console.log('⚡ 使用缓存的评审报告内容，长度:', reviewReportContent.length)
      setEditedReviewReportContent(reviewReportContent)
      return
    }

    // 如果没有缓存，才从API获取
    setReviewLoading(true)

    try {
      console.log('📍 从API获取最新的评审报告内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/review/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 评审报告已加载，长度:', content.length)
        setReviewReportContent(content)
        setEditedReviewReportContent(content)
      } else {
        console.error('❌ 获取评审报告失败，状态码:', response.status)
        setSnackbarMessage('获取评审报告失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取评审报告异常:', error)
      setSnackbarMessage('获取评审报告失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setReviewLoading(false)
    }
  }

  // 关闭评审报告对话框
  const handleCloseReviewDialog = () => {
    setShowReviewDialog(false)
    setEditedReviewReportContent('')  // 清空编辑状态
  }

  // 仅保存评审报告
  const handleSaveOnlyReview = async () => {
    if (!projectId) return

    setReviewSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/review/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedReviewReportContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // 更新缓存
        setReviewReportContent(editedReviewReportContent)
        setSnackbarMessage('评审报告已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
      } else {
        const errorData = await response.json().catch(() => ({}))
        setSnackbarMessage(errorData.detail || '保存失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('保存评审报告失败:', error)
      setSnackbarMessage('保存失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setReviewSaving(false)
    }
  }

  // 保存并继续（评审报告）
  const handleSaveAndContinueReview = async () => {
    if (!projectId) return

    setReviewSaving(true)

    try {
      // 1. 保存内容并指示继续工作流
      console.log('📍 开始保存评审报告并继续工作流...')
      const saveResponse = await fetch(`/api/v1/workflow/${projectId}/stage/review/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedReviewReportContent,
          continue_workflow: true,
        }),
      })

      console.log('📍 保存响应状态:', saveResponse.status, saveResponse.ok)

      if (!saveResponse.ok) {
        const errorData = await saveResponse.json().catch(() => ({}))
        console.error('❌ 保存失败:', errorData)
        setSnackbarMessage(errorData.detail || '保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      const saveData = await saveResponse.json()
      console.log('✅ 保存成功，响应数据:', saveData)

      // ✅ 更新缓存
      setReviewReportContent(editedReviewReportContent)

      // ✅ 更新 Redux store
      dispatch(updateStageOutput({ stage: 'review', output: editedReviewReportContent }))
      dispatch(updateStageStatus({ stage: 'review', status: 'completed' }))

      // ✅ 重置后续阶段状态
      dispatch(resetFollowingStages('review'))

      // ✅ 显示删除章节的消息（如果有的话）
      if (saveData.deleted_chapters_count) {
        setSnackbarMessage(`已删除 ${saveData.deleted_chapters_count} 个章节，正在重新生成...`)
      } else {
        setSnackbarMessage('评审报告已保存，正在启动迭代优化...')
      }
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      handleCloseReviewDialog()

      // ✅ 关键修复：真正调用后端API执行下一阶段（迭代优化）
      setIsRunning(true)
      setTimeout(async () => {
        const nextStage: StageType = 'iteration'
        dispatch(setCurrentStage(nextStage))

        console.log('🚀 使用异步模式继续工作流，下一阶段: iteration')
        executeStageAsync(nextStage)
      }, 1000)
    } catch (error) {
      console.error('❌ 保存评审报告失败:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setReviewSaving(false)
    }
  }

  // 保存并继续（章节初稿）
  const handleSaveAndContinueContent = async () => {
    if (!projectId) return

    setContentSaving(true)

    try {
      // 1. 保存内容并指示继续工作流
      const saveResponse = await fetch(`/api/v1/workflow/${projectId}/stage/content/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContentDraftContent,
          continue_workflow: true,  // 关键：设置为true以触发章节更新逻辑
        }),
      })

      if (!saveResponse.ok) {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      const saveData = await saveResponse.json();

      // ✅ 更新state，保持已保存的内容
      setContentDraftContent(editedContentDraftContent)

      // ✅ 更新 Redux store
      dispatch(updateStageOutput({ stage: 'content', output: editedContentDraftContent }))
      dispatch(updateStageStatus({ stage: 'content', status: 'completed' }))

      // ✅ 关键修复：重置后续阶段状态
      dispatch(resetFollowingStages('content'))

      // ✅ 显示删除成功的消息（如果有的话）
      if (saveData.deleted_chapter) {
        setSnackbarMessage(`已更新第${saveData.deleted_chapter.chapter_number}章并启动后续工作流...`)
      } else {
        setSnackbarMessage('内容已保存，正在启动后续工作流...')
      }

      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      handleCloseContentDialog()

      // ✅ 关键修复：真正调用后端API执行下一阶段
      setIsRunning(true)
      setTimeout(async () => {
        const nextStage: StageType = 'review'
        dispatch(setCurrentStage(nextStage))

        console.log('🚀 使用异步模式继续工作流...')
        executeStageAsync(nextStage)
      }, 1000)
    } catch (error) {
      console.error('Failed to save content:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentSaving(false)
    }
  }


  // 仅保存（章节初稿）
  const handleSaveOnlyContent = async () => {
    if (!projectId) return

    setContentSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/content/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContentDraftContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setContentDraftContent(editedContentDraftContent)

        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseContentDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save content:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentSaving(false)
    }
  }

  // 打开世界观设定对话框
  const handleOpenWorldDialog = async () => {
    setShowWorldDialog(true)
    setWorldSettingsTab('text')

    if (projectId) {
      const projectIdNum = Number(projectId)
      if (!Number.isNaN(projectIdNum)) {
        // 每次打开时刷新类型化设定集合
        loadSettingCollections(projectIdNum)
      }
    }

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (worldContent && worldContent.trim() !== '') {
      console.log('⚡ 使用缓存的世界观设定内容，长度:', worldContent.length)
      setEditedWorldContent(worldContent)
      return
    }

    // 如果没有缓存，才从API获取
    setWorldLoading(true)

    try {
      console.log('📍 从API获取最新的世界观设定内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/world_builder/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 世界观设定已加载，长度:', content.length)
        setWorldContent(content)
        setEditedWorldContent(content)
      } else {
        console.error('❌ 获取世界观设定失败，状态码:', response.status)
        setSnackbarMessage('获取世界观设定失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取世界观设定异常:', error)
      setSnackbarMessage('获取世界观设定失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setWorldLoading(false)
    }
  }

  // 关闭世界观设定对话框
  const handleCloseWorldDialog = () => {
    setShowWorldDialog(false)
    setShowTemplateDialog(false)
    // 不清空 worldContent，保持已保存的内容
    setEditedWorldContent('')  // 只清空编辑状态
  }

  // 保存并继续（世界观设定）

  // 仅保存（世界观设定）
  const handleSaveOnlyWorld = async () => {
    if (!projectId) return

    setWorldSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/world_builder/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedWorldContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setWorldContent(editedWorldContent)

        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseWorldDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save world setting:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setWorldSaving(false)
    }
  }

  // 打开人物设定对话框
  const handleOpenCharacterDialog = async () => {
    setShowCharacterDialog(true)

    // 打开时默认回到文本模式，且异步加载结构化人物列表/境界列表
    setCharacterTab('text')
    loadStructuredCharacters()
    loadAvailableRealms()

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (characterContent && characterContent.trim() !== '') {
      console.log('⚡ 使用缓存的人物设定内容，长度:', characterContent.length)
      setEditedCharacterContent(characterContent)
      return
    }

    // 如果没有缓存，才从API获取
    setCharacterLoading(true)

    try {
      console.log('📍 从API获取最新的人物设定内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/character_designer/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 人物设定已加载，长度:', content.length)
        setCharacterContent(content)
        setEditedCharacterContent(content)
      } else {
        console.error('❌ 获取人物设定失败，状态码:', response.status)
        setSnackbarMessage('获取人物设定失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取人物设定异常:', error)
      setSnackbarMessage('获取人物设定失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterLoading(false)
    }
  }

  // 关闭人物设定对话框
  const handleCloseCharacterDialog = () => {
    setShowCharacterDialog(false)
    // 不清空 characterContent，保持已保存的内容
    setEditedCharacterContent('')  // 只清空编辑状态
  }
  // 🧬 结构化人物：打开角色编辑对话框（新建/编辑）
  const handleOpenCharacterEditDialog = async (character?: any) => {
    if (!projectId) {
      setSnackbarMessage('请先选择一个项目')
      setSnackbarSeverity('warning')
      setSnackbarOpen(true)
      return
    }

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    setCharacterFormLoading(true)
    setShowCharacterEditDialog(true)

    try {
      // 基础表单
      if (character) {
        setCharacterFormData({ ...character })
        // 加载该角色已掌握的功法
        const techRes = await apiClient.getCharacterTechniques(character.id)
        setCharacterTechniques(techRes.data || [])
      } else {
        setCharacterFormData({
          project_id: projectIdNum,
          name: '',
          role: '',
          gender: '',
          age: undefined,
          faction: '',
          importance_level: '',
          appearance_status: '',
          life_status: '',
          current_realm_item_id: undefined,
          first_appearance_chapter: undefined,
          summary: '',
          profile: '',
          tags: [],
          relations: {},
        })
        setCharacterTechniques([])
      }

      // 保证功法/境界/势力/职业/种族 下拉列表已加载
      await Promise.all([
        loadAvailableTechniques(),
        loadAvailableRealms(),
        loadAvailableForces(),
        loadAvailableProfessions(),
        loadAvailableRaces(),
      ])
    } catch (error) {
      console.error('打开角色编辑对话框失败:', error)
      setSnackbarMessage('加载角色信息失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterFormLoading(false)
    }
  }

  const handleCloseCharacterEditDialog = () => {
    if (characterFormSaving) return
    setShowCharacterEditDialog(false)
    setCharacterFormData({})
    setCharacterTechniques([])
    setSelectedTechniqueId('')
  }

  // 保存角色基础信息 + 功法列表
  const handleSaveCharacterForm = async () => {
    if (!projectId) return

    const projectIdNum = Number(projectId)
    if (Number.isNaN(projectIdNum)) return

    setCharacterFormSaving(true)
    try {
      let savedCharacter = characterFormData

      if (characterFormData.id) {
        // 更新角色
        const { id, project_id, created_at, updated_at, ...updatePayload } = characterFormData
        const res = await apiClient.updateCharacter(characterFormData.id, updatePayload)
        savedCharacter = res.data
      } else {
        // 新建角色
        const createPayload = {
          ...characterFormData,
          project_id: projectIdNum,
        }
        const res = await apiClient.createCharacter(projectIdNum, createPayload)
        savedCharacter = res.data
      }

      // 保存功法列表（覆盖式）
      if (savedCharacter.id != null) {
        const payload = {
          techniques: characterTechniques.map((t: any) => ({
            technique_item_id: t.technique_item_id,
            proficiency: t.proficiency || null,
            learned_at_chapter: t.learned_at_chapter ?? null,
            notes: t.notes || null,
          })),
        }
        await apiClient.updateCharacterTechniques(savedCharacter.id, payload)
      }

      setSnackbarMessage('角色已保存')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      setShowCharacterEditDialog(false)
      setCharacterFormData({})
      setCharacterTechniques([])
      setSelectedTechniqueId('')

      // 刷新列表
      await loadStructuredCharacters()
    } catch (error) {
      console.error('保存角色失败:', error)
      setSnackbarMessage('保存角色失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterFormSaving(false)
    }
  }

  // 删除角色
  const handleDeleteCharacter = async (characterId: number) => {
    if (!window.confirm('确定要删除该角色及其功法关联吗？')) return

    try {
      await apiClient.deleteCharacter(characterId)
      setSnackbarMessage('角色已删除')
      setSnackbarSeverity('success')
      setSnackbarOpen(true)
      await loadStructuredCharacters()
    } catch (error) {
      console.error('删除角色失败:', error)
      setSnackbarMessage('删除角色失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  // 向当前角色功法列表中添加一条记录
  const handleAddTechniqueToCharacter = () => {
    if (!selectedTechniqueId) return
    const techniqueIdNumber = Number(selectedTechniqueId)

    // 防止重复添加
    if (characterTechniques.some((t: any) => t.technique_item_id === techniqueIdNumber)) {
      setSnackbarMessage('该功法已在角色列表中')
      setSnackbarSeverity('warning')
      setSnackbarOpen(true)
      return
    }

    const techniqueMeta = availableTechniques.find((t: any) => t.technique_item_id === techniqueIdNumber || t.id === techniqueIdNumber)
    const techniqueName = techniqueMeta?.technique_name || techniqueMeta?.name || '未知功法'

    setCharacterTechniques((prev: any[]) => [
      ...prev,
      {
        technique_item_id: techniqueIdNumber,
        proficiency: '',
        learned_at_chapter: undefined,
        notes: '',
        technique_name: techniqueName,
      },
    ])

    setSelectedTechniqueId('')
  }

  const handleUpdateCharacterTechniqueField = (index: number, field: string, value: any) => {
    setCharacterTechniques((prev: any[]) => {
      const next = [...prev]
      next[index] = { ...next[index], [field]: value }
      return next
    })
  }

  const handleRemoveCharacterTechnique = (index: number) => {
    setCharacterTechniques((prev: any[]) => prev.filter((_, i) => i !== index))
  }


  // 保存并继续（人物设定）

  // 仅保存（人物设定）
  const handleSaveOnlyCharacter = async () => {
    if (!projectId) return

    setCharacterSaving(true)

    try {
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/character_designer/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedCharacterContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setCharacterContent(editedCharacterContent)

        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseCharacterDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save character:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterSaving(false)
    }
  }

  // 打开最终版本对话框
  const handleOpenFinalProduct = async () => {
    setShowFinalVersionDialog(true)

    // ⚡ 优化：如果已经有缓存内容，直接使用，不再请求
    if (finalVersionContent && finalVersionContent.trim() !== '') {
      console.log('⚡ 使用缓存的最终版本内容，长度:', finalVersionContent.length)
      setEditedFinalVersionContent(finalVersionContent)
      return
    }

    // 如果没有缓存，才从API获取
    setFinalVersionLoading(true)

    try {
      console.log('📏 从API获取最新的最终版本内容...')
      const response = await fetch(`/api/v1/workflow/${projectId}/stage/iteration/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        const content = data.content || ''
        console.log('✅ 最终版本已加载，长度:', content.length)
        setFinalVersionContent(content)
        setEditedFinalVersionContent(content)
      } else {
        console.error('❌ 获取最终版本失败，状态码:', response.status)
        setSnackbarMessage('获取最终版本失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取最终版本异常:', error)
      setSnackbarMessage('获取最终版本失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setFinalVersionLoading(false)
    }
  }

  // 生成下一章（方案3：独立的章节生成工作流）
  const handleGenerateNextChapter = async () => {
    if (!projectId) return

    setGeneratingNextChapter(true)

    try {
      console.log('📍 开始生成下一章（异步模式）...')

      const response = await fetch(`/api/v1/workflow/${projectId}/generate-next-chapter`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
      })

      if (response.ok) {
        const data = await response.json()
        console.log('✅ 异步任务已创建:', data)

        // 后端返回: { task_id, status, message, next_chapter_number }
        const { task_id, next_chapter_number } = data

        // 🆕 使用 Redux action 设置任务状态
        dispatch(startGenerateNextChapter({ taskId: task_id, chapterNumber: next_chapter_number }))
        setIsGenerateNextChapterFlow(true)

        setSnackbarMessage(`🚀 已开始生成第${next_chapter_number}章，请等待...`)
        setSnackbarSeverity('info')
        setSnackbarOpen(true)

        // 注意：不再设置 setGeneratingNextChapter(false)，等待 WebSocket 完成事件
      } else {
        const errorData = await response.json()
        console.error('❌ 创建生成任务失败:', errorData)

        setSnackbarMessage(errorData.detail || errorData.error || '创建生成任务失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        setGeneratingNextChapter(false)
      }
    } catch (error) {
      console.error('❌ 生成下一章异常:', error)
      setSnackbarMessage('创建生成任务失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      setGeneratingNextChapter(false)
    }
  }

  // 关闭最终版本对话框
  const handleCloseFinalVersionDialog = () => {
    setShowFinalVersionDialog(false)
    // 不清空 finalVersionContent，保持已保存的内容
    setEditedFinalVersionContent('')  // 只清空编辑状态
  }

  // ✅ 已移除"仅保存"按钮功能，简化用户操作流程

  // 保存为章节（从最终版本）
  const handleSaveAsChapterFromFinalVersion = async () => {
    if (!projectId || !editedFinalVersionContent) {
      setSnackbarMessage('没有可保存的内容')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      return
    }

    setSavingChapter(true)

    try {
      console.log('📏 开始保存最终版本为章节...', {
        projectId,
        contentLength: editedFinalVersionContent.length,
        title: chapterTitleInput,
        token: localStorage.getItem('access_token') ? '存在' : '不存在'
      })

      // ✅ 更新state，保持已保存的内容
      setFinalVersionContent(editedFinalVersionContent)

      // 创建独立章节记录 - 使用apiClient确保正确的baseURL，URL末尾添加斜杠避免307重定向
      const response = await apiClient.post('/api/v1/chapters/', {
        project_id: parseInt(projectId),
        content: editedFinalVersionContent,
        title: chapterTitleInput || undefined, // 如果为空则自动生成
      })

      // axios成功响应（2xx状态码）
      const data = response.data
      console.log('✅ 章节保存成功:', data)

      // ✅ 关闭对话框
      handleCloseFinalVersionDialog()

      // 显示成功消息（后端直接返回章节对象，不是嵌套在chapter字段中）
      setSnackbarMessage(`✅ 第${data.chapter_number}章已保存：${data.title} (${data.word_count}字)`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // ✅ 返回 Dashboard 并自动展开章节列表
      setTimeout(() => {
        console.log('📏 返回 Dashboard')
        navigate(`/dashboard?projectId=${projectId}`)
      }, 1000)
    } catch (error: any) {
      // axios错误响应（非2xx状态码或网络错误）
      console.error('❌ 保存章节异常:', error)

      let errorMessage = '保存章节失败，请重试'

      if (error.response) {
        // 服务器返回错误响应
        errorMessage = error.response.data?.error || error.response.data?.detail || errorMessage
        console.error('❌ 服务器错误:', error.response.status, error.response.data)
      } else if (error.request) {
        // 请求已发送但无响应
        errorMessage = '无法连接到服务器，请检查后端服务是否启动'
        console.error('❌ 网络错误: 无响应')
      } else {
        // 其他错误
        errorMessage = error.message || errorMessage
        console.error('❌ 请求配置错误:', error.message)
      }

      setSnackbarMessage(errorMessage)
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      // ✅ 确保一定会执行
      setSavingChapter(false)
      console.log('🛡️ [保存状态] savingChapter 已设置为 false')
    }
  }



  const currentStageIndex = stages.indexOf(workflow.currentStage)

  return (
    <Container maxWidth="lg" sx={{ py: 2 }}>
      {/* 左侧顶部区域：返回按钮 + 标题 + 项目信息 */}
      <Box sx={{ maxWidth: { xs: '100%', md: 'calc(33.33% - 8px)' }, mb: 3 }}>
        {/* 返回按钮 */}
        <Box sx={{ mb: 3, py: 1 }}>
          <Button
            startIcon={<ArrowBackIcon />}
            onClick={() => navigate('/dashboard')}
            variant="outlined"
            size="medium"
            sx={{ py: 1, px: 2 }}
          >
            返回仪表板
          </Button>
        </Box>

        {/* 主标题 */}
        <Box sx={{ mb: 3, py: 1 }}>
          <Typography variant="h5" sx={{ fontWeight: 600, lineHeight: 1.4 }}>
            🚀 多Agent小说创作工作流程
          </Typography>
        </Box>

        {/* 项目信息 */}
        {(currentProject || workflow.projectId) && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, flexWrap: 'wrap', py: 1 }}>
            <Typography variant="body1" color="text.secondary">
              当前项目:
            </Typography>
            {currentProject && (
              <Chip
                label={`📝 ${currentProject.title}`}
                color="primary"
                variant="outlined"
                sx={{ fontSize: '0.85rem', height: '32px' }}
              />
            )}
            {workflow.projectId && (
              <Chip
                label={`ID: ${workflow.projectId}`}
                variant="outlined"
                sx={{ height: '32px' }}
              />
            )}
          </Box>
        )}
      </Box>

      {/* 错误提示 */}
      {workflow.error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {workflow.error}
        </Alert>
      )}

      {/* 异步任务进度提示 */}
      {currentTaskId && (
        <Alert severity="info" sx={{ mb: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <CircularProgress size={20} />
            <Box sx={{ flex: 1 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="body2">
                  正在执行 {stageNames[workflow.currentStage]}... ({taskProgress}%)
                </Typography>
                {estimatedRemainingTime > 0 && (() => {
                  // 🆕 置信区间显示逻辑
                  const timeDiff = estimatedRemainingTimeMax - estimatedRemainingTimeMin
                  const showRange = timeDiff >= 10  // 差距大于10秒才显示范围

                  if (showRange) {
                    return (
                      <Typography variant="caption" color="text.secondary">
                        预计剩余: {Math.ceil(estimatedRemainingTimeMin)}-{Math.ceil(estimatedRemainingTimeMax)}秒
                      </Typography>
                    )
                  } else {
                    return (
                      <Typography variant="caption" color="text.secondary">
                        预计剩余: {Math.ceil(estimatedRemainingTime)}秒
                      </Typography>
                    )
                  }
                })()}
              </Box>
              <LinearProgress variant="determinate" value={taskProgress} />
            </Box>
          </Box>
        </Alert>
      )}

      {/* 🆕 生成下一章任务进度提示 */}
      {generateNextChapterTaskId && generatingNextChapter && (
        <Alert severity="info" sx={{ mb: 3 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <CircularProgress size={20} />
            <Box sx={{ flex: 1 }}>
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                <Typography variant="body2">
                  🚀 正在生成第{generateNextChapterNumber}章... ({generateNextChapterProgress}%)
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {generateNextChapterProgress < 25 ? '步骤1/4: 章节规划' :
                   generateNextChapterProgress < 50 ? '步骤2/4: 内容创作' :
                   generateNextChapterProgress < 75 ? '步骤3/4: 质量评审' :
                   '步骤4/4: 迭代优化'}
                </Typography>
              </Box>
              <LinearProgress variant="determinate" value={generateNextChapterProgress} />
            </Box>
          </Box>
        </Alert>
      )}

      {/* 主内容区域 */}
      <Grid container spacing={2}>
        {/* 左侧：总进度 + 阶段信息 + Agent状态 */}
        <Grid item xs={12} md={4}>
          {/* 总进度条 - 与右侧 Stepper 对齐 */}
          <Card sx={{ mb: 1.5 }}>
            <CardContent sx={{ py: 1.5, px: 2, '&:last-child': { pb: 1.5 } }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.75 }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600, fontSize: '0.85rem' }}>
                  📈 总体进度
                </Typography>
                <Typography variant="subtitle2" sx={{ fontWeight: 700, color: 'primary.main', fontSize: '0.85rem' }}>
                  {workflow.overallProgress}%
                </Typography>
              </Box>
              <LinearProgress
                variant="determinate"
                value={workflow.overallProgress}
                sx={{ height: 6, borderRadius: 3 }}
              />
            </CardContent>
          </Card>

          {/* 阶段信息面板（工作步骤说明） */}
          <StageInfoPanel stage={workflow.currentStage} />

          {/* Agent状态 - 与右侧输出预览底部对齐 */}
          <Card sx={{ mb: 0, flex: 1 }}>
            <CardContent sx={{ py: 1.5, px: 2, '&:last-child': { pb: 1.5 } }}>
              <Typography variant="subtitle2" sx={{ mb: 1, fontSize: '0.85rem', fontWeight: 600 }}>
                📊 Agent状态
              </Typography>
              {workflow.stages[workflow.currentStage].agents.map((agent) => (
                <AgentStatusIndicator key={agent.id} agent={agent} />
              ))}
            </CardContent>
          </Card>

          {/* 开始/暂停操作按钮（Fab样式） */}
          <Box sx={{ display: 'flex', justifyContent: 'center', mt: 2 }}>
            {!isRunning ? (
              <Tooltip title="开始创作" placement="right">
                <Fab
                  color="primary"
                  onClick={handleStartButtonClick}
                  sx={{
                    width: 56,
                    height: 56,
                    boxShadow: 3,
                    '&:hover': {
                      boxShadow: 6,
                    },
                  }}
                >
                  <PlayArrowIcon />
                </Fab>
              </Tooltip>
            ) : (
              <Tooltip title="暂停" placement="right">
                <Fab
                  color="error"
                  onClick={() => setIsRunning(false)}
                  sx={{
                    width: 56,
                    height: 56,
                    boxShadow: 3,
                    '&:hover': {
                      boxShadow: 6,
                    },
                  }}
                >
                  <PauseIcon />
                </Fab>
              </Tooltip>
            )}
          </Box>

          {/* 🔧 记忆管理面板已隐藏，后台自动保存逻辑保留 */}
        </Grid>

        {/* 右侧：阶段导航 + 输出预览区域（向上移动与返回按钮顶部对齐） */}
        <Grid item xs={12} md={8} sx={{ mt: { xs: 0, md: -22 } }}>
          {/* 阶段导航 - 与左侧总进度对齐 */}
          <Paper sx={{ py: 2.5, px: 3, mb: 2 }}>
            <Stepper
              activeStep={currentStageIndex}
              sx={{
                '& .MuiStepConnector-line': {
                  minWidth: 24,
                },
              }}
            >
              {stages.map((stage) => (
                <Step
                  key={stage}
                  completed={workflow.stages[stage].status === 'completed'}
                  sx={{ cursor: 'pointer', px: 0.5 }}
                  onClick={() => {
                    // 跳转到对应阶段
                    dispatch(setCurrentStage(stage))
                    // 显示提示
                    setSnackbarMessage(`已切换到 ${stageNames[stage]}`)
                    setSnackbarSeverity('info')
                    setSnackbarOpen(true)
                  }}
                >
                  <StepLabel
                    sx={{
                      '& .MuiStepLabel-label': {
                        cursor: 'pointer',
                        fontSize: '0.9rem',
                        transition: 'color 0.2s, transform 0.2s',
                        '&:hover': {
                          color: 'primary.main',
                          transform: 'scale(1.05)',
                        },
                      },
                    }}
                  >
                    {stageNames[stage]}
                  </StepLabel>
                </Step>
              ))}
            </Stepper>
          </Paper>

          {/* 输出预览区域（始终可见，实时显示流式内容） */}
          <OutputPreviewPanel
            stage={workflow.currentStage}
            isStreaming={isStreaming}
            streamingStage={streamingStage}
            conceptContent={conceptContent}
            worldContent={worldContent}
            characterContent={characterContent}
            structureContent={structureContent}
            contentDraftContent={contentDraftContent}
            reviewReportContent={reviewReportContent}
            finalVersionContent={finalVersionContent}
            generateNextChapterStreamContent={generateNextChapterStreamContent}
            isGeneratingNextChapter={!!generateNextChapterTaskId}
          />

          {/* 控制按钮 - 在文本区域正下方居中 */}
          <Box
            sx={{
              mt: 1,  // 🔧 减小与文本区域的间距
              display: 'flex',
              gap: 2,
              justifyContent: 'center',
            }}
          >
        {/* ✅ 概念开发阶段不显示"上一步"按钮 */}
        {currentStageIndex > 0 && (
          <Button
            variant="outlined"
            onClick={handlePreviousStage}
            disabled={workflow.loading || isRunning}
          >
            上一步
          </Button>
        )}

        {/* 概念开发阶段：显示"故事概念"、"世界观设定"、"人物设定"按钮 */}
        {workflow.currentStage === 'concept' ? (
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              onClick={handleOpenConceptDialog}
              disabled={!conceptContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<DescriptionIcon />}
            >
              故事概念
            </Button>
            <Button
              variant="outlined"
              onClick={handleOpenWorldDialog}
              disabled={!worldContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<PublicIcon />}
            >
              世界观设定
            </Button>
            <Button
              variant="outlined"
              onClick={handleOpenCharacterDialog}
              disabled={!characterContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<PeopleIcon />}
            >
              人物设定
            </Button>
          </Box>
        ) : workflow.currentStage === 'structure' ? (
          /* 结构设计阶段：显示"情节大纲"按钮 */
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              onClick={handleOpenStructureDialog}
              disabled={!structureContent && workflow.stages.structure.status !== 'completed'}
              startIcon={<ArticleIcon />}
            >
              情节大纲
            </Button>
          </Box>
        ) : workflow.currentStage === 'content' ? (
          /* 内容创作阶段：显示“章节初稿”按钮 */
          <Button
            variant="outlined"
            onClick={handleOpenContentDialog}
            disabled={!contentDraftContent && workflow.stages.content.status !== 'completed'}
            startIcon={<EditNoteIcon />}
          >
            章节初稿
          </Button>
        ) : workflow.currentStage === 'review' ? (
          /* 质量评审阶段：显示"评审报告"按钮 */
          <Button
            variant="outlined"
            onClick={handleOpenReviewDialog}
            disabled={!reviewReportContent && workflow.stages.review.status !== 'completed'}
            startIcon={<ArticleIcon />}
          >
            评审报告
          </Button>
        ) : workflow.currentStage === 'iteration' ? (
          /* 迭代优化阶段：显示“最终成品”和“生成下一章”按钮 */
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              onClick={handleOpenFinalProduct}
              disabled={!finalVersionContent && workflow.stages.iteration.status !== 'completed'}
              startIcon={<CheckCircleIcon />}
            >
              最终成品
            </Button>
            <Button
              variant="outlined"
              onClick={handleGenerateNextChapter}
              disabled={workflow.stages.iteration.status !== 'completed' || generatingNextChapter}
              startIcon={generatingNextChapter ? <CircularProgress size={20} /> : <NavigateNextIcon />}
            >
              {generatingNextChapter ? '生成中...' : '生成下一章'}
            </Button>
          </Box>
        ) : (
          /* 其他阶段：显示"重新生成"按钮 */
          <Button
            variant="outlined"
            onClick={handleRegenerateStage}
            disabled={workflow.loading || !isRunning}
            startIcon={<RefreshIcon />}
          >
            重新生成
          </Button>
        )}

        {currentStageIndex !== stages.length - 1 && (
          <Button
            variant="outlined"
            onClick={handleNextStage}
            disabled={workflow.loading || isRunning}
          >
            下一步
          </Button>
        )}
          </Box>
        </Grid>
      </Grid>

      {/* 🆕 已有内容警告对话框 */}
      <Dialog
        open={showContentWarningDialog}
        onClose={() => setShowContentWarningDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2, display: 'flex', alignItems: 'center', gap: 1 }}>
            ⚠️ 警告：此项目已有内容
          </Typography>

          <Alert severity="warning" sx={{ mb: 3 }}>
            <Typography variant="body2" sx={{ mb: 1 }}>
              <strong>此项目已有 {existingChaptersCount} 章内容</strong>
              {workflow.stages.concept.status === 'completed' && '，以及已完成的故事概念'}
              {workflow.stages.structure.status === 'completed' && '、情节大纲'}。
            </Typography>
            <Typography variant="body2">
              重新开始创作将<strong style={{ color: '#d32f2f' }}>覆盖所有现有内容</strong>，此操作不可撤销！
            </Typography>
          </Alert>

          <Typography variant="body2" sx={{ mb: 2, color: 'text.secondary' }}>
            您想要的操作是：
          </Typography>

          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {existingChaptersCount > 0 && (
              <Button
                variant="contained"
                color="primary"
                onClick={handleContinueNextChapter}
                startIcon={<AddIcon />}
                sx={{ justifyContent: 'flex-start', py: 1.5 }}
              >
                <Box sx={{ textAlign: 'left' }}>
                  <Typography variant="button">继续创作下一章</Typography>
                  <Typography variant="caption" sx={{ display: 'block', opacity: 0.8 }}>
                    基于现有内容，生成第 {existingChaptersCount + 1} 章（推荐）
                  </Typography>
                </Box>
              </Button>
            )}

            <Button
              variant="outlined"
              color="error"
              onClick={handleConfirmRestart}
              startIcon={<RefreshIcon />}
              sx={{ justifyContent: 'flex-start', py: 1.5 }}
            >
              <Box sx={{ textAlign: 'left' }}>
                <Typography variant="button">重新开始（覆盖所有）</Typography>
                <Typography variant="caption" sx={{ display: 'block', opacity: 0.8 }}>
                  删除现有内容，从头开始创作
                </Typography>
              </Box>
            </Button>

            <Button
              variant="text"
              onClick={() => setShowContentWarningDialog(false)}
              sx={{ justifyContent: 'flex-start' }}
            >
              取消
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 开始创作对话框 */}
      <Dialog
        open={openDialog}
        onClose={() => !isStarting && setOpenDialog(false)}
        maxWidth="sm"
        fullWidth
      >
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            输入创作需求
          </Typography>

          {/* 启动中的加载提示 */}
          {isStarting && (
            <Alert severity="info" sx={{ mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <CircularProgress size={20} />
                <Typography variant="body2">
                  正在启动工作流，请稍候...
                </Typography>
              </Box>
            </Alert>
          )}

          <TextField
            fullWidth
            multiline
            rows={4}
            placeholder="请输入您的创作需求，例如：创作一部关于时空旅行的科幻小说..."
            value={requirement}
            onChange={(e) => setRequirement(e.target.value)}
            sx={{ mb: 2 }}
            disabled={isStarting}
          />
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
            <Button
              onClick={() => setOpenDialog(false)}
              disabled={isStarting}
            >
              取消
            </Button>
            <Button
              variant="contained"
              color="primary"
              onClick={handleStartWorkflow}
              disabled={workflow.loading || isStarting}
              startIcon={isStarting ? <CircularProgress size={20} /> : undefined}
            >
              {isStarting ? '启动中...' : '开始'}
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 保存章节对话框 */}
      <Dialog open={showSaveDialog} onClose={() => setShowSaveDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            🎉 工作流程已完成！
          </Typography>
          <Alert severity="success" sx={{ mb: 2 }}>
            所有5个阶段已成功完成，现在可以将生成的内容保存为新章节。
          </Alert>
          <TextField
            fullWidth
            label="章节标题（可选）"
            placeholder="例如：冒险开始（留空则自动生成）"
            value={chapterTitle}
            onChange={(e) => setChapterTitle(e.target.value)}
            sx={{ mb: 2 }}
            disabled={savingChapter}
            helperText="如果不输入标题，系统会根据章节内容自动生成标题，格式为：第一章 {AI生成的标题}"
          />
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              onClick={() => {
                setShowSaveDialog(false)
                setChapterTitle('')
              }}
              disabled={savingChapter}
            >
              稍后保存
            </Button>
            <Button
              variant="contained"
              color="primary"
              onClick={handleSaveAsChapter}
              disabled={savingChapter}
              startIcon={savingChapter ? <CircularProgress size={20} /> : <SaveIcon />}
            >
              {savingChapter ? '保存中...' : '保存为章节'}
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 故事概念对话框 */}
      <Dialog open={showConceptDialog} onClose={handleCloseConceptDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📖 故事概念文档
          </Typography>

          {conceptLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedContent}
                onChange={(e) => setEditedContent(e.target.value)}
                placeholder="故事概念文本内容..."
                sx={{ mb: 2 }}
                disabled={conceptSaving}
                InputProps={{
                  style: {
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                  }
                }}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseConceptDialog}
                  disabled={conceptSaving}
                >
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveOnly}
                  disabled={conceptSaving}
                  startIcon={conceptSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {conceptSaving ? '保存中...' : '保存'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 情节大纲对话框 */}
      <Dialog open={showStructureDialog} onClose={handleCloseStructureDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📋 情节大纲文档
          </Typography>

          {structureLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <TextField
                  fullWidth
                  multiline
                  rows={12}
                  value={editedStructureContent}
                  onChange={(e) => setEditedStructureContent(e.target.value)}
                  placeholder="情节大纲文本内容..."
                  sx={{ mb: 2 }}
                  disabled={structureSaving}
                  InputProps={{
                    style: {
                      fontFamily: 'monospace',
                      fontSize: '0.875rem',
                    }
                  }}
                />

                {/* 底部一行：左侧为目标章节数+扩展按钮，右侧为取消/保存 */}
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mt: 1 }}>
                  {/* 左侧：目标章节数 + 扩展情节大纲 */}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
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

                    <Tooltip
                      title="💡默认目标为100章，可在右侧输入框中调整。"
                      placement="top"
                      arrow
                    >
                      <span>
                        <Button
                          variant="contained"
                          color="secondary"
                          onClick={handleExpandOutline}
                          disabled={!structureContent || !worldContent || !characterContent || expandingOutline}
                          startIcon={expandingOutline ? <CircularProgress size={20} /> : <ArticleIcon />}
                        >
                          {expandingOutline ? '扩展中...' : `📖 扩展情节大纲${currentChapterCount > 0 ? ` (当前${currentChapterCount}章)` : ''}`}
                        </Button>
                      </span>
                    </Tooltip>
                  </Box>

                  {/* 右侧：取消 + 保存 */}
                  <Box sx={{ display: 'flex', gap: 2 }}>
                    <Button
                      onClick={handleCloseStructureDialog}
                      disabled={structureSaving}
                    >
                      取消
                    </Button>
                    <Button
                      variant="contained"
                      color="primary"
                      onClick={handleSaveOnlyStructure}
                      disabled={structureSaving}
                      startIcon={structureSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                    >
                      {structureSaving ? '保存中...' : '保存'}
                    </Button>
                  </Box>
                </Box>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 章节初稿对话框 */}
      <Dialog open={showContentDialog} onClose={handleCloseContentDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            ✍️ 章节初稿文档
          </Typography>

          {contentLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedContentDraftContent}
                onChange={(e) => setEditedContentDraftContent(e.target.value)}
                placeholder="章节初稿文本内容..."
                sx={{ mb: 2 }}
                disabled={contentSaving}
                InputProps={{
                  style: {
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                  }
                }}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseContentDialog}
                  disabled={contentSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnlyContent}
                  disabled={contentSaving}
                  startIcon={contentSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {contentSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinueContent}
                  disabled={contentSaving}
                  startIcon={contentSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {contentSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 评审报告对话框 */}
      <Dialog open={showReviewDialog} onClose={handleCloseReviewDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📋 质量评审报告
          </Typography>

          {reviewLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedReviewReportContent}
                onChange={(e) => setEditedReviewReportContent(e.target.value)}
                placeholder="评审报告内容..."
                sx={{ mb: 2 }}
                disabled={reviewSaving}
                InputProps={{
                  style: {
                    fontFamily: 'monospace',
                    fontSize: '0.875rem',
                  }
                }}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseReviewDialog}
                  disabled={reviewSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnlyReview}
                  disabled={reviewSaving}
                  startIcon={reviewSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {reviewSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinueReview}
                  disabled={reviewSaving}
                  startIcon={reviewSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {reviewSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 世界观设定对话框 */}
      <Dialog open={showWorldDialog} onClose={handleCloseWorldDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            🌍 世界观设定文档
          </Typography>

          {worldLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <Tabs
                value={worldSettingsTab}
                onChange={(_, value) => setWorldSettingsTab(value)}
                sx={{ mb: 2 }}
              >
                <Tab label="文本内容" value="text" />
                <Tab label="类型设定" value="settings" />
              </Tabs>

              {worldSettingsTab === 'text' && (
                <TextField
                  fullWidth
                  multiline
                  rows={12}
                  value={editedWorldContent}
                  onChange={(e) => setEditedWorldContent(e.target.value)}
                  placeholder="世界观设定文本内容..."
                  sx={{ mb: 2 }}
                  disabled={worldSaving}
                  InputProps={{
                    style: {
                      fontFamily: 'monospace',
                      fontSize: '0.875rem',
                    }
                  }}
                />
              )}

              {worldSettingsTab === 'settings' && (
                <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start', mt: 1 }}>
                  {/* 左侧：设定集合列表 */}
                  <Box sx={{ width: 260, flexShrink: 0 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                      <Box sx={{ display: 'flex', gap: 1 }}>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={handleOpenTemplateDialog}
                          disabled={!projectId}
                        >
                          从模板创建
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          startIcon={<AddIcon />}
                          onClick={handleCreateCollection}
                          disabled={!projectId}
                        >
                          新建
                        </Button>
                      </Box>
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
                          {getAvailableCategoriesToAdd().map((cat) => (
                            <MenuItem key={cat} value={cat}>
                              {getCategoryDisplayName(cat)}
                            </MenuItem>
                          ))}
                        </Select>
                      </FormControl>
                    )}

                    {settingCollectionsLoading ? (
                      <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
                        <CircularProgress size={24} />
                      </Box>
                    ) : (
                      <List dense sx={{ maxHeight: 360, overflow: 'auto' }}>
                        {settingCollections.length === 0 ? (
                          <ListItem>
                            <Typography variant="body2" color="text.secondary">
                              暂无设定集合，可点击右上角“新建”创建。
                            </Typography>
                          </ListItem>
                        ) : (
                          settingCollections.map((collection: any) => (
                            <ListItem
                              key={collection.id}
                              selected={collection.id === selectedCollectionId}
                              button
                              draggable
                              onDragStart={() => setDraggingCollectionId(collection.id)}
                              onDragOver={(e) => e.preventDefault()}
                              onDrop={(e) => {
                                e.preventDefault()
                                e.stopPropagation()
                                handleDropCollection(collection.id)
                              }}
                              onClick={() => {
                                setSelectedCollectionId(collection.id)
                                loadSettingItems(collection.id)
                              }}
                              secondaryAction={
                                <Box sx={{ display: 'flex', gap: 0.5 }}>
                                  <Tooltip title="编辑">
                                    <IconButton
                                      edge="end"
                                      size="small"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleEditCollection(collection)
                                      }}
                                    >
                                      <EditIcon fontSize="small" />
                                    </IconButton>
                                  </Tooltip>
                                  <Tooltip title="删除">
                                    <IconButton
                                      edge="end"
                                      size="small"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        handleDeleteCollection(collection.id)
                                      }}
                                    >
                                      <DeleteIcon fontSize="small" />
                                    </IconButton>
                                  </Tooltip>
                                </Box>
                              }
                              sx={{ cursor: 'grab' }}
                            >
                              <Box>
                                <Typography variant="body2">{collection.name}</Typography>
                                {collection.category && (
                                  <Typography variant="caption" color="text.secondary">
                                    {getCategoryDisplayName(collection.category)}
                                  </Typography>
                                )}
                              </Box>
                            </ListItem>
                          ))
                        )}
                      </List>
                    )}
                  </Box>

                  {/* 右侧：设定项列表 */}
                  <Box sx={{ flex: 1, minHeight: 320 }}>
                    {selectedCollectionId ? (
                      <>
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                          <Typography variant="subtitle1">设定项</Typography>
                          <Button
                            size="small"
                            variant="outlined"
                            startIcon={<AddIcon />}
                            onClick={handleCreateItem}
                          >
                            新建设定项
                          </Button>
                        </Box>

                        {settingItemsLoading ? (
                          <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
                            <CircularProgress size={24} />
                          </Box>
                        ) : settingItems.length === 0 ? (
                          <Typography variant="body2" color="text.secondary">
                            暂无设定项，可点击右上角“新建设定项”创建。
                          </Typography>
                        ) : (
                          <List dense sx={{ maxHeight: 360, overflow: 'auto' }}>
                            {settingItems.map((item: any) => (
                              <ListItem
                                key={item.id}
                                button
                                draggable
                                onDragStart={() => setDraggingItemId(item.id)}
                                onDragOver={(e) => e.preventDefault()}
                                onDrop={(e) => {
                                  e.preventDefault()
                                  e.stopPropagation()
                                  handleDropItem(item.id)
                                }}
                                onClick={() => handleEditItem(item)}
                                secondaryAction={
                                  <Box sx={{ display: 'flex', gap: 0.5 }}>
                                    <Tooltip title="复制">
                                      <IconButton
                                        edge="end"
                                        size="small"
                                        onClick={(e) => {
                                          e.stopPropagation()
                                          handleCopyItem(item)
                                        }}
                                      >
                                        <ContentCopyIcon fontSize="small" />
                                      </IconButton>
                                    </Tooltip>
                                    <Tooltip title="删除">
                                      <IconButton
                                        edge="end"
                                        size="small"
                                        onClick={(e) => {
                                          e.stopPropagation()
                                          handleDeleteItem(item.id)
                                        }}
                                      >
                                        <DeleteIcon fontSize="small" />
                                      </IconButton>
                                    </Tooltip>
                                  </Box>
                                }
                                sx={{ cursor: 'grab', pr: 10, pl: `${getIndentForItem(item) + 8}px` }}
                              >
                                <Box>
                                  <Typography variant="body2">
                                    {item.level != null ? `Lv.${item.level} ` : ''}
                                    {item.name}
                                  </Typography>
                                  {item.code && (
                                    <Chip label={item.code} size="small" variant="outlined" sx={{ mt: 0.5 }} />
                                  )}
                                </Box>
                              </ListItem>
                            ))}
                          </List>
                        )}



                      </>
                    ) : (
                      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
                        <Typography variant="body2" color="text.secondary">
                          请先在左侧选择一个设定集合，或新建集合。
                        </Typography>
                      </Box>
                    )}
                  </Box>
                </Box>
              )}

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
                <Button
                  onClick={handleCloseWorldDialog}
                  disabled={worldSaving}
                >
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveOnlyWorld}
                  disabled={worldSaving}
                  startIcon={worldSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {worldSaving ? '保存中...' : '保存'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 模板选择对话框 */}
      <Dialog
        open={showTemplateDialog}
        onClose={() => !applyingTemplate && setShowTemplateDialog(false)}
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

          <FormControlLabel
            sx={{ mt: 2 }}
            control={
              <Checkbox
                checked={clearExistingSettings}
                onChange={(e) => setClearExistingSettings(e.target.checked)}
              />
            }
            label="清空当前项目下已有的设定集合（谨慎操作）"
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowTemplateDialog(false)} disabled={applyingTemplate}>
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


      {/* 设定集合编辑对话框 */}
      <Dialog
        open={collectionDialogOpen}
        onClose={handleCloseCollectionDialog}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {collectionDialogMode === 'create' ? '新建设定集合' : '编辑设定集合'}
        </DialogTitle>
        <DialogContent dividers>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField
              label="集合名称"
              fullWidth
              required
              value={collectionForm.name}
              onChange={(e) =>
                setCollectionForm((prev) => ({ ...prev, name: e.target.value }))
              }
              error={collectionDialogSubmitted && !collectionForm.name.trim()}
              helperText={
                collectionDialogSubmitted && !collectionForm.name.trim()
                  ? '集合名称不能为空'
                  : '例如：境界体系、功法体系'
              }
              disabled={collectionDialogSaving}
            />
            <TextField
              label="集合分类标识（可选）"
              fullWidth
              value={collectionForm.category}
              onChange={(e) =>
                setCollectionForm((prev) => ({ ...prev, category: e.target.value }))
              }
              helperText="用于内部区分，如 cultivation_system / power_system / custom"
              disabled={collectionDialogSaving}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseCollectionDialog} disabled={collectionDialogSaving}>
            取消
          </Button>
          <Button
            onClick={handleSubmitCollectionDialog}
            variant="contained"
            disabled={collectionDialogSaving}
            startIcon={collectionDialogSaving ? <CircularProgress size={20} /> : undefined}
          >
            {collectionDialogSaving ? '保存中...' : '保存'}
          </Button>
        </DialogActions>
      </Dialog>


      {/* 设定项编辑对话框 */}
      <Dialog
        open={itemDialogOpen}
        onClose={handleCloseItemDialog}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle>{itemDialogMode === 'create' ? '新建设定项' : '编辑设定项'}</DialogTitle>
        <DialogContent dividers>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, mt: 1 }}>
            <TextField
              label="名称"
              fullWidth
              required
              value={itemForm.name}
              onChange={(e) =>
                setItemForm((prev) => ({
                  ...prev,
                  name: e.target.value,
                }))
              }
              error={itemDialogSubmitted && !itemForm.name.trim()}
              helperText={
                itemDialogSubmitted && !itemForm.name.trim()
                  ? '名称不能为空'
                  : '例如：炼气一层、金丹期、A级异能者'
              }
              disabled={itemDialogSaving}
            />

            <Box sx={{ display: 'flex', gap: 2 }}>
              <TextField
                label="等级（可选）"
                type="number"
                value={itemForm.level}
                onChange={(e) =>
                  setItemForm((prev) => ({
                    ...prev,
                    level: e.target.value,
                  }))
                }
                helperText="可用于排序和展示，如 1、2、3..."
                disabled={itemDialogSaving}
                sx={{ width: 160 }}
              />
              <TextField
                label="编码（可选）"
                value={itemForm.code}
                onChange={(e) =>
                  setItemForm((prev) => ({
                    ...prev,
                    code: e.target.value,
                  }))
                }
                helperText="内部唯一标识，如 QI_1 / POWER_A"
                disabled={itemDialogSaving}
                fullWidth
              />
            </Box>

            <TextField
              label="设定内容"
              fullWidth
              multiline
              minRows={4}
              value={itemForm.content}
              onChange={(e) =>
                setItemForm((prev) => ({
                  ...prev,
                  content: e.target.value,
                }))
              }
              helperText="支持多行文本，可使用简单的 Markdown 结构来组织信息。"
              disabled={itemDialogSaving}
            />

            {/* 标签管理 */}
            <Box sx={{ mt: 1 }}>
              <Typography variant="subtitle2" gutterBottom>
                标签
              </Typography>
              <TextField
                fullWidth
                size="small"
                placeholder="输入标签后按 Enter 或空格添加，如：主线/重要/高危"
                value={itemForm.tagsInput}
                onChange={(e) =>
                  setItemForm((prev) => ({
                    ...prev,
                    tagsInput: e.target.value,
                  }))
                }
                onKeyDown={handleTagInputKeyDown}
                disabled={itemDialogSaving}
              />
              <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                {itemForm.tags.map((tag) => (
                  <Chip
                    key={tag}
                    label={tag}
                    onDelete={() => handleRemoveTag(tag)}
                    size="small"
                  />
                ))}
                {itemForm.tags.length === 0 && (
                  <Typography variant="body2" color="text.secondary">
                    暂无标签。
                  </Typography>
                )}
              </Box>
            </Box>

            {/* 关联关系管理 */}
            <Box sx={{ mt: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                关联关系
              </Typography>
              {itemForm.relations.length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                  当前暂无关联，可点击“添加关联”来建立设定之间的前置、对立、包含等关系。
                </Typography>
              ) : (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {itemForm.relations.map((rel, index) => (
                    <Box
                      key={index}
                      sx={{ display: 'flex', gap: 1, alignItems: 'center' }}
                    >
                      <TextField
                        select
                        label="关系类型"
                        size="small"
                        sx={{ minWidth: 120 }}
                        value={rel.type}
                        onChange={(e) =>
                          handleChangeRelation(index, 'type', e.target.value)
                        }
                      >
                        {RELATION_TYPES.map((type) => (
                          <MenuItem key={type} value={type}>
                            {type}
                          </MenuItem>
                        ))}
                      </TextField>
                      <TextField
                        select
                        label="关联目标"
                        size="small"
                        sx={{ flex: 1, minWidth: 180 }}
                        value={rel.targetId ?? ''}
                        onChange={(e) =>
                          handleChangeRelation(
                            index,
                            'targetId',
                            e.target.value ? Number(e.target.value) : null,
                          )
                        }
                      >
                        <MenuItem value="">（未选择）</MenuItem>
                        {settingItems
                          .filter((i: any) => !editingItem || i.id !== editingItem.id)
                          .map((i: any) => (
                            <MenuItem key={i.id} value={i.id}>
                              {i.name}
                            </MenuItem>
                          ))}
                      </TextField>
                      <IconButton
                        size="small"
                        onClick={() => handleRemoveRelationRow(index)}
                      >
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Box>
                  ))}
                </Box>
              )}
              <Box sx={{ mt: 1 }}>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={handleAddRelation}
                  disabled={itemDialogSaving}
                >
                  添加关联
                </Button>
              </Box>
            </Box>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseItemDialog} disabled={itemDialogSaving}>
            取消
          </Button>
          <Button
            onClick={handleSubmitItemDialog}
            variant="contained"
            disabled={itemDialogSaving}
            startIcon={itemDialogSaving ? <CircularProgress size={20} /> : undefined}
          >
            {itemDialogSaving ? '保存中...' : '保存'}
          </Button>
        </DialogActions>
      </Dialog>


      {/* 删除确认对话框 */}
      <Dialog
        open={deleteDialogOpen}
        onClose={handleCancelDelete}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>确认删除</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2">
            {deleteTarget?.type === 'collection'
              ? '删除集合会同时删除其下所有设定项，此操作不可撤销，确认继续？'
              : '删除后不可恢复，确定要删除该设定项吗？'}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelDelete} disabled={deleteLoading}>
            取消
          </Button>
          <Button
            onClick={handleConfirmDelete}
            color="error"
            variant="contained"
            disabled={deleteLoading}
            startIcon={deleteLoading ? <CircularProgress size={20} /> : undefined}
          >
            {deleteLoading ? '删除中...' : '删除'}
          </Button>
        </DialogActions>
      </Dialog>





      {/* 人物设定对话框 */}
      <Dialog open={showCharacterDialog} onClose={handleCloseCharacterDialog} maxWidth="lg" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            👥 人物设定
          </Typography>

          {/* Tab 切换：文本模式 vs 结构化管理 */}
          <Tabs
            value={characterTab}
            onChange={(_, value) => setCharacterTab(value)}
            sx={{ mb: 2 }}
          >
            <Tab label="文本模式" value="text" />
            <Tab label="结构化管理（人物卡）" value="structured" />
          </Tabs>

          {characterTab === 'text' && (
            <>
              {characterLoading ? (
                <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
                  <CircularProgress />
                </Box>
              ) : (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <TextField
                    fullWidth
                    multiline
                    rows={12}
                    value={editedCharacterContent}
                    onChange={(e) => setEditedCharacterContent(e.target.value)}
                    placeholder="人物设定文本内容..."
                    sx={{ mb: 2 }}
                    disabled={characterSaving}
                  />

                  {/* 底部一行：左侧为目标人物数+扩展按钮，右侧为取消/保存 */}
                  <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mt: 1 }}>
                    {/* 左侧：目标人物数 + 扩展人物 */}
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                      <TextField
                        label="目标人物数"
                        type="number"
                        size="small"
                        value={targetCharacterCount}
                        onChange={(e) => {
                          const value = parseInt(e.target.value, 10)
                          setTargetCharacterCount(Number.isNaN(value) ? 0 : value)
                        }}
                        inputProps={{ min: 1 }}
                        sx={{ width: 150 }}
                      />

                      <Tooltip
                        title="💡默认目标为25个人物，可在右侧输入框中调整。"
                        placement="top"
                        arrow
                      >
                        <span>
                          <Button
                            variant="contained"
                            color="secondary"
                            onClick={handleExpandCharacters}
                            disabled={!characterContent || !worldContent || !structureContent || expandingCharacters}
                            startIcon={expandingCharacters ? <CircularProgress size={20} /> : <PeopleIcon />}
                          >
                            {expandingCharacters ? '扩展中...' : `👥 扩展人物${currentCharacterCount > 0 ? ` (当前${currentCharacterCount}个)` : ''}`}
                          </Button>
                        </span>
                      </Tooltip>
                    </Box>

                    {/* 右侧：取消 + 保存 */}
                    <Box sx={{ display: 'flex', gap: 2 }}>
                      <Button
                        onClick={handleCloseCharacterDialog}
                        disabled={characterSaving}
                      >
                        取消
                      </Button>
                      <Button
                        variant="contained"
                        color="primary"
                        onClick={handleSaveOnlyCharacter}
                        disabled={characterSaving}
                        startIcon={characterSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                      >
                        {characterSaving ? '保存中...' : '保存'}
                      </Button>
                    </Box>
                  </Box>
                </Box>
              )}
            </>
          )}

          {characterTab === 'structured' && (
            <Box sx={{ display: 'flex', gap: 3, mt: 1 }}>
              {/* 左侧：角色列表 */}
              <Box sx={{ flex: 1, minWidth: 260 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                  <Typography variant="subtitle1">角色列表</Typography>
                  <Button
                    variant="contained"
                    size="small"
                    startIcon={<AddIcon />}
                    onClick={() => handleOpenCharacterEditDialog()}
                  >
                    新建角色
                  </Button>
                </Box>

                {structuredCharactersLoading ? (
                  <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
                    <CircularProgress size={24} />
                  </Box>
                ) : (
                  <List dense sx={{ maxHeight: 420, overflowY: 'auto', border: '1px solid #eee', borderRadius: 1 }}>
                    {structuredCharacters.length === 0 && (
                      <Typography variant="body2" sx={{ p: 2, color: 'text.secondary' }}>
                        还没有创建任何结构化角色。可以点击右上角“新建角色”开始。
                      </Typography>
                    )}
                    {structuredCharacters.map((ch: any) => (
                      <ListItem
                        key={ch.id}
                        secondaryAction={
                          <Box sx={{ display: 'flex', gap: 1 }}>
                            <Tooltip title="编辑">
                              <IconButton size="small" onClick={() => handleOpenCharacterEditDialog(ch)}>
                                <EditIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                            <Tooltip title="删除">
                              <IconButton size="small" onClick={() => handleDeleteCharacter(ch.id)}>
                                <DeleteIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          </Box>
                        }
                      >
                        <Box sx={{ display: 'flex', flexDirection: 'column' }}>
                          <Typography variant="subtitle2">{ch.name}</Typography>
                          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 0.5 }}>
                            {ch.role && <Chip size="small" label={ch.role} />}
                            {ch.faction && <Chip size="small" label={ch.faction} />}
                            {ch.current_realm_item_id && (
                              <Chip
                                size="small"
                                color="primary"
                                label={
                                  availableRealms.find((r: any) => r.id === ch.current_realm_item_id)?.name ||
                                  '未知境界'
                                }
                              />
                            )}
                          </Box>
                        </Box>
                      </ListItem>
                    ))}
                  </List>
                )}
              </Box>

              {/* 右侧：提示 */}
              <Box sx={{ flex: 1.2, color: 'text.secondary', fontSize: 14 }}>
                <Typography variant="subtitle1" sx={{ mb: 1 }}>
                  使用说明
                </Typography>
                <Typography variant="body2" paragraph>
                  这里是结构化人物卡管理区：你可以为每个角色维护基础信息（阵营、境界、出场状态等）以及“已掌握功法列表”。
                </Typography>
                <Typography variant="body2" paragraph>
                  保存后，这些信息会参与到后端的章节逻辑检查 Agent 中，帮助检查“角色是否使用了未登记的功法”以及“境界是否达标”。
                </Typography>
                <Typography variant="body2" paragraph>
                  详细编辑（包括功法列表）请通过“新建/编辑角色”按钮打开单独的编辑对话框。
                </Typography>

                <Box sx={{ mt: 2 }}>
                  <Alert severity="info" variant="outlined">
                    文本模式中的人物设定依然有效，可以与结构化人物卡并行使用；后续如需完全切换到结构化模式，也可以逐步迁移内容。
                  </Alert>
                </Box>
              </Box>
            </Box>
          )}
        </Box>
      </Dialog>

      {/* 角色编辑对话框（结构化） */}
      <Dialog open={showCharacterEditDialog} onClose={handleCloseCharacterEditDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            {characterFormData?.id ? '编辑角色' : '新建角色'}
          </Typography>

          {characterFormLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {/* 基础信息 */}
              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 2 }}>
                <TextField
                  label="姓名"
                  required
                  value={characterFormData?.name || ''}
                  onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, name: e.target.value }))}
                />
                <TextField
                  select
                  label="角色定位（阵营/立场）"
                  value={characterFormData?.role || ''}
                  onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, role: e.target.value }))}
                >
                  <MenuItem value="">自定义</MenuItem>
                  <MenuItem value="主角方">主角方</MenuItem>
                  <MenuItem value="反派方">反派方</MenuItem>
                  <MenuItem value="中立方">中立方</MenuItem>
                  <MenuItem value="亦正亦邪">亦正亦邪</MenuItem>
                </TextField>
                <TextField
                  label="性别"
                  value={characterFormData?.gender || ''}
                  onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, gender: e.target.value }))}
                />
                <TextField
                  label="年龄"
                  type="number"
                  value={characterFormData?.age ?? ''}
                  onChange={(e) => {
                    const value = e.target.value
                    setCharacterFormData((prev: any) => ({
                      ...prev,
                      age: value === '' ? undefined : Number(value),
                    }))
                  }}
                />
                <TextField
                  select
                  label="阵营/势力"
                  value={characterFormData?.faction || ''}
                  onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, faction: e.target.value }))}
                  helperText={availableForces.length === 0 ? "未找到势力体系" : ""}
                >
                  <MenuItem value="">
                    <em>未设置</em>
                  </MenuItem>
                  {availableForces.map((force: any) => (
                    <MenuItem key={force.id} value={force.name}>
                      {force.name}
                    </MenuItem>
                  ))}
                </TextField>
                <TextField
                  select
                  label="重要性（戏份权重）"
                  value={characterFormData?.importance_level || ''}
                  onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, importance_level: e.target.value }))}
                >
                  <MenuItem value="">自定义</MenuItem>
                  <MenuItem value="主角">主角</MenuItem>
                  <MenuItem value="重要角色">重要角色</MenuItem>
                  <MenuItem value="次要角色">次要角色</MenuItem>
                  <MenuItem value="群众角色">群众角色</MenuItem>
                </TextField>
                <TextField
                  select
                  label="出场状态（未出场/已出场/已退场）"
                  value={characterFormData?.appearance_status || ''}
                  onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, appearance_status: e.target.value }))}
                >
                  <MenuItem value="未出场">未出场</MenuItem>
                  <MenuItem value="已出场">已出场</MenuItem>
                  <MenuItem value="已退场">已退场</MenuItem>
                </TextField>
                <TextField
                  select
                  label="生死状态（存活/死亡/失踪/未知）"
                  value={characterFormData?.life_status || ''}
                  onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, life_status: e.target.value }))}
                >
                  <MenuItem value="存活">存活</MenuItem>
                  <MenuItem value="死亡">死亡</MenuItem>
                  <MenuItem value="失踪">失踪</MenuItem>
                  <MenuItem value="未知">未知</MenuItem>
                </TextField>
                <TextField
                  label="首次出场章节编号"
                  type="number"
                  value={characterFormData?.first_appearance_chapter ?? ''}
                  onChange={(e) => {
                    const value = e.target.value
                    setCharacterFormData((prev: any) => ({
                      ...prev,
                      first_appearance_chapter: value === '' ? undefined : Number(value),
                    }))
                  }}
                />
                <TextField
                  select
                  label="当前境界"
                  value={characterFormData?.current_realm_item_id ?? ''}
                  onChange={(e) => {
                    const value = e.target.value
                    setCharacterFormData((prev: any) => ({
                      ...prev,
                      current_realm_item_id: value === '' ? undefined : Number(value),
                    }))
                  }}
                >
                  <MenuItem value="">
                    <em>未设置</em>
                  </MenuItem>
                  {availableRealms.map((realm: any) => (
                    <MenuItem key={realm.id} value={realm.id}>
                      {realm.name}
                    </MenuItem>
                  ))}
                </TextField>
              </Box>

              <TextField
                label="人物简介（1-3句话）"
                multiline
                minRows={2}
                value={characterFormData?.summary || ''}
                onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, summary: e.target.value }))}
              />

              <TextField
                label="完整人物档案"
                multiline
                minRows={4}
                value={characterFormData?.profile || ''}
                onChange={(e) => setCharacterFormData((prev: any) => ({ ...prev, profile: e.target.value }))}
              />

              {/* 功法管理 */}
              <Box sx={{ mt: 2 }}>
                <Typography variant="subtitle1" sx={{ mb: 1 }}>
                  已掌握功法
                </Typography>

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 1 }}>
                  <TextField
                    select
                    label="选择功法添加"
                    size="small"
                    sx={{ minWidth: 260 }}
                    value={selectedTechniqueId}
                    onChange={(e) => {
                      const value = e.target.value;
                      setSelectedTechniqueId(value === '' ? '' : Number(value));
                    }}
                  >
                    <MenuItem value="">
                      <em>请选择功法</em>
                    </MenuItem>
                    {availableTechniques.map((t: any) => (
                      <MenuItem key={t.technique_item_id || t.id} value={t.technique_item_id || t.id}>
                        {t.technique_name || t.name}{t.technique_code ? `（${t.technique_code}）` : ''}
                      </MenuItem>
                    ))}
                  </TextField>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={handleAddTechniqueToCharacter}
                    disabled={!selectedTechniqueId}
                  >
                    添加
                  </Button>
                </Box>

                <Box sx={{ maxHeight: 260, overflowY: 'auto', border: '1px solid #eee', borderRadius: 1, p: 1 }}>
                  {characterTechniques.length === 0 && (
                    <Typography variant="body2" sx={{ color: 'text.secondary', p: 1 }}>
                      尚未为该角色添加任何功法。
                    </Typography>
                  )}

                  {characterTechniques.map((t: any, index: number) => (
                    <Box
                      key={`${t.technique_item_id}-${index}`}
                      sx={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr auto', gap: 1, alignItems: 'center', mb: 1 }}
                    >
                      <TextField
                        label="功法名称"
                        value={t.technique_name ||
                          availableTechniques.find((meta: any) =>
                            meta.technique_item_id === t.technique_item_id || meta.id === t.technique_item_id,
                          )?.technique_name || '未知功法'
                        }
                        InputProps={{ readOnly: true }}
                      />
                      <TextField
                        label="熟练度（入门/小成/大成/圆满等）"
                        value={t.proficiency || ''}
                        onChange={(e) => handleUpdateCharacterTechniqueField(index, 'proficiency', e.target.value)}
                      />
                      <TextField
                        label="学会章节"
                        type="number"
                        value={t.learned_at_chapter ?? ''}
                        onChange={(e) => {
                          const value = e.target.value
                          handleUpdateCharacterTechniqueField(index, 'learned_at_chapter', value === '' ? undefined : Number(value))
                        }}
                      />
                      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                        <TextField
                          label="备注"
                          value={t.notes || ''}
                          onChange={(e) => handleUpdateCharacterTechniqueField(index, 'notes', e.target.value)}
                          size="small"
                        />
                        <IconButton size="small" color="error" onClick={() => handleRemoveCharacterTechnique(index)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Box>
                    </Box>
                  ))}
                </Box>
              </Box>

              <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 2, mt: 2 }}>
                <Button onClick={handleCloseCharacterEditDialog} disabled={characterFormSaving}>
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveCharacterForm}
                  disabled={characterFormSaving}
                  startIcon={characterFormSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {characterFormSaving ? '保存中...' : '保存'}
                </Button>
              </Box>
            </Box>
          )}
        </Box>
      </Dialog>

      {/* 最终版本对话框 */}
      <Dialog open={showFinalVersionDialog} onClose={handleCloseFinalVersionDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            ✨ 最终版本文档
          </Typography>

          {finalVersionLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedFinalVersionContent}
                onChange={(e) => setEditedFinalVersionContent(e.target.value)}
                placeholder="最终版本文本内容..."
                sx={{ mb: 2 }}
                disabled={savingChapter}
              />

              {/* 章节标题输入框 */}
              <TextField
                fullWidth
                label="章节标题（可选）"
                placeholder="例如：冒险开始（留空则自动生成）"
                value={chapterTitleInput}
                onChange={(e) => setChapterTitleInput(e.target.value)}
                sx={{ mb: 2 }}
                disabled={savingChapter}
                helperText="如果不输入标题，系统会根据章节内容自动生成标题"
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseFinalVersionDialog}
                  disabled={savingChapter}
                >
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAsChapterFromFinalVersion}
                  disabled={savingChapter || !editedFinalVersionContent}
                  startIcon={savingChapter ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {savingChapter ? '保存中...' : '保存为章节'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 提示信息 */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={4000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <MuiAlert
          onClose={() => setSnackbarOpen(false)}
          severity={snackbarSeverity}
          sx={{ width: '100%' }}
        >
          {snackbarMessage}
        </MuiAlert>
      </Snackbar>



      {/* 🆕 扩展大纲结果对话框 */}
      <Dialog open={showExpandOutlineDialog} onClose={() => {
        console.log('🔒 关闭扩展大纲对话框...')
        console.log('   关闭前当前阶段:', workflow.currentStage)
        setShowExpandOutlineDialog(false)
        console.log('   关闭后当前阶段:', workflow.currentStage)
      }} maxWidth="lg" fullWidth>
        <Box sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6">
              📖 扩展大纲结果 - 已扩展至{currentChapterCount}章
            </Typography>

            {/* 🔥 工具栏按钮组 */}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Tooltip title="编辑大纲">
                <span>
                  <IconButton
                    onClick={handleStartEditOutline}
                    color="primary"
                    disabled={expandingOutline || !expandedOutlineData}
                  >
                    <EditIcon />
                  </IconButton>
                </span>
              </Tooltip>

              <Tooltip title="导出为 Markdown">
                <IconButton
                  onClick={handleExportOutlineMarkdown}
                  color="primary"
                  disabled={expandingOutline || !expandedOutlineData}
                >
                  <DownloadIcon />
                </IconButton>
              </Tooltip>

              <Tooltip title="导出章节为 CSV">
                <IconButton
                  onClick={handleExportChapterCSV}
                  color="primary"
                  disabled={expandingOutline || !expandedOutlineData?.chapter_breakdown}
                >
                  <DownloadIcon />
                </IconButton>
              </Tooltip>

              <Tooltip title="查看历史版本">
                <IconButton
                  onClick={() => handleShowHistory('outline')}
                  color="primary"
                >
                  <HistoryIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          {/* 🔥 进度条显示 */}
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

              {/* 🔥 扩展中占位内容 */}
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

          {!expandingOutline && expandedOutlineData && (
            <Box>
              {/* 🔥 大纲摘要（智能提取） */}
              <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1 }}>
                  📊 大纲摘要
                </Typography>
                <Box sx={{
                  bgcolor: 'background.default',
                  p: 2,
                  borderRadius: 1,
                  maxHeight: 200,
                  overflow: 'auto'
                }}>
                  <FormattedContent
                    content={(() => {
                      const outline = expandedOutlineData.expanded_outline || '';
                      // 智能提取前500字作为摘要
                      const summary = outline.substring(0, 500).trim();
                      return summary ? summary + (outline.length > 500 ? '...' : '') : '大纲内容为空';
                    })()}
                    sx={{ fontSize: '0.875rem', color: 'text.secondary' }}
                  />
                </Box>
                <Typography variant="caption" sx={{ display: 'block', mt: 1, color: 'text.disabled' }}>
                  💡 提示：完整内容请查看下方"完整扩展大纲"
                </Typography>
              </Paper>

              {/* 🔥 章节概览（可折叠） */}
              <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                    📚 章节概览（共{expandedOutlineData.current_chapter_count || expandedOutlineData.target_chapters || 0}章）
                  </Typography>
                  <Button
                    size="small"
                    onClick={() => {
                      const elem = document.getElementById('chapter-breakdown-content');
                      if (elem) {
                        elem.style.display = elem.style.display === 'none' ? 'block' : 'none';
                      }
                    }}
                  >
                    {(() => {
                      const elem = document.getElementById('chapter-breakdown-content');
                      return elem && elem.style.display === 'none' ? '展开' : '折叠';
                    })()}
                  </Button>
                </Box>
                <Box id="chapter-breakdown-content" sx={{ maxHeight: 300, overflow: 'auto' }}>
                  {/* 🔧 兼容性处理：支持字符串和数组两种格式 */}
                  {typeof expandedOutlineData.chapter_breakdown === 'string' && expandedOutlineData.chapter_breakdown ? (
                    // 渐进式扩展返回的是字符串
                    <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1 }}>
                      <FormattedContent
                        content={expandedOutlineData.chapter_breakdown}
                        sx={{ fontSize: '0.875rem' }}
                      />
                    </Box>
                  ) : Array.isArray(expandedOutlineData.chapter_breakdown) ? (
                    // 一次性扩展返回的是数组
                    expandedOutlineData.chapter_breakdown.map((chapter: any, index: number) => (
                      <Box key={index} sx={{ mb: 2, p: 1.5, bgcolor: 'background.default', borderRadius: 1, border: '1px solid', borderColor: 'divider' }}>
                        <Typography variant="body2" sx={{ fontWeight: 'bold', color: 'primary.main' }}>
                          第{chapter.chapter_number}章：{chapter.title}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mt: 0.5 }}>
                          {chapter.summary}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'text.primary', display: 'block', mt: 0.5 }}>
                          🔑 关键事件：{chapter.key_events}
                        </Typography>
                      </Box>
                    ))
                  ) : (
                    <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1, textAlign: 'center' }}>
                      <Typography variant="body2" color="text.secondary">
                        📝 章节分解内容请查看下方"完整扩展大纲"
                      </Typography>
                    </Box>
                  )}
                </Box>
              </Paper>

              {/* 🔥 完整大纲（增强版） */}
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
                        setSnackbarMessage('✅ 已复制到剪贴板');
                        setSnackbarSeverity('success');
                        setSnackbarOpen(true);
                      }}
                    >
                      📋 复制
                    </Button>
                  </Box>
                </Box>

                {/* 🔥 编辑模式切换 */}
                {isEditingExpansion ? (
                  <Box>
                    <TextField
                      fullWidth
                      multiline
                      minRows={12}
                      maxRows={20}
                      value={editedExpansionContent}
                      onChange={(e) => setEditedExpansionContent(e.target.value)}
                      sx={{
                        mb: 2,
                        bgcolor: 'background.paper',
                        '& .MuiInputBase-root': {
                          fontSize: '0.9rem',
                          lineHeight: 1.8
                        }
                      }}
                      placeholder="编辑扩展大纲..."
                    />
                    <Box sx={{ display: 'flex', gap: 1, justifyContent: 'space-between', alignItems: 'center' }}>
                      <Typography variant="caption" color="text.secondary">
                        已输入 {editedExpansionContent.length} 字
                      </Typography>
                      <Box sx={{ display: 'flex', gap: 1 }}>
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

          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              variant="contained"
              onClick={() => {
                console.log('👉 点击“关闭”按钮...')
                console.log('   关闭前当前阶段:', workflow.currentStage)
                setShowExpandOutlineDialog(false)
                console.log('   关闭后当前阶段:', workflow.currentStage)
              }}
            >
              关闭
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 🆕 扩展人物结果对话框 */}
      <Dialog open={showExpandCharactersDialog} onClose={() => setShowExpandCharactersDialog(false)} maxWidth="lg" fullWidth>
        <Box sx={{ p: 3 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
            <Typography variant="h6">
              👥 扩展人物结果 - 已扩展至{currentCharacterCount}个角色
            </Typography>

            {/* 🔥 工具栏按钮组 */}
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Tooltip title="查看历史版本">
                <IconButton
                  onClick={() => handleShowHistory('character')}
                  color="primary"
                >
                  <HistoryIcon />
                </IconButton>
              </Tooltip>
            </Box>
          </Box>

          {expandedCharactersData && (
            <Box>
              {/* 角色分布 */}
              <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1 }}>
                  📊 角色分布
                </Typography>
                {expandedCharactersData.role_distribution && typeof expandedCharactersData.role_distribution === 'object' && Object.keys(expandedCharactersData.role_distribution).length > 0 ? (
                  <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                    {Object.entries(expandedCharactersData.role_distribution).map(([role, count]: [string, any]) => (
                      <Box key={role} sx={{
                        bgcolor: 'primary.main',
                        color: 'white',
                        px: 2,
                        py: 1,
                        borderRadius: 1
                      }}>
                        <Typography variant="body2">
                          {role}: {count}人
                        </Typography>
                      </Box>
                    ))}
                  </Box>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    {typeof expandedCharactersData.role_distribution === 'string' && expandedCharactersData.role_distribution
                      ? expandedCharactersData.role_distribution
                      : '暂无角色分布数据'}
                  </Typography>
                )}
              </Paper>

              {/* 角色列表 */}
              <Paper elevation={2} sx={{ p: 2, mb: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1 }}>
                  👤 所有角色（共{expandedCharactersData.current_character_count || expandedCharactersData.target_count || 0}人）
                </Typography>
                <Box sx={{ maxHeight: 300, overflow: 'auto' }}>
                  {/* 🔧 兼容性处理：支持字符串和数组两种格式 */}
                  {typeof expandedCharactersData.all_characters === 'string' ? (
                    // 渐进式扩展返回的是字符串
                    <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1, maxHeight: 400, overflow: 'auto' }}>
                      <FormattedContent
                        content={expandedCharactersData.all_characters}
                        sx={{ fontSize: '0.875rem' }}
                      />
                    </Box>
                  ) : Array.isArray(expandedCharactersData.all_characters) ? (
                    // 一次性扩展返回的是数组
                    expandedCharactersData.all_characters.map((character: any, index: number) => (
                      <Box key={index} sx={{ mb: 2, p: 2, bgcolor: 'background.default', borderRadius: 1 }}>
                        <Typography variant="body1" sx={{ fontWeight: 'bold', mb: 0.5 }}>
                          {character.name}（{character.role}）
                        </Typography>
                        <Typography variant="body2" sx={{ color: 'text.secondary', mb: 0.5 }}>
                          {character.description}
                        </Typography>
                        <Typography variant="caption" sx={{ color: 'primary.main' }}>
                          核心特质：{character.core_traits}
                        </Typography>
                      </Box>
                    ))
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      暂无人物数据
                    </Typography>
                  )}
                </Box>
              </Paper>

              {/* 人物关系网络 */}
              <Paper elevation={2} sx={{ p: 2 }}>
                <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 1 }}>
                  🔗 人物关系网络
                </Typography>
                {expandedCharactersData.character_relationships && expandedCharactersData.character_relationships.trim() !== '' ? (
                  <Box sx={{ bgcolor: 'background.default', p: 2, borderRadius: 1, maxHeight: 400, overflow: 'auto' }}>
                    <FormattedContent
                      content={expandedCharactersData.character_relationships}
                      sx={{ fontSize: '0.875rem' }}
                    />
                  </Box>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    正在生成人物关系网络...
                  </Typography>
                )}
              </Paper>
            </Box>
          )}

          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              variant="contained"
              onClick={() => setShowExpandCharactersDialog(false)}
            >
              关闭
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 🔥 历史记录对话框 */}
      <Dialog open={showHistoryDialog} onClose={() => setShowHistoryDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon />
            <Typography variant="h6">
              {historyType === 'outline' ? '大纲扩展' : '人物扩展'}历史记录
            </Typography>
          </Box>
        </DialogTitle>

        <DialogContent dividers>
          {(() => {
            const history = historyType === 'outline' ? outlineHistory : characterHistory

            if (history.length === 0) {
              return (
                <Box sx={{ py: 4, textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    暂无历史记录
                  </Typography>
                </Box>
              )
            }

            return (
              <List>
                {history.slice().reverse().map((record, index) => {
                  const actualIndex = history.length - 1 - index
                  const count = historyType === 'outline'
                    ? (record as any).chapterCount
                    : (record as any).characterCount

                  return (
                    <ListItem
                      key={record.timestamp}
                      sx={{
                        flexDirection: 'column',
                        alignItems: 'flex-start',
                        borderBottom: index < history.length - 1 ? 1 : 0,
                        borderColor: 'divider',
                        py: 2
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', width: '100%', mb: 1 }}>
                        <Typography variant="subtitle2">
                          版本 #{actualIndex + 1} - {new Date(record.timestamp).toLocaleString()}
                        </Typography>
                        <Typography variant="caption" color="primary">
                          {historyType === 'outline' ? `${count}章` : `${count}人`}
                        </Typography>
                      </Box>

                      <TextField
                        fullWidth
                        multiline
                        maxRows={6}
                        value={record.content}
                        InputProps={{ readOnly: true }}
                        size="small"
                        sx={{ bgcolor: 'background.default' }}
                      />

                      <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
                        <Button
                          size="small"
                          startIcon={<CompareArrowsIcon />}
                          onClick={() => {
                            if (historyType === 'outline') {
                              setStructureContent(record.content)
                              setExpandedOutlineData({
                                ...expandedOutlineData,
                                expanded_outline: record.content,
                                current_chapter_count: (record as any).chapterCount
                              })
                            }
                            setSnackbarMessage(`✅ 已回滚到版本 #${actualIndex + 1}`)
                            setSnackbarSeverity('success')
                            setSnackbarOpen(true)
                            setShowHistoryDialog(false)
                          }}
                        >
                          回滚到此版本
                        </Button>

                        <Button
                          size="small"
                          onClick={() => {
                            const markdown = exportToMarkdown(
                              record.content,
                              `${historyType === 'outline' ? '大纲' : '人物'}扩展 - 版本#${actualIndex + 1}`,
                              {
                                '版本号': `#${actualIndex + 1}`,
                                '保存时间': new Date(record.timestamp).toLocaleString(),
                                [historyType === 'outline' ? '章节数' : '人物数']: count
                              }
                            )
                            downloadFile(markdown, `历史版本_${actualIndex + 1}_${record.timestamp}.md`, 'text/markdown')
                            setSnackbarMessage('✅ 已导出历史版本')
                            setSnackbarSeverity('success')
                            setSnackbarOpen(true)
                          }}
                        >
                          导出此版本
                        </Button>
                      </Box>
                    </ListItem>
                  )
                })}
              </List>
            )
          })()}
        </DialogContent>

        <DialogActions>
          <Button onClick={() => setShowHistoryDialog(false)}>
            关闭
          </Button>
          {(historyType === 'outline' ? outlineHistory : characterHistory).length > 0 && (
            <Button
              color="error"
              onClick={() => {
                if (window.confirm(`确定要清除所有${historyType === 'outline' ? '大纲' : '人物'}扩展历史记录吗？`)) {
                  clearHistory(historyType)
                  if (historyType === 'outline') {
                    setOutlineHistory([])
                  } else {
                    setCharacterHistory([])
                  }
                  setSnackbarMessage('✅ 历史记录已清除')
                  setSnackbarSeverity('success')
                  setSnackbarOpen(true)
                  setShowHistoryDialog(false)
                }
              }}
            >
              清除所有历史
            </Button>
          )}
        </DialogActions>
      </Dialog>
    </Container>
  )
}

