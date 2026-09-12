/**
 * 人物卡管理组件
 * 用于结构化管理角色信息（基础信息、境界、功法等）
 */
import { useState, useEffect } from 'react'
import {
  Box,
  Button,
  Typography,
  List,
  ListItem,
  IconButton,
  Chip,
  CircularProgress,
  Tooltip,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  MenuItem,
  Grid,
  Snackbar,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import HistoryIcon from '@mui/icons-material/History'
import CloseIcon from '@mui/icons-material/Close'
import SyncIcon from '@mui/icons-material/Sync'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import ReactFlow, {
  Background,
  Controls,
  MiniMap,
  useNodesState,
  useEdgesState,
  Node,
  Edge,
} from 'reactflow'
import 'reactflow/dist/style.css'
import {
  buildCharacterRelationsPayload,
  parseCharacterRelations,
} from '@/utils/characterRelations'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { useTranslation } from 'react-i18next'

interface CharacterCardManagerProps {
  projectId: number
  onCharacterUpdate?: () => void
}

const EMPTY_CHARACTER_FORM = {
  name: '',
  role: '',
  role_position: '',
  faction: '',
  importance_level: '',
}

// value 为表单提交值（发后端，不可翻译），labelKey 驱动 UI 显示
const STORY_STANCE_OPTIONS: { value: string; label: string; labelKey: string }[] = [
  { value: '主角方', label: '主角方', labelKey: 'characterCard.stanceProtagonist' },
  { value: '反派方', label: '反派方', labelKey: 'characterCard.stanceAntagonist' },
  { value: '中立方', label: '中立方', labelKey: 'characterCard.stanceNeutral' },
  { value: '亦正亦邪', label: '亦正亦邪', labelKey: 'characterCard.stanceGray' },
]
const IMPORTANCE_OPTIONS: { value: string; label: string; labelKey: string }[] = [
  { value: '主角', label: '主角', labelKey: 'characterCard.importanceLead' },
  { value: '核心角色', label: '核心角色', labelKey: 'characterCard.importanceCore' },
  { value: '重要角色', label: '重要角色', labelKey: 'characterCard.importanceImportant' },
  { value: '次要角色', label: '次要角色', labelKey: 'characterCard.importanceMinor' },
  { value: '边缘角色', label: '边缘角色', labelKey: 'characterCard.importanceEdge' },
  { value: '群众角色', label: '群众角色', labelKey: 'characterCard.importanceExtra' },
]

export default function CharacterCardManager({ projectId, onCharacterUpdate }: CharacterCardManagerProps) {
  const { t } = useTranslation()
  const [characters, setCharacters] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editingCharacter, setEditingCharacter] = useState<any | null>(null)
  const [formData, setFormData] = useState<any>({})
  const [availableRealms, setAvailableRealms] = useState<any[]>([])
  
  // 出场历程时间线状态
  const [timelineDialogOpen, setTimelineDialogOpen] = useState(false)
  const [timelineData, setTimelineData] = useState<any>(null)
  const [timelineLoading, setTimelineLoading] = useState(false)

  // 自动追踪关联状态
  const [autoTrackedData, setAutoTrackedData] = useState<any>(null)
  const [autoTrackedLoading, setAutoTrackedLoading] = useState(false)

  // 功法管理状态
  const [characterTechniques, setCharacterTechniques] = useState<any[]>([])
  const [availableTechniques, setAvailableTechniques] = useState<any[]>([])
  const [selectedTechniqueId, setSelectedTechniqueId] = useState<number | ''>('')
  const [saving, setSaving] = useState(false)

  // 🆕 同步到工作流状态
  const [syncDialogOpen, setSyncDialogOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [syncPreview, setSyncPreview] = useState<any>(null)
  const [syncPreviewLoading, setSyncPreviewLoading] = useState(false)

  // 🆕 Snackbar 状态
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' }>({ open: false, message: '', severity: 'success' })

  // 🆕 关系图状态
  const [graphDialogOpen, setGraphDialogOpen] = useState(false)
  const [graphLoading, setGraphLoading] = useState(false)
  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])
  const [graphStats, setGraphStats] = useState<{ total_nodes: number; total_edges: number }>({ total_nodes: 0, total_edges: 0 })
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)  // 🆕 选中的节点ID
  const [allEdges, setAllEdges] = useState<Edge[]>([])  // 🆕 存储所有边的备份

  // 🆕 人物关系管理状态
  const [characterRelations, setCharacterRelations] = useState<any[]>([])
  const [newRelationTarget, setNewRelationTarget] = useState('')
  const [newRelationType, setNewRelationType] = useState('')

  // 加载角色列表
  const loadCharacters = async () => {
    setLoading(true)
    try {
      const response = await apiClient.getCharacters(projectId)
      setCharacters(response.data || [])
    } catch {
      // 加载角色列表失败
    } finally {
      setLoading(false)
    }
  }

  // 加载可用境界列表（用于境界选择）
  const loadAvailableRealms = async () => {
    try {
      // 境界体系的category列表
      const realmCategories = [
        'cultivation_realm_system',  // 修仙境界
        'magic_realm_system',        // 魔法境界
        'martial_realm_system',      // 武道境界
        'ability_realm_system',      // 异能境界
      ]

      // 1. 获取项目所有设定集合
      const collectionsRes = await apiClient.getSettingCollections(projectId)
      const collections = collectionsRes.data || []

      // 2. 筛选境界体系集合
      const realmCollections = collections.filter((c: any) =>
        realmCategories.includes(c.category)
      )

      // 3. 获取所有境界项
      const realmItems: any[] = []
      for (const collection of realmCollections) {
        const itemsRes = await apiClient.getSettingItems(collection.id)
        const items = itemsRes.data || []
        // 添加集合信息，便于显示分组
        items.forEach((item: any) => {
          item.collectionName = collection.name
        })
        realmItems.push(...items)
      }

      setAvailableRealms(realmItems)
    } catch {
      setAvailableRealms([])
    }
  }

  useEffect(() => {
    loadCharacters()
    loadAvailableRealms()
    loadAvailableTechniques()
  }, [projectId])

  // 加载可用功法列表
  const loadAvailableTechniques = async () => {
    try {
      const response = await apiClient.getProjectTechniques(projectId)
      setAvailableTechniques(response.data || [])
    } catch {
      // 加载功法列表失败
    }
  }

  // 加载角色功法列表
  const loadCharacterTechniques = async (characterId: number) => {
    try {
      const response = await apiClient.getCharacterTechniques(characterId)
      setCharacterTechniques(response.data || [])
    } catch {
      // 加载角色功法失败
    }
  }

  // 加载自动追踪关联数据
  const loadAutoTrackedData = async (characterId: number) => {
    setAutoTrackedLoading(true)
    try {
      const response = await apiClient.getCharacterAutoTrackedRelations(characterId)
      setAutoTrackedData(response.data)
    } catch {
      // 加载自动追踪数据失败
    } finally {
      setAutoTrackedLoading(false)
    }
  }

  // 打开编辑对话框
  const handleOpenEditDialog = async (character?: any) => {
    try {
      if (character) {
        setEditingCharacter(character)
        setFormData(character)
        // 加载自动追踪数据
        loadAutoTrackedData(character.id)
        // 加载角色功法
        loadCharacterTechniques(character.id)
        // 🆕 加载人物关系
        setCharacterRelations(parseCharacterRelations(character.relations))
      } else {
        setEditingCharacter(null)
        setFormData({ ...EMPTY_CHARACTER_FORM })
        setAutoTrackedData(null)
        setCharacterTechniques([])
        setCharacterRelations([])
      }
      setSelectedTechniqueId('')
      setNewRelationTarget('')
      setNewRelationType('')
      setEditDialogOpen(true)
    } catch {
      setSnackbar({ open: true, message: t('characterCard.page.openEditFailed'), severity: 'error' })
    }
  }

  // 关闭编辑对话框
  const handleCloseEditDialog = () => {
    setEditDialogOpen(false)
    setEditingCharacter(null)
    setFormData({ ...EMPTY_CHARACTER_FORM })
    setAutoTrackedData(null)
    setCharacterTechniques([])
    setSelectedTechniqueId('')
    setCharacterRelations([])
    setNewRelationTarget('')
    setNewRelationType('')
  }

  // 🆕 添加人物关系
  const handleAddRelation = () => {
    if (!newRelationTarget || !newRelationType) return
    // 检查是否已存在
    if (characterRelations.some((r: any) => r.target === newRelationTarget && r.type === newRelationType)) {
      setSnackbar({ open: true, message: t('characterCard.page.relationExists'), severity: 'error' })
      return
    }
    setCharacterRelations((prev) => [
      ...prev,
      { target: newRelationTarget, type: newRelationType }
    ])
    setNewRelationTarget('')
    setNewRelationType('')
  }

  // 🆕 删除人物关系
  const handleRemoveRelation = (index: number) => {
    setCharacterRelations((prev) => prev.filter((_, i) => i !== index))
  }

  // 添加功法到角色
  const handleAddTechnique = () => {
    if (!selectedTechniqueId) return
    // 检查是否已添加
    if (characterTechniques.some((t: any) => t.technique_item_id === selectedTechniqueId)) {
      return
    }
    const technique = availableTechniques.find((t: any) => 
      (t.technique_item_id || t.id) === selectedTechniqueId
    )
    if (technique) {
      setCharacterTechniques((prev) => [
        ...prev,
        {
          technique_item_id: selectedTechniqueId,
          technique_name: technique.technique_name || technique.name,
          proficiency: '',
          learned_at_chapter: null,
          notes: '',
        },
      ])
      setSelectedTechniqueId('')
    }
  }

  // 移除功法
  const handleRemoveTechnique = (index: number) => {
    setCharacterTechniques((prev) => prev.filter((_, i) => i !== index))
  }

  // 更新功法字段
  const handleUpdateTechniqueField = (index: number, field: string, value: any) => {
    setCharacterTechniques((prev) => {
      const next = [...prev]
      next[index] = { ...next[index], [field]: value }
      return next
    })
  }

  // 保存角色
  const handleSaveCharacter = async () => {
    setSaving(true)
    try {
      const dataToSave = {
        ...formData,
        relations: buildCharacterRelationsPayload(characterRelations),
      }
      
      let savedCharacter = dataToSave

      const response = editingCharacter
        ? await apiClient.updateCharacter(editingCharacter.id, dataToSave)
        : await apiClient.createCharacter(projectId, dataToSave)

      savedCharacter = response.data

      // 保存功法列表（覆盖式）
      if (savedCharacter.id) {
        const techniquesPayload = {
          techniques: characterTechniques.map((t: any) => ({
            technique_item_id: t.technique_item_id,
            proficiency: t.proficiency || null,
            learned_at_chapter: t.learned_at_chapter ?? null,
            notes: t.notes || null,
          })),
        }
        await apiClient.updateCharacterTechniques(savedCharacter.id, techniquesPayload)
      }

      await loadCharacters()
      handleCloseEditDialog()
      onCharacterUpdate?.()
      setSnackbar({ open: true, message: t('characterCard.page.saveSuccess'), severity: 'success' })
    } catch {
      setSnackbar({ open: true, message: t('characterCard.page.saveFailed'), severity: 'error' })
    } finally {
      setSaving(false)
    }
  }

  // 删除角色
  const handleDeleteCharacter = async (characterId: number) => {
    if (!confirm(t('characterCard.page.deleteConfirm'))) return

    try {
      await apiClient.deleteCharacter(characterId)
      await loadCharacters()
      onCharacterUpdate?.()
    } catch {
      // 删除角色失败
    }
  }

  // 加载出场历程时间线
  const handleLoadTimeline = async (character: any) => {
    setTimelineLoading(true)
    setTimelineDialogOpen(true)
    setTimelineData(null)
    
    try {
      const response = await apiClient.getCharacterAppearanceTimeline(character.id)
      setTimelineData(response.data)
    } catch {
      // 加载出场历程失败
    } finally {
      setTimelineLoading(false)
    }
  }

  // 🆕 打开同步对话框并加载预览
  const handleOpenSyncDialog = async () => {
    setSyncDialogOpen(true)
    setSyncPreviewLoading(true)
    setSyncPreview(null)
    
    try {
      const response = await apiClient.getCharactersTextPreview(projectId)
      setSyncPreview(response.data)
    } catch {
      // 加载预览失败
    } finally {
      setSyncPreviewLoading(false)
    }
  }

  // 🆕 执行同步
  const handleSyncToWorkflow = async () => {
    setSyncing(true)
    
    try {
      const response = await apiClient.syncCharactersToWorkflow(projectId)
      const data = response.data
      setSnackbar({ open: true, message: `✅ ${data.message}`, severity: 'success' })
      setSyncDialogOpen(false)
      onCharacterUpdate?.()
    } catch (error) {
      setSnackbar({
        open: true,
        message: await extractApiErrorMessage(error, t('characterCard.page.syncFailed')),
        severity: 'error',
      })
    } finally {
      setSyncing(false)
    }
  }

  // 🆕 加载关系图数据
  const handleOpenGraphDialog = async () => {
    setGraphDialogOpen(true)
    setGraphLoading(true)
    
    try {
      const response = await apiClient.getCharacterRelationshipGraph(projectId)
      const data = response.data
        
      // 转换为 React Flow 格式
      // 🔧 优化：使用多层级布局算法防止节点重叠
      
      // 1. 构建BFS邻接表
      const adjacency = new Map<string, Set<string>>()
      data.nodes.forEach((node: any) => adjacency.set(node.id, new Set()))
      data.edges.forEach((edge: any) => {
        adjacency.get(edge.source)?.add(edge.target)
        adjacency.get(edge.target)?.add(edge.source)
      })
      
      // 2. BFS计算每个节点的层级（以度最高的节点为中心）
      const centerNode = data.nodes.reduce((max: any, node: any) => {
        const degree = (adjacency.get(node.id)?.size || 0)
        return degree > (adjacency.get(max?.id)?.size || 0) ? node : max
      }, data.nodes[0])
      
      const nodeLevels = new Map<string, number>()
      nodeLevels.set(centerNode.id, 0)
      
      const queue = [centerNode.id]
      const visited = new Set([centerNode.id])
      
      while (queue.length > 0) {
        const current = queue.shift()!
        const currentLevel = nodeLevels.get(current)!
        
        adjacency.get(current)?.forEach(neighbor => {
          if (!visited.has(neighbor)) {
            visited.add(neighbor)
            nodeLevels.set(neighbor, currentLevel + 1)
            queue.push(neighbor)
          }
        })
      }
      
      // 3. 按层级分组
      const nodesByLevel = new Map<number, any[]>()
      data.nodes.forEach((node: any) => {
        const level = nodeLevels.get(node.id) ?? 3
        if (!nodesByLevel.has(level)) nodesByLevel.set(level, [])
        nodesByLevel.get(level)!.push(node)
      })
      
      // 4. 布局参数
      const centerX = 400
      const centerY = 300
      const baseRadius = 220
      const radiusIncrement = 250
      const minNodeSpacing = 180
      
      // 5. 计算节点位置
      const flowNodes: Node[] = data.nodes.map((node: any) => {
        const isCenter = node.id === centerNode.id
        const level = nodeLevels.get(node.id) ?? 3
        
        let x = centerX
        let y = centerY
        
        if (!isCenter) {
          const levelNodes = nodesByLevel.get(level) || []
          const nodeIndex = levelNodes.findIndex((n: any) => n.id === node.id)
          const nodesInLevel = levelNodes.length
          
          const requiredCircumference = nodesInLevel * minNodeSpacing
          const minRequiredRadius = requiredCircumference / (2 * Math.PI)
          const radius = Math.max(baseRadius + (level - 1) * radiusIncrement, minRequiredRadius)
          
          const angleOffset = (level % 2) * (Math.PI / Math.max(nodesInLevel, 1))
          const angle = (nodeIndex * 2 * Math.PI) / nodesInLevel + angleOffset
          
          x = centerX + radius * Math.cos(angle)
          y = centerY + radius * Math.sin(angle)
        }
        
        return {
          id: node.id,
          position: { x, y },
          data: {
            label: (
              <Box sx={{ textAlign: 'center', p: 0.5, cursor: 'pointer' }}>
                <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                  {node.name}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {node.importance}
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', color: 'primary.main', fontSize: 10 }}>
                  {t('characterCard.graph.filterHint')}
                </Typography>
              </Box>
            ),
            characterId: node.character_id,  // 🆕 储存人物ID
            characterName: node.name,
          },
          style: {
            background: node.color || 'var(--sg-bg-paper)',
            border: `2px solid ${node.borderColor || 'var(--sg-border-strong)'}`,
            borderRadius: 8,
            padding: 8,
            minWidth: 80,
            cursor: 'pointer',
          },
        }
      })
      
      const flowEdges: Edge[] = data.edges.map((edge: any) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
        label: edge.label,
        type: 'smoothstep',
        animated: false,
        style: { stroke: 'var(--sg-text-disabled)' },
        labelStyle: { fontSize: 10, fill: 'var(--sg-text-secondary)' },
      }))
      
      setNodes(flowNodes)
      setAllEdges(flowEdges)  // 🆕 存储全部边
      setEdges(flowEdges)
      setSelectedNodeId(null)  // 🆕 重置选中状态
      setGraphStats(data.stats)
    } catch {
      // 加载关系图失败
    } finally {
      setGraphLoading(false)
    }
  }

  // 🆕 节点点击处理 - 过滤显示关系线
  const handleNodeClick = (_event: React.MouseEvent, node: Node) => {
    const nodeId = node.id
    
    // 如果点击的是已选中节点，则取消选中，显示所有边
    if (selectedNodeId === nodeId) {
      setSelectedNodeId(null)
      setEdges(allEdges.map(edge => ({
        ...edge,
        animated: false,
        style: { stroke: 'var(--sg-text-disabled)' },
      })))
      // 恢复所有节点样式
      setNodes(prevNodes => prevNodes.map(n => ({
        ...n,
        style: {
          ...n.style,
          opacity: 1,
        },
      })))
    } else {
      // 选中节点，只显示相关边
      setSelectedNodeId(nodeId)
      
      // 过滤边：只显示与该节点直接相关的边
      const filteredEdges = allEdges.map(edge => {
        const isRelated = edge.source === nodeId || edge.target === nodeId
        return {
          ...edge,
          animated: isRelated,
          style: {
            stroke: isRelated ? 'var(--sg-accent)' : 'var(--sg-divider)',
            strokeWidth: isRelated ? 2 : 1,
          },
        }
      })
      setEdges(filteredEdges)
      
      // 高亮相关节点，淡化其他节点
      const relatedNodeIds = new Set<string>([nodeId])
      allEdges.forEach(edge => {
        if (edge.source === nodeId) relatedNodeIds.add(edge.target)
        if (edge.target === nodeId) relatedNodeIds.add(edge.source)
      })
      
      setNodes(prevNodes => prevNodes.map(n => ({
        ...n,
        style: {
          ...n.style,
          opacity: relatedNodeIds.has(n.id) ? 1 : 0.3,
        },
      })))
    }
  }

  return (
    <Box>
      {/* 顶部操作栏 */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6">{t('characterCard.page.title')}</Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Tooltip title={t('characterCard.page.graphTooltip')}>
            <span>
              <Button
                variant="outlined"
                color="secondary"
                startIcon={<AccountTreeIcon />}
                onClick={handleOpenGraphDialog}
                disabled={characters.length === 0}
              >
                {t('characterCard.page.graphBtn')}
              </Button>
            </span>
          </Tooltip>
          <Tooltip title={t('characterCard.page.syncTooltip')}>
            <span>
              <Button
                variant="outlined"
                color="primary"
                startIcon={syncing ? <CircularProgress size={20} /> : <SyncIcon />}
                onClick={handleOpenSyncDialog}
                disabled={characters.length === 0 || syncing}
              >
                {t('characterCard.page.syncToWorkflow')}
              </Button>
            </span>
          </Tooltip>
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => handleOpenEditDialog()}
          >
            {t('characterCard.page.newCharacter')}
          </Button>
        </Box>
      </Box>

      {/* 使用说明 */}
      <Alert severity="info" sx={{ mb: 2 }}>
        {t('characterCard.page.usageHint')}
      </Alert>

      {/* 角色列表 */}
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <List sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 1, maxHeight: 500, overflowY: 'auto' }}>
          {characters.length === 0 ? (
            <Box sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>
              {t('characterCard.page.emptyHint')}
            </Box>
          ) : (
            characters.map((character) => (
              <ListItem
                key={character.id}
                secondaryAction={
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Tooltip title={t('characterCard.page.timelineTooltip')}>
                      <IconButton size="small" onClick={() => handleLoadTimeline(character)}>
                        <HistoryIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t('characterCard.page.editTooltip')}>
                      <IconButton size="small" onClick={() => handleOpenEditDialog(character)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title={t('common.delete')}>
                      <IconButton size="small" onClick={() => handleDeleteCharacter(character.id)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                }
                sx={{ borderBottom: '1px solid', borderBottomColor: 'divider', py: 2 }}
              >
                <Box sx={{ display: 'flex', flexDirection: 'column', flex: 1, gap: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                      {character.name}
                    </Typography>
                    {character.gender && (
                      <Chip size="small" label={character.gender} variant="outlined" />
                    )}
                    {character.age && (
                      <Chip size="small" label={t('characterCard.page.ageChip', { count: character.age })} variant="outlined" />
                    )}
                  </Box>
                  
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    {character.role && <Chip size="small" label={character.role} color="primary" />}
                    {character.role_position && (
                      <Chip size="small" label={character.role_position} variant="outlined" />
                    )}
                    {character.faction && <Chip size="small" label={character.faction} />}
                    {character.importance_level && (
                      <Chip size="small" label={character.importance_level} color="secondary" />
                    )}
                    {character.current_realm_item_id && (
                      <Chip
                        size="small"
                        color="warning"
                        label={
                          availableRealms.find((r: any) => r.id === character.current_realm_item_id)?.name ||
                          t('characterCard.page.realmFallback')
                        }
                      />
                    )}
                    {character.appearance_status && (
                      <Chip size="small" label={character.appearance_status} variant="outlined" />
                    )}
                    {character.life_status && (
                      <Chip 
                        size="small" 
                        label={character.life_status}
                        color={character.life_status === '存活' ? 'success' : character.life_status === '死亡' ? 'error' : 'default'}
                        variant="outlined"
                      />
                    )}
                  </Box>

                  {character.summary && (
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                      {character.summary}
                    </Typography>
                  )}
                </Box>
              </ListItem>
            ))
          )}
        </List>
      )}

      {/* 编辑对话框 */}
      <Dialog open={editDialogOpen} onClose={handleCloseEditDialog} maxWidth="md" fullWidth>
        <DialogTitle>{editingCharacter ? t('characterCard.page.editCharacter') : t('characterCard.page.newCharacter')}</DialogTitle>
        <DialogContent>
          <Grid container spacing={2}>
            {/* 第一行：姓名 + 故事立场 + 角色定位 */}
            <Grid item xs={4}>
              <TextField
                autoFocus
                margin="dense"
                label={t('characterCard.form.name')}
                fullWidth
                value={formData.name || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, name: e.target.value }))}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
                label={t('characterCard.form.stance')}
                fullWidth
                value={formData.role || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, role: e.target.value }))}
              >
                <MenuItem value="">{t('characterCard.form.unset')}</MenuItem>
                {STORY_STANCE_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.labelKey ? t(option.labelKey) : option.label}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label={t('characterCard.form.rolePosition')}
                fullWidth
                placeholder={t('characterCard.form.rolePositionPlaceholder')}
                value={formData.role_position || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, role_position: e.target.value }))}
              />
            </Grid>

            {/* 第二行：性别 + 年龄 + 所属势力 + 重要性 */}
            <Grid item xs={3}>
              <TextField
                margin="dense"
                label={t('characterCard.form.gender')}
                fullWidth
                value={formData.gender || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, gender: e.target.value }))}
              />
            </Grid>
            <Grid item xs={3}>
              <TextField
                margin="dense"
                label={t('characterCard.form.age')}
                type="number"
                fullWidth
                value={formData.age || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, age: e.target.value }))}
              />
            </Grid>
            <Grid item xs={3}>
              <TextField
                margin="dense"
                label={t('characterCard.form.faction')}
                fullWidth
                value={formData.faction || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, faction: e.target.value }))}
              />
            </Grid>
            <Grid item xs={3}>
              <TextField
                select
                margin="dense"
                label={t('characterCard.form.importance')}
                fullWidth
                value={formData.importance_level || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, importance_level: e.target.value }))}
              >
                <MenuItem value="">{t('characterCard.form.unset')}</MenuItem>
                {IMPORTANCE_OPTIONS.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.labelKey ? t(option.labelKey) : option.label}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>

            {/* 第三行：出场状态 + 生死状态 + 当前境界 */}
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
                label={t('characterCard.form.appearance')}
                fullWidth
                value={formData.appearance_status || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, appearance_status: e.target.value }))}
              >
                <MenuItem value="">{t('characterCard.form.unset')}</MenuItem>
                <MenuItem value="未出场">{t('characterCard.appearanceNotAppeared')}</MenuItem>
                <MenuItem value="已出场">{t('characterCard.appearanceAppeared')}</MenuItem>
                <MenuItem value="已退场">{t('characterCard.appearanceExited')}</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
                label={t('characterCard.form.lifeStatus')}
                fullWidth
                value={formData.life_status || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, life_status: e.target.value }))}
              >
                <MenuItem value="">{t('characterCard.form.unset')}</MenuItem>
                <MenuItem value="存活">{t('characterCard.lifeAlive')}</MenuItem>
                <MenuItem value="死亡">{t('characterCard.lifeDead')}</MenuItem>
                <MenuItem value="失踪">{t('characterCard.lifeMissing')}</MenuItem>
                <MenuItem value="未知">{t('characterCard.lifeUnknown')}</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
                label={t('characterCard.form.currentRealm')}
                fullWidth
                value={formData.current_realm_item_id || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, current_realm_item_id: e.target.value }))}
              >
                <MenuItem value="">{t('characterCard.form.unset')}</MenuItem>
                {availableRealms.map((realm: any) => (
                  <MenuItem key={realm.id} value={realm.id}>
                    {realm.name}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>

            {/* 人物简介 (1-3句话) */}
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label={t('characterCard.form.summary')}
                fullWidth
                multiline
                rows={2}
                value={formData.summary || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, summary: e.target.value }))}
              />
            </Grid>

            {/* 完整人物档案 */}
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label={t('characterCard.form.profile')}
                fullWidth
                multiline
                rows={6}
                value={formData.profile || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, profile: e.target.value }))}
                placeholder={t('characterCard.form.profilePlaceholder')}
              />
            </Grid>

            {/* 功法管理 */}
            <Grid item xs={12}>
              <Box sx={{ mt: 1, p: 2, bgcolor: 'grey.50', borderRadius: 1, border: '1px solid', borderColor: 'grey.200' }}>
                <Typography variant="subtitle2" sx={{ mb: 1.5 }}>
                  {t('characterCard.techniques.title')}
                </Typography>

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                  <TextField
                    select
                    label={t('characterCard.techniques.selectToAdd')}
                    size="small"
                    sx={{ minWidth: 220 }}
                    value={selectedTechniqueId}
                    onChange={(e) => {
                      const value = e.target.value
                      setSelectedTechniqueId(value === '' ? '' : Number(value))
                    }}
                  >
                    <MenuItem value=""><em>{t('characterCard.techniques.selectPlaceholder')}</em></MenuItem>
                    {availableTechniques.map((t: any) => (
                      <MenuItem key={t.technique_item_id || t.id} value={t.technique_item_id || t.id}>
                        {t.technique_name || t.name}{t.technique_code ? `（${t.technique_code}）` : ''}
                      </MenuItem>
                    ))}
                  </TextField>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={handleAddTechnique}
                    disabled={!selectedTechniqueId}
                  >
                    {t('characterCard.shared.add')}
                  </Button>
                </Box>

                <Box sx={{ maxHeight: 200, overflowY: 'auto' }}>
                  {characterTechniques.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      {t('characterCard.techniques.empty')}
                    </Typography>
                  ) : (
                    characterTechniques.map((t: any, index: number) => (
                      <Box
                        key={`${t.technique_item_id}-${index}`}
                        sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1, p: 1, bgcolor: 'white', borderRadius: 1 }}
                      >
                        <Typography variant="body2" sx={{ minWidth: 100, fontWeight: 500 }}>
                          {t.technique_name || availableTechniques.find((m: any) => 
                            (m.technique_item_id || m.id) === t.technique_item_id
                          )?.technique_name || t('characterCard.techniques.unknown')}
                        </Typography>
                        <TextField
                          size="small"
                          label={t('characterCard.techniques.proficiency')}
                          value={t.proficiency || ''}
                          onChange={(e) => handleUpdateTechniqueField(index, 'proficiency', e.target.value)}
                          sx={{ width: 100 }}
                        />
                        <TextField
                          size="small"
                          label={t('characterCard.techniques.learnedAtChapter')}
                          type="number"
                          value={t.learned_at_chapter ?? ''}
                          onChange={(e) => handleUpdateTechniqueField(index, 'learned_at_chapter', 
                            e.target.value === '' ? null : Number(e.target.value))}
                          sx={{ width: 80 }}
                        />
                        <TextField
                          size="small"
                          label={t('characterCard.techniques.notes')}
                          value={t.notes || ''}
                          onChange={(e) => handleUpdateTechniqueField(index, 'notes', e.target.value)}
                          sx={{ flex: 1 }}
                        />
                        <IconButton size="small" color="error" onClick={() => handleRemoveTechnique(index)}>
                          <DeleteIcon fontSize="small" />
                        </IconButton>
                      </Box>
                    ))
                  )}
                </Box>
              </Box>
            </Grid>

            {/* 🆕 人物关系管理 */}
            <Grid item xs={12}>
              <Box sx={{ mt: 1, p: 2, bgcolor: 'grey.50', borderRadius: 1, border: '1px solid', borderColor: 'grey.200' }}>
                <Typography variant="subtitle2" sx={{ mb: 1.5 }}>
                  {t('characterCard.relations.title')}
                </Typography>

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
                  <TextField
                    select
                    label={t('characterCard.relations.target')}
                    size="small"
                    sx={{ minWidth: 160 }}
                    value={newRelationTarget}
                    onChange={(e) => setNewRelationTarget(e.target.value)}
                  >
                    <MenuItem value=""><em>{t('characterCard.relations.targetPlaceholder')}</em></MenuItem>
                    {characters
                      .filter((c: any) => c.id !== editingCharacter?.id)
                      .map((c: any) => (
                        <MenuItem key={c.id} value={c.name}>
                          {c.name}
                        </MenuItem>
                      ))}
                  </TextField>
                  <TextField
                    select
                    label={t('characterCard.relations.type')}
                    size="small"
                    sx={{ minWidth: 140 }}
                    value={newRelationType}
                    onChange={(e) => setNewRelationType(e.target.value)}
                  >
                    <MenuItem value=""><em>{t('characterCard.relations.typePlaceholder')}</em></MenuItem>
                    <MenuItem value="父子">{t('characterCard.relationFatherSon')}</MenuItem>
                    <MenuItem value="母子">{t('characterCard.relationMotherSon')}</MenuItem>
                    <MenuItem value="兄弟">{t('characterCard.relationBrothers')}</MenuItem>
                    <MenuItem value="姐妹">{t('characterCard.relationSisters')}</MenuItem>
                    <MenuItem value="师徒">{t('characterCard.relationMasterDisciple')}</MenuItem>
                    <MenuItem value="同门">{t('characterCard.relationSameSchool')}</MenuItem>
                    <MenuItem value="恋人">{t('characterCard.relationLovers')}</MenuItem>
                    <MenuItem value="夫妻">{t('characterCard.relationSpouses')}</MenuItem>
                    <MenuItem value="战友">{t('characterCard.relationComrades')}</MenuItem>
                    <MenuItem value="朋友">{t('characterCard.relationFriends')}</MenuItem>
                    <MenuItem value="仇敌">{t('characterCard.relationEnemies')}</MenuItem>
                    <MenuItem value="竞争者">{t('characterCard.relationCompetitors')}</MenuItem>
                    <MenuItem value="下属">{t('characterCard.relationSubordinates')}</MenuItem>
                    <MenuItem value="上级">{t('characterCard.relationSuperiors')}</MenuItem>
                    <MenuItem value="盟友">{t('characterCard.relationAllies')}</MenuItem>
                    <MenuItem value="其他">{t('characterCard.relationOthers')}</MenuItem>
                  </TextField>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={handleAddRelation}
                    disabled={!newRelationTarget || !newRelationType}
                  >
                    {t('characterCard.shared.add')}
                  </Button>
                </Box>

                <Box sx={{ maxHeight: 150, overflowY: 'auto' }}>
                  {characterRelations.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      {t('characterCard.relations.empty')}
                    </Typography>
                  ) : (
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                      {characterRelations.map((r: any, index: number) => (
                        <Chip
                          key={`${r.target}-${r.type}-${index}`}
                          label={t('characterCard.relations.chip', { target: r.target, type: r.type })}
                          onDelete={() => handleRemoveRelation(index)}
                          size="small"
                          color="secondary"
                          variant="outlined"
                        />
                      ))}
                    </Box>
                  )}
                </Box>
              </Box>
            </Grid>

            {/* 自动追踪关联（只读展示） */}
            {editingCharacter && (
              <Grid item xs={12}>
                <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1, border: '1px solid', borderColor: 'grey.200' }}>
                  <Typography variant="subtitle2" sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                    {t('characterCard.autoTracked.title')}
                  </Typography>
                  
                  {autoTrackedLoading ? (
                    <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
                      <CircularProgress size={20} />
                    </Box>
                  ) : autoTrackedData ? (
                    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                      {/* 掌握功法 */}
                      <Box>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                          {t('characterCard.autoTracked.techniques')}
                        </Typography>
                        {autoTrackedData.techniques?.length > 0 ? (
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {autoTrackedData.techniques.map((t: any) => (
                              <Chip
                                key={t.id}
                                size="small"
                                variant="outlined"
                                color="primary"
                                label={t('characterCard.autoTracked.chapterChip', { name: t.name, chapters: t.chapters?.join(',') || '?' })}
                              />
                            ))}
                          </Box>
                        ) : (
                          <Typography variant="body2" color="text.disabled">
                          {t('characterCard.autoTracked.noTechniques')}
                          </Typography>
                        )}
                      </Box>

                      {/* 持有法宝 */}
                      <Box>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                          {t('characterCard.autoTracked.artifacts')}
                        </Typography>
                        {autoTrackedData.artifacts?.length > 0 ? (
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {autoTrackedData.artifacts.map((a: any) => (
                              <Chip
                                key={a.id}
                                size="small"
                                variant="outlined"
                                color="warning"
                                label={t('characterCard.autoTracked.chapterChip', { name: a.name, chapters: a.chapters?.join(',') || '?' })}
                              />
                            ))}
                          </Box>
                        ) : (
                          <Typography variant="body2" color="text.disabled">
                          {t('characterCard.autoTracked.noArtifacts')}
                          </Typography>
                        )}
                      </Box>

                      {/* 关联地点 */}
                      <Box>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                          {t('characterCard.autoTracked.locations')}
                        </Typography>
                        {autoTrackedData.locations?.length > 0 ? (
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {autoTrackedData.locations.map((l: any) => (
                              <Chip
                                key={l.id}
                                size="small"
                                variant="outlined"
                                color="success"
                                label={t('characterCard.autoTracked.chapterChip', { name: l.name, chapters: l.chapters?.join(',') || '?' })}
                              />
                            ))}
                          </Box>
                        ) : (
                          <Typography variant="body2" color="text.disabled">
                          {t('characterCard.autoTracked.noLocations')}
                          </Typography>
                        )}
                      </Box>
                    </Box>
                  ) : (
                    <Typography variant="body2" color="text.disabled">
                      {t('characterCard.autoTracked.empty')}
                    </Typography>
                  )}
                </Box>
              </Grid>
            )}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseEditDialog} disabled={saving}>{t('common.cancel')}</Button>
          <Button 
            variant="contained" 
            onClick={handleSaveCharacter} 
            disabled={!formData.name || saving}
          >
            {saving ? t('state.saving') : t('common.save')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 出场历程时间线对话框 */}
      <Dialog 
        open={timelineDialogOpen} 
        onClose={() => setTimelineDialogOpen(false)} 
        maxWidth="md" 
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <HistoryIcon />
            {t('characterCard.timeline.title', { name: timelineData?.character_name || '' })}
          </Box>
          <IconButton onClick={() => setTimelineDialogOpen(false)} size="small">
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent>
          {timelineLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : timelineData ? (
            <Box>
              {/* 统计信息 */}
              <Box sx={{ mb: 3, p: 2, bgcolor: 'grey.50', borderRadius: 1 }}>
                <Typography variant="body2" color="text.secondary">
                  {t('characterCard.timeline.totalHead')}<strong>{timelineData.total_appearances}</strong>{t('characterCard.timeline.totalTail')}
                  {timelineData.first_appearance && (
                    <> {t('characterCard.timeline.firstHead')}<strong>{timelineData.first_appearance}</strong>{t('characterCard.timeline.firstTail')}</>
                  )}
                  {timelineData.last_appearance && (
                    <> {t('characterCard.timeline.lastHead')}<strong>{timelineData.last_appearance}</strong>{t('characterCard.timeline.lastTail')}</>
                  )}
                </Typography>
              </Box>

              {/* 时间线列表 */}
              {timelineData.timeline.length === 0 ? (
                <Box sx={{ textAlign: 'center', py: 4, color: 'text.secondary' }}>
                  {t('characterCard.timeline.noRecord')}
                </Box>
              ) : (
                <Box sx={{ position: 'relative', pl: 3 }}>
                  {/* 时间线竖线 */}
                  <Box
                    sx={{
                      position: 'absolute',
                      left: 8,
                      top: 0,
                      bottom: 0,
                      width: 2,
                      bgcolor: 'primary.light',
                    }}
                  />
                  
                  {timelineData.timeline.map((item: any, index: number) => (
                    <Box
                      key={item.chapter_id}
                      sx={{
                        position: 'relative',
                        pb: 3,
                        '&:last-child': { pb: 0 },
                      }}
                    >
                      {/* 时间线节点 */}
                      <Box
                        sx={{
                          position: 'absolute',
                          left: -19,
                          top: 4,
                          width: 12,
                          height: 12,
                          borderRadius: '50%',
                          bgcolor: index === 0 ? 'primary.main' : 'primary.light',
                          border: '2px solid white',
                          boxShadow: 1,
                        }}
                      />
                      
                      {/* 章节内容 */}
                      <Box
                        sx={{
                          p: 2,
                          bgcolor: 'background.paper',
                          border: '1px solid',
                          borderColor: 'divider',
                          borderRadius: 1,
                          '&:hover': { borderColor: 'primary.main' },
                        }}
                      >
                        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
                            {t('characterCard.timeline.chapterLine', { number: item.chapter_number, title: item.chapter_title })}
                          </Typography>
                          <Chip 
                            size="small" 
                            label={t('characterCard.timeline.wordCount', { count: item.word_count })} 
                            variant="outlined"
                          />
                        </Box>
                        
                        {/* 章节摘要 */}
                        {item.summary && (
                          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                            📝 {item.summary}
                          </Typography>
                        )}
                        
                        {/* 人物相关摘录 */}
                        {item.excerpts && item.excerpts.length > 0 && (
                          <Box sx={{ mt: 1 }}>
                            {item.excerpts.map((excerpt: string, i: number) => (
                              <Typography
                                key={i}
                                variant="body2"
                                sx={{
                                  pl: 2,
                                  py: 0.5,
                                  borderLeft: '2px solid',
                                  borderColor: 'warning.main',
                                  bgcolor: 'warning.50',
                                  fontSize: '0.85rem',
                                  color: 'text.secondary',
                                  mb: 0.5,
                                }}
                              >
                                "{excerpt}"
                              </Typography>
                            ))}
                          </Box>
                        )}
                      </Box>
                    </Box>
                  ))}
                </Box>
              )}
            </Box>
          ) : (
            <Box sx={{ textAlign: 'center', py: 4, color: 'text.secondary' }}>
              {t('characterCard.timeline.loadFailed')}
            </Box>
          )}
        </DialogContent>
      </Dialog>

      {/* 🆕 同步到工作流确认对话框 */}
      <Dialog
        open={syncDialogOpen}
        onClose={() => !syncing && setSyncDialogOpen(false)}
        maxWidth="md"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <SyncIcon color="primary" />
            {t('characterCard.sync.title')}
          </Box>
          <IconButton onClick={() => setSyncDialogOpen(false)} disabled={syncing} size="small">
            <CloseIcon />
          </IconButton>
        </DialogTitle>
        <DialogContent dividers>
          {syncPreviewLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : syncPreview ? (
            <Box>
              {/* 统计信息 */}
              <Box sx={{ mb: 3, p: 2, bgcolor: 'primary.50', borderRadius: 1, border: '1px solid', borderColor: 'primary.200' }}>
                <Typography variant="body2">
                  {t('characterCard.sync.previewHead')}<strong>{syncPreview.character_count}</strong>{t('characterCard.sync.previewMid')}<strong>{syncPreview.text_length}</strong>{t('characterCard.sync.previewTail')}
                </Typography>
                {syncPreview.stats && (
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
                    {t('characterCard.sync.byImportance')}{Object.entries(syncPreview.stats.by_importance || {}).map(([k, v]) => `${k}: ${v}`).join(', ')}
                  </Typography>
                )}
              </Box>

              {/* 预览内容 */}
              <Typography variant="subtitle2" sx={{ mb: 1 }}>{t('characterCard.sync.textPreview')}</Typography>
              <Box
                sx={{
                  p: 2,
                  bgcolor: 'grey.50',
                  borderRadius: 1,
                  border: '1px solid',
                  borderColor: 'grey.300',
                  maxHeight: 300,
                  overflowY: 'auto',
                  fontFamily: 'monospace',
                  fontSize: '0.85rem',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {syncPreview.text?.substring(0, 2000)}
                {syncPreview.text?.length > 2000 && `\n\n${t('characterCard.sync.moreOmitted')}`}
              </Box>

              <Alert severity="warning" sx={{ mt: 2 }}>
                {t('characterCard.sync.warningBody')}
              </Alert>
            </Box>
          ) : (
            <Box sx={{ textAlign: 'center', py: 4, color: 'text.secondary' }}>
              {t('characterCard.sync.loadPreviewFailed')}
            </Box>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setSyncDialogOpen(false)} disabled={syncing}>
            {t('common.cancel')}
          </Button>
          <Button
            variant="contained"
            color="primary"
            onClick={handleSyncToWorkflow}
            disabled={syncing || !syncPreview}
            startIcon={syncing ? <CircularProgress size={20} /> : <SyncIcon />}
          >
            {syncing ? t('characterCard.sync.syncing') : t('characterCard.sync.confirmSync')}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 🆕 Snackbar 消息提示 */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={4000}
        onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
        anchorOrigin={{ vertical: 'top', horizontal: 'center' }}
      >
        <Alert
          onClose={() => setSnackbar(prev => ({ ...prev, open: false }))}
          severity={snackbar.severity}
          sx={{ width: '100%' }}
        >
          {snackbar.message}
        </Alert>
      </Snackbar>

      {/* 🆕 关系图对话框 */}
      <Dialog
        open={graphDialogOpen}
        onClose={() => setGraphDialogOpen(false)}
        maxWidth="lg"
        fullWidth
      >
        <DialogTitle sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <AccountTreeIcon color="secondary" />
            {t('characterCard.graph.title')}
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Typography variant="body2" color="text.secondary">
              {t('characterCard.graph.stats', { nodes: graphStats.total_nodes, edges: graphStats.total_edges })}
            </Typography>
            {selectedNodeId && (
              <Button 
                size="small" 
                variant="outlined" 
                onClick={() => handleNodeClick({} as React.MouseEvent, { id: selectedNodeId } as Node)}
              >
                {t('characterCard.graph.resetFilter')}
              </Button>
            )}
            <IconButton onClick={() => setGraphDialogOpen(false)} size="small">
              <CloseIcon />
            </IconButton>
          </Box>
        </DialogTitle>
        <DialogContent dividers sx={{ p: 0, height: 500 }}>
          {graphLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%' }}>
              <CircularProgress />
            </Box>
          ) : nodes.length === 0 ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100%', color: 'text.secondary' }}>
              {t('characterCard.graph.noData')}
            </Box>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={handleNodeClick}
              fitView
              attributionPosition="bottom-left"
            >
              <Background color="var(--sg-divider)" gap={16} />
              <Controls />
              <MiniMap nodeColor={(node) => node.style?.background as string || 'var(--sg-divider)'} />
            </ReactFlow>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGraphDialogOpen(false)}>{t('common.close')}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
