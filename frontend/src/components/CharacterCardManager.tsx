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
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import { apiClient } from '@/services/api'

interface CharacterCardManagerProps {
  projectId: number
  onCharacterUpdate?: () => void
}

export default function CharacterCardManager({ projectId, onCharacterUpdate }: CharacterCardManagerProps) {
  const [characters, setCharacters] = useState<any[]>([])
  const [loading, setLoading] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)
  const [editingCharacter, setEditingCharacter] = useState<any | null>(null)
  const [formData, setFormData] = useState<any>({})
  const [availableRealms, setAvailableRealms] = useState<any[]>([])

  // 加载角色列表
  const loadCharacters = async () => {
    setLoading(true)
    try {
      const response = await fetch(`/api/v1/projects/${projectId}/characters`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      if (response.ok) {
        const data = await response.json()
        setCharacters(data)
      }
    } catch (error) {
      console.error('加载角色列表失败:', error)
    } finally {
      setLoading(false)
    }
  }

  // 加载可用境界列表（用于境界选择）
  const loadAvailableRealms = async () => {
    try {
      // TODO: 调用API获取境界列表
      // 暂时设置为空数组
      setAvailableRealms([])
    } catch (error) {
      console.error('加载境界列表失败:', error)
    }
  }

  useEffect(() => {
    loadCharacters()
    loadAvailableRealms()
  }, [projectId])

  // 打开编辑对话框
  const handleOpenEditDialog = (character?: any) => {
    if (character) {
      setEditingCharacter(character)
      setFormData(character)
    } else {
      setEditingCharacter(null)
      setFormData({ name: '', role: '', faction: '' })
    }
    setEditDialogOpen(true)
  }

  // 关闭编辑对话框
  const handleCloseEditDialog = () => {
    setEditDialogOpen(false)
    setEditingCharacter(null)
    setFormData({})
  }

  // 保存角色
  const handleSaveCharacter = async () => {
    try {
      const url = editingCharacter
        ? `/api/v1/characters/${editingCharacter.id}`
        : `/api/v1/projects/${projectId}/characters`
      
      const method = editingCharacter ? 'PUT' : 'POST'
      
      const response = await fetch(url, {
        method,
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      })

      if (response.ok) {
        await loadCharacters()
        handleCloseEditDialog()
        onCharacterUpdate?.()
      }
    } catch (error) {
      console.error('保存角色失败:', error)
    }
  }

  // 删除角色
  const handleDeleteCharacter = async (characterId: number) => {
    if (!confirm('确定要删除此角色吗？')) return

    try {
      const response = await fetch(`/api/v1/characters/${characterId}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        await loadCharacters()
        onCharacterUpdate?.()
      }
    } catch (error) {
      console.error('删除角色失败:', error)
    }
  }

  return (
    <Box>
      {/* 顶部操作栏 */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6">🎴 人物卡管理</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => handleOpenEditDialog()}
        >
          新建角色
        </Button>
      </Box>

      {/* 使用说明 */}
      <Alert severity="info" sx={{ mb: 2 }}>
        这里可以结构化管理角色信息（阵营、境界、出场状态等），保存后会参与章节逻辑检查。
      </Alert>

      {/* 角色列表 */}
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      ) : (
        <List sx={{ border: '1px solid #eee', borderRadius: 1, maxHeight: 500, overflowY: 'auto' }}>
          {characters.length === 0 ? (
            <Box sx={{ p: 4, textAlign: 'center', color: 'text.secondary' }}>
              还没有创建任何角色，点击"新建角色"开始
            </Box>
          ) : (
            characters.map((character) => (
              <ListItem
                key={character.id}
                secondaryAction={
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <Tooltip title="编辑">
                      <IconButton size="small" onClick={() => handleOpenEditDialog(character)}>
                        <EditIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                    <Tooltip title="删除">
                      <IconButton size="small" onClick={() => handleDeleteCharacter(character.id)}>
                        <DeleteIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                }
              >
                <Box sx={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                  <Typography variant="subtitle1">{character.name}</Typography>
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 0.5 }}>
                    {character.role && <Chip size="small" label={character.role} />}
                    {character.faction && <Chip size="small" label={character.faction} color="primary" />}
                    {character.current_realm_item_id && (
                      <Chip
                        size="small"
                        color="secondary"
                        label={
                          availableRealms.find((r: any) => r.id === character.current_realm_item_id)?.name ||
                          '境界'
                        }
                      />
                    )}
                  </Box>
                </Box>
              </ListItem>
            ))
          )}
        </List>
      )}

      {/* 编辑对话框 */}
      <Dialog open={editDialogOpen} onClose={handleCloseEditDialog} maxWidth="sm" fullWidth>
        <DialogTitle>{editingCharacter ? '编辑角色' : '新建角色'}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              label="姓名"
              required
              fullWidth
              value={formData.name || ''}
              onChange={(e) => setFormData((prev: any) => ({ ...prev, name: e.target.value }))}
            />
            <TextField
              select
              label="故事立场"
              fullWidth
              value={formData.role || ''}
              onChange={(e) => setFormData((prev: any) => ({ ...prev, role: e.target.value }))}
            >
              <MenuItem value="">自定义</MenuItem>
              <MenuItem value="主角方">主角方</MenuItem>
              <MenuItem value="对手方">对手方</MenuItem>
              <MenuItem value="中立方">中立方</MenuItem>
            </TextField>
            <TextField
              label="阵营"
              fullWidth
              value={formData.faction || ''}
              onChange={(e) => setFormData((prev: any) => ({ ...prev, faction: e.target.value }))}
            />
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseEditDialog}>取消</Button>
          <Button variant="contained" onClick={handleSaveCharacter} disabled={!formData.name}>
            保存
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}
