import { useEffect, useState, useCallback } from 'react'
import ReactFlow, {
  Node,
  Edge,
  Controls,
  Background,
  useNodesState,
  useEdgesState,
  MarkerType,
  Position,
} from 'reactflow'
import 'reactflow/dist/style.css'
import {
  Box,
  Card,
  CardContent,
  Typography,
  CircularProgress,
  Alert,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Chip,
  IconButton,
  Tooltip,
} from '@mui/material'
import RefreshIcon from '@mui/icons-material/Refresh'
import { apiClient, extractApiErrorMessage } from '@/services/api'

interface RelationshipGraphProps {
  itemId: number
  itemName: string
  onNodeClick?: (nodeId: number) => void
}

export default function RelationshipGraph(props: RelationshipGraphProps) {
  const { itemId, itemName, onNodeClick } = props

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [direction, setDirection] = useState<'both' | 'out' | 'in'>('both')
  const [maxDepth, setMaxDepth] = useState(1)

  const [nodes, setNodes, onNodesChange] = useNodesState([])
  const [edges, setEdges, onEdgesChange] = useEdgesState([])

  const loadGraph = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const response = await apiClient.get(`/api/v1/setting-items/${itemId}/graph-neighbors`, {
        params: {
          direction,
          max_depth: maxDepth,
          min_confidence: 0.0,
        },
      })

      const data = response.data
      const graphNodes = data.nodes || []
      const graphEdges = data.edges || []

      // 🔧 优化：改进的多层级布局算法
      
      // 1. 使用BFS计算每个节点的层级
      const nodeLevels = new Map<number, number>()
      nodeLevels.set(itemId, 0)
      
      const queue = [itemId]
      const visited = new Set([itemId])
      
      while (queue.length > 0) {
        const current = queue.shift()!
        const currentLevel = nodeLevels.get(current)!
        
        // 查找所有相关边
        graphEdges.forEach((edge: any) => {
          let neighbor: number | null = null
          
          // 判断当前节点是源还是目标
          if (edge.source === current) {
            neighbor = edge.target
          } else if (edge.target === current) {
            neighbor = edge.source
          }
          
          // 如果找到未访问的邻居节点
          if (neighbor !== null && !visited.has(neighbor)) {
            visited.add(neighbor)
            nodeLevels.set(neighbor, currentLevel + 1)
            queue.push(neighbor)
          }
        })
      }
      
      // 2. 按层级分组节点
      const nodesByLevel = new Map<number, any[]>()
      graphNodes.forEach((node: any) => {
        const level = nodeLevels.get(node.id) ?? maxDepth
        if (!nodesByLevel.has(level)) {
          nodesByLevel.set(level, [])
        }
        nodesByLevel.get(level)!.push(node)
      })
      
      // 3. 布局参数
      const centerX = 500
      const centerY = 400
      const baseRadius = 220 // 增大基础半径
      const radiusIncrement = 250 // 增大层间距
      const minNodeSpacing = 170 // 增大节点间距
      
      // 4. 为每个节点计算位置
      const flowNodes: Node[] = graphNodes.map((node: any) => {
        const isCenter = node.id === itemId
        const level = nodeLevels.get(node.id) ?? maxDepth
        
        let x = centerX
        let y = centerY
        
        if (!isCenter) {
          const levelNodes = nodesByLevel.get(level) || []
          const nodeIndex = levelNodes.findIndex((n: any) => n.id === node.id)
          const nodesInLevel = levelNodes.length
          
          // 计算所需半径（确保节点不重叠）
          const requiredCircumference = nodesInLevel * minNodeSpacing
          const minRequiredRadius = requiredCircumference / (2 * Math.PI)
          const radius = Math.max(baseRadius + (level - 1) * radiusIncrement, minRequiredRadius)
          
          // 均匀分布在圆周上
          const angleOffset = (level % 2) * (Math.PI / Math.max(nodesInLevel, 1))
          const angle = (nodeIndex * 2 * Math.PI) / nodesInLevel + angleOffset
          
          x = centerX + radius * Math.cos(angle)
          y = centerY + radius * Math.sin(angle)
        }

        return {
          id: String(node.id),
          position: { x, y },
          data: {
            label: (
              <Box textAlign="center">
                <Typography variant="body2" fontWeight={isCenter ? 600 : 400}>
                  {node.name}
                </Typography>
                <Chip
                  label={node.collection_name}
                  size="small"
                  sx={{ mt: 0.5, height: 18, fontSize: '0.7rem' }}
                  color={isCenter ? 'primary' : 'default'}
                />
              </Box>
            ),
          },
          style: {
            background: isCenter ? '#1976d2' : '#fff',
            color: isCenter ? '#fff' : '#000',
            border: isCenter ? '2px solid #1976d2' : '1px solid #ddd',
            borderRadius: 8,
            padding: 10,
            width: 150,
          },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
        }
      })

      const flowEdges: Edge[] = graphEdges.map((edge: any) => {
        const confidence = typeof edge.confidence === 'number' ? edge.confidence : 0
        const accentColor = confidence > 0.8 ? '#1976d2' : '#999'
        return {
          id: String(edge.id ?? `${edge.source}-${edge.target}-${edge.relation_type}`),
          source: String(edge.source),
          target: String(edge.target),
          label: edge.relation_type,
          type: 'smoothstep',
          animated: confidence > 0.8,
          style: {
            stroke: accentColor,
            strokeWidth: 2,
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: accentColor,
          },
          labelStyle: { fontSize: 12, fill: '#666' },
          labelBgStyle: { fill: '#fff', fillOpacity: 0.9 },
        }
      })

      setNodes(flowNodes)
      setEdges(flowEdges)
    } catch (err: any) {
      setError(await extractApiErrorMessage(err, '加载失败'))
    } finally {
      setLoading(false)
    }
  }, [itemId, direction, maxDepth, setNodes, setEdges])

  useEffect(() => {
    if (itemId) {
      loadGraph()
    }
  }, [itemId, loadGraph])

  const handleNodeClick = (_: React.MouseEvent, node: Node) => {
    if (onNodeClick && node.id !== String(itemId)) {
      onNodeClick(Number(node.id))
    }
  }

  return (
    <Card elevation={2}>
      <CardContent>
        <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
          <Typography variant="h6" fontWeight={600}>
            关系网络图 - {itemName}
          </Typography>
          <Box display="flex" gap={2} alignItems="center">
            <FormControl size="small" sx={{ minWidth: 120 }}>
              <InputLabel>方向</InputLabel>
              <Select
                value={direction}
                label="方向"
                onChange={(e) => setDirection(e.target.value as any)}
              >
                <MenuItem value="both">双向</MenuItem>
                <MenuItem value="out">出边</MenuItem>
                <MenuItem value="in">入边</MenuItem>
              </Select>
            </FormControl>

            <FormControl size="small" sx={{ minWidth: 100 }}>
              <InputLabel>深度</InputLabel>
              <Select
                value={maxDepth}
                label="深度"
                onChange={(e) => setMaxDepth(Number(e.target.value))}
              >
                <MenuItem value={1}>1跳</MenuItem>
                <MenuItem value={2}>2跳</MenuItem>
                <MenuItem value={3}>3跳</MenuItem>
              </Select>
            </FormControl>

            <Tooltip title="刷新">
              <span>
                <IconButton size="small" onClick={loadGraph} disabled={loading}>
                  <RefreshIcon />
                </IconButton>
              </span>
            </Tooltip>
          </Box>
        </Box>

        {loading && (
          <Box display="flex" justifyContent="center" py={4}>
            <CircularProgress />
          </Box>
        )}

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {!loading && !error && nodes.length === 0 && (
          <Alert severity="info">
            暂无关系数据
          </Alert>
        )}

        {!loading && !error && nodes.length > 0 && (
          <Box sx={{ height: 700, border: '1px solid #ddd', borderRadius: 1 }}>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              onNodesChange={onNodesChange}
              onEdgesChange={onEdgesChange}
              onNodeClick={handleNodeClick}
              fitView
              fitViewOptions={{ padding: 0.2, maxZoom: 1.2 }}
              minZoom={0.1}
              maxZoom={2}
            >
              <Background />
              <Controls />
            </ReactFlow>
          </Box>
        )}

        <Box mt={2} display="flex" gap={2} alignItems="center">
          <Typography variant="caption" color="text.secondary">
            节点总数: {nodes.length}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            关系总数: {edges.length}
          </Typography>
          <Chip
            label="蓝色边=高置信度(>0.8)"
            size="small"
            sx={{ height: 20, fontSize: '0.7rem' }}
          />
        </Box>
      </CardContent>
    </Card>
  )
}
