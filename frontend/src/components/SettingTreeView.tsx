import { useEffect, useState } from 'react'
import { Box, CircularProgress, List, ListItemButton, ListItemText, Typography, IconButton, Stack, Tooltip } from '@mui/material'
import FolderIcon from '@mui/icons-material/Folder'
import FolderOpenIcon from '@mui/icons-material/FolderOpen'
import DescriptionIcon from '@mui/icons-material/Description'
import RefreshIcon from '@mui/icons-material/Refresh'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import { useTranslation } from 'react-i18next'
import { apiClient } from '@/services/api'
import type {
  SettingItem,
  SettingItemsTreeResponse,
  SettingTreeActionItem,
  SettingTreeApiNode,
} from '@/types/settings'

interface TreeNode extends Omit<SettingTreeApiNode, 'children'> {
  children: TreeNode[]
  name: string
  path: string
}

interface SettingTreeViewProps {
  collectionId: number
  selectedItemId?: number
  onSelectItem?: (item: SettingItem | null) => void
  onSelectCategory?: (categoryPath: string, categoryItem: SettingItem | null) => void  // 🆕 添加 categoryItem 参数
  onSelectInstance?: (item: SettingItem) => void
  onAddItem?: (parentPath: string, parentItem: SettingItem | null) => void
  onDeleteItem?: (item: SettingTreeActionItem) => void
  title?: string
  showHeader?: boolean
  showActions?: boolean  // 是否显示添加/删除按钮
  refreshTrigger?: number  // 🆕 刷新触发器，变化时重新加载
}

export default function SettingTreeView(props: SettingTreeViewProps) {
  const { collectionId, selectedItemId, onSelectItem, onSelectCategory, onSelectInstance, onAddItem, onDeleteItem, title, showHeader = true, showActions = true, refreshTrigger = 0 } = props
  const { t } = useTranslation()
  const [hoveredPath, setHoveredPath] = useState<string | null>(null)

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
      const data: SettingItemsTreeResponse = resp.data

      const buildWithPath = (nodes: SettingTreeApiNode[], parentPath: string): TreeNode[] => {
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
    } catch {
      setError(t('settingTree.loadError'))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTree()
  }, [collectionId, refreshTrigger])  // 🆕 添加 refreshTrigger 依赖

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
        onSelectCategory(node.path, node.item)  // 🆕 传递分类节点的 item
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

  const handleAdd = (e: React.MouseEvent, node: TreeNode) => {
    e.stopPropagation()
    if (onAddItem) {
      onAddItem(node.path, node.item)
    }
  }

  const handleDelete = (e: React.MouseEvent, node: TreeNode) => {
    e.stopPropagation()
    if (onDeleteItem) {
      const nextItem: SettingTreeActionItem = {
        ...(node.item ?? {}),
        path: node.path,
        is_leaf: node.is_leaf,
        name: node.name,
      }
      onDeleteItem(nextItem)
    }
  }

  const renderNodes = (nodes: TreeNode[], level: number = 0) => {
    return nodes.map((node) => {
      const hasChildren = node.children && node.children.length > 0
      const isExpanded = expanded.has(node.path)
      const isSelected = !!(node.item && selectedItemId != null && node.item.id === selectedItemId)
      const isHovered = hoveredPath === node.path

      const IconComponent = node.is_leaf ? DescriptionIcon : isExpanded ? FolderOpenIcon : FolderIcon

      return (
        <Box key={node.path}>
          <ListItemButton
            dense
            selected={isSelected}
            onClick={() => handleClickNode(node)}
            onMouseEnter={() => setHoveredPath(node.path)}
            onMouseLeave={() => setHoveredPath(null)}
            sx={{ pl: 1.5 + level * 2, pr: 1 }}
          >
            <Stack direction="row" alignItems="center" spacing={1} sx={{ flex: 1, minWidth: 0 }}>
              <IconComponent fontSize="small" />
              <ListItemText
                primary={
                  <Typography variant="body2" noWrap>
                    {node.name}
                  </Typography>
                }
              />
            </Stack>
            {/* 操作按钮 - 悬停时显示 */}
            {showActions && isHovered && (
              <Stack direction="row" spacing={0} sx={{ ml: 1 }}>
                {/* 添加子节点按钮 */}
                {onAddItem && (
                  <Tooltip title={t('settingTree.addChild')} placement="top">
                    <IconButton
                      size="small"
                      onClick={(e) => handleAdd(e, node)}
                      sx={{ padding: '2px' }}
                    >
                      <AddIcon sx={{ fontSize: 16 }} />
                    </IconButton>
                  </Tooltip>
                )}
                {/* 删除按钮 - 所有层级都可删除 */}
                {onDeleteItem && (
                  <Tooltip title={node.is_leaf ? t('settingTree.deleteItem') : t('settingTree.deleteCategory')} placement="top">
                    <IconButton
                      size="small"
                      onClick={(e) => handleDelete(e, node)}
                      sx={{ padding: '2px' }}
                    >
                      <DeleteIcon sx={{ fontSize: 16, color: 'error.main' }} />
                    </IconButton>
                  </Tooltip>
                )}
              </Stack>
            )}
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
            {title || t('settingTree.defaultTitle')}
          </Typography>
          <Stack direction="row" spacing={0.5}>
            {/* 顶层添加按钮 */}
            {showActions && onAddItem && (
              <Tooltip title={t('settingTree.addRoot')} placement="top">
                <IconButton size="small" onClick={() => onAddItem('', null)}>
                  <AddIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            )}
            <IconButton size="small" onClick={loadTree} disabled={loading}>
              <RefreshIcon fontSize="small" />
            </IconButton>
          </Stack>
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
            {t('settingTree.empty')}
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
