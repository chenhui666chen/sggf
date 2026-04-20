import { useState, useEffect } from 'react'
import {
  Box,
  Typography,
  Chip,
  Tooltip,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Divider,
  Alert,
  AlertTitle,
  CircularProgress,
  Tabs,
  Tab,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import PlayCircleIcon from '@mui/icons-material/PlayCircle'
import CloseIcon from '@mui/icons-material/Close'
import RestoreIcon from '@mui/icons-material/Restore'
import SaveIcon from '@mui/icons-material/Save'
import InfoIcon from '@mui/icons-material/Info'
import { Agent } from '@/store/slices/workflowSlice'
import { apiClient } from '@/services/api'

// Agent 功能描述映射
const agentDescriptions: Record<string, string> = {
  '创意总监': '负责分析创作需求，确定整体创意方向和故事基调',
  '世界观架构师': '构建故事的世界观体系，包括时代背景、社会结构、文化特色等',
  '人物设计师': '设计角色的外貌、性格、背景故事和人物关系',
  '情节架构师': '规划故事的整体结构，设计事件序列和情节走向',
  '事件验证官': '验证事件逻辑的合理性，确保情节连贯性和可信度',
  '内容创作师': '根据大纲进行具体章节内容的创作',
  '文风优化师': '优化文字表达，确保语言风格统一流畅',
  '质量评审官': '对初稿进行全面评审，发现问题并提出改进建议',
  '迭代协调官': '分析评审反馈、确定优化优先级、制定改进计划并协调执行',
  '内容修订师': '根据评审意见和改进计划，修订和优化章节内容',
  '最终审核官': '对修订后的内容进行最终审核，确保质量达标后输出成品',
}

const nameToKeyMap: Record<string, string> = {
  '创意总监': 'creative_director',
  '世界观架构师': 'world_architect',
  '人物设计师': 'character_designer',
  '情节架构师': 'plot_architect',
  '事件验证官': 'event_validator',
  '内容创作师': 'content_creator',
  '文风优化师': 'style_optimizer',
  '质量评审官': 'quality_reviewer',
  '迭代协调官': 'iteration_coordinator',
  '大纲规划解析器': 'outline_plan_parser',
  '章节逻辑检查官': 'chapter_logic_checker',
  '内容修订师': 'content_reviser',
  '最终审核官': 'final_reviewer',
}

interface UserPromptData {
  key: string
  template: string
  default_template: string
  is_customized: boolean
}

function PromptEditorInner({
  agentName,
  agentKey,
  onClose,
  onSaveSuccess,
}: {
  agentName: string
  agentKey: string
  onClose: () => void
  onSaveSuccess?: () => void
}) {
  const [tab, setTab] = useState(0)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [defaultSystemPrompt, setDefaultSystemPrompt] = useState('')
  const [userPrompts, setUserPrompts] = useState<Record<string, UserPromptData>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [isCustomized, setIsCustomized] = useState(false)
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string; severity: 'success' | 'error' | 'info' }>({ open: false, message: '', severity: 'info' })

  const showSnackbar = (message: string, severity: 'success' | 'error' | 'info' = 'info') => {
    setSnackbar({ open: true, message, severity })
    setTimeout(() => setSnackbar((s) => ({ ...s, open: false })), 3000)
  }

  const loadDetail = async () => {
    setLoading(true)
    try {
      const res = await apiClient.get(`/api/v1/agent-prompts/detail/${agentKey}`)
      setSystemPrompt(res.data.prompt || '')
      setDefaultSystemPrompt(res.data.default_prompt || '')
      setIsCustomized(res.data.is_customized || false)
      setUserPrompts(res.data.user_prompts || {})
    } catch (err: any) {
      showSnackbar('加载提示词失败: ' + (err.response?.data?.detail || err.message), 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadDetail() }, [])

  const userPromptKeys = Object.keys(userPrompts)
  const hasUserPrompts = userPromptKeys.length > 0

  const diffCount = (() => {
    if (!isCustomized) return 0
    const a = systemPrompt.split('\n'), b = defaultSystemPrompt.split('\n')
    let c = 0
    for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) c++
    return c
  })()

  const handleSave = async (isUserPrompt = false, promptKey = '') => {
    if (isUserPrompt) {
      const tpl = userPrompts[promptKey]?.template || ''
      if (!tpl.trim()) { showSnackbar('提示词不能为空', 'error'); return }
      setSaving(true)
      try {
        await apiClient.put(`/api/v1/agent-prompts/update-user-prompt/${promptKey}`, { prompt: tpl })
        setUserPrompts((prev) => ({ ...prev, [promptKey]: { ...prev[promptKey], is_customized: true } }))
        showSnackbar(`User prompt 已保存`, 'success')
        onSaveSuccess?.()
      } catch (err: any) {
        showSnackbar('保存失败: ' + (err.response?.data?.detail || err.message), 'error')
      } finally { setSaving(false) }
    } else {
      if (!systemPrompt.trim()) { showSnackbar('提示词不能为空', 'error'); return }
      setSaving(true)
      try {
        await apiClient.put(`/api/v1/agent-prompts/update/${agentKey}`, { prompt: systemPrompt })
        setIsCustomized(true)
        showSnackbar(`「${agentName}」的提示词已保存`, 'success')
        onSaveSuccess?.()
      } catch (err: any) {
        showSnackbar('保存失败: ' + (err.response?.data?.detail || err.message), 'error')
      } finally { setSaving(false) }
    }
  }

  const handleReset = async (isUserPrompt = false, promptKey = '') => {
    setResetting(true)
    let res: any = { data: { message: '' } }
    try {
      if (isUserPrompt) {
        res = await apiClient.post(`/api/v1/agent-prompts/reset-user-prompt/${promptKey}`)
        if (res.data.message) {
          setUserPrompts((prev) => {
            const up = { ...prev }
            if (up[promptKey]) up[promptKey] = { ...up[promptKey], template: up[promptKey].default_template, is_customized: false }
            return up
          })
        }
        await loadDetail()
      } else {
        res = await apiClient.post(`/api/v1/agent-prompts/reset/${agentKey}`)
        await loadDetail()
      }
      showSnackbar(res.data.message || '已恢复为默认提示词', 'success')
      onSaveSuccess?.()
    } catch (err: any) {
      showSnackbar('重置失败: ' + (err.response?.data?.detail || err.message), 'error')
    } finally { setResetting(false) }
  }

  const currentUserPrompt = userPrompts[userPromptKeys[tab - 1] || ''] || null
  const currentUserPromptDiff = currentUserPrompt ? (() => {
    const a = currentUserPrompt.template.split('\n'), b = currentUserPrompt.default_template.split('\n')
    let c = 0
    for (let i = 0; i < Math.max(a.length, b.length); i++) if (a[i] !== b[i]) c++
    return c
  })() : 0

  return (
    <>
      <Dialog open onClose={onClose} maxWidth="md" fullWidth PaperProps={{ sx: { minHeight: '60vh', maxHeight: '90vh' } }}>
        <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', py: 1.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
            <Typography variant="h6" fontWeight={600}>编辑 Agent 提示词</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 400 }}>— {agentName}</Typography>
            {isCustomized && <Chip label={`System 已修改（差异 ${diffCount} 行）`} size="small" color="warning" variant="outlined" icon={<InfoIcon sx={{ fontSize: 14 }} />} />}
          </Box>
          <IconButton onClick={onClose} size="small"><CloseIcon /></IconButton>
        </DialogTitle>
        <Divider />
        <DialogContent sx={{ py: 2 }}>
          {loading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}><CircularProgress /></Box>
          ) : (
            <>
              <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
                <Tab label="System Prompt" />
                {hasUserPrompts && userPromptKeys.map((key) => (
                  <Tab key={key} label={`User Prompt: ${key.replace(agentKey + '_', '')}`} />
                ))}
              </Tabs>

              {tab === 0 && (
                <>
                  {isCustomized && <Alert severity="info" sx={{ mb: 2 }} icon={<InfoIcon />}><AlertTitle>当前使用自定义提示词</AlertTitle>此 Agent 的 system prompt 已被修改。您可以继续编辑，或点击「恢复默认」还原。</Alert>}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Typography variant="subtitle2" color="text.secondary">System Prompt</Typography>
                    <Tooltip title="这是发送给 LLM 的系统提示词，定义了 Agent 的角色、职责和行为规范"><InfoIcon sx={{ fontSize: 16, color: 'text.disabled', cursor: 'help' }} /></Tooltip>
                  </Box>
                  <TextField fullWidth multiline minRows={15} maxRows={30} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} variant="outlined" placeholder="输入系统提示词..." sx={{ '& .MuiInputBase-root': { fontFamily: 'monospace', fontSize: '0.875rem', lineHeight: 1.6 } }} />
                  <Box sx={{ mt: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary">{systemPrompt.length} 字符</Typography>
                    {isCustomized && <Typography variant="caption" color="warning.main">已修改 {diffCount} 行</Typography>}
                  </Box>
                </>
              )}

              {tab > 0 && currentUserPrompt && (
                <>
                  {currentUserPrompt.is_customized && <Alert severity="info" sx={{ mb: 2 }} icon={<InfoIcon />}><AlertTitle>当前使用自定义模板</AlertTitle>此 user prompt 已被修改。您可以继续编辑，或点击「恢复默认」还原。</Alert>}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Typography variant="subtitle2" color="text.secondary">User Prompt Template</Typography>
                    <Tooltip title="这是 Agent 在处理特定任务时使用的提示词模板，支持 {变量} 动态替换"><InfoIcon sx={{ fontSize: 16, color: 'text.disabled', cursor: 'help' }} /></Tooltip>
                  </Box>
                  <TextField fullWidth multiline minRows={12} maxRows={25} value={currentUserPrompt.template} onChange={(e) => setUserPrompts((prev) => ({ ...prev, [userPromptKeys[tab - 1]]: { ...prev[userPromptKeys[tab - 1]], template: e.target.value } }))} variant="outlined" placeholder="输入 user prompt 模板..." sx={{ '& .MuiInputBase-root': { fontFamily: 'monospace', fontSize: '0.875rem', lineHeight: 1.6 } }} />
                  <Box sx={{ mt: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary">{currentUserPrompt.template.length} 字符</Typography>
                    {currentUserPrompt.is_customized && <Typography variant="caption" color="warning.main">已修改 {currentUserPromptDiff} 行</Typography>}
                  </Box>
                </>
              )}
            </>
          )}
        </DialogContent>
        <Divider />
        <DialogActions sx={{ px: 2, py: 1.5, gap: 1 }}>
          <Button variant="outlined" color="warning" onClick={() => handleReset(tab > 0, tab > 0 ? userPromptKeys[tab - 1] : '')} disabled={resetting || loading || (tab === 0 && !isCustomized) || (tab > 0 && !currentUserPrompt?.is_customized)} startIcon={resetting ? <CircularProgress size={18} /> : <RestoreIcon />}>恢复默认</Button>
          <Box sx={{ flex: 1 }} />
          <Button variant="text" onClick={onClose}>取消</Button>
          <Button variant="contained" color="primary" onClick={() => handleSave(tab > 0, tab > 0 ? userPromptKeys[tab - 1] : '')} disabled={saving || loading || (tab === 0 && !systemPrompt.trim()) || (tab > 0 && !currentUserPrompt?.template?.trim())} startIcon={saving ? <CircularProgress size={18} /> : <SaveIcon />}>保存</Button>
        </DialogActions>
      </Dialog>

      {snackbar.open && <Box sx={{ position: 'fixed', bottom: 16, right: 16, zIndex: 9999 }}><Alert severity={snackbar.severity as any} onClose={() => setSnackbar((s) => ({ ...s, open: false }))} sx={{ minWidth: 280 }}>{snackbar.message}</Alert></Box>}
    </>
  )
}

interface AgentStatusIndicatorProps {
  agent: Agent
}

export default function AgentStatusIndicator({ agent }: AgentStatusIndicatorProps) {
  const [editorOpen, setEditorOpen] = useState(false)

  const getAgentDescription = () => agentDescriptions[agent.name] || `${agent.name} - 智能创作助手`

  const getStatusIcon = () => {
    switch (agent.status) {
      case 'completed': return <CheckCircleIcon sx={{ fontSize: 20, color: 'success.main' }} />
      case 'error': return <ErrorIcon sx={{ fontSize: 20, color: 'error.main' }} />
      case 'working': return <HourglassEmptyIcon sx={{ fontSize: 20, color: 'warning.main' }} />
      case 'idle': return <PlayCircleIcon sx={{ fontSize: 20, color: 'action.disabled' }} />
      default: return null
    }
  }

  const getStatusColor = () => {
    switch (agent.status) {
      case 'completed': return 'success'
      case 'error': return 'error'
      case 'working': return 'warning'
      default: return 'default'
    }
  }

  const getStatusLabel = () => {
    switch (agent.status) {
      case 'completed': return '已完成'
      case 'error': return '错误'
      case 'working': return '工作中'
      case 'idle': return '就绪'
      default: return '未知'
    }
  }

  const agentKey = nameToKeyMap[agent.name]
  const canEditPrompt = !!agentKey

  return (
    <>
      <Tooltip title={getAgentDescription()} placement="right" arrow enterDelay={300} leaveDelay={100}>
        <Box
          sx={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            py: 0.75, px: 1.5, mb: 1, bgcolor: 'grey.50', borderRadius: 1,
            border: '1px solid', borderColor: 'divider',
            cursor: canEditPrompt ? 'pointer' : 'help',
            transition: 'all 0.2s',
            '&:hover': { bgcolor: canEditPrompt ? 'primary.50' : 'grey.100', borderColor: canEditPrompt ? 'primary.main' : 'divider' },
          }}
          onClick={() => { if (canEditPrompt) setEditorOpen(true) }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {getStatusIcon()}
            <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>{agent.name}</Typography>
          </Box>
          <Tooltip title={agent.message || getStatusLabel()}>
            <Chip label={getStatusLabel()} size="small" color={getStatusColor() as any} variant="outlined" sx={{ height: 20, fontSize: '0.75rem' }} />
          </Tooltip>
        </Box>
      </Tooltip>

      {editorOpen && agentKey && (
        <PromptEditorInner agentName={agent.name} agentKey={agentKey} onClose={() => setEditorOpen(false)} />
      )}
    </>
  )
}
