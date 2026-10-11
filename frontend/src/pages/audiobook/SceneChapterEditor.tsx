import { useCallback, useEffect, useMemo, useState } from 'react'

import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from '@mui/material'
import AddIcon from '@mui/icons-material/Add'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import CloseIcon from '@mui/icons-material/Close'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import {
  applySegmentDetailDraft,
  segmentMusicCueDraftValue,
  segmentSoundEffectsDraftValue,
  serializeVoiceCharacters,
  voiceBindingDraftFromEcho,
  EMPTY_VOICE_CHARACTER_DRAFT,
  type SegmentDetailDraft,
  type VoiceCharacterDraft,
} from './sceneEditorDraftUtils'
import { useAudiobookSceneVoicePool } from './useAudiobookSceneVoicePool'
import { markSeedSceneIncompatibleVoicePresets } from './seedSceneVoiceCompatibility'
import { TTS_MODELS, getTtsModelLabel } from './ttsModels'
import type {
  SceneDirectionOverrideItem,
  SceneEditSaveResponse,
  SceneEditorDocument,
  SceneEditorScene,
  SceneEditType,
  ScriptSegment,
  VoicePreset,
} from './types'

/**
 * 场景编辑器（GUIDE 阶段 3.5，seed_scene 引擎章节编辑入口）。
 *
 * 由 AudiobookPage 点击已生成章节分流打开（§3.1）：legacy_stems 走剧本编辑器，
 * seed_scene 走本组件。三段式编辑（台词/dialogue、导演覆盖/director_override、
 * 音色/voice_binding）均携带 base_revision_hash，409 Conflict 提示刷新。
 */
export interface SceneChapterEditorProps {
  open: boolean
  chapterId: number
  /** 章节序号（标题展示优先；缺省回退 chapterId）。 */
  chapterNumber?: number | null
  audiobookProjectId: number
  engineMode: 'legacy_stems' | 'seed_scene'
  renderStatus: string | null
  /** 批次切换器列表（§2.5 规则 3：同引擎多批次时可切换）。 */
  batches?: readonly {
    id: number
    engine_mode?: string | null
    created_at?: string | null
  }[]
  onSwitchBatch?: (audiobookProjectId: number) => void
  /** 复用 useAudiobookAudioPlayback.playExternalUrl。 */
  onPreviewAudio?: (url: string) => void
  /** 保存成功回调（父级刷新 chapterStateById 与项目详情）。 */
  onSaved?: () => void
  onClose: () => void
  /** 禁用 portal（SSR 测试等场景下直接渲染内容）。 */
  disablePortal?: boolean
}

export const SCENE_STATUS_LABELS: Record<string, { labelKey: string; color: 'success' | 'warning' | 'info' | 'default' | 'error' }> = {
  passed: { labelKey: 'audiobook.sceneChapterEditor.statusLabels.passed', color: 'success' },
  manual_review: { labelKey: 'audiobook.sceneChapterEditor.statusLabels.manualReview', color: 'warning' },
  legacy_stems: { labelKey: 'audiobook.sceneChapterEditor.statusLabels.legacyStems', color: 'info' },
  stale: { labelKey: 'audiobook.sceneChapterEditor.statusLabels.stale', color: 'default' },
  failed: { labelKey: 'audiobook.sceneChapterEditor.statusLabels.failed', color: 'error' },
}

export const EDIT_TYPE_LABELS: Record<SceneEditType, string> = {
  dialogue: 'audiobook.sceneChapterEditor.editTypeTabs.dialogue',
  director_override: 'audiobook.sceneChapterEditor.editTypeTabs.directorOverride',
  voice_binding: 'audiobook.sceneChapterEditor.editTypeTabs.voiceBinding',
}

/** P2：导演覆盖类型中文标签与用途说明。 */
export const DIRECTION_TYPE_LABELS: Record<string, string> = {
  performance: 'audiobook.sceneChapterEditor.directionTypeLabels.performance',
  sfx: 'audiobook.sceneChapterEditor.directionTypeLabels.sfx',
  music: 'audiobook.sceneChapterEditor.directionTypeLabels.music',
  acoustic: 'audiobook.sceneChapterEditor.directionTypeLabels.acoustic',
}

export const DIRECTION_TYPE_HINTS: Record<string, string> = {
  performance: 'audiobook.sceneChapterEditor.directionTypeHints.performance',
  sfx: 'audiobook.sceneChapterEditor.directionTypeHints.sfx',
  music: 'audiobook.sceneChapterEditor.directionTypeHints.music',
  acoustic: 'audiobook.sceneChapterEditor.directionTypeHints.acoustic',
}

const sceneStatusChip = (status: string, t: TFunction) => {
  const config = SCENE_STATUS_LABELS[String(status || '').toLowerCase()] ?? {
    labelKey: status || 'unknown',
    color: 'default' as const,
  }
  return <Chip size="small" color={config.color} variant="outlined" label={t(config.labelKey)} />
}

const SceneChapterEditor = ({
  open,
  chapterId,
  chapterNumber = null,
  audiobookProjectId,
  renderStatus,
  batches = [],
  onSwitchBatch,
  onPreviewAudio,
  onSaved,
  onClose,
  disablePortal = false,
}: SceneChapterEditorProps) => {
  const { t } = useTranslation()
  const [document, setDocument] = useState<SceneEditorDocument | null>(null)
  const [scriptSegments, setScriptSegments] = useState<ScriptSegment[]>([])
  const [scriptStatus, setScriptStatus] = useState('pending')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<SceneEditType>('dialogue')
  const [selectedSceneId, setSelectedSceneId] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [conflictMessage, setConflictMessage] = useState<string | null>(null)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)

  // 台词细编草稿（segment_key -> 编辑过的字段；仅覆盖用户改过的项）
  const [dialogueDraft, setDialogueDraft] = useState<Record<string, SegmentDetailDraft>>({})
  // 渲染提示词展示区开关（P1 透明化）
  const [showPrompt, setShowPrompt] = useState(false)
  // 导演覆盖草稿
  const [overrideDraft, setOverrideDraft] = useState<SceneDirectionOverrideItem[]>([])
  // 音色编辑草稿（P2：结构化角色表单行）
  const [ttsModelDraft, setTtsModelDraft] = useState('')
  const [voiceRows, setVoiceRows] = useState<VoiceCharacterDraft[]>([
    { ...EMPTY_VOICE_CHARACTER_DRAFT },
  ])

  // 音色库（私有复刻/设计 + 公共音色池）：仅编辑器打开时拉取
  const sceneVoicePool = useAudiobookSceneVoicePool(open)
  const voicePresetOptions = useMemo<VoicePreset[]>(
    () => markSeedSceneIncompatibleVoicePresets(sceneVoicePool.presets),
    [sceneVoicePool.presets],
  )

  const resetDrafts = useCallback(() => {
    setDialogueDraft({})
    setOverrideDraft([])
    setTtsModelDraft('')
    setVoiceRows([{ ...EMPTY_VOICE_CHARACTER_DRAFT }])
    setConflictMessage(null)
    setSaveMessage(null)
  }, [])

  const loadDocument = useCallback(async () => {
    if (!open || !audiobookProjectId || !chapterId) {
      return
    }
    setLoading(true)
    setError(null)
    resetDrafts()
    try {
      const [docRes, scriptRes] = await Promise.all([
        apiClient.getSceneEditorDocument(audiobookProjectId, chapterId),
        apiClient.getAudiobookChapterScript(audiobookProjectId, chapterId),
      ])
      const doc = docRes.data as unknown as SceneEditorDocument
      setDocument(doc)
      setScriptSegments(
        Array.isArray((scriptRes.data as { script_segments?: unknown })?.script_segments)
          ? (scriptRes.data as { script_segments: ScriptSegment[] }).script_segments
          : [],
      )
      setScriptStatus(
        typeof (scriptRes.data as { script_status?: unknown })?.script_status === 'string'
          ? (scriptRes.data as { script_status: string }).script_status
          : 'pending',
      )
      setSelectedSceneId((prev) => {
        if (prev && doc.scenes.some((scene) => scene.scene_id === prev)) {
          return prev
        }
        return doc.scenes[0]?.scene_id ?? null
      })
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, t('audiobook.sceneChapterEditor.loadFailed')))
    } finally {
      setLoading(false)
    }
  }, [audiobookProjectId, chapterId, open, resetDrafts])

  useEffect(() => {
    if (open) {
      void loadDocument()
    } else {
      setDocument(null)
      setScriptSegments([])
      setError(null)
    }
  }, [open, loadDocument])

  // 场景切换时初始化导演覆盖草稿（锚点与基线 hash 自动填充）
  useEffect(() => {
    if (!document || !selectedSceneId) {
      return
    }
    const scene = document.scenes.find((item) => item.scene_id === selectedSceneId)
    if (!scene) {
      return
    }
    const existing = document.editable_overrides?.[scene.scene_id] as
      | { overrides?: unknown }
      | undefined
    const existingItems: SceneDirectionOverrideItem[] = Array.isArray(existing?.overrides)
      ? (existing.overrides as SceneDirectionOverrideItem[])
      : []
    setOverrideDraft(existingItems.length > 0 ? existingItems.map((item) => ({ ...item })) : [
      { direction_type: 'performance', content: '' },
    ])
    // 回显当前生效的音色绑定，让用户基于已有配置修改而非从空表单起步
    const voiceEcho = voiceBindingDraftFromEcho(document.voice_binding_current)
    setTtsModelDraft(voiceEcho.ttsModel)
    setVoiceRows(voiceEcho.rows)
  }, [document, selectedSceneId])

  const selectedScene = useMemo(
    () => document?.scenes.find((scene) => scene.scene_id === selectedSceneId) ?? null,
    [document, selectedSceneId],
  )

  const sceneSegments = useMemo(() => {
    if (!selectedScene) {
      return []
    }
    const keys = new Set(selectedScene.source_segment_keys ?? [])
    const segmentKeyOf = (segment: ScriptSegment) => String(segment.segment_key || '')
    return scriptSegments.filter((segment) => keys.has(segmentKeyOf(segment)))
  }, [scriptSegments, selectedScene])

  const baseRevisionHash = (editType: SceneEditType): string | null => (
    document?.last_revisions?.[editType]?.revision_hash ?? null
  )

  const handleConflict = useCallback(async (err: unknown) => {
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 409) {
      setConflictMessage(t('audiobook.sceneChapterEditor.conflictMessage'))
      await loadDocument()
      return true
    }
    setConflictMessage(await extractApiErrorMessage(err, t('audiobook.sceneChapterEditor.saveFailed')))
    return false
  }, [loadDocument])

  const applySaveResponse = useCallback((response: SceneEditSaveResponse, editType: SceneEditType) => {
    setDocument((prev) => (prev ? {
      ...prev,
      last_revisions: response.revision_heads,
      revision_set_hash: response.revision_set_hash ?? prev.revision_set_hash,
      script_status: response.script_status ?? prev.script_status,
    } : prev))
    setSaveMessage(t('audiobook.sceneChapterEditor.savedMessage', { type: t(EDIT_TYPE_LABELS[editType]) }))
    setConflictMessage(null)
    onSaved?.()
  }, [onSaved])

  const updateDialogueDraft = useCallback((draftKey: string, patch: SegmentDetailDraft) => {
    setDialogueDraft((prev) => ({
      ...prev,
      [draftKey]: { ...prev[draftKey], ...patch },
    }))
  }, [])

  const handleSaveDialogue = useCallback(async () => {
    if (!document) return
    setSaving(true)
    try {
      // 声音设计字段随台词一起提交，后端 sanitize 保留并转译进渲染提示词
      const segments = scriptSegments.map((segment) => applySegmentDetailDraft(
        segment,
        dialogueDraft[String(segment.segment_key || segment.index || '')],
      ))
      const response = (await apiClient.updateSceneEditorDocument(
        audiobookProjectId,
        chapterId,
        'dialogue',
        {
          script_segments: segments,
          base_revision_hash: baseRevisionHash('dialogue'),
        },
      )).data
      applySaveResponse(response, 'dialogue')
      setScriptSegments(segments)
    } catch (err: unknown) {
      await handleConflict(err)
    } finally {
      setSaving(false)
    }
  }, [audiobookProjectId, chapterId, dialogueDraft, document, handleConflict, scriptSegments, applySaveResponse])

  const handleSaveDirectorOverride = useCallback(async () => {
    if (!document || !selectedScene) return
    setSaving(true)
    try {
      const scene = selectedScene
      const response = (await apiClient.updateSceneEditorDocument(
        audiobookProjectId,
        chapterId,
        'director_override',
        {
          scene_id: scene.scene_id,
          stable_anchors: {
            source_segment_keys: scene.source_segment_keys ?? [],
            baseline_script_revision_hash: document.source_script_revision,
            baseline_scene_topology_hash: document.scene_topology_hash ?? '',
          },
          overrides: overrideDraft.filter((item) => String(item.content || '').trim() !== ''),
          base_revision_hash: baseRevisionHash('director_override'),
        },
      )).data
      applySaveResponse(response, 'director_override')
    } catch (err: unknown) {
      await handleConflict(err)
    } finally {
      setSaving(false)
    }
  }, [audiobookProjectId, chapterId, document, handleConflict, overrideDraft, selectedScene, applySaveResponse])

  const handleSaveVoiceBinding = useCallback(async () => {
    if (!document) return
    const characters = serializeVoiceCharacters(voiceRows)
    if (characters.length === 0) {
      setConflictMessage(t('audiobook.sceneChapterEditor.noCharacters'))
      return
    }
    setSaving(true)
    try {
      const response = (await apiClient.updateSceneEditorDocument(
        audiobookProjectId,
        chapterId,
        'voice_binding',
        {
          tts_model: ttsModelDraft.trim() || null,
          characters,
          base_revision_hash: baseRevisionHash('voice_binding'),
        },
      )).data
      applySaveResponse(response, 'voice_binding')
    } catch (err: unknown) {
      await handleConflict(err)
    } finally {
      setSaving(false)
    }
  }, [audiobookProjectId, chapterId, document, handleConflict, ttsModelDraft, voiceRows, applySaveResponse])

  /** 以当前编辑基线重渲染整章（GUIDE §3.2：revision_set_hash 失配 409 提示刷新）。 */
  const handleRerender = useCallback(async () => {
    if (!document || !document.revision_set_hash) return
    setSaving(true)
    try {
      await apiClient.generateAudioFromScripts(audiobookProjectId, {
        chapter_ids: [chapterId],
        revision_set_hash: document.revision_set_hash,
      })
      setSaveMessage(t('audiobook.sceneChapterEditor.rerenderSubmitted'))
      setConflictMessage(null)
      onSaved?.()
    } catch (err: unknown) {
      await handleConflict(err)
    } finally {
      setSaving(false)
    }
  }, [audiobookProjectId, chapterId, document, handleConflict, onSaved])

  /** seed_scene dialogue 链独立审批（R8，§2.9 审批闭环）：verdict=approved 一次性直批。 */
  const handleApproveScript = useCallback(async () => {
    if (!document) return
    setSaving(true)
    try {
      const response = (await apiClient.reviewSceneDialogue(audiobookProjectId, chapterId, {
        verdict: 'approved',
        review_json: { source: 'scene_editor' },
        base_revision_set_hash: document.revision_set_hash ?? null,
      })).data
      const nextStatus = response.script_status ?? 'approved'
      setDocument((prev) => (prev ? { ...prev, script_status: nextStatus } : prev))
      setScriptStatus(nextStatus)
      setSaveMessage(t('audiobook.sceneChapterEditor.scriptApproved'))
      setConflictMessage(null)
      onSaved?.()
    } catch (err: unknown) {
      await handleConflict(err)
    } finally {
      setSaving(false)
    }
  }, [audiobookProjectId, chapterId, document, handleConflict, onSaved])

  const handlePreviewScene = useCallback((scene: SceneEditorScene) => {
    if (scene.scene_audio_url && onPreviewAudio) {
      onPreviewAudio(scene.scene_audio_url)
    }
  }, [onPreviewAudio])

  const seedBatches = useMemo(
    () => batches.filter((batch) => (batch.engine_mode || 'legacy_stems') === 'seed_scene'),
    [batches],
  )

  return (
    <Dialog
      open={open}
      onClose={onClose}
      fullWidth
      maxWidth="lg"
      disablePortal={disablePortal}
      aria-labelledby="scene-chapter-editor-title"
    >
      <DialogTitle id="scene-chapter-editor-title">
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
          <GraphicEqIcon color="primary" />
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            {t('audiobook.sceneChapterEditor.title', { number: chapterNumber ?? chapterId })}
          </Typography>
          {renderStatus && (
            <Chip size="small" color="primary" variant="outlined" label={renderStatus} />
          )}
          <IconButton aria-label="close" onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Stack>
      </DialogTitle>
      <DialogContent dividers sx={{ minHeight: 480 }}>
        {seedBatches.length > 1 && (
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2, flexWrap: 'wrap' }}>
            <Typography variant="caption" color="text.secondary">
              {t('audiobook.sceneChapterEditor.batchSwitcher')}
            </Typography>
            <ToggleButtonGroup
              size="small"
              exclusive
              value={audiobookProjectId}
              onChange={(_, value) => {
                if (typeof value === 'number' && value !== audiobookProjectId) {
                  onSwitchBatch?.(value)
                }
              }}
            >
              {seedBatches.map((batch) => (
                <ToggleButton key={batch.id} value={batch.id}>
                  #{batch.id}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Stack>
        )}

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 8 }}>
            <CircularProgress />
          </Box>
        )}
        {!loading && error && (
          <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
        )}
        {!loading && !error && document && (
          <Stack direction="row" spacing={2} sx={{ height: '100%' }}>
            {/* 左侧：场景列表 */}
            <Box sx={{ width: 300, flexShrink: 0, overflowY: 'auto', maxHeight: 520 }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                {t('audiobook.sceneChapterEditor.sceneListTitle', { count: document.scenes.length })}
              </Typography>
              <List dense disablePadding>
                {document.scenes.map((scene) => (
                  <ListItemButton
                    key={scene.scene_id}
                    selected={scene.scene_id === selectedSceneId}
                    onClick={() => setSelectedSceneId(scene.scene_id)}
                    sx={{ borderRadius: 1, mb: 0.5 }}
                  >
                    <ListItemText
                      primary={
                        <Stack direction="row" alignItems="center" spacing={1}>
                          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                            {scene.scene_id}
                          </Typography>
                          {sceneStatusChip(scene.status, t)}
                        </Stack>
                      }
                      secondary={(
                        <Stack direction="row" alignItems="center" spacing={1}>
                          <Typography variant="caption" color="text.secondary">
                            {typeof scene.metadata?.expected_duration_s === 'number'
                              ? `${scene.metadata.expected_duration_s.toFixed(1)}s`
                              : '--'}
                          </Typography>
                          {scene.attempts ? t('audiobook.sceneChapterEditor.retryCount', { count: scene.attempts }) : ''}
                        </Stack>
                      )}
                    />
                    <IconButton
                      size="small"
                      aria-label={t('audiobook.sceneChapterEditor.previewAria', { id: scene.scene_id })}
                      disabled={!scene.scene_audio_url}
                      onClick={(event) => {
                        event.stopPropagation()
                        handlePreviewScene(scene)
                      }}
                    >
                      <PlayArrowIcon fontSize="small" />
                    </IconButton>
                  </ListItemButton>
                ))}
              </List>
              <Divider sx={{ my: 1 }} />
              <Typography variant="caption" color="text.secondary">
                {t('audiobook.sceneChapterEditor.executionStatus', { status: document.execution_status })}
                {document.desired_render_status
                  ? t('audiobook.sceneChapterEditor.desiredStatusSuffix', { status: document.desired_render_status })
                  : ''}
              </Typography>
            </Box>

            <Divider orientation="vertical" flexItem />

            {/* 右侧：三段式编辑 */}
            <Box sx={{ flexGrow: 1, minWidth: 0 }}>
              <Tabs
                value={activeTab}
                onChange={(_, value: SceneEditType) => setActiveTab(value)}
                sx={{ mb: 1 }}
              >
                <Tab label={t(EDIT_TYPE_LABELS.dialogue)} value="dialogue" />
                <Tab label={t(EDIT_TYPE_LABELS.director_override)} value="director_override" />
                <Tab label={t(EDIT_TYPE_LABELS.voice_binding)} value="voice_binding" />
              </Tabs>

              {conflictMessage && (
                <Alert severity="warning" sx={{ mb: 1 }} onClose={() => setConflictMessage(null)}>
                  {conflictMessage}
                </Alert>
              )}
              {saveMessage && (
                <Alert severity="success" sx={{ mb: 1 }} onClose={() => setSaveMessage(null)}>
                  {saveMessage}
                </Alert>
              )}

              {activeTab === 'dialogue' && (
                <Box sx={{ maxHeight: 420, overflowY: 'auto' }}>
                  <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                    <Typography variant="subtitle2">{t('audiobook.sceneChapterEditor.reviewedScript')}</Typography>
                    <Chip size="small" label={`script_status: ${scriptStatus}`} />
                    {document.chapter_audio_stale && (
                      <Chip size="small" color="warning" variant="outlined" label={t('audiobook.sceneChapterEditor.audioStale')} />
                    )}
                    {document.script_status === 'pending' && (
                      <Tooltip title={t('audiobook.sceneChapterEditor.pendingReviewTooltip')}>
                        <Chip size="small" color="warning" variant="outlined" label={t('audiobook.sceneChapterEditor.pendingReview')} />
                      </Tooltip>
                    )}
                  </Stack>
                  {/* P1 透明化：渲染时发送的完整提示词对用户可见可对照 */}
                  {selectedScene && (
                    <Box sx={{ mb: 1.5 }}>
                      <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
                        <Button size="small" onClick={() => setShowPrompt((prev) => !prev)}>
                          {showPrompt ? t('audiobook.sceneChapterEditor.hidePrompt') : t('audiobook.sceneChapterEditor.showPrompt')}
                        </Button>
                        <Typography variant="caption" color="text.secondary">
                          {t('audiobook.sceneChapterEditor.promptExplain')}
                        </Typography>
                      </Stack>
                      <Collapse in={showPrompt}>
                        <Box
                          sx={{
                            mt: 1,
                            p: 1,
                            borderRadius: 1,
                            bgcolor: 'action.hover',
                            maxHeight: 240,
                            overflowY: 'auto',
                          }}
                        >
                          {selectedScene.prompt ? (
                            <Typography
                              variant="body2"
                              component="pre"
                              sx={{ whiteSpace: 'pre-wrap', fontFamily: 'monospace', m: 0 }}
                            >
                              {selectedScene.prompt}
                            </Typography>
                          ) : (
                            <Typography variant="caption" color="text.secondary">
                              {t('audiobook.sceneChapterEditor.promptMissingLegacy')}
                            </Typography>
                          )}
                        </Box>
                      </Collapse>
                    </Box>
                  )}
                  {sceneSegments.length === 0 && (
                    <Typography variant="body2" color="text.secondary">
                      {t('audiobook.sceneChapterEditor.noSceneSegments')}
                    </Typography>
                  )}
                  {sceneSegments.map((segment) => {
                    const draftKey = String(segment.segment_key || segment.index || '')
                    const draft = dialogueDraft[draftKey]
                    return (
                      <Box
                        key={draftKey}
                        sx={{
                          mb: 2,
                          p: 1.5,
                          border: '1px solid',
                          borderColor: 'divider',
                          borderRadius: 1,
                        }}
                      >
                        <TextField
                          size="small"
                          fullWidth
                          multiline
                          minRows={2}
                          sx={{ mb: 1 }}
                          label={`${segment.speaker || segment.speaker_name || t('audiobook.sceneChapterEditor.narrator')} · ${segment.segment_key || `#${segment.index ?? ''}`}`}
                          value={draft?.text ?? segment.text ?? ''}
                          onChange={(event) => updateDialogueDraft(draftKey, { text: event.target.value })}
                        />
                        <TextField
                          size="small"
                          fullWidth
                          sx={{ mb: 1 }}
                          label={t('audiobook.sceneChapterEditor.sceneEnvLabel')}
                          placeholder={t('audiobook.sceneChapterEditor.sceneEnvPlaceholder')}
                          value={draft?.instruct_scene ?? segment.instruct_scene ?? ''}
                          onChange={(event) => updateDialogueDraft(draftKey, { instruct_scene: event.target.value })}
                        />
                        <TextField
                          size="small"
                          fullWidth
                          sx={{ mb: 1 }}
                          label={t('audiobook.sceneChapterEditor.performanceLabel')}
                          placeholder={t('audiobook.sceneChapterEditor.performancePlaceholder')}
                          value={draft?.performance_notes ?? segment.performance_notes ?? ''}
                          onChange={(event) => updateDialogueDraft(draftKey, { performance_notes: event.target.value })}
                        />
                        <TextField
                          size="small"
                          fullWidth
                          multiline
                          minRows={2}
                          sx={{ mb: 1 }}
                          label={t('audiobook.sceneChapterEditor.sfxLabel')}
                          placeholder={t('audiobook.sceneChapterEditor.sfxPlaceholder')}
                          helperText={t('audiobook.sceneChapterEditor.sfxHelper')}
                          value={draft?.sound_effects ?? segmentSoundEffectsDraftValue(segment)}
                          onChange={(event) => updateDialogueDraft(draftKey, { sound_effects: event.target.value })}
                        />
                        <TextField
                          size="small"
                          fullWidth
                          label={t('audiobook.sceneChapterEditor.musicLabel')}
                          placeholder={t('audiobook.sceneChapterEditor.musicPlaceholder')}
                          helperText={t('audiobook.sceneChapterEditor.musicHelper')}
                          value={draft?.music_cue ?? segmentMusicCueDraftValue(segment)}
                          onChange={(event) => updateDialogueDraft(draftKey, { music_cue: event.target.value })}
                        />
                      </Box>
                    )
                  })}
                  {sceneSegments.length > 0 && (
                    <Button
                      variant="contained"
                      size="small"
                      disabled={saving || Object.keys(dialogueDraft).length === 0}
                      onClick={() => void handleSaveDialogue()}
                    >
                      {t('audiobook.sceneChapterEditor.saveDialogue')}
                    </Button>
                  )}
                  <Stack direction="row" alignItems="center" spacing={1} sx={{ mt: 2 }}>
                    {document.script_status !== 'approved' && (
                      <Tooltip title={t('audiobook.sceneChapterEditor.approveTooltip')}>
                        <span>
                          <Button
                            variant="contained"
                            size="small"
                            startIcon={<CheckCircleOutlineIcon />}
                            disabled={saving || loading}
                            onClick={() => void handleApproveScript()}
                          >
                            {t('audiobook.sceneChapterEditor.approve')}
                          </Button>
                        </span>
                      </Tooltip>
                    )}
                    <Tooltip title={document.script_status === 'approved' && document.revision_set_hash
                      ? t('audiobook.sceneChapterEditor.rerenderTooltipReady')
                      : t('audiobook.sceneChapterEditor.rerenderTooltipBlocked')}>
                      <span>
                        <Button
                          variant="outlined"
                          size="small"
                          startIcon={<AutoAwesomeIcon />}
                          disabled={saving || document.script_status !== 'approved' || !document.revision_set_hash}
                          onClick={() => void handleRerender()}
                        >
                          {t('audiobook.sceneChapterEditor.rerender')}
                        </Button>
                      </span>
                    </Tooltip>
                    {document.script_status !== 'approved' && (
                      <Typography variant="caption" color="text.secondary">
                        {t('audiobook.sceneChapterEditor.approveHint', { status: scriptStatus })}
                      </Typography>
                    )}
                  </Stack>
                </Box>
              )}

              {activeTab === 'director_override' && (
                <Box sx={{ maxHeight: 420, overflowY: 'auto' }}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    {t('audiobook.sceneChapterEditor.directorOverrideTitle', { id: selectedScene?.scene_id ?? t('audiobook.sceneChapterEditor.noSceneSelected') })}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    {t('audiobook.sceneChapterEditor.stableAnchors', { anchors: selectedScene?.source_segment_keys?.join(', ') || t('audiobook.sceneChapterEditor.noAnchors') })}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                    {t('audiobook.sceneChapterEditor.overrideExplain')}
                  </Typography>
                  {Object.entries(DIRECTION_TYPE_LABELS).map(([type, labelKey]) => (
                    <Typography key={type} variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      {t('audiobook.sceneChapterEditor.directionTypeLine', { label: t(labelKey), type, hint: t(DIRECTION_TYPE_HINTS[type]) })}
                    </Typography>
                  ))}
                  <Box sx={{ height: 8 }} />
                  {overrideDraft.map((item, index) => (
                    <Stack key={index} direction="row" spacing={1} sx={{ mb: 1 }}>
                      <TextField
                        select
                        size="small"
                        sx={{ width: 180 }}
                        label={t('audiobook.sceneChapterEditor.overrideTypeLabel')}
                        value={item.direction_type}
                        onChange={(event) => {
                          setOverrideDraft((prev) => prev.map((entry, i) => (
                            i === index ? { ...entry, direction_type: event.target.value } : entry
                          )))
                        }}
                      >
                        {['performance', 'sfx', 'music', 'acoustic'].map((type) => (
                          <option key={type} value={type}>
                            {t('audiobook.sceneChapterEditor.overrideTypeOption', { label: t(DIRECTION_TYPE_LABELS[type]), type })}
                          </option>
                        ))}
                      </TextField>
                      <TextField
                        size="small"
                        fullWidth
                        multiline
                        label={t('audiobook.sceneChapterEditor.overrideContentLabel')}
                        value={item.content}
                        onChange={(event) => {
                          setOverrideDraft((prev) => prev.map((entry, i) => (
                            i === index ? { ...entry, content: event.target.value } : entry
                          )))
                        }}
                      />
                      <IconButton
                        size="small"
                        onClick={() => {
                          setOverrideDraft((prev) => prev.filter((_, i) => i !== index))
                        }}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Stack>
                  ))}
                  <Stack direction="row" spacing={1}>
                    <Button
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={() => {
                        setOverrideDraft((prev) => [
                          ...prev,
                          { direction_type: 'performance', content: '' },
                        ])
                      }}
                    >
                      {t('audiobook.sceneChapterEditor.addOverride')}
                    </Button>
                    <Button
                      variant="contained"
                      size="small"
                      disabled={saving || !selectedScene}
                      onClick={() => void handleSaveDirectorOverride()}
                    >
                      {t('audiobook.sceneChapterEditor.saveOverride')}
                    </Button>
                  </Stack>
                </Box>
              )}

              {activeTab === 'voice_binding' && (
                <Box sx={{ maxHeight: 420, overflowY: 'auto' }}>
                  <Typography variant="subtitle2" sx={{ mb: 1 }}>
                    {t('audiobook.sceneChapterEditor.voiceBindingTitle')}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                    {t('audiobook.sceneChapterEditor.voiceBindingExplain')}
                  </Typography>
                  {sceneVoicePool.error && (
                    <Alert severity="warning" sx={{ mb: 1 }}>
                      {t('audiobook.sceneChapterEditor.voicePoolError', { error: sceneVoicePool.error })}
                    </Alert>
                  )}
                  <TextField
                    size="small"
                    fullWidth
                    select
                    sx={{ mb: 1.5 }}
                    label={t('audiobook.sceneChapterEditor.ttsModelLabel')}
                    helperText={t('audiobook.sceneChapterEditor.ttsModelHelper')}
                    value={ttsModelDraft}
                    onChange={(event) => setTtsModelDraft(event.target.value)}
                  >
                    {ttsModelDraft && !(TTS_MODELS as readonly string[]).includes(ttsModelDraft) && (
                      <MenuItem value={ttsModelDraft}>{t('audiobook.sceneChapterEditor.ttsModelCurrent', { model: ttsModelDraft })}</MenuItem>
                    )}
                    {TTS_MODELS.map((model) => (
                      <MenuItem key={model} value={model}>
                        {getTtsModelLabel(model)}
                      </MenuItem>
                    ))}
                  </TextField>
                  {voiceRows.map((row, rowIndex) => {
                    const matchedPreset = voicePresetOptions.find(
                      (preset) => preset.speaker === row.voice_id,
                    ) ?? null
                    const updateRow = (patch: Partial<VoiceCharacterDraft>) => {
                      setVoiceRows((prev) => prev.map((entry, i) => (
                        i === rowIndex ? { ...entry, ...patch } : entry
                      )))
                    }
                    return (
                      <Stack key={rowIndex} direction="row" spacing={1} sx={{ mb: 1 }} alignItems="center">
                        <TextField
                          size="small"
                          sx={{ width: 140 }}
                          label={t('audiobook.sceneChapterEditor.characterNameLabel')}
                          placeholder={t('audiobook.sceneChapterEditor.characterNamePlaceholder')}
                          value={row.character_name}
                          onChange={(event) => updateRow({ character_name: event.target.value })}
                        />
                        <Autocomplete
                          size="small"
                          fullWidth
                          freeSolo
                          loading={sceneVoicePool.loading}
                          options={voicePresetOptions}
                          value={matchedPreset}
                          inputValue={matchedPreset ? matchedPreset.label : row.voice_id}
                          getOptionLabel={(option) => (typeof option === 'string' ? option : option.label)}
                          getOptionDisabled={(option) => typeof option !== 'string' && Boolean(option.disabled)}
                          isOptionEqualToValue={(option, selected) => option.speaker === selected.speaker}
                          renderOption={(props, option) => (
                            <li {...props} key={option.id}>
                              <Stack spacing={0}>
                                <Typography variant="body2">{option.label}</Typography>
                                {option.disabledReason && (
                                  <Typography variant="caption" color="text.secondary">
                                    {option.disabledReason}
                                  </Typography>
                                )}
                              </Stack>
                            </li>
                          )}
                          onInputChange={(_, value, reason) => {
                            // reset 为选中回填，由 onChange 统一写回音色字段
                            if (reason === 'reset') return
                            updateRow({
                              voice_id: value,
                              reference_source: '',
                              reference_audio_url: '',
                              voice_reference_asset_id: '',
                              voice_pool_publication_id: '',
                            })
                          }}
                          onChange={(_, value) => {
                            if (!value || typeof value === 'string') return
                            updateRow({
                              voice_id: value.speaker,
                              reference_source: value.referenceSource ?? '',
                              reference_audio_url: value.referenceAudioUrl ?? '',
                              voice_reference_asset_id: value.voiceReferenceAssetId ?? '',
                              voice_pool_publication_id: value.voicePoolPublicationId ?? '',
                            })
                          }}
                          renderInput={(params) => (
                            <TextField
                              {...params}
                              label={t('audiobook.sceneChapterEditor.voiceLabel')}
                              placeholder={t('audiobook.sceneChapterEditor.voicePlaceholder')}
                            />
                          )}
                        />
                        <TextField
                          size="small"
                          select
                          sx={{ width: 150 }}
                          label={t('audiobook.sceneChapterEditor.voiceSourceLabel')}
                          value={row.reference_source}
                          onChange={(event) => updateRow({ reference_source: event.target.value })}
                        >
                          <MenuItem value="">{t('audiobook.sceneChapterEditor.voiceSourceAuto')}</MenuItem>
                          <MenuItem value="user_private">{t('audiobook.sceneChapterEditor.voiceSourcePrivate')}</MenuItem>
                          <MenuItem value="public_pool">{t('audiobook.sceneChapterEditor.voiceSourcePublic')}</MenuItem>
                        </TextField>
                        <IconButton
                          size="small"
                          aria-label={t('audiobook.sceneChapterEditor.deleteRowAria')}
                          disabled={voiceRows.length === 1}
                          onClick={() => {
                            setVoiceRows((prev) => prev.filter((_, i) => i !== rowIndex))
                          }}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Stack>
                    )
                  })}
                  <Stack direction="row" spacing={1}>
                    <Button
                      size="small"
                      startIcon={<AddIcon />}
                      onClick={() => {
                        setVoiceRows((prev) => [
                          ...prev,
                          { ...EMPTY_VOICE_CHARACTER_DRAFT },
                        ])
                      }}
                    >
                      {t('audiobook.sceneChapterEditor.addCharacter')}
                    </Button>
                    <Button
                      variant="contained"
                      size="small"
                      disabled={saving || !ttsModelDraft.trim()}
                      onClick={() => void handleSaveVoiceBinding()}
                    >
                      {t('audiobook.sceneChapterEditor.saveVoiceBinding')}
                    </Button>
                  </Stack>
                </Box>
              )}
            </Box>
          </Stack>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        {document?.chapter_audio_url && (
          <Button
            size="small"
            startIcon={<PlayArrowIcon />}
            onClick={() => onPreviewAudio?.(document.chapter_audio_url as string)}
          >
            {t('audiobook.sceneChapterEditor.previewChapter')}
          </Button>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <Button size="small" startIcon={<RefreshIcon />} onClick={() => void loadDocument()}>
          {t('admin.common.refresh')}
        </Button>
        <Button size="small" onClick={onClose}>
          {t('action.close')}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default SceneChapterEditor
