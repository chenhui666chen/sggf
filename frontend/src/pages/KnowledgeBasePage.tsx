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
import PeopleAltIcon from '@mui/icons-material/PeopleAlt'
import Tooltip from '@mui/material/Tooltip'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import SyncIcon from '@mui/icons-material/Sync'
import { logger } from '@/utils/logger'
import MarkdownRenderer from '@/components/MarkdownRenderer'
import VditorEditor from '@/components/VditorEditor'
import { apiClient } from '@/services/api'
import SettingTreeView from '@/components/SettingTreeView'
import SettingRecommendations from '@/components/SettingRecommendations'
import ConflictDetector from '@/components/ConflictDetector'
import RelationshipGraph from '@/components/RelationshipGraph'
import CharacterCardManager from '@/components/CharacterCardManager'
import ExpansionConfigDialog from '@/components/workflow/ExpansionConfigDialog'

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

  // 🆕 扩展人物结果弹窗状态
  const [showExpandCharactersDialog, setShowExpandCharactersDialog] = useState(false)
  const [expandCharactersResult, setExpandCharactersResult] = useState<any>(null)

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
  const [expandingOutline, setExpandingOutline] = useState(false)  // 🆕 后台任务状态
  const [targetChapterCount, setTargetChapterCount] = useState<number>(0)
  const [outlineHistory, setOutlineHistory] = useState<Array<{timestamp: number, content: string, chapterCount: number}>>([])
  const [showHistoryDialog, setShowHistoryDialog] = useState(false)
  
  // 🔥 多模式扩展状态
  const [expansionMode, setExpansionMode] = useState<'total' | 'volume' | 'incremental' | 'epic_framework' | 'volume_detail'>('total')
  const [targetVolumes] = useState<number>(3)
  const [chaptersPerVolumeMin] = useState<number>(20)
  const [chaptersPerVolumeMax] = useState<number>(30)
  const [incrementalStep, setIncrementalStep] = useState<number>(10)
  const [showExpansionConfig, setShowExpansionConfig] = useState(false)  // 显示高级配置弹窗
  
  // 🌟 史诗框架模式状态
  const [totalVolumes, setTotalVolumes] = useState<number>(30)  // 总卷数
  const [totalChaptersMin, setTotalChaptersMin] = useState<number>(2000)  // 总章节范围最小值
  const [totalChaptersMax, setTotalChaptersMax] = useState<number>(2500)  // 总章节范围最大值
  const [autoExpandAllVolumes, setAutoExpandAllVolumes] = useState<boolean>(true)  // 是否自动扩展全部卷
  
  // 🆕 单卷扩展相关
  const [savedFramework] = useState<string>('')  // 保存的史诗框架（仅读）
  const [targetVolumeIndex, setTargetVolumeIndex] = useState<number>(0)  // 扩展第几卷（0表示未选择）
  const [volumeChaptersMin, setVolumeChaptersMin] = useState<number>(50)  // 本卷章节最小值
  const [volumeChaptersMax, setVolumeChaptersMax] = useState<number>(80)  // 本卷章节最大值
  const [loadingFramework, setLoadingFramework] = useState<boolean>(false)  // 🆕 加载框架状态
  const [frameworkMetadata, setFrameworkMetadata] = useState<any>(null)  // 🆕 框架元数据
  
  // 🆕 二次确认对话框状态
  const [confirmDialogOpen, setConfirmDialogOpen] = useState(false)
  const [confirmDialogType, setConfirmDialogType] = useState<'regenerate' | 'duplicate' | null>(null)
  const [confirmDialogMessage, setConfirmDialogMessage] = useState('')
  const [pendingAction, setPendingAction] = useState<(() => void) | null>(null)
  
  // 💡 智能推荐相关状态
  const [recommendedMode, setRecommendedMode] = useState<'total' | 'epic_framework' | 'incremental'>('total')
  const [recommendedVolumes, setRecommendedVolumes] = useState(3)
  const [recommendedChaptersPerVolumeMin, setRecommendedChaptersPerVolumeMin] = useState(20)
  const [recommendedChaptersPerVolumeMax, setRecommendedChaptersPerVolumeMax] = useState(30)
  const [recommendedAutoExpandAllVolumes, setRecommendedAutoExpandAllVolumes] = useState(true)
  const [recommendationReason, setRecommendationReason] = useState('')
  
  // 🆕 扩展结果对话框状态
  const [showExpandOutlineDialog, setShowExpandOutlineDialog] = useState(false)
  const [expandOutlineResult, setExpandOutlineResult] = useState<any>(null)
  
  // 🆕 项目信息
  const [projectInfo, setProjectInfo] = useState<any>(null)

  // ==================== 人物扩展相关状态 ====================
  const [expandingCharacters, setExpandingCharacters] = useState(false)
  const [targetCharacterCount, setTargetCharacterCount] = useState<number>(0)
  
  // 🆕 人物扩展按钮状态：idle | loading | resultReady
  const [characterExpandState, setCharacterExpandState] = useState<'idle' | 'loading' | 'resultReady'>('idle')
  // 🆕 控制图标高亮动效的key（每次有新结果时+1触发动画）
  const [characterButtonHighlightKey, setCharacterButtonHighlightKey] = useState(0)
  
  // 🔢 计算当前已有人物数
  const getCurrentCharacterCount = (): number => {
    if (!characters) return 0
    // 匹配【姓名】： 关键字
    const namePattern = /【姓名】：/g
    const matches = characters.match(namePattern)
    return matches ? matches.length : 0
  }

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

    const outlineKey = `expanding_outline_${projectId}`
    const charactersKey = `expanding_characters_${projectId}`
    const outlineStartKey = `expanding_outline_start_${projectId}`
    const charactersStartKey = `expanding_characters_start_${projectId}`

    const savedOutlineState = localStorage.getItem(outlineKey)
    const savedCharactersState = localStorage.getItem(charactersKey)
    const outlineStartTime = localStorage.getItem(outlineStartKey)
    const charactersStartTime = localStorage.getItem(charactersStartKey)

    const TASK_TIMEOUT = 30 * 60 * 1000  // 30分钟超时
    const now = Date.now()

    // 检查大纲扩展任务
    if (savedOutlineState === 'true') {
      if (outlineStartTime) {
        const elapsed = now - parseInt(outlineStartTime)
        if (elapsed > TASK_TIMEOUT) {
          // 超时，清除状态
          console.warn('⚠️ 大纲扩展任务超时，已自动清除')
          localStorage.removeItem(outlineKey)
          localStorage.removeItem(outlineStartKey)
          showSnackbar('⚠️ 大纲扩展任务超时30分钟，可能已失败，请重试', 'error')
        } else {
          // 未超时，恢复状态
          setExpandingOutline(true)
          console.log('🔄 恢复大纲扩展状态：进行中')
        }
      } else {
        // 没有开始时间，恢复状态
        setExpandingOutline(true)
        console.log('🔄 恢复大纲扩展状态：进行中')
      }
    }

    // 检查人物扩展任务
    if (savedCharactersState === 'true') {
      if (charactersStartTime) {
        const elapsed = now - parseInt(charactersStartTime)
        if (elapsed > TASK_TIMEOUT) {
          // 超时，清除状态
          console.warn('⚠️ 人物扩展任务超时，已自动清除')
          localStorage.removeItem(charactersKey)
          localStorage.removeItem(charactersStartKey)
          showSnackbar('⚠️ 人物扩展任务超时30分钟，可能已失败，请重试', 'error')
        } else {
          // 未超时，恢复状态
          setExpandingCharacters(true)
          console.log('🔄 恢复人物扩展状态：进行中')
        }
      } else {
        // 没有开始时间，恢复状态
        setExpandingCharacters(true)
        console.log('🔄 恢复人物扩展状态：进行中')
      }
    }
    
    // 🆕 恢复人物扩展结果状态（如果有未查看的结果）
    const characterResultKey = `character_expand_result_${projectId}`
    const characterStateKey = `character_expand_state_${projectId}`
    
    const savedCharacterState = localStorage.getItem(characterStateKey)
    const savedCharacterResult = localStorage.getItem(characterResultKey)
    
    if (savedCharacterState === 'resultReady' && savedCharacterResult) {
      setCharacterExpandState('resultReady')
      setExpandCharactersResult(JSON.parse(savedCharacterResult))
      console.log('🔄 恢复人物扩展状态：有未查看结果')
    }
  }, [projectId])

  // 🆕 WebSocket 监听后台任务（使用统一的WebSocket服务）
  useEffect(() => {
    if (!projectId) return

    // 导入统一的 WebSocket 服务
    import('@/services/websocket').then(({ workflowWebSocket }) => {
      // 连接 WebSocket
      workflowWebSocket.connect().then(() => {
        workflowWebSocket.joinProject(parseInt(projectId))
        console.log('🔗 WebSocket 连接已建立')
      }).catch((error: any) => {
        console.error('❌ WebSocket 连接失败:', error)
        // ✅ 修复：使用函数式setState检查并清除状态
        setExpandingOutline(prev => {
          if (prev) {
            console.log('❌ WebSocket连接失败，清除大纲扩展状态')
            localStorage.removeItem(`expanding_outline_${projectId}`)
            showSnackbar('❌ 后端服务断开，大纲扩展任务已取消', 'error')
          }
          return false
        })
        setExpandingCharacters(prev => {
          if (prev) {
            console.log('❌ WebSocket连接失败，清除人物扩展状态')
            localStorage.removeItem(`expanding_characters_${projectId}`)
            showSnackbar('❌ 后端服务断开，人物扩展任务已取消', 'error')
          }
          return false
        })
      })

      // 监听任务完成
      workflowWebSocket.onTaskComplete((data: any) => {
        console.log('✅ 收到任务完成:', data)
        const taskId = data.task_id || ''
        
        // 大纲扩展完成
        if (taskId.startsWith('expand-outline')) {
          console.log('✅ 大纲扩展任务完成', data)
          showSnackbar(data.message || '✅ 大纲扩展完成！', 'success')
          
          // 🆕 显示结果弹窗（不再使用通用结果弹窗）
          setExpandOutlineResult(data.result)
          setShowExpandOutlineDialog(true)
          
          // 🔄 刷新数据（立即加载最新大纲）
          console.log('🔄 开始刷新工作流数据...')
          loadWorkflowData().then(() => {
            console.log('✅ 工作流数据刷新完成')
            console.log('📝 当前 plotOutline 长度:', plotOutline.length)
          })
          
          // ✅ 修复：使用函数式setState，避免闭包陷阱
          setExpandingOutline(prev => {
            console.log('🔄 清除扩展状态: prev =', prev, '-> false')
            return false
          })
          // 🆕 清除localStorage状态
          localStorage.removeItem(`expanding_outline_${projectId}`)
        }
        
        // 人物扩展完成
        if (taskId.startsWith('expand-characters')) {
          console.log('✅ 人物扩展任务完成', data)
          showSnackbar(data.message || '✅ 人物扩展完成！可点击「查看结果」查看AI建议', 'success')
          
          // 🆕 存储结果到 localStorage + state
          const resultData = data.result || {}
          setExpandCharactersResult(resultData)
          localStorage.setItem(`character_expand_result_${projectId}`, JSON.stringify(resultData))
          
          // 🆕 切换按钮状态为 resultReady
          setCharacterExpandState('resultReady')
          localStorage.setItem(`character_expand_state_${projectId}`, 'resultReady')
          
          // 🆕 触发一次动效
          setCharacterButtonHighlightKey(prev => prev + 1)
          
          // 刷新数据
          loadWorkflowData()
          
          // ✅ 修复：使用函数式setState，避免闭包陷阱
          setExpandingCharacters(prev => {
            console.log('🔄 清除人物扩展状态: prev =', prev, '-> false')
            return false
          })
          // 🆕 清除localStorage状态
          localStorage.removeItem(`expanding_characters_${projectId}`)
          localStorage.removeItem(`expanding_characters_start_${projectId}`)
        }
      })

      // 监听任务进度
      workflowWebSocket.onTaskProgress((data: any) => {
        const taskId = data.task_id || ''
        const message = data.message || ''
        
        if (taskId.startsWith('expand-outline') || taskId.startsWith('expand-characters')) {
          console.log(`🔄 ${message}`)
          // 可以在这里显示进度条（可选）
        }
      })

      // 监听任务错误
      workflowWebSocket.onTaskError((data: any) => {
        const taskId = data.task_id || ''
        const error = data.error || '任务失败'
        
        if (taskId.startsWith('expand-outline')) {
          showSnackbar(`❌ 大纲扩展失败: ${error}`, 'error')
          // ✅ 修复：使用函数式setState
          setExpandingOutline(prev => {
            console.log('❌ 大纲扩展失败，清除状态: prev =', prev, '-> false')
            return false
          })
          // 🆕 清除localStorage状态
          localStorage.removeItem(`expanding_outline_${projectId}`)
        }
        
        if (taskId.startsWith('expand-characters')) {
          showSnackbar(`❌ 人物扩展失败: ${error}`, 'error')
          // ✅ 修复：使用函数式setState
          setExpandingCharacters(prev => {
            console.log('❌ 人物扩展失败，清除状态: prev =', prev, '-> false')
            return false
          })
          // 🆕 清除localStorage状态
          localStorage.removeItem(`expanding_characters_${projectId}`)
        }
      })

      // 🆕 监听WebSocket断开
      workflowWebSocket.onDisconnect(() => {
        console.warn('⚠️ WebSocket 连接断开')
        // ✅ 修复：使用函数式setState检查并清除状态
        setExpandingOutline(prev => {
          if (prev) {
            console.log('⚠️ WebSocket断开，清除大纲扩展状态')
            localStorage.removeItem(`expanding_outline_${projectId}`)
            showSnackbar('❌ 后端服务断开，大纲扩展任务已取消', 'error')
          }
          return false
        })
        setExpandingCharacters(prev => {
          if (prev) {
            console.log('⚠️ WebSocket断开，清除人物扩展状态')
            localStorage.removeItem(`expanding_characters_${projectId}`)
            showSnackbar('❌ 后端服务断开，人物扩展任务已取消', 'error')
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
      setRecommendedAutoExpandAllVolumes(false)
      
      const estimatedVolumes = Math.max(5, Math.min(50, Math.ceil(maxChapters / 90)))
      setRecommendedVolumes(estimatedVolumes)
      setRecommendedChaptersPerVolumeMin(80)
      setRecommendedChaptersPerVolumeMax(100)
      
      reason = `推荐「史诗框架」：

• 题材：${projectGenre || '通用'}
• 篇幅：超长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：80-100章
• 扩展方式：手动选择扩展（分阶段创作）`
      console.log(`✅ 推荐模式：史诗框架（超长篇） - 手动选卷`)
    } else if (lengthType === 'long' || maxChapters >= 100) {
      // 长篇：史诗框架 + 根据章数决定是否自动扩展
      setRecommendedMode('epic_framework')
      
      if (maxChapters <= 500) {
        setRecommendedAutoExpandAllVolumes(true)
      } else {
        setRecommendedAutoExpandAllVolumes(false)
      }

      // 🎯 根据题材推荐卷数和每卷章数
      if (projectGenre === '修仙' || projectGenre === '玄幻') {
        const estimatedVolumes = Math.max(5, Math.min(8, Math.ceil(maxChapters / 90)))
        setRecommendedVolumes(estimatedVolumes)
        setRecommendedChaptersPerVolumeMin(80)
        setRecommendedChaptersPerVolumeMax(100)
        reason = `推荐「史诗框架」：

• 题材：${projectGenre}（境界体系）
• 篇幅：长篇（${maxChapters}章）
• 推荐卷数：${estimatedVolumes}卷
• 每卷章节：80-100章
• 扩展方式：${maxChapters <= 500 ? '自动扩展全部卷' : '手动选择扩展'}
• 适用：修炼体系分阶段推进`
        console.log(`  💫 ${projectGenre}：${estimatedVolumes}卷 × 80-100章`)
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
      setLoadingFramework(true)
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
            total_chapters_range: [totalChaptersMin, totalChaptersMax],  // 使用当前设置
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
    } finally {
      setLoadingFramework(false)
    }
  }

  // 大纲扩展主函数（🆕 异步后台执行）
  const handleExpandOutline = async () => {
    if (!projectId) return

    try {
      // 🆕 阶段1: 检测框架状态（仅针对史诗框架模式）
      if (expansionMode === 'epic_framework') {
        const response = await apiClient.getEpicFrameworkState(parseInt(projectId))
        const state = response.data
        
        // 如果已有框架且没有选择具体卷，提示重生
        if (state.has_framework && targetVolumeIndex === 0 && !autoExpandAllVolumes) {
          setConfirmDialogType('regenerate')
          setConfirmDialogMessage(
            `已存在${state.total_volumes}卷框架，重新生成将清除所有已扩展的卷细纲（${state.expanded_volumes.length}个卷）。\n\n确认要重生框架吗？`
          )
          setConfirmDialogOpen(true)
          setPendingAction(() => executeExpandOutline)
          return  // 等待用户确认
        }
        
        // 如果选择了具体卷，检查是否已有该卷细纲
        if (targetVolumeIndex > 0 && state.has_framework && state.expanded_volumes.includes(targetVolumeIndex)) {
          setConfirmDialogType('duplicate')
          setConfirmDialogMessage(
            `第${targetVolumeIndex}卷细纲已存在，重新生成将覆盖现有内容。\n\n确认要重新生成该卷吗？`
          )
          setConfirmDialogOpen(true)
          setPendingAction(() => executeExpandOutline)
          return  // 等待用户确认
        }
      }
      
      // 直接执行扩展
      await executeExpandOutline()
      
    } catch (error) {
      console.error('❌ 检测框架状态失败:', error)
      // 失败也继续执行
      await executeExpandOutline()
    }
  }

  // 🆕 实际执行扩展的函数
  const executeExpandOutline = async () => {
    if (!projectId) return

    try {
      setExpandingOutline(true)
      console.log('📖 开始扩展大纲...')
      
      // 🔥 根据模式验证参数
      let calculatedTargetChapters = targetChapterCount
      
      if (expansionMode === 'epic_framework') {
        // 🌟 史诗框架模式:验证卷数和章节范围
        if (!totalVolumes || totalVolumes < 5 || totalVolumes > 50) {
          showSnackbar('请输入有效的总卷数 (5-50)', 'error')
          setExpandingOutline(false)
          return
        }
        if (!totalChaptersMin || !totalChaptersMax || totalChaptersMin < 400 || totalChaptersMax > 5000 || totalChaptersMin > totalChaptersMax) {
          showSnackbar('请输入有效的总章节范围 (400-5000)', 'error')
          setExpandingOutline(false)
          return
        }
        console.log(`🌟 史诗框架模式: ${totalVolumes}卷, ${totalChaptersMin}-${totalChaptersMax}章`)
        
        // 🆕 如果选择了具体卷编号，验证单卷参数
        if (!autoExpandAllVolumes && targetVolumeIndex > 0) {
          if (targetVolumeIndex > (frameworkMetadata?.metadata?.total_volumes || totalVolumes)) {
            showSnackbar(`卷编号超出范围 (1-${frameworkMetadata?.metadata?.total_volumes || totalVolumes})`, 'error')
            setExpandingOutline(false)
            return
          }
          if (!volumeChaptersMin || !volumeChaptersMax || volumeChaptersMin < 30 || volumeChaptersMax > 150 || volumeChaptersMin > volumeChaptersMax) {
            showSnackbar('请输入有效的本卷章节范围 (30-150)', 'error')
            setExpandingOutline(false)
            return
          }
          console.log(`📖 将扩展第${targetVolumeIndex}卷: ${volumeChaptersMin}-${volumeChaptersMax}章`)
        }
      } else if (expansionMode === 'volume_detail') {
        // 📖 单卷详细模式:验证框架内容和卷编号
        if (!savedFramework || savedFramework.trim().length < 100) {
          showSnackbar('请先使用史诗框架模式生成框架', 'error')
          setExpandingOutline(false)
          return
        }
        if (!targetVolumeIndex || targetVolumeIndex < 1 || targetVolumeIndex > (frameworkMetadata?.total_volumes || 50)) {
          showSnackbar(`请输入有效的卷编号 (1-${frameworkMetadata?.total_volumes || 50})`, 'error')
          setExpandingOutline(false)
          return
        }
        if (!volumeChaptersMin || !volumeChaptersMax || volumeChaptersMin < 30 || volumeChaptersMax > 150 || volumeChaptersMin > volumeChaptersMax) {
          showSnackbar('请输入有效的本卷章节范围 (30-150)', 'error')
          setExpandingOutline(false)
          return
        }
        console.log(`📖 单卷详细模式: 扩展第${targetVolumeIndex}卷, ${volumeChaptersMin}-${volumeChaptersMax}章`)
      } else if (expansionMode === 'volume') {
        // 按卷模式:计算目标总章节数
        if (!targetVolumes || targetVolumes < 1 || targetVolumes > 10) {
          showSnackbar('请输入有效的目标卷数 (1-10)', 'error')
          setExpandingOutline(false)
          return
        }
        const avgChapters = Math.floor((chaptersPerVolumeMin + chaptersPerVolumeMax) / 2)
        calculatedTargetChapters = targetVolumes * avgChapters
        console.log(`📚 按卷模式: ${targetVolumes}卷 x 约${avgChapters}章 = ${calculatedTargetChapters}章`)
      } else if (expansionMode === 'incremental') {
        // 渐进式模式:当前章节数 + 增量
        const currentChapters = getCurrentChapterCount()
        if (!incrementalStep || incrementalStep < 5 || incrementalStep > 30) {
          showSnackbar('请输入有效的每次扩展章节数 (5-30)', 'error')
          setExpandingOutline(false)
          return
        }
        calculatedTargetChapters = currentChapters + incrementalStep
        console.log(`🔄 渐进式模式: ${currentChapters}章 + ${incrementalStep}章 = ${calculatedTargetChapters}章`)
      } else {
        // 按总章数模式:校验目标章节数
        if (!calculatedTargetChapters || calculatedTargetChapters < 10 || calculatedTargetChapters > 200) {
          showSnackbar('请输入有效的目标章节数 (10-200)', 'error')
          setExpandingOutline(false)
          return
        }
      }

      // 从当前阶段获取数据
      let currentOutline = plotOutline || ''
      const worldSettingData = worldSetting || ''
      const charactersData = characters || ''

      if (!currentOutline) {
        showSnackbar('⚠️ 请先完成结构设计阶段，生成情节大纲', 'error')
        setExpandingOutline(false)
        return
      }

      // 🆕 确定实际发送的扩展模式
      let actualExpansionMode = expansionMode
      
      // 如果是史诗框架模式 + 手动选卷 + 选择了具体卷编号，切换到 volume_detail 模式
      if (expansionMode === 'epic_framework' && !autoExpandAllVolumes && targetVolumeIndex > 0) {
        actualExpansionMode = 'volume_detail'
        console.log(`📖 自动切换到单卷详细模式: 第${targetVolumeIndex}卷`)
      }

      // 🆕 启动后台任务（只调用一次，立即返回）
      const increment = 10
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
          current_chapter_count: 0,  // 自动识别
          increment: increment,
          target_total_chapters: calculatedTargetChapters,  // 严格遵守目标数
          // 🔥 多模式参数
          expansion_mode: actualExpansionMode,  // 🆕 使用实际模式
          target_volumes: targetVolumes,
          chapters_per_volume_min: chaptersPerVolumeMin,
          chapters_per_volume_max: chaptersPerVolumeMax,
          incremental_step: incrementalStep,
          // 🌟 史诗框架模式参数
          total_volumes: totalVolumes,
          total_chapters_min: totalChaptersMin,
          total_chapters_max: totalChaptersMax,
          auto_expand_all_volumes: autoExpandAllVolumes,  // 🆕 是否自动扩全部卷
          // 📖 单卷详细模式参数
          framework_content: savedFramework,
          target_volume_index: targetVolumeIndex,
          volume_chapters_min: volumeChaptersMin,
          volume_chapters_max: volumeChaptersMax,
        }),
      })

      if (!response.ok) {
        throw new Error(`扩展大纲失败: ${response.status}`)
      }

      const data = await response.json()
      console.log(`✅ 后台任务已启动，Task ID: ${data.task_id}`)

      // 🆕 保存到localStorage
      localStorage.setItem(`expanding_outline_${projectId}`, 'true')
      // 🆕 记录任务开始时间
      localStorage.setItem(`expanding_outline_start_${projectId}`, Date.now().toString())

      showSnackbar('📖 大纲扩展任务已启动，正在后台执行，你可以切换到其他页面', 'success')
      
      // ✅ 保持按钮禁用状态，直到WebSocket接收到任务完成消息
      // setExpandingOutline(false) —— 已移除，由WebSocket监听器清除状态
      
    } catch (error) {
      console.error('❌ 扩展大纲失败:', error)
      showSnackbar(`扩展大纲失败: ${error}`, 'error')
      setExpandingOutline(false)
      localStorage.removeItem(`expanding_outline_start_${projectId}`)
    }
  }

  // 🆕 人物扩展主函数（异步后台执行）
  const handleExpandCharacters = async () => {
    if (!projectId) return

    try {
      setExpandingCharacters(true)
      console.log('👥 开始扩展人物...')
      
      // 🔴 校验目标人物数
      if (!targetCharacterCount || targetCharacterCount < 5 || targetCharacterCount > 50) {
        showSnackbar('请输入有效的目标人物数 (5-50)', 'error')
        setExpandingCharacters(false)
        return
      }

      const mainCharacters = characters || ''
      const worldSettingData = worldSetting || ''
      const plotOutlineData = plotOutline || ''

      if (!mainCharacters) {
        showSnackbar('⚠️ 请先完成人物设定', 'error')
        setExpandingCharacters(false)
        return
      }

      // 🆕 启动后台任务（立即返回）
      const response = await fetch('/api/v1/workflow/expand-characters', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          project_id: parseInt(projectId),
          main_characters: mainCharacters,
          world_setting: worldSettingData,
          plot_outline: plotOutlineData,
          current_character_count: 0,  // 自动识别
          target_total_characters: targetCharacterCount || 25,  // 严格遵守目标数
        }),
      })

      if (!response.ok) {
        throw new Error(`扩展人物失败: ${response.status}`)
      }

      const data = await response.json()
      console.log('✅ 后台任务已启动:', data)

      // 🆕 保存到localStorage
      localStorage.setItem(`expanding_characters_${projectId}`, 'true')
      // 🆕 记录任务开始时间
      localStorage.setItem(`expanding_characters_start_${projectId}`, Date.now().toString())

      showSnackbar('👥 人物扩展任务已启动，正在后台执行，你可以切换到其他页面', 'success')
      
      // ✅ 保持按钮禁用状态，直到WebSocket接收到任务完成消息
      // setExpandingCharacters(false) —— 已移除，由WebSocket监听器清除状态
      
    } catch (error) {
      console.error('❌ 扩展人物失败:', error)
      showSnackbar(`扩展人物失败: ${error}`, 'error')
      setExpandingCharacters(false)
      localStorage.removeItem(`expanding_characters_start_${projectId}`)
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
          onChange={(_, newValue) => setMainTabValue(newValue)}
          sx={{
            '& .MuiTab-root': {
              fontWeight: 600,
              fontSize: '1rem',
              minHeight: 56,
            }
          }}
        >
          <Tab label="🌍 世界观设定" />
          <Tab label="👥 人物设定" />
          <Tab label="📋 大纲设定" />
          <Tab label="🎨 设定中心" />
          <Tab label="⚠️ 冲突检测" />
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
                onChange={(_, newValue) => setCharacterSubTabValue(newValue)}
              >
                <Tab label="📝 人物文本" />
                <Tab label="🎴 人物卡管理" />
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
                      disabled={!getCurrentContent() || expandingCharacters || expandingOutline}
                      sx={{ borderRadius: 2 }}
                    >
                      编辑{getTabTitle()}
                    </Button>
                    
                    {/* 大纲设定扩展按钮 */}
                    {mainTabValue === 2 && (
                      <Tooltip
                        title="💡 建议扩展人物和扩展大纲交替进行，直到满意再进行后续创作，人物和大纲是后续创作的根基"
                        placement="top"
                        arrow
                      >
                        <Button
                          variant="contained"
                          startIcon={<ArticleIcon />}
                          onClick={() => {
                            // 💡 打开对话框前自动选中推荐模式
                            console.log('💡 打开大纲扩展配置，自动选中推荐模式：', recommendedMode)
                            setExpansionMode(recommendedMode)
                            
                            // 🔄 如果推荐史诗框架，同步推荐的参数
                            if (recommendedMode === 'epic_framework') {
                              setTotalVolumes(recommendedVolumes)
                              setTotalChaptersMin(recommendedVolumes * recommendedChaptersPerVolumeMin)
                              setTotalChaptersMax(recommendedVolumes * recommendedChaptersPerVolumeMax)
                              setAutoExpandAllVolumes(recommendedAutoExpandAllVolumes)
                            }
                            
                            // 🆕 始终加载框架状态（无论是否为史诗模式）
                            loadEpicFramework()
                            
                            setShowExpansionConfig(true)
                          }}
                          disabled={expandingOutline || expandingCharacters}
                          sx={{ borderRadius: 2 }}
                        >
                          扩展大纲
                        </Button>
                      </Tooltip>
                    )}
                    {mainTabValue === 1 && characterSubTabValue === 0 && (
                      <>
                        <TextField
                          label="目标人物数"
                          type="number"
                          size="small"
                          value={targetCharacterCount || ''}
                          onChange={(e) => {
                            const value = parseInt(e.target.value, 10)
                            setTargetCharacterCount(Number.isNaN(value) ? 0 : value)
                          }}
                          placeholder={`已有 ${getCurrentCharacterCount()} 个人物`}
                          inputProps={{ min: 5, max: 50 }}
                          error={targetCharacterCount > 0 && (targetCharacterCount < 5 || targetCharacterCount > 50)}
                          helperText={
                            targetCharacterCount > 0 && (targetCharacterCount < 5 || targetCharacterCount > 50)
                              ? '请输入 5-50 之间的数字'
                              : ''
                          }
                          sx={{ width: 150 }}
                        />
                        <Tooltip
                          title={
                            expandingCharacters 
                              ? "扩展进行中，请稍候" 
                              : characterExpandState === 'resultReady'
                              ? "查看AI生成的人物扩展结果与建议"
                              : "💡 建议扩展人物和扩展大纲交替进行，直到满意再进行后续创作，人物和大纲是后续创作的根基"
                          }
                          placement="top"
                          arrow
                        >
                          <span>
                            <Button
                              variant="outlined"
                              color="primary"
                              startIcon={
                                expandingCharacters 
                                  ? <CircularProgress size={20} /> 
                                  : characterExpandState === 'resultReady'
                                  ? <Box sx={{ position: 'relative', display: 'inline-flex' }}>
                                      <PeopleAltIcon />
                                      <Box
                                        sx={{
                                          position: 'absolute',
                                          top: -4,
                                          right: -4,
                                          width: 8,
                                          height: 8,
                                          borderRadius: '50%',
                                          bgcolor: '#ff5252',
                                          border: '2px solid white',
                                        }}
                                      />
                                    </Box>
                                  : <PeopleAltIcon />
                              }
                              onClick={() => {
                                if (characterExpandState === 'resultReady') {
                                  // 🆕 查看结果模式：直接打开结果弹窗
                                  setShowExpandCharactersDialog(true)
                                } else {
                                  // 🆕 正常模式：执行扩展逻辑
                                  handleExpandCharacters()
                                }
                              }}
                              disabled={expandingCharacters || expandingOutline || (characterExpandState === 'idle' && (!characters || !worldSetting || !plotOutline))}
                              sx={{ 
                                borderRadius: 2,
                                // 🆕 动效：只在状态变为 resultReady 时触发一次
                                animation: characterExpandState === 'resultReady' && characterButtonHighlightKey > 0
                                  ? 'characterButtonPulse 0.8s ease-in-out'
                                  : 'none',
                                '@keyframes characterButtonPulse': {
                                  '0%': { transform: 'scale(1)' },
                                  '30%': { transform: 'scale(1.05)' },
                                  '60%': { transform: 'scale(0.98)' },
                                  '100%': { transform: 'scale(1)' },
                                },
                              }}
                            >
                              {expandingCharacters 
                                ? '扩展中...' 
                                : characterExpandState === 'resultReady'
                                ? '🔍 查看结果'
                                : '扩展人物'
                              }
                            </Button>
                          </span>
                        </Tooltip>
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
                    </>
                  )}

                  {/* 子Tab 1: 人物卡管理 */}
                  {characterSubTabValue === 1 && (
                    <CharacterCardManager
                      projectId={Number(projectId)}
                      onCharacterUpdate={() => {
                        // 角色更新后，可以刷新其他相关数据
                        console.log('角色已更新')
                      }}
                    />
                  )}

                  {/* 已移除“扩展人物”子页；改为顶部与“编辑人物设定”并排的输入框+按钮展示，复用原有逻辑 */}
                </>
              ) : (
                // 世界观设定和大纲设定Tab的原有内容
                <>
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
                </>
              )}
            </>
          )}
        </Box>
      )}

      {/* ==================== Tab 3: 设定中心 ==================== */}
      <TabPanel value={mainTabValue} index={3}>
        {/* 子Tab导航栏 */}
        <Box sx={{ borderBottom: 1, borderColor: 'divider', mb: 3 }}>
          <Tabs
            value={settingSubTabValue}
            onChange={(_, newValue) => setSettingSubTabValue(newValue)}
          >
            <Tab label="📋 设定管理" />
            <Tab label="⭐ 热门设定" />
            <Tab label="🌐 关系网络" />
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
        )}

        {/* 子Tab 1: 热门设定 */}
        {settingSubTabValue === 1 && (
          <Box>
            <SettingRecommendations
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
          </Box>
        )}

        {/* 子Tab 2: 关系网络 */}
        {settingSubTabValue === 2 && (
          <Box>
            {selectedItem ? (
              <RelationshipGraph
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
        <ConflictDetector
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


      {/* 🆕 扩展大纲结果弹窗 */}
      <Dialog 
        open={showExpandOutlineDialog} 
        onClose={() => setShowExpandOutlineDialog(false)}
        maxWidth="md" 
        fullWidth
      >
        <DialogTitle>📖 大纲扩展结果</DialogTitle>
        <DialogContent dividers>
          {expandOutlineResult && (
            <Box>
              {/* 基本信息 */}
              <Paper elevation={2} sx={{ p: 2, mb: 2, bgcolor: 'primary.50' }}>
                {expandOutlineResult.framework_type === 'epic' ? (
                  // 🌟 史诗框架模式
                  <Box sx={{ display: 'flex', gap: 3, alignItems: 'center' }}>
                    <Box>
                      <Typography variant="caption" color="text.secondary">总卷数</Typography>
                      <Typography variant="h4" color="primary.main" sx={{ fontWeight: 'bold' }}>
                        {expandOutlineResult.total_volumes || 0}
                      </Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">预计章节</Typography>
                      <Typography variant="h4" color="success.main" sx={{ fontWeight: 'bold' }}>
                        {expandOutlineResult.estimated_chapters || 0}
                      </Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">字数</Typography>
                      <Typography variant="h6" color="text.primary">
                        {expandOutlineResult.expanded_outline?.length || 0}
                      </Typography>
                    </Box>
                  </Box>
                ) : expandOutlineResult.volume_index ? (
                  // 📖 单卷详细模式
                  <Box sx={{ display: 'flex', gap: 3, alignItems: 'center' }}>
                    <Box>
                      <Typography variant="caption" color="text.secondary">卷编号</Typography>
                      <Typography variant="h4" color="primary.main" sx={{ fontWeight: 'bold' }}>
                        第{expandOutlineResult.volume_index}卷
                      </Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">章节数</Typography>
                      <Typography variant="h4" color="success.main" sx={{ fontWeight: 'bold' }}>
                        {expandOutlineResult.chapter_count || 0}
                      </Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary">字数</Typography>
                      <Typography variant="h6" color="text.primary">
                        {expandOutlineResult.expanded_outline?.length || 0}
                      </Typography>
                    </Box>
                  </Box>
                ) : (
                  // 原有模式
                  <Box sx={{ display: 'flex', gap: 3, alignItems: 'center' }}>
                    <Box>
                      <Typography variant="caption" color="text.secondary">当前章节数</Typography>
                      <Typography variant="h4" color="primary.main" sx={{ fontWeight: 'bold' }}>
                        {expandOutlineResult.current_chapter_count || 0}
                      </Typography>
                    </Box>
                    {expandOutlineResult.target_chapter_count && (
                      <Box>
                        <Typography variant="caption" color="text.secondary">目标章节数</Typography>
                        <Typography variant="h4" color="success.main" sx={{ fontWeight: 'bold' }}>
                          {expandOutlineResult.target_chapter_count}
                        </Typography>
                      </Box>
                    )}
                    <Box>
                      <Typography variant="caption" color="text.secondary">字数</Typography>
                      <Typography variant="h6" color="text.primary">
                        {expandOutlineResult.expanded_outline?.length || 0}
                      </Typography>
                    </Box>
                  </Box>
                )}
              </Paper>

              {/* 🤖 AI建议显示 */}
              {expandOutlineResult.ai_suggestion && expandOutlineResult.ai_suggestion.reason && (
                <Box sx={{ 
                  mt: 2, 
                  p: 1.5, 
                  bgcolor: expandOutlineResult.ai_suggestion.should_continue ? 'info.50' : 'success.50', 
                  borderRadius: 1, 
                  border: '1px solid', 
                  borderColor: expandOutlineResult.ai_suggestion.should_continue ? 'info.200' : 'success.200' 
                }}>
                  <Typography variant="body2" color={expandOutlineResult.ai_suggestion.should_continue ? 'info.dark' : 'success.dark'} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <span>🤖</span>
                    <strong>AI建议：</strong>
                    {expandOutlineResult.ai_suggestion.reason}
                  </Typography>
                </Box>
              )}

              {/* 内容预览 */}
              <Paper elevation={1} sx={{ p: 2, mt: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                    📝 内容预览
                  </Typography>
                  <Button
                    size="small"
                    onClick={() => {
                      navigator.clipboard.writeText(expandOutlineResult.expanded_outline || '');
                      showSnackbar('✅ 已复制到剪贴板', 'success');
                    }}
                  >
                    📋 复制全部
                  </Button>
                </Box>
                <Box sx={{
                  maxHeight: 400,
                  overflow: 'auto',
                  p: 2,
                  bgcolor: 'background.default',
                  borderRadius: 1,
                  border: '1px solid',
                  borderColor: 'divider'
                }}>
                  <Typography 
                    component="pre" 
                    sx={{ 
                      whiteSpace: 'pre-wrap', 
                      wordBreak: 'break-word',
                      fontFamily: 'inherit',
                      margin: 0
                    }}
                  >
                    {expandOutlineResult.expanded_outline || '内容为空'}
                  </Typography>
                </Box>
              </Paper>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setShowExpandOutlineDialog(false)} variant="contained">
            关闭
          </Button>
        </DialogActions>
      </Dialog>

      {/* 🆕 扩展人物结果弹窗 */}
      <Dialog 
        open={showExpandCharactersDialog} 
        onClose={() => {
          setShowExpandCharactersDialog(false)
          // 🆕 关闭弹窗后，恢复按钮状态为 idle
          setCharacterExpandState('idle')
          localStorage.setItem(`character_expand_state_${projectId}`, 'idle')
          // 🆕 保留结果内容以便查看历史（可选）
          // localStorage.removeItem(`character_expand_result_${projectId}`)
        }}
        maxWidth="md" 
        fullWidth
      >
        <DialogTitle>👥 人物扩展结果</DialogTitle>
        <DialogContent dividers>
          {expandCharactersResult && (
            <Box>
              {/* 基本信息 */}
              <Paper elevation={2} sx={{ p: 2, mb: 2, bgcolor: 'primary.50' }}>
                <Box sx={{ display: 'flex', gap: 3, alignItems: 'center' }}>
                  <Box>
                    <Typography variant="caption" color="text.secondary">当前人物数</Typography>
                    <Typography variant="h4" color="primary.main" sx={{ fontWeight: 'bold' }}>
                      {expandCharactersResult.current_character_count || 0}
                    </Typography>
                  </Box>
                  {expandCharactersResult.target_character_count && (
                    <Box>
                      <Typography variant="caption" color="text.secondary">目标人物数</Typography>
                      <Typography variant="h4" color="success.main" sx={{ fontWeight: 'bold' }}>
                        {expandCharactersResult.target_character_count}
                      </Typography>
                    </Box>
                  )}
                  <Box>
                    <Typography variant="caption" color="text.secondary">字数</Typography>
                    <Typography variant="h6" color="text.primary">
                      {expandCharactersResult.all_characters?.length || 0}
                    </Typography>
                  </Box>
                  {expandCharactersResult.character_sync && (
                    <Box>
                      <Typography variant="caption" color="text.secondary">同步结果</Typography>
                      <Typography variant="body2" color="text.primary">
                        解析{expandCharactersResult.character_sync.parsed}个 • 
                        创建{expandCharactersResult.character_sync.created}个 • 
                        更新{expandCharactersResult.character_sync.updated}个
                      </Typography>
                    </Box>
                  )}
                </Box>
                
                {/* 🤖 AI建议显示 */}
                {expandCharactersResult.ai_suggestion && expandCharactersResult.ai_suggestion.reason && (
                  <Box sx={{ 
                    mt: 2, 
                    p: 1.5, 
                    bgcolor: expandCharactersResult.ai_suggestion.should_continue ? 'info.50' : 'success.50', 
                    borderRadius: 1, 
                    border: '1px solid', 
                    borderColor: expandCharactersResult.ai_suggestion.should_continue ? 'info.200' : 'success.200' 
                  }}>
                    <Typography variant="body2" color={expandCharactersResult.ai_suggestion.should_continue ? 'info.dark' : 'success.dark'} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <span>🤖</span>
                      <strong>AI建议：</strong>
                      {expandCharactersResult.ai_suggestion.reason}
                    </Typography>
                  </Box>
                )}
              </Paper>

              {/* 内容预览 */}
              <Paper elevation={1} sx={{ p: 2 }}>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 'bold' }}>
                    📝 内容预览
                  </Typography>
                  <Button
                    size="small"
                    onClick={() => {
                      navigator.clipboard.writeText(expandCharactersResult.all_characters || '');
                      showSnackbar('✅ 已复制到剪贴板', 'success');
                    }}
                  >
                    📋 复制全部
                  </Button>
                </Box>
                <Box sx={{
                  maxHeight: 400,
                  overflow: 'auto',
                  p: 2,
                  bgcolor: 'background.default',
                  borderRadius: 1,
                  border: '1px solid',
                  borderColor: 'divider'
                }}>
                  <Typography 
                    component="pre" 
                    sx={{ 
                      whiteSpace: 'pre-wrap', 
                      wordBreak: 'break-word',
                      fontFamily: 'inherit',
                      margin: 0
                    }}
                  >
                    {expandCharactersResult.all_characters || '内容为空'}
                  </Typography>
                </Box>
              </Paper>
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          {/* 🆕 如果AI建议继续扩展，显示“继续扩展人物”按钮 */}
          {expandCharactersResult?.ai_suggestion?.should_continue && (
            <Button 
              onClick={() => {
                setShowExpandCharactersDialog(false)
                // 恢复按钮状态
                setCharacterExpandState('idle')
                localStorage.setItem(`character_expand_state_${projectId}`, 'idle')
                // 继续扩展：再次触发扩展逻辑
                handleExpandCharacters()
              }} 
              variant="outlined"
              color="primary"
            >
              👥 继续扩展人物
            </Button>
          )}
          <Button 
            onClick={() => {
              setShowExpandCharactersDialog(false)
              setCharacterExpandState('idle')
              localStorage.setItem(`character_expand_state_${projectId}`, 'idle')
            }} 
            variant="contained"
          >
            关闭
          </Button>
        </DialogActions>
      </Dialog>

      {/* ⚙️ 扩展配置对话框 */}
      <ExpansionConfigDialog
        open={showExpansionConfig}
        onClose={() => setShowExpansionConfig(false)}
        expansionMode={expansionMode}
        targetChapterCount={targetChapterCount}
        incrementalStep={incrementalStep}
        totalVolumes={totalVolumes}
        totalChaptersMin={totalChaptersMin}
        totalChaptersMax={totalChaptersMax}
        autoExpandAllVolumes={autoExpandAllVolumes}
        frameworkMetadata={frameworkMetadata}
        loadingFramework={loadingFramework}
        onExpansionModeChange={(mode) => {
          setExpansionMode(mode)
          // 如果切换到史诗框架模式，需要加载框架
          if (mode === 'epic_framework' && !frameworkMetadata) {
            loadEpicFramework()
          }
        }}
        onTargetChapterCountChange={setTargetChapterCount}
        onIncrementalStepChange={setIncrementalStep}
        onTotalVolumesChange={setTotalVolumes}
        onTotalChaptersMinChange={setTotalChaptersMin}
        onTotalChaptersMaxChange={setTotalChaptersMax}
        onAutoExpandAllVolumesChange={setAutoExpandAllVolumes}
        targetVolumeIndex={targetVolumeIndex}
        volumeChaptersMin={volumeChaptersMin}
        volumeChaptersMax={volumeChaptersMax}
        onTargetVolumeIndexChange={setTargetVolumeIndex}
        onVolumeChaptersMinChange={setVolumeChaptersMin}
        onVolumeChaptersMaxChange={setVolumeChaptersMax}
        onConfirm={() => {
          setShowExpansionConfig(false)
          // 调用扩展函数
          handleExpandOutline()
        }}
        genre={projectInfo?.genre || ''}
        recommendedMode={recommendedMode}
        recommendedVolumes={recommendedVolumes}
        recommendedChaptersPerVolumeMin={recommendedChaptersPerVolumeMin}
        recommendedChaptersPerVolumeMax={recommendedChaptersPerVolumeMax}
        recommendedAutoExpandAllVolumes={recommendedAutoExpandAllVolumes}
        recommendationReason={recommendationReason}
      />

      {/* 🆕 二次确认对话框 */}
      <Dialog
        open={confirmDialogOpen}
        onClose={() => setConfirmDialogOpen(false)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {confirmDialogType === 'regenerate' ? '⚠️ 确认重生框架' : '⚠️ 确认重新生成'}
        </DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 2 }}>
            {confirmDialogMessage}
          </Alert>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDialogOpen(false)}>取消</Button>
          <Button
            onClick={() => {
              setConfirmDialogOpen(false)
              if (pendingAction) {
                pendingAction()
                setPendingAction(null)
              }
            }}
            variant="contained"
            color="warning"
          >
            确认继续
          </Button>
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
