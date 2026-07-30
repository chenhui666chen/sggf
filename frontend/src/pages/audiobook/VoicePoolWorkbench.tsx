import { useMemo, useState } from 'react'

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItem,
  MenuItem,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import LibraryAddIcon from '@mui/icons-material/LibraryAdd'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import StarIcon from '@mui/icons-material/Star'
import SyncIcon from '@mui/icons-material/Sync'

import {
  apiClient,
  extractApiErrorMessage,
  type VoicePoolPublicationPayload,
  type VoicePoolVoiceRecord,
  type VoiceReferenceAssetRecord,
  type VoiceReferenceMaterializeResponse,
} from '../../services/api'


interface VoicePoolWorkbenchProps {
  privateAssets: VoiceReferenceAssetRecord[]
  publicVoices: VoicePoolVoiceRecord[]
  taxonomy: Record<string, string[] | string>
  loading: boolean
  error: string | null
  onRefresh: () => Promise<void>
}

const OPTION_LABELS: Record<string, string> = {
  female: '女性感', male: '男性感', neutral: '中性', child: '儿童', teen: '少年',
  young_adult: '青年', adult: '成年', mature: '中年', elder: '老年', natural: '自然',
  gentle: '温柔', sweet: '甜美', bright: '明亮', restrained: '克制', intellectual: '知性',
  powerful: '有力', cold: '冷峻', narration: '旁白', roleplay: '角色演绎', clear: '清晰',
  warm: '温暖', deep: '低沉', magnetic: '磁性', soft: '柔和', slightly_husky: '轻微沙哑',
  husky: '沙哑', airy: '气声', audiobook: '有声书', dialogue: '对白', suspense: '悬疑',
  romance: '情感', historical: '古装', fantasy: '奇幻', children: '儿童故事', documentary: '纪录片',
  commercial: '商业配音', self_voice: '本人声音', licensed_voice: '已获授权声音',
  synthetic_source: '合成来源', synthetic_design: '合成设计',
}

const optionLabel = (value: string) => OPTION_LABELS[value] || value

const optionList = (taxonomy: Record<string, string[] | string>, key: string) => {
  const value = taxonomy[key]
  return Array.isArray(value) ? value : []
}

const playableUri = (asset: VoiceReferenceAssetRecord) => {
  const uri = asset.source_url || asset.storage_uri || ''
  return uri.startsWith('http://') || uri.startsWith('https://') ? uri : ''
}

const VoicePoolWorkbench = ({
  privateAssets,
  publicVoices,
  taxonomy,
  loading,
  error,
  onRefresh,
}: VoicePoolWorkbenchProps) => {
  const [tab, setTab] = useState(0)
  const [busyAssetId, setBusyAssetId] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [costConfirmation, setCostConfirmation] = useState<VoiceReferenceMaterializeResponse | null>(null)
  const [publishAsset, setPublishAsset] = useState<VoiceReferenceAssetRecord | null>(null)
  const [publishName, setPublishName] = useState('')
  const [publishDescription, setPublishDescription] = useState('')
  const [gender, setGender] = useState<'female' | 'male' | 'neutral'>('neutral')
  const [age, setAge] = useState<'child' | 'teen' | 'young_adult' | 'adult' | 'mature' | 'elder'>('adult')
  const [style, setStyle] = useState('natural')
  const [timbreTags, setTimbreTags] = useState<string[]>([])
  const [scenarioTags, setScenarioTags] = useState<string[]>(['audiobook'])
  const [rightsBasis, setRightsBasis] = useState<VoicePoolPublicationPayload['rights_basis']>('synthetic_source')

  const pendingAsset = useMemo(
    () => privateAssets.find((asset) => asset.asset_id === costConfirmation?.source_asset_id) || null,
    [costConfirmation?.source_asset_id, privateAssets],
  )

  const materialize = async (asset: VoiceReferenceAssetRecord, confirmCost: boolean) => {
    setBusyAssetId(asset.asset_id)
    setActionError(null)
    try {
      const response = await apiClient.materializeVoiceReference(asset.asset_id, confirmCost)
      if (response.data.requires_cost_confirmation) {
        setCostConfirmation(response.data)
        return
      }
      setCostConfirmation(null)
      setNotice(response.data.cache_hit ? '已复用标准参考试听。' : '标准参考试听已生成并缓存。')
      await onRefresh()
    } catch (requestError: unknown) {
      setActionError(await extractApiErrorMessage(requestError, '生成标准参考试听失败'))
    } finally {
      setBusyAssetId(null)
    }
  }

  const openPublish = (asset: VoiceReferenceAssetRecord) => {
    setPublishAsset(asset)
    setPublishName(String(asset.metadata_json?.display_name || asset.source_voice_id || ''))
    setPublishDescription('')
    setTimbreTags([])
    setScenarioTags(['audiobook'])
    setRightsBasis(
      asset.authorization_basis === 'synthetic_design'
        ? 'synthetic_design'
        : 'synthetic_source',
    )
    setActionError(null)
  }

  const submitPublication = async () => {
    if (!publishAsset) return
    const uri = playableUri(publishAsset)
    if (!uri) {
      setActionError('请先生成并上传标准参考试听。')
      return
    }
    if (!publishName.trim() || timbreTags.length === 0 || scenarioTags.length === 0) {
      setActionError('公开名称、音色质感和适用场景为必填项。')
      return
    }
    if (!['self_voice', 'licensed_voice', 'synthetic_source', 'synthetic_design'].includes(rightsBasis)) {
      setActionError('当前音色缺少可公开的权利依据。')
      return
    }
    setBusyAssetId(publishAsset.asset_id)
    try {
      const payload: VoicePoolPublicationPayload = {
        display_name: publishName.trim(),
        description: publishDescription.trim(),
        gender_presentation: gender,
        age_impression: age,
        primary_style: style,
        language: 'zh-CN',
        timbre_tags: timbreTags,
        scenario_tags: scenarioTags,
        emotion_tags: [],
        rights_basis: rightsBasis,
        license_version: String(taxonomy.license_version || 'voice-pool-license-v1'),
        consent_at: new Date().toISOString(),
      }
      await apiClient.publishVoiceToPool(publishAsset.asset_id, payload)
      setPublishAsset(null)
      setNotice('发布申请已提交，审核通过后才会进入公共音色池。')
      await onRefresh()
    } catch (requestError: unknown) {
      setActionError(await extractApiErrorMessage(requestError, '提交公共音色失败'))
    } finally {
      setBusyAssetId(null)
    }
  }

  const rateVoice = async (voice: VoicePoolVoiceRecord, score: number) => {
    try {
      await apiClient.ratePublicVoice(voice.publication_id, score)
      setNotice('评分已更新。')
      await onRefresh()
    } catch (requestError: unknown) {
      setActionError(await extractApiErrorMessage(requestError, '评分失败'))
    }
  }

  return (
    <Box sx={{ mt: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
        <Tabs value={tab} onChange={(_event, value) => setTab(value)}>
          <Tab label={`我的参考音色 ${privateAssets.length}`} />
          <Tab label={`公共音色池 ${publicVoices.length}`} />
        </Tabs>
        <Tooltip title="刷新音色池">
          <span>
            <IconButton onClick={() => void onRefresh()} disabled={loading} size="small">
              {loading ? <CircularProgress size={18} /> : <SyncIcon fontSize="small" />}
            </IconButton>
          </span>
        </Tooltip>
      </Box>

      {(error || actionError) && <Alert severity="error" sx={{ my: 1 }}>{actionError || error}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice(null)} sx={{ my: 1 }}>{notice}</Alert>}

      {tab === 0 && (
        <List disablePadding sx={{ maxHeight: 360, overflow: 'auto', borderTop: 1, borderColor: 'divider' }}>
          {privateAssets.map((asset) => {
            const uri = playableUri(asset)
            const isBusy = busyAssetId === asset.asset_id
            return (
              <ListItem key={asset.asset_id} divider disableGutters sx={{ py: 1.25, gap: 1.5 }}>
                <Box sx={{ minWidth: 0, flex: 1 }}>
                  <Typography variant="body2" fontWeight={700} noWrap>
                    {asset.source_voice_id || asset.asset_id}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {asset.source_model || '未知模型'} · {asset.authorization_basis === 'synthetic_design' ? '设计音色' : '复刻音色'}
                  </Typography>
                </Box>
                {uri && (
                  <Tooltip title="试听标准参考音频">
                    <IconButton component="a" href={uri} target="_blank" rel="noreferrer" size="small">
                      <PlayArrowIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                )}
                <Button
                  size="small"
                  variant="outlined"
                  disabled={isBusy}
                  onClick={() => void materialize(asset, false)}
                >
                  {isBusy ? '处理中' : uri ? '检查缓存' : '生成参考试听'}
                </Button>
                <Button
                  size="small"
                  variant="contained"
                  startIcon={<LibraryAddIcon fontSize="small" />}
                  disabled={!uri || isBusy}
                  onClick={() => openPublish(asset)}
                >
                  发布
                </Button>
              </ListItem>
            )
          })}
          {!loading && privateAssets.length === 0 && (
            <ListItem><Typography variant="body2" color="text.secondary">暂无可发布的私有音色。</Typography></ListItem>
          )}
        </List>
      )}

      {tab === 1 && (
        <List disablePadding sx={{ maxHeight: 360, overflow: 'auto', borderTop: 1, borderColor: 'divider' }}>
          {publicVoices.map((voice) => (
            <ListItem key={voice.publication_id} divider disableGutters sx={{ py: 1.25, gap: 1.25 }}>
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="body2" fontWeight={700}>{voice.display_name}</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                  {voice.description || `${voice.age_impression} · ${voice.primary_style}`}
                </Typography>
                <Stack direction="row" spacing={0.5} sx={{ mt: 0.5, flexWrap: 'wrap' }}>
                  {[...voice.timbre_tags, ...voice.scenario_tags].slice(0, 5).map((tag) => (
                    <Chip key={tag} label={optionLabel(tag)} size="small" sx={{ height: 20 }} />
                  ))}
                </Stack>
              </Box>
              <Tooltip title="试听">
                <IconButton component="a" href={voice.public_preview_uri} target="_blank" rel="noreferrer" size="small">
                  <PlayArrowIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                {[1, 2, 3, 4, 5].map((score) => (
                  <Tooltip key={score} title={`${score} 分`}>
                    <IconButton size="small" onClick={() => void rateVoice(voice, score)}>
                      <StarIcon fontSize="small" color={score <= Math.round(voice.average_score) ? 'warning' : 'disabled'} />
                    </IconButton>
                  </Tooltip>
                ))}
              </Box>
            </ListItem>
          ))}
          {!loading && publicVoices.length === 0 && (
            <ListItem><Typography variant="body2" color="text.secondary">暂无已审核公共音色。</Typography></ListItem>
          )}
        </List>
      )}

      <Dialog open={Boolean(costConfirmation)} onClose={() => setCostConfirmation(null)} maxWidth="sm" fullWidth>
        <DialogTitle>确认生成标准参考试听</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2">{costConfirmation?.cost_quote?.billing_notice}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
            {costConfirmation?.preview_text}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCostConfirmation(null)}>取消</Button>
          <Button
            variant="contained"
            disabled={!pendingAsset || busyAssetId === pendingAsset.asset_id}
            onClick={() => pendingAsset && void materialize(pendingAsset, true)}
          >
            确认生成
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(publishAsset)} onClose={() => setPublishAsset(null)} maxWidth="sm" fullWidth>
        <DialogTitle>发布到公共音色池</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <TextField label="公开名称" value={publishName} onChange={(event) => setPublishName(event.target.value)} required />
            <TextField label="描述" value={publishDescription} onChange={(event) => setPublishDescription(event.target.value)} multiline minRows={2} />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <FormControl fullWidth><InputLabel>声音性别感</InputLabel><Select label="声音性别感" value={gender} onChange={(event) => setGender(event.target.value as typeof gender)}>{optionList(taxonomy, 'gender_presentation').map((value) => <MenuItem key={value} value={value}>{optionLabel(value)}</MenuItem>)}</Select></FormControl>
              <FormControl fullWidth><InputLabel>年龄感</InputLabel><Select label="年龄感" value={age} onChange={(event) => setAge(event.target.value as typeof age)}>{optionList(taxonomy, 'age_impression').map((value) => <MenuItem key={value} value={value}>{optionLabel(value)}</MenuItem>)}</Select></FormControl>
            </Stack>
            <FormControl fullWidth><InputLabel>主要风格</InputLabel><Select label="主要风格" value={style} onChange={(event) => setStyle(event.target.value)}>{optionList(taxonomy, 'primary_style').map((value) => <MenuItem key={value} value={value}>{optionLabel(value)}</MenuItem>)}</Select></FormControl>
            <FormControl fullWidth><InputLabel>音色质感</InputLabel><Select multiple label="音色质感" value={timbreTags} onChange={(event) => setTimbreTags(event.target.value as string[])}>{optionList(taxonomy, 'timbre_tags').map((value) => <MenuItem key={value} value={value}>{optionLabel(value)}</MenuItem>)}</Select></FormControl>
            <FormControl fullWidth><InputLabel>适用场景</InputLabel><Select multiple label="适用场景" value={scenarioTags} onChange={(event) => setScenarioTags(event.target.value as string[])}>{optionList(taxonomy, 'scenario_tags').map((value) => <MenuItem key={value} value={value}>{optionLabel(value)}</MenuItem>)}</Select></FormControl>
            <FormControl fullWidth>
              <InputLabel>权利依据</InputLabel>
              <Select
                label="权利依据"
                value={rightsBasis}
                disabled={publishAsset?.authorization_basis === 'synthetic_design'}
                onChange={(event) => setRightsBasis(event.target.value as VoicePoolPublicationPayload['rights_basis'])}
              >
                {(publishAsset?.authorization_basis === 'synthetic_design'
                  ? ['synthetic_design']
                  : ['self_voice', 'licensed_voice', 'synthetic_source']
                ).map((value) => <MenuItem key={value} value={value}>{optionLabel(value)}</MenuItem>)}
              </Select>
            </FormControl>
            <Alert severity="warning">提交即确认你有权公开该衍生音色；原始复刻录音不会进入公共池。</Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPublishAsset(null)}>取消</Button>
          <Button variant="contained" onClick={() => void submitPublication()} disabled={Boolean(publishAsset && busyAssetId === publishAsset.asset_id)}>提交审核</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

export default VoicePoolWorkbench
