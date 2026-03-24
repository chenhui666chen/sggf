import { lazy, Suspense, useEffect, useState } from 'react'
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
import Tooltip from '@mui/material/Tooltip'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import SyncIcon from '@mui/icons-material/Sync'
import { logger } from '@/utils/logger'
import { apiClient } from '@/services/api'
import FormattedContent from '@/components/common/FormattedContent'
import StoryExpansionResultDialog from '@/components/workflow/StoryExpansionResultDialog'
import {
  buildStoryExpansionCompletionMessage,
  getStoryExpansionSummary,
} from '@/utils/storyExpansionFeedback'
import type {
  StoryExpansionAnalysis,
  StoryExpansionIntent,
  StoryExpansionMode,
  StoryPreserveWrittenMode,
  StoryExpansionStrategy,
} from '@/components/workflow/StoryExpansionDialog'

const loadMarkdownRenderer = () => import('@/components/MarkdownRenderer')
const loadVditorEditor = () => import('@/components/VditorEditor')
const loadSettingTreeView = () => import('@/components/SettingTreeView')
const loadSettingRecommendations = () => import('@/components/SettingRecommendations')
const loadConflictDetector = () => import('@/components/ConflictDetector')
const loadRelationshipGraph = () => import('@/components/RelationshipGraph')
const loadCharacterCardManager = () => import('@/components/CharacterCardManager')
const loadStoryExpansionDialog = () => import('@/components/workflow/StoryExpansionDialog')

const LazyMarkdownRenderer = lazy(loadMarkdownRenderer)
const LazyVditorEditor = lazy(loadVditorEditor)
const LazySettingTreeView = lazy(loadSettingTreeView)
const LazySettingRecommendations = lazy(loadSettingRecommendations)
const LazyConflictDetector = lazy(loadConflictDetector)
const LazyRelationshipGraph = lazy(loadRelationshipGraph)
const LazyCharacterCardManager = lazy(loadCharacterCardManager)
const LazyStoryExpansionDialog = lazy(loadStoryExpansionDialog)

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

const STORY_EXPANSION_MODE_LABELS: Record<string, string> = {
  total: '常规协同',
  epic_framework: '长篇框架协同',
  volume_detail: '单卷细化协同',
}

const STORY_STRATEGY_LABELS: Record<string, string> = {
  auto: '自动协同',
  balanced: '均衡推进',
  plot_first: '剧情优先',
  character_first: '人物优先',
}

const STORY_INTENT_LABELS: Record<string, string> = {
  auto: '自动判断',
  outline_led: '大纲主导',
  character_led: '人物主导',
  balanced: '均衡协同',
}

const STORY_PRESERVE_WRITTEN_MODE_LABELS: Record<string, string> = {
  extract_extend: '提取后扩展',
  preserve_written: '仅保护正文',
  regenerate_all: '忽略已写正文',
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
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  // 主 Tab 状态 (0=世界观设定, 1=人物设定, 2=大纲设定, 3=设定中心, 4=冲突检测)
  const [mainTabValue, setMainTabValue] = useState(0)
  
  // 设定中心子 Tab 状态 (0=设定管理, 1=热门设定, 2=关系网络)
  const [settingSubTabValue, setSettingSubTabValue] = useState(0)
  
  // 人物设定子 Tab 状态 (0=人物文本, 1=人物卡管理)
  const [characterSubTabValue, setCharacterSubTabValue] = useState(0)

  // ==================== 文本内容相关状态 ====================
  const [loading, setLoading] = useState(false)  // 🔥 修复：初始值为false，避免页面初始时一直加载
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
  const [selectedCategoryItem, setSelectedCategoryItem] = useState<SettingItem | null>(null)  // 🆕 分类节点的item
  
  // 模板相关状态
  const [settingTemplates, setSettingTemplates] = useState<any[]>([])
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
  const [createChildItemDialog, setCreateChildItemDialog] = useState(false)  // 🆕 层级视图添加子项对话框
  const [parentItemPath, setParentItemPath] = useState<string>('')  // 🆕 父节点路径
  const [, setParentItemRef] = useState<any>(null)  // 🆕 父节点引用
  const [newItemIsLeaf, setNewItemIsLeaf] = useState<boolean>(true)  // 🆕 是否为叶子节点
  const [treeRefreshTrigger, setTreeRefreshTrigger] = useState<number>(0)  // 🆕 树刷新触发器
  const [moveItemDialog, setMoveItemDialog] = useState(false)  // 🆕 移动到对话框
  const [moveTargetPath, setMoveTargetPath] = useState<string>('')  // 🆕 移动目标路径

  // 表单数据
  const [newCollectionName, setNewCollectionName] = useState('')
  const [newCollectionCategory, setNewCollectionCategory] = useState('')
  const [newCollectionDescription, setNewCollectionDescription] = useState('')

  const [newItemName, setNewItemName] = useState('')
  const [newItemCode, setNewItemCode] = useState('')
  const [newItemLevel, setNewItemLevel] = useState(1)
  const [newItemContent, setNewItemContent] = useState('')
  const [newItemTags, setNewItemTags] = useState('')

  // 🆕 智能提取相关状态
  const [smartExtractLoading, setSmartExtractLoading] = useState(false)
  const [smartExtractData, setSmartExtractData] = useState<any>(null)

  // 🆕 设定同步到工作流状态
  const [syncingSettings, setSyncingSettings] = useState(false)

  // 提示消息
  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')

  // ==================== 大纲扩展相关状态 ====================
  const [expandingStory, setExpandingStory] = useState(false)
  const [showStoryExpansionDialog, setShowStoryExpansionDialog] = useState(false)
  const [showStoryExpansionResultDialog, setShowStoryExpansionResultDialog] = useState(false)
  const [storyExpansionResult, setStoryExpansionResult] = useState<any>(null)
  const [storyTargetChapterCount, setStoryTargetChapterCount] = useState<number>(0)
  const [storyTargetCharacterCount, setStoryTargetCharacterCount] = useState<number>(0)
  const [storyExpansionMode, setStoryExpansionMode] = useState<StoryExpansionMode>('total')
  const [storyTotalVolumes, setStoryTotalVolumes] = useState<number>(30)
  const [storyTotalChaptersMin, setStoryTotalChaptersMin] = useState<number>(2000)
  const [storyTotalChaptersMax, setStoryTotalChaptersMax] = useState<number>(2500)
  const [storyTargetVolumeIndex, setStoryTargetVolumeIndex] = useState<number>(0)
  const [storyVolumeChaptersMin, setStoryVolumeChaptersMin] = useState<number>(50)
  const [storyVolumeChaptersMax, setStoryVolumeChaptersMax] = useState<number>(80)
  const [storyExpansionStrategy, setStoryExpansionStrategy] = useState<StoryExpansionStrategy>('auto')
  const [storyExpansionIntent, setStoryExpansionIntent] = useState<StoryExpansionIntent>('auto')
  const [storyAutoSupplementEnabled, setStoryAutoSupplementEnabled] = useState(true)
  const [storyPreserveWrittenMode, setStoryPreserveWrittenMode] = useState<StoryPreserveWrittenMode>('extract_extend')
  const [storyExpansionAnalysis, setStoryExpansionAnalysis] = useState<StoryExpansionAnalysis | null>(null)
  const [storyExpansionAnalysisLoading, setStoryExpansionAnalysisLoading] = useState(false)
  const [outlineHistory, setOutlineHistory] = useState<Array<{timestamp: number, content: string, chapterCount: number}>>([])
  const [showHistoryDialog, setShowHistoryDialog] = useState(false)
  const [frameworkMetadata, setFrameworkMetadata] = useState<any>(null)  // 🆕 框架元数据
  const storyExpansionFeedback = getStoryExpansionSummary(storyExpansionResult)
  const storyExpansionModeLabel =
    STORY_EXPANSION_MODE_LABELS[storyExpansionResult?.story_expansion_mode || ''] ||
    storyExpansionResult?.story_expansion_mode ||
    '常规协同'
  const storyExpansionStrategyLabel =
    STORY_STRATEGY_LABELS[storyExpansionResult?.story_strategy || ''] ||
    storyExpansionResult?.story_strategy ||
    '自动协同'
  const storyExpansionIntentLabel =
    STORY_INTENT_LABELS[storyExpansionResult?.story_intent || ''] ||
    storyExpansionResult?.story_intent ||
    '自动判断'
  const storyExpansionPreserveWrittenModeLabel =
    STORY_PRESERVE_WRITTEN_MODE_LABELS[storyExpansionResult?.story_preserve_written_mode || ''] ||
    storyExpansionResult?.story_preserve_written_mode ||
    '提取后扩展'
  const storyExpansionWrittenContextLabel = storyExpansionResult?.written_chapter_context?.applied
    ? STORY_PRESERVE_WRITTEN_MODE_LABELS[
        storyExpansionResult?.written_chapter_context?.preserve_written_mode || ''
      ] || STORY_PRESERVE_WRITTEN_MODE_LABELS[storyExpansionResult?.story_preserve_written_mode || ''] ||
      storyExpansionResult?.written_chapter_context?.preserve_written_mode ||
      storyExpansionResult?.story_preserve_written_mode ||
      '提取后扩展'
    : ''
  
  // 💡 智能推荐相关状态
  const [recommendedMode, setRecommendedMode] = useState<'total' | 'epic_framework' | 'incremental'>('total')
  const [recommendedVolumes, setRecommendedVolumes] = useState(3)
  const [recommendedChaptersPerVolumeMin, setRecommendedChaptersPerVolumeMin] = useState(20)
  const [recommendedChaptersPerVolumeMax, setRecommendedChaptersPerVolumeMax] = useState(30)
  // 🗑️ 删除了 recommendedAutoExpandAllVolumes 状态
  const [recommendationReason, setRecommendationReason] = useState('')

  // 🆕 项目信息
  const [projectInfo, setProjectInfo] = useState<any>(null)

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

  // 🔢 计算当前已有人物数
  const getCurrentCharacterCount = (): number => {
    if (!characters) return 0
    // 匹配【姓名】： 关键字
    const namePattern = /【姓名】：/g
    const matches = characters.match(namePattern)
    return matches ? matches.length : 0
  }

  useEffect(() => {
    if (!projectId) return

    const legacyKeys = [
      `expanding_outline_${projectId}`,
      `expanding_outline_start_${projectId}`,
      `expanding_outline_task_${projectId}`,
      `expanding_characters_${projectId}`,
      `expanding_characters_start_${projectId}`,
      `expanding_characters_task_${projectId}`,
      `character_expand_result_${projectId}`,
      `character_expand_state_${projectId}`,
    ]

    legacyKeys.forEach((key) => localStorage.removeItem(key))
  }, [projectId])

  // 🔢 计算当前已有章节数
  const getCurrentChapterCount = (): number => {
    if (!plotOutline) return 0
    // 匹配章节标记，如 "第1章"、"第 1 章" 等
    const chapterPattern = /第\s*\d+\s*章/g
    const matches = plotOutline.match(chapterPattern)
    return matches ? matches.length : 0
  }

  // ==================== 生命周期 ====================

  // 🆕 页面加载时从localStorage恢复按钮状态
  useEffect(() => {
    if (!projectId) return

    const storyKey = `expanding_story_${projectId}`
    const storyStartKey = `expanding_story_start_${projectId}`
    const storyTaskKey = `expanding_story_task_${projectId}`

    const savedStoryState = localStorage.getItem(storyKey)
    const storyStartTime = localStorage.getItem(storyStartKey)
    const storyTaskId = localStorage.getItem(storyTaskKey)

    const TASK_TIMEOUT = 30 * 60 * 1000  // 30分钟超时
    const now = Date.now()

    if (savedStoryState === 'true') {
      if (storyStartTime) {
        const elapsed = now - parseInt(storyStartTime)
        if (elapsed > TASK_TIMEOUT) {
          localStorage.removeItem(storyKey)
          localStorage.removeItem(storyStartKey)
          localStorage.removeItem(storyTaskKey)
          showSnackbar('协同拓展任务已超时，请重新发起', 'error')
        } else {
          setExpandingStory(true)
        }
      } else {
        setExpandingStory(true)
      }
    }

    const storyResultKey = `story_expand_result_${projectId}`

    const savedStoryResult = localStorage.getItem(storyResultKey)
    if (savedStoryResult) {
      setStoryExpansionResult(JSON.parse(savedStoryResult))
    }

    let cancelled = false

    const fetchTaskStatus = async (taskId: string) => {
      const token = localStorage.getItem('access_token')
      if (!token || !taskId) return null
      try {
        const res = await fetch(`/api/v1/workflow/task/${taskId}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (!res.ok) return null
        return await res.json()
      } catch (error) {
        console.warn('?? ????????:', error)
        return null
      }
    }

    const recoverStoryIfDone = async () => {
      if (savedStoryState !== 'true' || !storyTaskId) return
      const statusData = await fetchTaskStatus(storyTaskId)
      if (!statusData || cancelled) return
      const statusRaw = String(statusData.status || '').toLowerCase()
      if (statusRaw === 'completed') {
        setExpandingStory(false)
        localStorage.removeItem(storyKey)
        localStorage.removeItem(storyStartKey)
        localStorage.removeItem(storyTaskKey)
        const resultData = statusData.result || {}
        setStoryExpansionResult(resultData)
        localStorage.setItem(storyResultKey, JSON.stringify(resultData))
        setShowStoryExpansionResultDialog(true)
        loadWorkflowData()
        const baseMessage = typeof resultData.message === 'string' && resultData.message.trim()
          ? resultData.message.trim()
          : '协同拓展已完成'
        showSnackbar(buildStoryExpansionCompletionMessage(baseMessage, resultData), 'success')
      } else if (statusRaw === 'failed' || statusRaw === 'timeout') {
        setExpandingStory(false)
        localStorage.removeItem(storyKey)
        localStorage.removeItem(storyStartKey)
        localStorage.removeItem(storyTaskKey)
        const errorMsg = statusData.error || '任务失败'
        showSnackbar(`协同拓展失败: ${errorMsg}`, 'error')
      }
    }

    void recoverStoryIfDone()

    return () => {
      cancelled = true
    }
  }, [projectId])

  // 🆕 WebSocket 监听后台任务（使用统一的WebSocket服务）
  useEffect(() => {
    if (!projectId) return

    console.log('🔌 KnowledgeBasePage: 初始化 WebSocket 监听器, projectId =', projectId)

    // 导入统一的 WebSocket 服务
    import('@/services/websocket').then(({ workflowWebSocket }) => {
      // 连接 WebSocket
      workflowWebSocket.connect().then(() => {
        workflowWebSocket.joinProject(parseInt(projectId))
        console.log('🔗 WebSocket 连接已建立, 已加入项目房间:', projectId)
      }).catch((error: any) => {
        console.error('❌ WebSocket 连接失败:', error)
        // ✅ 修复：使用函数式setState检查并清除状态
        setExpandingStory(prev => {
          if (prev) {
            localStorage.removeItem(`expanding_story_${projectId}`)
            localStorage.removeItem(`expanding_story_start_${projectId}`)
            localStorage.removeItem(`expanding_story_task_${projectId}`)
            showSnackbar('协同拓展任务已因连接中断取消', 'error')
          }
          return false
        })
      })

      // 监听任务完成
      const handleTaskComplete = (data: any) => {
        console.log('✅ 收到任务完成:', data)
        console.log('🔍 任务详情:', {
          task_id: data.task_id,
          result: data.result,
          message: data.message,
          status: data.status
        })
        const taskId = data.task_id || ''
        console.log('🔍 提取的 taskId:', taskId)
        
        // 协同拓展完成
        if (taskId.startsWith('expand-story')) {
          const resultData = data.result || {}
          setStoryExpansionResult(resultData)
          localStorage.setItem(`story_expand_result_${projectId}`, JSON.stringify(resultData))
          setShowStoryExpansionResultDialog(true)
          loadWorkflowData()
          void loadEpicFramework()
          setExpandingStory(false)
          localStorage.removeItem(`expanding_story_${projectId}`)
          localStorage.removeItem(`expanding_story_start_${projectId}`)
          localStorage.removeItem(`expanding_story_task_${projectId}`)
          const baseMessage = typeof resultData.message === 'string' && resultData.message.trim()
            ? resultData.message.trim()
            : (data.message || '协同拓展完成')
          showSnackbar(buildStoryExpansionCompletionMessage(baseMessage, resultData), 'success')
        }
      }
      
      workflowWebSocket.onTaskComplete(handleTaskComplete)
      console.log('✅ 已注册 onTaskComplete 监听器')

      // 监听任务进度
      workflowWebSocket.onTaskProgress((data: any) => {
        const taskId = data.task_id || ''
        const message = data.message || ''
        
        if (taskId.startsWith('expand-story')) {
          console.log(`🔄 ${message}`)
          // 可以在这里显示进度条（可选）
        }
      })

      // 监听任务错误
      workflowWebSocket.onTaskError((data: any) => {
        const taskId = data.task_id || ''
        const error = data.error || '任务失败'

        if (taskId.startsWith('expand-story')) {
          showSnackbar(`❌ 协同拓展失败: ${error}`, 'error')
          setExpandingStory(false)
          localStorage.removeItem(`expanding_story_${projectId}`)
          localStorage.removeItem(`expanding_story_start_${projectId}`)
          localStorage.removeItem(`expanding_story_task_${projectId}`)
        }
      })

      // 🆕 监听WebSocket断开
      workflowWebSocket.onDisconnect(() => {
        console.warn('⚠️ WebSocket 连接断开')
        // ✅ 修复：使用函数式setState检查并清除状态
        setExpandingStory(prev => {
          if (prev) {
            localStorage.removeItem(`expanding_story_${projectId}`)
            localStorage.removeItem(`expanding_story_start_${projectId}`)
            localStorage.removeItem(`expanding_story_task_${projectId}`)
            showSnackbar('❌ 后端服务断开，协同拓展任务已取消', 'error')
          }
          return false
        })
      })

      // 🆕 监听体系自动添加通知
      workflowWebSocket.onNotification((data: any) => {
        if (data.type === 'system_collections_created' && data.data?.collections) {
          const collections = data.data.collections
          const collectionNames = collections.map((c: any) => c.name).join('、')
          showSnackbar(`🎉 ${data.message}: ${collectionNames}`, 'success')
          
          // 如果当前在设定中心Tab，刷新集合列表
          if (mainTabValue === 3) {
            loadSettingCollections()
          }
        } else {
          // 通用通知显示
          showSnackbar(data.message, data.type === 'success' ? 'success' : 'error')
        }
      })
    })

    // 清理：组件卸载时移除监听器
    return () => {
      import('@/services/websocket').then(({ workflowWebSocket }) => {
        // 只移除监听器，保持 WebSocket 连接（其他页面可能还在用）
        workflowWebSocket.onTaskComplete(() => {})
        workflowWebSocket.onTaskProgress(() => {})
        workflowWebSocket.onTaskError(() => {})
        workflowWebSocket.onDisconnect(() => {})
        workflowWebSocket.onNotification(() => {})
      })
    }
  }, [projectId])

  useEffect(() => {
    if (mainTabValue <= 2) {
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

  useEffect(() => {
    preloadMainTabResources(mainTabValue)

    if (isEditing) {
      warmImport(loadVditorEditor)
    }

    if (showStoryExpansionDialog) {
      warmImport(loadStoryExpansionDialog)
    }
  }, [mainTabValue, characterSubTabValue, settingSubTabValue, isEditing, showStoryExpansionDialog])


  // 加载历史记录
  useEffect(() => {
    const historyData = getHistory('outline')
    setOutlineHistory(historyData)
  }, [])
  
  // 🆕 加载项目信息
  useEffect(() => {
    const loadProjectInfo = async () => {
      if (!projectId) return
      try {
        const response = await fetch(`/api/v1/projects/${projectId}`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })
        if (response.ok) {
          const data = await response.json()
          setProjectInfo(data)
        }
      } catch (error) {
        console.error('加载项目信息失败:', error)
      }
    }
    loadProjectInfo()
  }, [projectId])

  // 💡 智能推荐大纲扩展模式和参数
  useEffect(() => {
    if (!projectInfo) return

    const projectGenre = projectInfo.genre || ''
    const lengthType = projectInfo.planned_length_type || ''
    const maxChapters = projectInfo.planned_chapters_max || 0

    console.log('🧠 [知识库] 智能推荐大纲扩展模式：', { projectGenre, lengthType, maxChapters })

    let reason = ''

    // 📌 优先级：篇幅判断
    if (lengthType === 'short' || maxChapters < 50) {
      // 短篇：直接按总章数
      setRecommendedMode('total')
      reason = `推荐「按总章数扩展」：

• 题材：${projectGenre || '通用'}
• 篇幅：短篇（${maxChapters}章）
• 优势：快速规划，2分钟内完成
• 适用：快速验证创意，无需复杂配置`
      console.log('✅ 推荐模式：按总章数（短篇）')
    } else if (lengthType === 'epic' || maxChapters > 500) {
      // 超长篇：史诗框架 + 手动选卷
      setRecommendedMode('epic_framework')
      // 🔥 删除了智能推荐自动扩展逻辑
      
      const estimatedVolumes = Math.max(5, Math.min(50, Math.ceil(maxChapters / 90)))
      setRecommendedVolumes(estimatedVolumes)
      setRecommendedChaptersPerVolumeMin(80)
      setRecommendedChaptersPerVolumeMax(100)
      
      reason = `推荐「史诗框架」：

• 题材：${projectGenre || '通用'}
• 篇幅：超长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：60-80章（上限80章）
• 扩展方式：手动选择扩展（分阶段创作）`
      console.log(`✅ 推荐模式：史诗框架（超长篇） - 手动选卷`)
    } else if (lengthType === 'long' || maxChapters >= 100) {
      // 长篇：史诗框架 + 根据章数决定是否自动扩展
      setRecommendedMode('epic_framework')
      
      if (maxChapters <= 500) {
      // 🔥 删除了智能推荐自动扩展逻辑
      } else {
        // 🔥 删除了智能推荐自动扩展逻辑
      }

      // 🎯 根据题材推荐卷数和每卷章数
      if (projectGenre === '修仙' || projectGenre === '玄幻') {
        const estimatedVolumes = Math.max(5, Math.min(12, Math.ceil(maxChapters / 70)))  // 🌟 改为每印70章计算卷数
        setRecommendedVolumes(estimatedVolumes)
        setRecommendedChaptersPerVolumeMin(60)
        setRecommendedChaptersPerVolumeMax(80)  // 🌟 上限80章
        reason = `推荐「史诗框架」：

• 题材：${projectGenre}（境界体系）
• 篇幅：长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：60-80章（上限80章）
• 扩展方式：${maxChapters <= 500 ? '自动扩展全部卷' : '手动选择扩展'}
• 适用：修炼体系分阶段推进`
        console.log(`  💫 ${projectGenre}：${estimatedVolumes}卷 × 60-80章`)
      } else if (projectGenre === '都市') {
        const estimatedVolumes = Math.max(5, Math.min(10, Math.ceil(maxChapters / 40)))
        setRecommendedVolumes(estimatedVolumes)
        setRecommendedChaptersPerVolumeMin(30)
        setRecommendedChaptersPerVolumeMax(50)
        reason = `推荐「史诗框架」：

• 题材：都市（事业发展）
• 篇幅：长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：30-50章
• 扩展方式：${maxChapters <= 500 ? '自动扩展全部卷' : '手动选择扩展'}
• 适用：事业发展和人际关系递进`
        console.log(`  🏙️ 都市：${estimatedVolumes}卷 × 30-50章`)
      } else if (projectGenre === '悬疑') {
        const estimatedVolumes = Math.max(5, Math.min(8, Math.ceil(maxChapters / 35)))
        setRecommendedVolumes(estimatedVolumes)
        setRecommendedChaptersPerVolumeMin(20)
        setRecommendedChaptersPerVolumeMax(50)
        reason = `推荐「史诗框架」：

• 题材：悬疑（线索布局）
• 篇幅：长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：20-50章
• 扩展方式：${maxChapters <= 500 ? '自动扩展全部卷' : '手动选择扩展'}
• 适用：每卷一个大反转`
        console.log(`  🔍 悬疑：${estimatedVolumes}卷 × 20-50章`)
      } else if (projectGenre === '言情' || projectGenre === '耽美') {
        const estimatedVolumes = Math.max(5, Math.min(8, Math.ceil(maxChapters / 40)))
        setRecommendedVolumes(estimatedVolumes)
        setRecommendedChaptersPerVolumeMin(20)
        setRecommendedChaptersPerVolumeMax(60)
        reason = `推荐「史诗框架」：

• 题材：${projectGenre}（感情递进）
• 篇幅：长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：20-60章
• 扩展方式：${maxChapters <= 500 ? '自动扩展全部卷' : '手动选择扩展'}
• 适用：相识→相知→相守`
        console.log(`  💖 ${projectGenre}：${estimatedVolumes}卷 × 20-60章`)
      } else if (projectGenre === '科幻') {
        const estimatedVolumes = Math.max(5, Math.min(8, Math.ceil(maxChapters / 65)))
        setRecommendedVolumes(estimatedVolumes)
        setRecommendedChaptersPerVolumeMin(50)
        setRecommendedChaptersPerVolumeMax(80)
        reason = `推荐「史诗框架」：

• 题材：科幻（探索升级）
• 篇幅：长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：50-80章
• 扩展方式：${maxChapters <= 500 ? '自动扩展全部卷' : '手动选择扩展'}
• 适用：地球→星系→宇宙`
        console.log(`  🚀 科幻：${estimatedVolumes}卷 × 50-80章`)
      } else {
        // 通用默认：5-8卷，每卷 30-50章
        const estimatedVolumes = Math.max(5, Math.min(8, Math.ceil(maxChapters / 40)))
        setRecommendedVolumes(estimatedVolumes)
        setRecommendedChaptersPerVolumeMin(30)
        setRecommendedChaptersPerVolumeMax(50)
        reason = `推荐「史诗框架」：

• 题材：${projectGenre || '通用'}
• 篇幅：长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：30-50章
• 扩展方式：${maxChapters <= 500 ? '自动扩展全部卷' : '手动选择扩展'}`
        console.log(`  📚 通用：${estimatedVolumes}卷 × 30-50章`)
      }
      console.log(`✅ 推荐模式：史诗框架（长篇）`)
    } else {
      // 中篇：渐进式扩展
      setRecommendedMode('incremental')
      reason = `推荐「渐进式扩展」：

• 题材：${projectGenre || '通用'}
• 篇幅：中篇（${maxChapters}章）
• 优势：精细控制，随时调整
• 适用：探索性写作，多线并进`
      console.log('✅ 推荐模式：渐进式（中篇）')
    }

    setRecommendationReason(reason)
  }, [projectInfo])

  // ==================== 文本内容相关函数 ====================

  const loadWorkflowData = async () => {
    if (!projectId) return

    setLoading(true)
    setError(null)

    try {
      // 🔥 添加10秒超时控制
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), 10000)

      const response = await fetch(`/api/v1/workflow/${projectId}/all-stages-content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
        signal: controller.signal,
      })

      clearTimeout(timeoutId)

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
    } catch (err: any) {
      if (err.name === 'AbortError') {
        logger.error('❌ 加载工作流数据超时')
        setError('加载超时，请重试')
      } else {
        logger.error('❌ 加载工作流数据失败:', err)
        setError('加载失败，请重试')
      }
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
        switch (mainTabValue) {
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
    switch (mainTabValue) {
      case 0: return '世界观设定'
      case 1: return '人物设定'
      case 2: return '大纲设定'
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
    setSmartExtractData(null)  // 🆕 清空智能提取数据
    setNewItemIsLeaf(true)  // 🆕 重置为叶子节点
  }

  // 🆕 层级视图添加子项
  const handleTreeAddItem = (parentPath: string, parentItem: any) => {
    setParentItemPath(parentPath)
    setParentItemRef(parentItem)
    resetItemForm()
    setCreateChildItemDialog(true)
  }

  // 🆕 层级视图删除项（支持删除单项或整个分类）
  const handleTreeDeleteItem = async (item: any) => {
    const isLeaf = item.is_leaf
    const itemPath = item.path
    const itemName = item.name

    if (isLeaf) {
      // 删除单个叶子节点
      if (!confirm(`确定要删除「${itemName}」吗？`)) return

      try {
        await apiClient.deleteSettingItem(item.id)
        await loadSettingItems(selectedCollection!.id)
        setTreeRefreshTrigger(prev => prev + 1)  // 🆕 触发树刷新
        if (selectedItem?.id === item.id) {
          setSelectedItem(null)
        }
        showSnackbar('✅ 删除成功', 'success')
      } catch (err) {
        logger.error('❌ 删除设定项失败:', err)
        showSnackbar('删除失败', 'error')
      }
    } else {
      // 删除整个分类（批量删除该路径下的所有项）
      const itemsToDelete = settingItems.filter(it => 
        it.path && (it.path === itemPath || it.path.startsWith(itemPath + '/'))
      )
      
      if (itemsToDelete.length === 0) {
        showSnackbar('该分类下没有可删除的项', 'error')
        return
      }

      if (!confirm(`确定要删除「${itemName}」及其下的 ${itemsToDelete.length} 个项吗？\n\n此操作不可撤销！`)) return

      try {
        // 批量删除
        for (const delItem of itemsToDelete) {
          await apiClient.deleteSettingItem(delItem.id)
        }
        await loadSettingItems(selectedCollection!.id)
        setTreeRefreshTrigger(prev => prev + 1)  // 🆕 触发树刷新
        setSelectedItem(null)
        setSelectedCategoryPath(null)
        showSnackbar(`✅ 已删除 ${itemsToDelete.length} 个项`, 'success')
      } catch (err) {
        logger.error('❌ 批量删除失败:', err)
        showSnackbar('删除失败', 'error')
      }
    }
  }

  // 🆕 创建子项（来自层级视图）
  const handleCreateChildItem = async () => {
    if (!selectedCollection || !newItemName) {
      showSnackbar('请填写设定项名称', 'error')
      return
    }

    try {
      // 构建路径：父路径 + 新项名称
      const itemPath = parentItemPath ? `${parentItemPath}/${newItemName}` : `${selectedCollection.name}/${newItemName}`
      
      await apiClient.createSettingItem(selectedCollection.id, {
        name: newItemName,
        code: newItemCode,
        level: newItemLevel,
        content: newItemContent,  // 🆕 分类节点也可以有描述
        tags: newItemTags ? newItemTags.split(',').map(t => t.trim()) : [],
        order: settingItems.length,
        depth: parentItemPath ? (parentItemPath.split('/').length) : 1,
        is_leaf: newItemIsLeaf,
        path: itemPath,
      })

      await loadSettingItems(selectedCollection.id)
      setTreeRefreshTrigger(prev => prev + 1)  // 🆕 触发树刷新
      setCreateChildItemDialog(false)
      resetItemForm()
      showSnackbar(`✅ ${newItemIsLeaf ? '设定项' : '分类'}创建成功`, 'success')
    } catch (err) {
      logger.error('❌ 创建设定项失败:', err)
      showSnackbar('创建失败', 'error')
    }
  }

  // 🆕 移动节点到新的父节点下
  const handleMoveItem = async () => {
    if (!selectedItem || !selectedCollection) {
      showSnackbar('请先选择要移动的项', 'error')
      return
    }

    try {
      // 构建新路径
      const newPath = moveTargetPath 
        ? `${moveTargetPath}/${selectedItem.name}` 
        : `${selectedCollection.name}/${selectedItem.name}`
      
      // 计算新的深度
      const newDepth = moveTargetPath ? moveTargetPath.split('/').length : 1

      // 更新设定项的路径和深度
      await apiClient.updateSettingItem(selectedItem.id, {
        path: newPath,
        depth: newDepth,
      })

      // 如果是分类节点，还需要更新其所有子节点的路径
      if (!selectedItem.is_leaf) {
        const oldPath = selectedItem.path || ''
        const childItems = settingItems.filter(it => 
          it.path && it.path.startsWith(oldPath + '/')
        )
        
        for (const child of childItems) {
          const childNewPath = child.path!.replace(oldPath, newPath)
          const childNewDepth = childNewPath.split('/').length - 1
          await apiClient.updateSettingItem(child.id, {
            path: childNewPath,
            depth: childNewDepth,
          })
        }
      }

      await loadSettingItems(selectedCollection.id)
      setTreeRefreshTrigger(prev => prev + 1)
      setMoveItemDialog(false)
      setMoveTargetPath('')
      showSnackbar('✅ 移动成功', 'success')
    } catch (err) {
      logger.error('❌ 移动失败:', err)
      showSnackbar('移动失败', 'error')
    }
  }

  // 🆕 获取可用的移动目标（所有分类节点 + 根节点）
  const getAvailableMoveTargets = () => {
    if (!selectedItem || !selectedCollection) return []
    
    const targets: { path: string; label: string; depth: number }[] = [
      { path: '', label: `📁 ${selectedCollection.name}（根目录）`, depth: 0 }
    ]
    
    // 添加所有分类节点
    settingItems
      .filter(it => !it.is_leaf && it.id !== selectedItem.id)  // 排除自己
      .filter(it => !(it.path || '').startsWith((selectedItem.path || '') + '/'))  // 排除自己的子节点
      .forEach(it => {
        const depth = (it.path || '').split('/').length - 1
        const indent = '  '.repeat(depth)
        targets.push({
          path: it.path || '',
          label: `${indent}📁 ${it.name}`,
          depth,
        })
      })
    
    return targets
  }

  // 🆕 智能提取设定项相关内容
  const handleSmartExtract = async () => {
    if (!selectedItem) return

    setSmartExtractLoading(true)
    setSmartExtractData(null)

    try {
      const response = await fetch(`/api/v1/setting-items/${selectedItem.id}/smart-extract`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setSmartExtractData(data)
        showSnackbar('✅ 智能提取完成', 'success')
      } else {
        showSnackbar('提取失败', 'error')
      }
    } catch (error) {
      logger.error('智能提取失败:', error)
      showSnackbar('提取失败', 'error')
    } finally {
      setSmartExtractLoading(false)
    }
  }

  // 🆕 应用推荐的标签
  const handleApplySuggestedTags = (tags: string[]) => {
    const currentTags = newItemTags ? newItemTags.split(',').map(t => t.trim()) : []
    const mergedTags = [...new Set([...currentTags, ...tags])]
    setNewItemTags(mergedTags.join(', '))
    showSnackbar(`✅ 已添加 ${tags.length} 个标签`, 'success')
  }

  // 🆕 应用提取的内容
  const handleApplyExtractedContent = (excerpt: string) => {
    if (newItemContent) {
      setNewItemContent(`${newItemContent}\n\n---\n${excerpt}`)
    } else {
      setNewItemContent(excerpt)
    }
    showSnackbar('✅ 已追加内容', 'success')
  }

  const showSnackbar = (message: string, severity: 'success' | 'error') => {
    setSnackbarMessage(message)
    setSnackbarSeverity(severity)
    setSnackbarOpen(true)
  }

  // ==================== 大纲扩展相关函数 ====================

  // 获取历史
  const getHistory = (type: 'outline'): Array<{timestamp: number, content: string, chapterCount: number}> => {
    const key = `${type}_history`
    return JSON.parse(localStorage.getItem(key) || '[]')
  }

  // 🌟 加载史诗框架状态
  const loadEpicFramework = async () => {
    if (!projectId) return

    try {
      // 🆕 使用新的状态检测API
      const response = await apiClient.getEpicFrameworkState(parseInt(projectId))
      const data = response.data
      
      if (data.has_framework) {
        // 构造元数据对象
        setFrameworkMetadata({
          has_framework: true,
          metadata: {
            total_volumes: data.total_volumes,
            expanded_volumes: data.expanded_volumes,
            total_chapters_range: [storyTotalChaptersMin, storyTotalChaptersMax],
          },
          framework_generated_at: data.framework_generated_at
        })
        console.log('✅ 史诗框架状态加载成功:', data)
      } else {
        setFrameworkMetadata(null)
        console.log('ℹ️ 暂无史诗框架')
      }
    } catch (error) {
      console.error('❌ 加载框架状态失败:', error)
      setFrameworkMetadata(null)
    }
  }

  const loadStoryExpansionAnalysis = async () => {
    if (!projectId) return
    if (!worldSetting || (!plotOutline && !characters)) return

    setStoryExpansionAnalysisLoading(true)
    try {
      const currentChapters = getCurrentChapterCount()
      const currentCharacters = getCurrentCharacterCount()
      const requestedTargetChapters =
        storyExpansionMode === 'epic_framework'
          ? (storyTotalChaptersMax > currentChapters ? storyTotalChaptersMax : undefined)
          : (
            storyExpansionMode === 'volume_detail'
              ? undefined
              : (storyTargetChapterCount > currentChapters ? storyTargetChapterCount : undefined)
          )
      const requestedTargetCharacters =
        storyTargetCharacterCount > currentCharacters ? storyTargetCharacterCount : undefined
      const requiresEpicFrameworkReset =
        storyExpansionMode === 'total'
        && !!frameworkMetadata?.has_framework
        && requestedTargetChapters !== undefined

      const response = await fetch('/api/v1/workflow/expand-story/analysis', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          project_id: parseInt(projectId),
          current_outline: plotOutline || '',
          world_setting: worldSetting || '',
          characters: characters || '',
          current_chapter_count: currentChapters,
          current_character_count: currentCharacters,
          target_total_chapters: requestedTargetChapters,
          target_total_characters: requestedTargetCharacters,
          strategy: storyExpansionStrategy,
          intent: storyExpansionIntent,
          enable_auto_supplement: storyAutoSupplementEnabled,
          expansion_mode: storyExpansionMode,
          total_volumes: storyExpansionMode === 'epic_framework' ? storyTotalVolumes : undefined,
          total_chapters_min: storyExpansionMode === 'epic_framework' ? storyTotalChaptersMin : undefined,
          total_chapters_max: storyExpansionMode === 'epic_framework' ? storyTotalChaptersMax : undefined,
          target_volume_index: storyExpansionMode === 'volume_detail' ? storyTargetVolumeIndex : undefined,
          volume_chapters_min: storyExpansionMode === 'volume_detail' ? storyVolumeChaptersMin : undefined,
          volume_chapters_max: storyExpansionMode === 'volume_detail' ? storyVolumeChaptersMax : undefined,
          preserve_written_mode: storyPreserveWrittenMode,
          reset_epic_framework: requiresEpicFrameworkReset,
        }),
      })

      if (!response.ok) {
        throw new Error(`协同预检失败: ${response.status}`)
      }

      const data = await response.json()
      setStoryExpansionAnalysis(data?.analysis || null)
    } catch (error) {
      console.error('❌ 协同预检失败:', error)
      setStoryExpansionAnalysis(null)
    } finally {
      setStoryExpansionAnalysisLoading(false)
    }
  }

  useEffect(() => {
    if (!showStoryExpansionDialog || !projectId) return
    if (!worldSetting || (!plotOutline && !characters)) return

    void loadStoryExpansionAnalysis()
  }, [
    showStoryExpansionDialog,
    projectId,
    plotOutline,
    worldSetting,
    characters,
    storyTargetChapterCount,
    storyTargetCharacterCount,
    storyExpansionMode,
    storyTotalVolumes,
    storyTotalChaptersMin,
    storyTotalChaptersMax,
    storyTargetVolumeIndex,
    storyVolumeChaptersMin,
    storyVolumeChaptersMax,
    storyExpansionStrategy,
    storyExpansionIntent,
    storyAutoSupplementEnabled,
    storyPreserveWrittenMode,
    frameworkMetadata,
  ])

  const openStoryExpansion = (entryPoint: 'outline' | 'character' = 'outline') => {
    const currentChapters = getCurrentChapterCount()
    const currentCharacters = getCurrentCharacterCount()
    const defaultChapterTarget = currentChapters > 0 ? currentChapters + 8 : 8
    const defaultCharacterTarget = currentCharacters > 0 ? currentCharacters + 3 : 3

    setStoryExpansionStrategy('auto')
    setStoryAutoSupplementEnabled(true)
    setStoryExpansionIntent(entryPoint === 'character' ? 'character_led' : 'outline_led')
    setStoryExpansionMode(
      entryPoint === 'character'
        ? 'total'
        : (recommendedMode === 'epic_framework' ? 'epic_framework' : 'total')
    )
    setStoryTargetChapterCount(entryPoint === 'character' ? currentChapters : defaultChapterTarget)
    setStoryTargetCharacterCount(entryPoint === 'character' ? defaultCharacterTarget : currentCharacters)
    setStoryTotalVolumes((prev) => prev || (recommendedMode === 'epic_framework' ? recommendedVolumes : 30))
    setStoryTotalChaptersMin((prev) => (
      prev || (
        recommendedMode === 'epic_framework'
          ? recommendedVolumes * recommendedChaptersPerVolumeMin
          : 2000
      )
    ))
    setStoryTotalChaptersMax((prev) => (
      prev || (
        recommendedMode === 'epic_framework'
          ? recommendedVolumes * recommendedChaptersPerVolumeMax
          : 2500
      )
    ))
    setStoryTargetVolumeIndex((prev) => prev || 1)
    setStoryVolumeChaptersMin((prev) => prev || 50)
    setStoryVolumeChaptersMax((prev) => prev || 80)
    if (!frameworkMetadata) {
      void loadEpicFramework()
    }
    setStoryExpansionAnalysis(null)
    setShowStoryExpansionDialog(true)
  }

  const handleExpandStory = async () => {
    if (!projectId) return

    try {
      const currentChapters = getCurrentChapterCount()
      const currentCharacters = getCurrentCharacterCount()
      const requestedTargetChapterCount =
        storyExpansionMode === 'epic_framework'
          ? storyTotalChaptersMax
          : (storyExpansionMode === 'volume_detail' ? undefined : storyTargetChapterCount)
      const chapterDelta = (requestedTargetChapterCount ?? currentChapters) - currentChapters
      const characterDelta = storyTargetCharacterCount - currentCharacters
      const requiresEpicFrameworkReset =
        storyExpansionMode === 'total'
        && !!frameworkMetadata?.has_framework
        && chapterDelta > 0

      if (!worldSetting || (!plotOutline && !characters)) {
        showSnackbar('请先准备好世界观和情节大纲，再执行协同拓展', 'error')
        return
      }

      const isVolumeDetailMode = storyExpansionMode === 'volume_detail'
      if (!isVolumeDetailMode && chapterDelta <= 0 && characterDelta <= 0) {
        showSnackbar('目标章节数或目标人物数至少要有一项高于当前值', 'error')
        return
      }

      if (storyExpansionMode === 'epic_framework') {
        if (!storyTotalVolumes || storyTotalVolumes < 5 || storyTotalVolumes > 50) {
          showSnackbar('长篇框架协同需要有效的总卷数 (5-50)', 'error')
          return
        }
        if (
          !storyTotalChaptersMin ||
          !storyTotalChaptersMax ||
          storyTotalChaptersMin < 400 ||
          storyTotalChaptersMax > 5000 ||
          storyTotalChaptersMin > storyTotalChaptersMax
        ) {
          showSnackbar('长篇框架协同需要有效的总章节范围 (400-5000)', 'error')
          return
        }
      }

      if (isVolumeDetailMode) {
        if (!frameworkMetadata?.has_framework) {
          showSnackbar('单卷细化协同需要先生成史诗框架', 'error')
          return
        }
        if (
          !storyTargetVolumeIndex ||
          storyTargetVolumeIndex < 1 ||
          storyTargetVolumeIndex > (frameworkMetadata.metadata?.total_volumes || 50)
        ) {
          showSnackbar(`请输入有效的卷编号 (1-${frameworkMetadata.metadata?.total_volumes || 50})`, 'error')
          return
        }
        if (
          !storyVolumeChaptersMin ||
          !storyVolumeChaptersMax ||
          storyVolumeChaptersMin < 30 ||
          storyVolumeChaptersMax > 80 ||
          storyVolumeChaptersMin > storyVolumeChaptersMax
        ) {
          showSnackbar('请输入有效的本卷章节范围 (30-80)', 'error')
          return
        }
        if (frameworkMetadata.metadata?.expanded_volumes?.includes(storyTargetVolumeIndex)) {
          const confirmed = confirm(`第${storyTargetVolumeIndex}卷细纲已存在，重新协同生成将覆盖现有细纲。\n\n确认继续吗？`)
          if (!confirmed) {
            return
          }
        }
      }

      if ((requestedTargetChapterCount || 0) > Math.max(5000, currentChapters)) {
        showSnackbar('协同拓展当前目标超出章节规划上限，请缩小目标范围', 'error')
        return
      }

      if (storyTargetCharacterCount > Math.max(200, currentCharacters)) {
        showSnackbar('协同拓展当前目标超出人物规划上限，请缩小目标范围', 'error')
        return
      }

      if (requiresEpicFrameworkReset) {
        const confirmed = confirm(
          '当前项目已存在史诗框架与卷细纲。\n\n继续使用“常规协同”补章节会清空旧框架状态，后续将以新的章节大纲为准。\n\n确认继续吗？'
        )
        if (!confirmed) {
          return
        }
      }

      localStorage.removeItem(`story_expand_result_${projectId}`)
      setStoryExpansionResult(null)
      setExpandingStory(true)
      setShowStoryExpansionDialog(false)

      const effectiveTargetChapterCount =
        storyExpansionAnalysis?.effective_target_chapter_count &&
        storyExpansionAnalysis.effective_target_chapter_count > currentChapters
          ? storyExpansionAnalysis.effective_target_chapter_count
          : (isVolumeDetailMode
            ? undefined
            : (chapterDelta > 0 ? requestedTargetChapterCount : undefined))
      const effectiveTargetCharacterCount =
        storyExpansionAnalysis?.effective_target_character_count &&
        storyExpansionAnalysis.effective_target_character_count > currentCharacters
          ? storyExpansionAnalysis.effective_target_character_count
          : (characterDelta > 0 ? storyTargetCharacterCount : undefined)
      const effectiveStrategy =
        (storyExpansionAnalysis?.effective_strategy as StoryExpansionStrategy | undefined) || storyExpansionStrategy

      const payload = {
        project_id: parseInt(projectId),
        current_outline: plotOutline || '',
        world_setting: worldSetting || '',
        characters: characters || '',
        current_chapter_count: currentChapters,
        current_character_count: currentCharacters,
        target_total_chapters: effectiveTargetChapterCount,
        target_total_characters: effectiveTargetCharacterCount,
        strategy: effectiveStrategy,
        intent: storyExpansionIntent,
        enable_auto_supplement: storyAutoSupplementEnabled,
        expansion_mode: storyExpansionMode,
        total_volumes: storyExpansionMode === 'epic_framework' ? storyTotalVolumes : undefined,
        total_chapters_min: storyExpansionMode === 'epic_framework' ? storyTotalChaptersMin : undefined,
        total_chapters_max: storyExpansionMode === 'epic_framework' ? storyTotalChaptersMax : undefined,
        target_volume_index: storyExpansionMode === 'volume_detail' ? storyTargetVolumeIndex : undefined,
        volume_chapters_min: storyExpansionMode === 'volume_detail' ? storyVolumeChaptersMin : undefined,
        volume_chapters_max: storyExpansionMode === 'volume_detail' ? storyVolumeChaptersMax : undefined,
        preserve_written_mode: storyPreserveWrittenMode,
        reset_epic_framework: requiresEpicFrameworkReset,
      }

      const response = await fetch('/api/v1/workflow/expand-story', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })

      if (!response.ok) {
        throw new Error(`协同拓展失败: ${response.status}`)
      }

      const data = await response.json()
      if (data?.task_id) {
        localStorage.setItem(`expanding_story_task_${projectId}`, String(data.task_id))
      } else {
        localStorage.removeItem(`expanding_story_task_${projectId}`)
      }

      localStorage.setItem(`expanding_story_${projectId}`, 'true')
      localStorage.setItem(`expanding_story_start_${projectId}`, Date.now().toString())
      showSnackbar('协同拓展任务已启动，正在后台执行', 'success')
    } catch (error) {
      console.error('❌ 协同拓展失败:', error)
      showSnackbar(`协同拓展失败: ${error}`, 'error')
      setExpandingStory(false)
      localStorage.removeItem(`expanding_story_${projectId}`)
      localStorage.removeItem(`expanding_story_start_${projectId}`)
      localStorage.removeItem(`expanding_story_task_${projectId}`)
    }
  }

  // ==================== 辅助函数 ====================

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
      showSnackbar(`✅ 已添加「${collectionName}」`, 'success')
      setSelectedCategoryToAdd('')
    } catch (err) {
      logger.error('✅ 快速添加体系失败:', err)
      showSnackbar('添加体系失败', 'error')
    }
  }

  // 🆕 同步设定到工作流
  const handleSyncSettingsToWorkflow = async () => {
    if (!projectId) return

    setSyncingSettings(true)
    try {
      const response = await fetch(`/api/v1/projects/${projectId}/sync-settings-to-workflow`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        showSnackbar(`✅ ${data.message}`, 'success')
        // 刷新工作流数据
        loadWorkflowData()
      } else {
        showSnackbar('同步失败，请重试', 'error')
      }
    } catch (err) {
      logger.error('❗ 同步设定到工作流失败:', err)
      showSnackbar('同步失败，请重试', 'error')
    } finally {
      setSyncingSettings(false)
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
          返回
        </Button>
        <Alert severity="info" sx={{ flex: 1, mx: 3, py: 0.5 }} icon={false}>
          📚 此页面展示工作流生成的设定数据，编辑后将同步到工作流中
        </Alert>
        <Typography variant="h5" sx={{
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 1
        }}>
          🌍 知识库
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
          <Tab label="🌍 世界观设定" onMouseEnter={() => preloadMainTabResources(0)} onFocus={() => preloadMainTabResources(0)} />
          <Tab label="👥 人物设定" onMouseEnter={() => preloadMainTabResources(1)} onFocus={() => preloadMainTabResources(1)} />
          <Tab label="📋 大纲设定" onMouseEnter={() => preloadMainTabResources(2)} onFocus={() => preloadMainTabResources(2)} />
          <Tab label="🎨 设定中心" onMouseEnter={() => preloadMainTabResources(3)} onFocus={() => preloadMainTabResources(3)} />
          <Tab label="⚠️ 冲突检测" onMouseEnter={() => preloadMainTabResources(4)} onFocus={() => preloadMainTabResources(4)} />
        </Tabs>
      </Box>

      {/* ==================== Tab 0-2: 世界观/人物/大纲 ==================== */}
      {mainTabValue <= 2 && (
        <Box>
          {/* 🆕 人物设定Tab添加二级导航 */}
          {mainTabValue === 1 && (
            <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
              <Tabs
                value={characterSubTabValue}
                onChange={(_, newValue) => { preloadCharacterTabResources(newValue); setCharacterSubTabValue(newValue) }}
              >
                <Tab label="📝 人物文本" onMouseEnter={() => preloadCharacterTabResources(0)} onFocus={() => preloadCharacterTabResources(0)} />
                <Tab label="🎴 人物卡管理" onMouseEnter={() => preloadCharacterTabResources(1)} onFocus={() => preloadCharacterTabResources(1)} />
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
                重试
              </Button>
            </Alert>
          )}

          {!loading && !error && (
            <>
              {/* 🆕 只在非人物Tab或人物文本子Tab显示操作按钮 */}
              {(mainTabValue !== 1 || characterSubTabValue === 0) && (
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
                      编辑{getTabTitle()}
                    </Button>
                    {(mainTabValue === 2 || (mainTabValue === 1 && characterSubTabValue === 0)) && (
                      <>
                        <Tooltip
                          title={recommendationReason || '协同拓展会同时分析章节缺口和人物缺口，只补新增内容，不会整本重写'}
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
                              onClick={() => openStoryExpansion(mainTabValue === 1 ? 'character' : 'outline')}
                              disabled={expandingStory || !worldSetting || (!plotOutline && !characters)}
                              sx={{
                                borderRadius: 2,
                                bgcolor: '#0f766e',
                                '&:hover': {
                                  bgcolor: '#115e59',
                                },
                              }}
                            >
                              {expandingStory ? '协同拓展中...' : '协同拓展'}
                            </Button>
                          </span>
                        </Tooltip>
                        {storyExpansionResult && !expandingStory && (
                          <Button
                            variant="text"
                            onClick={() => setShowStoryExpansionResultDialog(true)}
                            sx={{ borderRadius: 2 }}
                          >
                            查看协同结果
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
              )}

              {/* 🆕 根据人物子Tab显示不同内容 */}
              {mainTabValue === 1 ? (
                <>
                  {/* 子Tab 0: 人物文本 */}
                  {characterSubTabValue === 0 && (
                    <>
                      {isEditing ? (
                        <Suspense fallback={<LazySectionFallback minHeight={500} />}>
                          <LazyVditorEditor
                          value={editedContent}
                          onChange={(val) => setEditedContent(val)}
                          placeholder={`${getTabTitle()}内容（支持 Markdown 格式）...`}
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
                              📭 暂无{getTabTitle()}，请先在工作流中生成
                            </Typography>
                          )}
                        </Paper>
                      )}
                    </>
                  )}

                  {/* 子Tab 1: 人物卡管理 */}
                  {characterSubTabValue === 1 && (
                    <Suspense fallback={<LazySectionFallback minHeight={360} />}>
                      <LazyCharacterCardManager
                      projectId={Number(projectId)}
                      onCharacterUpdate={() => {
                        // 角色更新后，可以刷新其他相关数据
                        console.log('角色已更新')
                      }}
                      />
                    </Suspense>
                  )}

                  {/* 已移除“扩展人物”子页；改为顶部与“编辑人物设定”并排的输入框+按钮展示，复用原有逻辑 */}
                </>
              ) : (
                // 世界观设定和大纲设定Tab的原有内容
                <>
                  {isEditing ? (
                <Suspense fallback={<LazySectionFallback minHeight={500} />}>
                  <LazyVditorEditor
                  value={editedContent}
                  onChange={(val) => setEditedContent(val)}
                  placeholder={`${getTabTitle()}内容（支持 Markdown 格式）...`}
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
                      📭 暂无{getTabTitle()}，请先在工作流中生成
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

      {/* ==================== Tab 3: 设定中心 ==================== */}
      <TabPanel value={mainTabValue} index={3}>
        {/* Tab 3 Nav */}
        <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
          <Tabs
            value={settingSubTabValue}
            onChange={(_, newValue) => { preloadSettingTabResources(newValue); setSettingSubTabValue(newValue) }}
          >
            <Tab label={'\u8bbe\u5b9a\u7ba1\u7406'} onMouseEnter={() => preloadSettingTabResources(0)} onFocus={() => preloadSettingTabResources(0)} />
            <Tab label={'\u70ed\u95e8\u8bbe\u5b9a'} onMouseEnter={() => preloadSettingTabResources(1)} onFocus={() => preloadSettingTabResources(1)} />
            <Tab label={'\u5173\u7cfb\u7f51\u7edc'} onMouseEnter={() => preloadSettingTabResources(2)} onFocus={() => preloadSettingTabResources(2)} />
          </Tabs>
        </Box>

        {/* 子Tab 0: 设定管理 */}
        {settingSubTabValue === 0 && (
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
                  
                  {/* 🆕 同步到工作流按钮 */}
                  <Tooltip
                    title="将所有设定同步到工作流的世界观设定字段，供AI生成内容时参考"
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
                        {syncingSettings ? '同步中...' : '同步到工作流'}
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
                      <Suspense fallback={<LazySectionFallback minHeight={360} />}>
                        <LazySettingTreeView
                        collectionId={selectedCollection.id}
                        selectedItemId={selectedItem?.id}
                        refreshTrigger={treeRefreshTrigger}
                        onSelectCategory={(path, categoryItem) => {
                          setSelectedCategoryPath(path)
                          setSelectedCategoryItem(categoryItem)  // 🆕 保存分类节点的item
                          setSelectedItem(null)
                        }}
                        onSelectInstance={(item) => {
                          setSelectedItem(item)
                          setSelectedCategoryPath(null)
                        }}
                        onAddItem={handleTreeAddItem}
                        onDeleteItem={handleTreeDeleteItem}
                        title="层级视图"
                        />
                      </Suspense>
                    </Box>

                    {/* 右：详情/列表（根据选择切换） */}
                    <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                      {/* 🆕 分类描述区域 - 选中分类时显示 */}
                      {!selectedItem && selectedCategoryPath && selectedCategoryItem && (
                        <Box sx={{ p: 2, bgcolor: 'primary.50', borderRadius: 1, mb: 2, border: '1px solid', borderColor: 'primary.200' }}>
                          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <FolderIcon sx={{ color: 'primary.main' }} />
                              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                {selectedCategoryItem.name}
                              </Typography>
                              <Chip label="分类" size="small" color="primary" variant="outlined" />
                            </Box>
                            <Box sx={{ display: 'flex', gap: 0.5 }}>
                              <Tooltip title="编辑分类描述">
                                <Button size="small" startIcon={<EditIcon />} onClick={() => {
                                  // 将分类设为当前编辑项
                                  setSelectedItem(selectedCategoryItem)
                                  handleEditItem()
                                }}>
                                  编辑
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
                              点击“编辑”添加分类描述...
                            </Typography>
                          )}
                          <Typography variant="caption" color="text.secondary">
                            路径: {selectedCategoryPath}
                          </Typography>
                        </Box>
                      )}

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
                            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                              <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                                {selectedItem.name}
                              </Typography>
                              {!selectedItem.is_leaf && (
                                <Chip label="分类" size="small" color="primary" variant="outlined" />
                              )}
                            </Box>
                            <Box sx={{ display: 'flex', gap: 0.5 }}>
                              <Tooltip title="移动到其他分类">
                                <Button size="small" onClick={() => setMoveItemDialog(true)}>
                                  移动到
                                </Button>
                              </Tooltip>
                              <Button size="small" startIcon={<EditIcon />} onClick={handleEditItem}>
                                编辑
                              </Button>
                            </Box>
                          </Box>
                          {selectedItem.path && (
                            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                              路径: {selectedItem.path}
                            </Typography>
                          )}
                          {selectedItem.content ? (
                            <FormattedContent 
                              content={selectedItem.content} 
                              sx={{ color: 'text.secondary', fontSize: '0.875rem' }} 
                            />
                          ) : (
                            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                              点击“编辑”添加内容描述...
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
        )}

        {/* 子Tab 1: 热门设定 */}
        {settingSubTabValue === 1 && (
          <Box>
            <Suspense fallback={<LazySectionFallback minHeight={320} />}>
              <LazySettingRecommendations
              projectId={Number(projectId)}
              limit={50}
              showInsertButton={false}
              onSelectItem={(item) => {
                // 跳转到设定管理子Tab
                setSettingSubTabValue(0)
                // 查找对应的集合
                const collection = collections.find(c => c.id === item.collection_id)
                if (collection) {
                  setSelectedCollection(collection)
                  // 加载该集合的设定项
                  loadSettingItems(collection.id).then(() => {
                    // 查找并选中该设定项（从 settingItems 中获取完整对象）
                    const fullItem = settingItems.find(i => i.id === item.id)
                    if (fullItem) {
                      setSelectedItem(fullItem)
                      // 如果有路径，也设置路径以便树形视图高亮
                      if (fullItem.path) {
                        const pathParts = fullItem.path.split('/')
                        if (pathParts.length > 1) {
                          setSelectedCategoryPath(pathParts.slice(0, -1).join('/'))
                        }
                      }
                    }
                  })
                }
              }}
              title="热门设定"
              />
            </Suspense>
          </Box>
        )}

        {/* 子Tab 2: 关系网络 */}
        {settingSubTabValue === 2 && (
          <Box>
            {selectedItem ? (
              <Suspense fallback={<LazySectionFallback minHeight={360} />}>
                <LazyRelationshipGraph
                itemId={selectedItem.id}
                itemName={selectedItem.name}
                onNodeClick={(nodeId) => {
                  // 跳转到设定管理子Tab
                  setSettingSubTabValue(0)
                  // 查找该节点对应的设定项
                  const item = settingItems.find(i => i.id === nodeId)
                  if (item) {
                    setSelectedItem(item)
                    // 如果需要，也查找对应的集合
                    const collection = collections.find(c => c.id === item.collection_id)
                    if (collection) {
                      setSelectedCollection(collection)
                      loadSettingItems(collection.id)
                    }
                  }
                }}
                />
              </Suspense>
            ) : (
              <Alert severity="info" sx={{ mt: 2 }}>
                请先在"设定管理"中选择一个设定项，以查看其关系网络图
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
            // 跳转到设定中心Tab并查找该设定项
            setMainTabValue(3)
            setSettingSubTabValue(0)  // 切换到设定管理子Tab
            // 查找该设定项并选中
            const item = settingItems.find(i => i.id === itemId)
            if (item) {
              // 先找到对应的集合
              const collection = collections.find(c => c.id === item.collection_id)
              if (collection) {
                setSelectedCollection(collection)
                // 加载该集合的设定项
                loadSettingItems(collection.id).then(() => {
                  setSelectedItem(item)
                  // 如果有路径，也设置路径以便树形视图高亮
                  if (item.path) {
                    const pathParts = item.path.split('/')
                    if (pathParts.length > 1) {
                      setSelectedCategoryPath(pathParts.slice(0, -1).join('/'))
                    }
                  }
                })
              }
            }
          }}
          title="设定冲突检测"
          />
        </Suspense>
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

      {/* 🆕 层级视图创建子项对话框 */}
      <Dialog open={createChildItemDialog} onClose={() => setCreateChildItemDialog(false)} maxWidth="md" fullWidth>
        <DialogTitle>
          添加{newItemIsLeaf ? '设定项' : '分类'}
          {parentItemPath && (
            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              路径: {parentItemPath}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent>
          <Grid container spacing={2}>
            {/* 类型选择 */}
            <Grid item xs={12}>
              <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                <Chip
                  label="📄 设定项"
                  color={newItemIsLeaf ? 'primary' : 'default'}
                  variant={newItemIsLeaf ? 'filled' : 'outlined'}
                  onClick={() => setNewItemIsLeaf(true)}
                  sx={{ cursor: 'pointer' }}
                />
                <Chip
                  label="📁 分类（文件夹）"
                  color={!newItemIsLeaf ? 'primary' : 'default'}
                  variant={!newItemIsLeaf ? 'filled' : 'outlined'}
                  onClick={() => setNewItemIsLeaf(false)}
                  sx={{ cursor: 'pointer' }}
                />
              </Box>
              <Typography variant="caption" color="text.secondary">
                {newItemIsLeaf ? '设定项是叶子节点，包含具体的设定内容' : '分类是文件夹节点，用于组织其他设定项'}
              </Typography>
            </Grid>
            <Grid item xs={8}>
              <TextField
                autoFocus
                margin="dense"
                label={newItemIsLeaf ? '设定项名称 *' : '分类名称 *'}
                fullWidth
                value={newItemName}
                onChange={(e) => setNewItemName(e.target.value)}
                placeholder={newItemIsLeaf ? '例如: 灶气期、绍沙城、砚红仙千' : '例如: 修炼境界、地点分类'}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label="代码"
                fullWidth
                value={newItemCode}
                onChange={(e) => setNewItemCode(e.target.value)}
                placeholder="可选"
              />
            </Grid>
            {newItemIsLeaf && (
              <Grid item xs={12}>
                <TextField
                  margin="dense"
                  label="标签（逗号分隔）"
                  fullWidth
                  value={newItemTags}
                  onChange={(e) => setNewItemTags(e.target.value)}
                  placeholder="例如: 修炼境界, 初期"
                />
              </Grid>
            )}
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label={newItemIsLeaf ? '内容描述' : '分类描述（可选）'}
                fullWidth
                multiline
                rows={newItemIsLeaf ? 6 : 3}
                value={newItemContent}
                onChange={(e) => setNewItemContent(e.target.value)}
                placeholder={newItemIsLeaf ? '详细描述该设定项的内容...' : '可以为这个分类添加说明文字...'}
              />
            </Grid>
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setCreateChildItemDialog(false); resetItemForm() }}>取消</Button>
          <Button onClick={handleCreateChildItem} variant="contained">创建{newItemIsLeaf ? '设定项' : '分类'}</Button>
        </DialogActions>
      </Dialog>

      {/* 🆕 移动到对话框 */}
      <Dialog open={moveItemDialog} onClose={() => setMoveItemDialog(false)} maxWidth="sm" fullWidth>
        <DialogTitle>
          移动到其他分类
          {selectedItem && (
            <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
              移动: {selectedItem.name}
            </Typography>
          )}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            选择目标分类，该项将被移动到指定分类下。这对于调整层级关系很有用。
          </Typography>
          <FormControl fullWidth margin="dense">
            <InputLabel>目标分类</InputLabel>
            <Select
              value={moveTargetPath}
              label="目标分类"
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
              新路径将为: {moveTargetPath}/{selectedItem.name}
            </Alert>
          )}
          {selectedItem && moveTargetPath === '' && selectedCollection && (
            <Alert severity="info" sx={{ mt: 2 }}>
              新路径将为: {selectedCollection.name}/{selectedItem.name}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setMoveItemDialog(false); setMoveTargetPath('') }}>取消</Button>
          <Button onClick={handleMoveItem} variant="contained">移动</Button>
        </DialogActions>
      </Dialog>

      {/* 编辑设定项对话框 - 🆕 添加智能提取面板 */}
      <Dialog open={editItemDialog} onClose={() => setEditItemDialog(false)} maxWidth="lg" fullWidth>
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          编辑设定项
          <Button
            variant="outlined"
            size="small"
            startIcon={smartExtractLoading ? <CircularProgress size={16} /> : <AutoFixHighIcon />}
            onClick={handleSmartExtract}
            disabled={smartExtractLoading}
          >
            {smartExtractLoading ? '提取中...' : '智能提取'}
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
                    🧠 AI智能提取结果
                  </Typography>

                  {/* 推荐标签 */}
                  {smartExtractData.suggested_tags?.length > 0 && (
                    <Box sx={{ mb: 2 }}>
                      <Typography variant="caption" color="text.secondary">推荐标签</Typography>
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
                            label="全部添加"
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
                    从章节中提取的相关内容 ({smartExtractData.related_contents?.length || 0}条)
                  </Typography>
                  <Box sx={{ mt: 1, maxHeight: 300, overflow: 'auto' }}>
                    {smartExtractData.related_contents?.length > 0 ? (
                      smartExtractData.related_contents.map((content: any, idx: number) => (
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
                              第{content.chapter_number}章 《{content.chapter_title}》
                              {content.ai_validated && (
                                <Chip label="AI验证" size="small" color="success" sx={{ ml: 1, height: 18 }} />
                              )}
                            </Typography>
                            <Button
                              size="small"
                              onClick={() => handleApplyExtractedContent(content.excerpt)}
                            >
                              追加
                            </Button>
                          </Box>
                          <Typography variant="body2" sx={{ fontSize: '0.85rem', color: 'text.primary' }}>
                            {content.excerpt}
                          </Typography>
                        </Paper>
                      ))
                    ) : (
                      <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>
                        未找到相关内容
                      </Typography>
                    )}
                  </Box>
                </Paper>
              </Grid>
            )}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => { setEditItemDialog(false); resetItemForm() }}>取消</Button>
          <Button onClick={handleSaveItemEdit} variant="contained">保存</Button>
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
                    {(record.content || '').substring(0, 200)}...
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

      <StoryExpansionResultDialog
        open={showStoryExpansionResultDialog}
        result={storyExpansionResult}
        expansionModeLabel={storyExpansionModeLabel}
        strategyLabel={storyExpansionStrategyLabel}
        intentLabel={storyExpansionIntentLabel}
        preserveWrittenModeLabel={storyExpansionPreserveWrittenModeLabel}
        writtenContextLabel={storyExpansionWrittenContextLabel}
        summary={storyExpansionFeedback}
        onClose={() => setShowStoryExpansionResultDialog(false)}
        onCopied={(message) => showSnackbar(message, 'success')}
      />

      {showStoryExpansionDialog && (
        <Suspense fallback={null}>
          <LazyStoryExpansionDialog
            open={showStoryExpansionDialog}
            loading={expandingStory}
            analysisLoading={storyExpansionAnalysisLoading}
            currentChapterCount={getCurrentChapterCount()}
            currentCharacterCount={getCurrentCharacterCount()}
            targetChapterCount={storyTargetChapterCount}
            targetCharacterCount={storyTargetCharacterCount}
            expansionMode={storyExpansionMode}
            totalVolumes={storyTotalVolumes}
            totalChaptersMin={storyTotalChaptersMin}
            totalChaptersMax={storyTotalChaptersMax}
            strategy={storyExpansionStrategy}
            intent={storyExpansionIntent}
            autoSupplementEnabled={storyAutoSupplementEnabled}
            preserveWrittenMode={storyPreserveWrittenMode}
            analysis={storyExpansionAnalysis}
            onClose={() => setShowStoryExpansionDialog(false)}
            onTargetChapterCountChange={setStoryTargetChapterCount}
            onTargetCharacterCountChange={setStoryTargetCharacterCount}
            onExpansionModeChange={(mode) => {
              setStoryExpansionMode(mode)
              if ((mode === 'epic_framework' || mode === 'volume_detail') && !frameworkMetadata) {
                void loadEpicFramework()
              }
            }}
            onTotalVolumesChange={setStoryTotalVolumes}
            onTotalChaptersMinChange={setStoryTotalChaptersMin}
            onTotalChaptersMaxChange={setStoryTotalChaptersMax}
            frameworkMetadata={frameworkMetadata}
            targetVolumeIndex={storyTargetVolumeIndex}
            volumeChaptersMin={storyVolumeChaptersMin}
            volumeChaptersMax={storyVolumeChaptersMax}
            onTargetVolumeIndexChange={setStoryTargetVolumeIndex}
            onVolumeChaptersMinChange={setStoryVolumeChaptersMin}
            onVolumeChaptersMaxChange={setStoryVolumeChaptersMax}
            onStrategyChange={setStoryExpansionStrategy}
            onIntentChange={setStoryExpansionIntent}
            onAutoSupplementChange={setStoryAutoSupplementEnabled}
            onPreserveWrittenModeChange={setStoryPreserveWrittenMode}
            onConfirm={handleExpandStory}
          />
        </Suspense>
      )}

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
