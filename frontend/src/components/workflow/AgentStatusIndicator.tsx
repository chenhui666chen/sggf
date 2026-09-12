import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
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

// Agent 中文名 → 英文 key（agent.name 为状态数据值，中文作匹配键）
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

// Agent key → workflow.agent.* 描述资源 key（未登记 agent 走 generic 后备）
const agentDescriptionKeys: Record<string, string> = {
  creative_director: 'workflow.agent.creativeDirectorDescription',
  world_architect: 'workflow.agent.worldArchitectDescription',
  character_designer: 'workflow.agent.characterDesignerDescription',
  plot_architect: 'workflow.agent.plotArchitectDescription',
  event_validator: 'workflow.agent.eventValidatorDescription',
  content_creator: 'workflow.agent.contentCreatorDescription',
  style_optimizer: 'workflow.agent.styleOptimizerDescription',
  quality_reviewer: 'workflow.agent.qualityReviewerDescription',
  iteration_coordinator: 'workflow.agent.iterationCoordinatorDescription',
  content_reviser: 'workflow.agent.contentReviserDescription',
  final_reviewer: 'workflow.agent.finalReviewerDescription',
}

// Agent key → 名称 i18n key（未登记 agent 显示原文数据值）
const agentNameKeys: Record<string, string> = {
  creative_director: 'workflow.agentNames.creativeDirector',
  world_architect: 'workflow.agentNames.worldArchitect',
  character_designer: 'workflow.agentNames.characterDesigner',
  plot_architect: 'workflow.agentNames.plotArchitect',
  event_validator: 'workflow.agentNames.eventValidator',
  content_creator: 'workflow.agentNames.contentCreator',
  style_optimizer: 'workflow.agentNames.styleOptimizer',
  quality_reviewer: 'workflow.agentNames.qualityReviewer',
  iteration_coordinator: 'workflow.agentNames.iterationCoordinator',
  outline_plan_parser: 'workflow.agentNames.outlinePlanParser',
  chapter_logic_checker: 'workflow.agentNames.chapterLogicChecker',
  content_reviser: 'workflow.agentNames.contentReviser',
  final_reviewer: 'workflow.agentNames.finalReviewer',
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
  const { t } = useTranslation()
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
      showSnackbar(t('workflow.agentEditor.loadFail', { error: err.response?.data?.detail || err.message }), 'error')
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
      if (!tpl.trim()) { showSnackbar(t('workflow.agentEditor.promptEmpty'), 'error'); return }
      setSaving(true)
      try {
        await apiClient.put(`/api/v1/agent-prompts/update-user-prompt/${promptKey}`, { prompt: tpl })
        setUserPrompts((prev) => ({ ...prev, [promptKey]: { ...prev[promptKey], is_customized: true } }))
        showSnackbar(t('workflow.agentEditor.userPromptSaved'), 'success')
        onSaveSuccess?.()
      } catch (err: any) {
        showSnackbar(t('workflow.agentEditor.saveFail', { error: err.response?.data?.detail || err.message }), 'error')
      } finally { setSaving(false) }
    } else {
      if (!systemPrompt.trim()) { showSnackbar(t('workflow.agentEditor.promptEmpty'), 'error'); return }
      setSaving(true)
      try {
        await apiClient.put(`/api/v1/agent-prompts/update/${agentKey}`, { prompt: systemPrompt })
        setIsCustomized(true)
        showSnackbar(t('workflow.agentEditor.agentPromptSaved', { name: agentName }), 'success')
        onSaveSuccess?.()
      } catch (err: any) {
        showSnackbar(t('workflow.agentEditor.saveFail', { error: err.response?.data?.detail || err.message }), 'error')
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
      showSnackbar(res.data.message || t('workflow.agentEditor.restoredDefault'), 'success')
      onSaveSuccess?.()
    } catch (err: any) {
      showSnackbar(t('workflow.agentEditor.resetFail', { error: err.response?.data?.detail || err.message }), 'error')
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
            <Typography variant="h6" fontWeight={600}>{t('workflow.agentEditor.title')}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ fontWeight: 400 }}>— {agentName}</Typography>
            {isCustomized && <Chip label={t('workflow.agentEditor.systemModifiedChip', { count: diffCount })} size="small" color="warning" variant="outlined" icon={<InfoIcon sx={{ fontSize: 14 }} />} />}
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
                  {isCustomized && <Alert severity="info" sx={{ mb: 2 }} icon={<InfoIcon />}><AlertTitle>{t('workflow.agentEditor.usingCustomPromptTitle')}</AlertTitle>{t('workflow.agentEditor.usingCustomPromptBody')}</Alert>}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Typography variant="subtitle2" color="text.secondary">System Prompt</Typography>
                    <Tooltip title={t('workflow.agentEditor.systemPromptTooltip')}><InfoIcon sx={{ fontSize: 16, color: 'text.disabled', cursor: 'help' }} /></Tooltip>
                  </Box>
                  <TextField fullWidth multiline minRows={15} maxRows={30} value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} variant="outlined" placeholder={t('workflow.agentEditor.systemPromptPlaceholder')} sx={{ '& .MuiInputBase-root': { fontFamily: 'monospace', fontSize: '0.875rem', lineHeight: 1.6 } }} />
                  <Box sx={{ mt: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary">{t('workflow.agentEditor.charCount', { count: systemPrompt.length })}</Typography>
                    {isCustomized && <Typography variant="caption" color="warning.main">{t('workflow.agentEditor.modifiedLines', { count: diffCount })}</Typography>}
                  </Box>
                </>
              )}

              {tab > 0 && currentUserPrompt && (
                <>
                  {currentUserPrompt.is_customized && <Alert severity="info" sx={{ mb: 2 }} icon={<InfoIcon />}><AlertTitle>{t('workflow.agentEditor.usingCustomTemplateTitle')}</AlertTitle>{t('workflow.agentEditor.usingCustomTemplateBody')}</Alert>}
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
                    <Typography variant="subtitle2" color="text.secondary">User Prompt Template</Typography>
                    <Tooltip title={t('workflow.agentEditor.userPromptTooltip')}><InfoIcon sx={{ fontSize: 16, color: 'text.disabled', cursor: 'help' }} /></Tooltip>
                  </Box>
                  <TextField fullWidth multiline minRows={12} maxRows={25} value={currentUserPrompt.template} onChange={(e) => setUserPrompts((prev) => ({ ...prev, [userPromptKeys[tab - 1]]: { ...prev[userPromptKeys[tab - 1]], template: e.target.value } }))} variant="outlined" placeholder={t('workflow.agentEditor.userPromptPlaceholder')} sx={{ '& .MuiInputBase-root': { fontFamily: 'monospace', fontSize: '0.875rem', lineHeight: 1.6 } }} />
                  <Box sx={{ mt: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <Typography variant="caption" color="text.secondary">{t('workflow.agentEditor.charCount', { count: currentUserPrompt.template.length })}</Typography>
                    {currentUserPrompt.is_customized && <Typography variant="caption" color="warning.main">{t('workflow.agentEditor.modifiedLines', { count: currentUserPromptDiff })}</Typography>}
                  </Box>
                </>
              )}
            </>
          )}
        </DialogContent>
        <Divider />
        <DialogActions sx={{ px: 2, py: 1.5, gap: 1 }}>
          <Button variant="outlined" color="warning" onClick={() => handleReset(tab > 0, tab > 0 ? userPromptKeys[tab - 1] : '')} disabled={resetting || loading || (tab === 0 && !isCustomized) || (tab > 0 && !currentUserPrompt?.is_customized)} startIcon={resetting ? <CircularProgress size={18} /> : <RestoreIcon />}>{t('workflow.agentEditor.restoreDefault')}</Button>
          <Box sx={{ flex: 1 }} />
          <Button variant="text" onClick={onClose}>{t('action.cancel')}</Button>
          <Button variant="contained" color="primary" onClick={() => handleSave(tab > 0, tab > 0 ? userPromptKeys[tab - 1] : '')} disabled={saving || loading || (tab === 0 && !systemPrompt.trim()) || (tab > 0 && !currentUserPrompt?.template?.trim())} startIcon={saving ? <CircularProgress size={18} /> : <SaveIcon />}>{t('action.save')}</Button>
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
  const { t } = useTranslation()
  const [editorOpen, setEditorOpen] = useState(false)

  const getAgentDescription = () => {
    const key = nameToKeyMap[agent.name]
    const descriptionKey = key ? agentDescriptionKeys[key] : ''
    if (descriptionKey) {
      return t(descriptionKey)
    }
    return t('workflow.agent.genericDescription', { name: agent.name })
  }

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
      case 'completed': return t('workflow.agent.statusCompleted')
      case 'error': return t('workflow.agent.statusError')
      case 'working': return t('workflow.agent.statusWorking')
      case 'idle': return t('workflow.agent.statusIdle')
      default: return t('workflow.agent.statusUnknown')
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
            <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>{agentNameKeys[agentKey] ? t(agentNameKeys[agentKey]) : agent.name}</Typography>
          </Box>
          <Tooltip title={agent.message || getStatusLabel()}>
            <Chip label={getStatusLabel()} size="small" color={getStatusColor() as any} variant="outlined" sx={{ height: 20, fontSize: '0.75rem' }} />
          </Tooltip>
        </Box>
      </Tooltip>

      {editorOpen && agentKey && (
        <PromptEditorInner agentName={agentNameKeys[agentKey] ? t(agentNameKeys[agentKey]) : agent.name} agentKey={agentKey} onClose={() => setEditorOpen(false)} />
      )}
    </>
  )
}
