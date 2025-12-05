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
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import EditIcon from '@mui/icons-material/Edit'
import DeleteIcon from '@mui/icons-material/Delete'
import HistoryIcon from '@mui/icons-material/History'
import CloseIcon from '@mui/icons-material/Close'

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
  
  // 出场历程时间线状态
  const [timelineDialogOpen, setTimelineDialogOpen] = useState(false)
  const [timelineData, setTimelineData] = useState<any>(null)
  const [timelineLoading, setTimelineLoading] = useState(false)

  // 自动追踪关联状态
  const [autoTrackedData, setAutoTrackedData] = useState<any>(null)
  const [autoTrackedLoading, setAutoTrackedLoading] = useState(false)

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
      // 境界体系的category列表
      const realmCategories = [
        'cultivation_realm_system',  // 修仙境界
        'magic_realm_system',        // 魔法境界
        'martial_realm_system',      // 武道境界
        'ability_realm_system',      // 异能境界
      ]

      // 1. 获取项目所有设定集合
      const collectionsRes = await fetch(`/api/v1/projects/${projectId}/setting-collections`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (!collectionsRes.ok) {
        console.error('获取设定集合失败')
        setAvailableRealms([])
        return
      }

      const collections = await collectionsRes.json()

      // 2. 筛选境界体系集合
      const realmCollections = collections.filter((c: any) =>
        realmCategories.includes(c.category)
      )

      // 3. 获取所有境界项
      const realmItems: any[] = []
      for (const collection of realmCollections) {
        const itemsRes = await fetch(`/api/v1/setting-collections/${collection.id}/items`, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          },
        })
        if (itemsRes.ok) {
          const items = await itemsRes.json()
          // 添加集合信息，便于显示分组
          items.forEach((item: any) => {
            item.collectionName = collection.name
          })
          realmItems.push(...items)
        }
      }

      setAvailableRealms(realmItems)
    } catch (error) {
      console.error('加载境界列表失败:', error)
      setAvailableRealms([])
    }
  }

  useEffect(() => {
    loadCharacters()
    loadAvailableRealms()
  }, [projectId])

  // 加载自动追踪关联数据
  const loadAutoTrackedData = async (characterId: number) => {
    setAutoTrackedLoading(true)
    try {
      const response = await fetch(`/api/v1/characters/${characterId}/auto-tracked-relations`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      if (response.ok) {
        const data = await response.json()
        setAutoTrackedData(data)
      }
    } catch (error) {
      console.error('加载自动追踪数据失败:', error)
    } finally {
      setAutoTrackedLoading(false)
    }
  }

  // 打开编辑对话框
  const handleOpenEditDialog = async (character?: any) => {
    if (character) {
      setEditingCharacter(character)
      setFormData(character)
      // 加载自动追踪数据
      loadAutoTrackedData(character.id)
    } else {
      setEditingCharacter(null)
      setFormData({ name: '', role: '', faction: '' })
      setAutoTrackedData(null)
    }
    setEditDialogOpen(true)
  }

  // 关闭编辑对话框
  const handleCloseEditDialog = () => {
    setEditDialogOpen(false)
    setEditingCharacter(null)
    setFormData({})
    setAutoTrackedData(null)
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

  // 加载出场历程时间线
  const handleLoadTimeline = async (character: any) => {
    setTimelineLoading(true)
    setTimelineDialogOpen(true)
    setTimelineData(null)
    
    try {
      const response = await fetch(`/api/v1/characters/${character.id}/appearance-timeline`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })
      
      if (response.ok) {
        const data = await response.json()
        setTimelineData(data)
      } else {
        console.error('加载出场历程失败')
      }
    } catch (error) {
      console.error('加载出场历程失败:', error)
    } finally {
      setTimelineLoading(false)
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
                    <Tooltip title="出场历程">
                      <IconButton size="small" onClick={() => handleLoadTimeline(character)}>
                        <HistoryIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
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
      <Dialog open={editDialogOpen} onClose={handleCloseEditDialog} maxWidth="md" fullWidth>
        <DialogTitle>{editingCharacter ? '编辑角色' : '新建角色'}</DialogTitle>
        <DialogContent>
          <Grid container spacing={2}>
            {/* 第一行：姓名 + 故事立场 + 性别 */}
            <Grid item xs={4}>
              <TextField
                autoFocus
                margin="dense"
                label="姓名 *"
                fullWidth
                value={formData.name || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, name: e.target.value }))}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
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
            </Grid>
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label="性别"
                fullWidth
                value={formData.gender || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, gender: e.target.value }))}
              />
            </Grid>

            {/* 第二行：年龄 + 所属势力 + 重要性 */}
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label="年龄"
                type="number"
                fullWidth
                value={formData.age || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, age: e.target.value }))}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                margin="dense"
                label="所属势力"
                fullWidth
                value={formData.faction || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, faction: e.target.value }))}
              />
            </Grid>
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
                label="重要性（战力权重）"
                fullWidth
                value={formData.importance_level || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, importance_level: e.target.value }))}
              >
                <MenuItem value="">未设置</MenuItem>
                <MenuItem value="主角">主角</MenuItem>
                <MenuItem value="重要配角">重要配角</MenuItem>
                <MenuItem value="普通配角">普通配角</MenuItem>
                <MenuItem value="龙套">龙套</MenuItem>
              </TextField>
            </Grid>

            {/* 第三行：出场状态 + 生死状态 + 当前境界 */}
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
                label="出场状态"
                fullWidth
                value={formData.appearance_status || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, appearance_status: e.target.value }))}
              >
                <MenuItem value="">未设置</MenuItem>
                <MenuItem value="未出场">未出场</MenuItem>
                <MenuItem value="已出场">已出场</MenuItem>
                <MenuItem value="已退场">已退场</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
                label="生死状态"
                fullWidth
                value={formData.life_status || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, life_status: e.target.value }))}
              >
                <MenuItem value="">未设置</MenuItem>
                <MenuItem value="存活">存活</MenuItem>
                <MenuItem value="死亡">死亡</MenuItem>
                <MenuItem value="失踪">失踪</MenuItem>
                <MenuItem value="未知">未知</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={4}>
              <TextField
                select
                margin="dense"
                label="当前境界"
                fullWidth
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
            </Grid>

            {/* 人物简介 (1-3句话) */}
            <Grid item xs={12}>
              <TextField
                margin="dense"
                label="人物简介（1-3句话）"
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
                label="完整人物档案"
                fullWidth
                multiline
                rows={6}
                value={formData.profile || ''}
                onChange={(e) => setFormData((prev: any) => ({ ...prev, profile: e.target.value }))}
                placeholder="可包含外貌特征、性格特点、背景故事等详细信息"
              />
            </Grid>

            {/* 自动追踪关联（只读展示） */}
            {editingCharacter && (
              <Grid item xs={12}>
                <Box sx={{ mt: 2, p: 2, bgcolor: 'grey.50', borderRadius: 1, border: '1px solid', borderColor: 'grey.200' }}>
                  <Typography variant="subtitle2" sx={{ mb: 1.5, display: 'flex', alignItems: 'center', gap: 1 }}>
                    🤖 自动追踪关联（基于章节内容）
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
                          📜 掌握功法
                        </Typography>
                        {autoTrackedData.techniques?.length > 0 ? (
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {autoTrackedData.techniques.map((t: any) => (
                              <Chip
                                key={t.id}
                                size="small"
                                variant="outlined"
                                color="primary"
                                label={`${t.name}（第${t.chapters?.join(',') || '?'}章）`}
                              />
                            ))}
                          </Box>
                        ) : (
                          <Typography variant="body2" color="text.disabled">
                            尚未在章节中识别到该角色使用功法
                          </Typography>
                        )}
                      </Box>

                      {/* 持有法宝 */}
                      <Box>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                          ⚔️ 持有法宝
                        </Typography>
                        {autoTrackedData.artifacts?.length > 0 ? (
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {autoTrackedData.artifacts.map((a: any) => (
                              <Chip
                                key={a.id}
                                size="small"
                                variant="outlined"
                                color="warning"
                                label={`${a.name}（第${a.chapters?.join(',') || '?'}章）`}
                              />
                            ))}
                          </Box>
                        ) : (
                          <Typography variant="body2" color="text.disabled">
                            尚未在章节中识别到该角色持有法宝
                          </Typography>
                        )}
                      </Box>

                      {/* 关联地点 */}
                      <Box>
                        <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                          📍 关联地点
                        </Typography>
                        {autoTrackedData.locations?.length > 0 ? (
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                            {autoTrackedData.locations.map((l: any) => (
                              <Chip
                                key={l.id}
                                size="small"
                                variant="outlined"
                                color="success"
                                label={`${l.name}（第${l.chapters?.join(',') || '?'}章）`}
                              />
                            ))}
                          </Box>
                        ) : (
                          <Typography variant="body2" color="text.disabled">
                            尚未在章节中识别到该角色关联地点
                          </Typography>
                        )}
                      </Box>
                    </Box>
                  ) : (
                    <Typography variant="body2" color="text.disabled">
                      暂无自动追踪数据
                    </Typography>
                  )}
                </Box>
              </Grid>
            )}
          </Grid>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseEditDialog}>取消</Button>
          <Button variant="contained" onClick={handleSaveCharacter} disabled={!formData.name}>
            保存
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
            📖 {timelineData?.character_name || ''} 的出场历程
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
                  共出场 <strong>{timelineData.total_appearances}</strong> 章
                  {timelineData.first_appearance && (
                    <> · 首次出场第 <strong>{timelineData.first_appearance}</strong> 章</>
                  )}
                  {timelineData.last_appearance && (
                    <> · 最后出场第 <strong>{timelineData.last_appearance}</strong> 章</>
                  )}
                </Typography>
              </Box>

              {/* 时间线列表 */}
              {timelineData.timeline.length === 0 ? (
                <Box sx={{ textAlign: 'center', py: 4, color: 'text.secondary' }}>
                  该角色暂无出场记录
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
                            第{item.chapter_number}章：{item.chapter_title}
                          </Typography>
                          <Chip 
                            size="small" 
                            label={`${item.word_count}字`} 
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
              加载失败
            </Box>
          )}
        </DialogContent>
      </Dialog>
    </Box>
  )
}
