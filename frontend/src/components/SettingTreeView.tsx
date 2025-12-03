import { useEffect, useState } from 'react'
import { Box, CircularProgress, List, ListItemButton, ListItemText, Typography, IconButton, Stack } from '@mui/material'
import FolderIcon from '@mui/icons-material/Folder'
import FolderOpenIcon from '@mui/icons-material/FolderOpen'
import DescriptionIcon from '@mui/icons-material/Description'
import RefreshIcon from '@mui/icons-material/Refresh'
import { apiClient } from '@/services/api'

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

interface TreeNode {
  name: string
  depth: number | null
  is_leaf: boolean
  item: SettingItem | null
  children: TreeNode[]
  path: string
}

interface SettingTreeViewProps {
  collectionId: number
  selectedItemId?: number
  onSelectItem?: (item: SettingItem | null) => void
  onSelectCategory?: (categoryPath: string) => void
  onSelectInstance?: (item: SettingItem) => void
  title?: string
  showHeader?: boolean
}

export default function SettingTreeView(props: SettingTreeViewProps) {
  const { collectionId, selectedItemId, onSelectItem, onSelectCategory, onSelectInstance, title, showHeader = true } = props

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tree, setTree] = useState<TreeNode[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const loadTree = async () => {
    if (!collectionId) return
    setLoading(true)
    setError(null)
    try {
      const resp = await apiClient.getSettingItemsTree(collectionId)
      const data = resp.data as { collection: string; tree: any[] }

      const buildWithPath = (nodes: any[], parentPath: string): TreeNode[] => {
        return nodes.map((node) => {
          const currentPath = parentPath ? `${parentPath}/${node.name}` : node.name
          const children = buildWithPath(node.children || [], currentPath)
          return {
            name: node.name,
            depth: node.depth,
            is_leaf: !!node.is_leaf,
            item: node.item || null,
            children,
            path: currentPath,
          }
        })
      }

      const treeWithPath = buildWithPath(data.tree || [], data.collection || '')
      setTree(treeWithPath)

      const initialExpanded = new Set<string>()
      treeWithPath.forEach((n) => initialExpanded.add(n.path))
      setExpanded(initialExpanded)
    } catch (e) {
      console.error('加载设定树失败', e)
      setError('加载设定树失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTree()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [collectionId])

  const handleToggle = (path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(path)) {
        next.delete(path)
      } else {
        next.add(path)
      }
      return next
    })
  }

  const handleClickNode = (node: TreeNode) => {
    if (!node.is_leaf) {
      handleToggle(node.path)
      if (onSelectCategory) {
        onSelectCategory(node.path)
      }
      return
    }
    if (node.is_leaf) {
      if (onSelectInstance && node.item) {
        onSelectInstance(node.item)
      }
      if (onSelectItem) {
        onSelectItem(node.item)
      }
    }
  }

  const renderNodes = (nodes: TreeNode[], level: number = 0) => {
    return nodes.map((node) => {
      const hasChildren = node.children && node.children.length > 0
      const isExpanded = expanded.has(node.path)
      const isSelected = !!(node.item && selectedItemId != null && node.item.id === selectedItemId)

      const IconComponent = node.is_leaf ? DescriptionIcon : isExpanded ? FolderOpenIcon : FolderIcon

      return (
        <Box key={node.path}>
          <ListItemButton
            dense
            selected={isSelected}
            onClick={() => handleClickNode(node)}
            sx={{ pl: 1.5 + level * 2 }}
          >
            <Stack direction="row" alignItems="center" spacing={1}>
              <IconComponent fontSize="small" />
              <ListItemText
                primary={
                  <Typography variant="body2" noWrap>
                    {node.name}
                  </Typography>
                }
              />
            </Stack>
          </ListItemButton>
          {hasChildren && isExpanded && (
            <Box>
              {renderNodes(node.children, level + 1)}
            </Box>
          )}
        </Box>
      )
    })
  }

  return (
    <Box display="flex" flexDirection="column" height="100%">
      {showHeader && (
        <Box px={1.5} py={1} display="flex" alignItems="center" justifyContent="space-between">
          <Typography variant="subtitle2">
            {title || '层级视图'}
          </Typography>
          <IconButton size="small" onClick={loadTree} disabled={loading}>
            <RefreshIcon fontSize="small" />
          </IconButton>
        </Box>
      )}

      {loading && (
        <Box flex={1} display="flex" alignItems="center" justifyContent="center" py={2}>
          <CircularProgress size={24} />
        </Box>
      )}

      {!loading && error && (
        <Box px={2} py={1}>
          <Typography variant="body2" color="error">
            {error}
          </Typography>
        </Box>
      )}

      {!loading && !error && !tree.length && (
        <Box px={2} py={1}>
          <Typography variant="body2" color="text.secondary">
            暂无设定项
          </Typography>
        </Box>
      )}

      {!loading && !error && tree.length > 0 && (
        <Box flex={1} overflow="auto">
          <List dense sx={{ py: 0 }}>
            {renderNodes(tree)}
          </List>
        </Box>
      )}
    </Box>
  )
}
