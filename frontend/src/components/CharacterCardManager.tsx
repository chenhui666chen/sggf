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
                sx={{ borderBottom: '1px solid #eee', py: 2 }}
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
                      <Chip size="small" label={`${character.age}岁`} variant="outlined" />
                    )}
                  </Box>
                  
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                    {character.role && <Chip size="small" label={character.role} color="primary" />}
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
                          '境界'
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
      <Dialog open={editDialogOpen} onClose={handleCloseEditDialog} maxWidth="sm" fullWidth>
        <DialogTitle>{editingCharacter ? '编辑角色' : '新建角色'}</DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            {/* 第一行：姓名 + 故事立场 */}
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 2 }}>
              <TextField
                label="姓名"
                required
                value={formData.name || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, name: e.target.value }))}
              />
              <TextField
                select
                label="故事立场"
                value={formData.role || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, role: e.target.value }))}
              >
                <MenuItem value="">自定义</MenuItem>
                <MenuItem value="主角方">主角方</MenuItem>
                <MenuItem value="对手方">对手方</MenuItem>
                <MenuItem value="中立方">中立方</MenuItem>
              </TextField>
            </Box>

            {/* 第二行：性别 + 年龄 */}
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 2 }}>
              <TextField
                label="性别"
                value={formData.gender || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, gender: e.target.value }))}
              />
              <TextField
                label="年龄"
                type="number"
                value={formData.age || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, age: e.target.value }))}
              />
            </Box>

            {/* 第三行：所属势力 + 重要性 */}
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 2 }}>
              <TextField
                label="所属势力"
                value={formData.faction || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, faction: e.target.value }))}
              />
              <TextField
                select
                label="重要性（战力权重）"
                value={formData.importance_level || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, importance_level: e.target.value }))}
              >
                <MenuItem value="">未设置</MenuItem>
                <MenuItem value="主角">主角</MenuItem>
                <MenuItem value="重要配角">重要配角</MenuItem>
                <MenuItem value="普通配角">普通配角</MenuItem>
                <MenuItem value="龙套">龙套</MenuItem>
              </TextField>
            </Box>

            {/* 第四行：出场状态 + 生死状态 */}
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 2 }}>
              <TextField
                select
                label="出场状态（未出场/已出场/已退场）"
                value={formData.appearance_status || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, appearance_status: e.target.value }))}
              >
                <MenuItem value="">未设置</MenuItem>
                <MenuItem value="未出场">未出场</MenuItem>
                <MenuItem value="已出场">已出场</MenuItem>
                <MenuItem value="已退场">已退场</MenuItem>
              </TextField>
              <TextField
                select
                label="生死状态（存活/死亡/失踪/未知）"
                value={formData.life_status || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, life_status: e.target.value }))}
              >
                <MenuItem value="">未设置</MenuItem>
                <MenuItem value="存活">存活</MenuItem>
                <MenuItem value="死亡">死亡</MenuItem>
                <MenuItem value="失踪">失踪</MenuItem>
                <MenuItem value="未知">未知</MenuItem>
              </TextField>
            </Box>

            {/* 第五行：首次出场章节编号 + 当前境界 */}
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 2 }}>
              <TextField
                label="首次出场章节编号"
                value={formData.first_appearance_chapter || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, first_appearance_chapter: e.target.value }))}
              />
              <TextField
                select
                label="当前境界"
                value={formData.current_realm_item_id || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, current_realm_item_id: e.target.value }))}
              >
                <MenuItem value="">未设置</MenuItem>
                {availableRealms.map((realm: any) => (
                  <MenuItem key={realm.id} value={realm.id}>
                    {realm.name}
                  </MenuItem>
                ))}
              </TextField>
            </Box>

            {/* 人物简介 (1-3句话) */}
            <TextField
              label="人物简介（1-3句话）"
              multiline
              rows={2}
              fullWidth
              value={formData.summary || ''}
              onChange={(e) => setFormData((prev: any) => ({ ...prev, summary: e.target.value }))}
            />

            {/* 完整人物档案 */}
            <TextField
              label="完整人物档案"
              multiline
              rows={6}
              fullWidth
              value={formData.profile || ''}
              onChange={(e) => setFormData((prev: any) => ({ ...prev, profile: e.target.value }))}
              placeholder="可包含外貌特征、性格特点、背景故事等详细信息"
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
