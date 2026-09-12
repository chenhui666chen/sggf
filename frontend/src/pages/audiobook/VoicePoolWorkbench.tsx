import { useMemo, useState } from 'react'

import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'

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

const OPTION_LABEL_KEYS: Record<string, string> = {
  female: 'audiobook.voicePoolWorkbench.options.female', male: 'audiobook.voicePoolWorkbench.options.male', neutral: 'audiobook.voicePoolWorkbench.options.neutral', child: 'audiobook.voicePoolWorkbench.options.child', teen: 'audiobook.voicePoolWorkbench.options.teen',
  young_adult: 'audiobook.voicePoolWorkbench.options.young_adult', adult: 'audiobook.voicePoolWorkbench.options.adult', mature: 'audiobook.voicePoolWorkbench.options.mature', elder: 'audiobook.voicePoolWorkbench.options.elder', natural: 'audiobook.voicePoolWorkbench.options.natural',
  gentle: 'audiobook.voicePoolWorkbench.options.gentle', sweet: 'audiobook.voicePoolWorkbench.options.sweet', bright: 'audiobook.voicePoolWorkbench.options.bright', restrained: 'audiobook.voicePoolWorkbench.options.restrained', intellectual: 'audiobook.voicePoolWorkbench.options.intellectual',
  powerful: 'audiobook.voicePoolWorkbench.options.powerful', cold: 'audiobook.voicePoolWorkbench.options.cold', narration: 'audiobook.voicePoolWorkbench.options.narration', roleplay: 'audiobook.voicePoolWorkbench.options.roleplay', clear: 'audiobook.voicePoolWorkbench.options.clear',
  warm: 'audiobook.voicePoolWorkbench.options.warm', deep: 'audiobook.voicePoolWorkbench.options.deep', magnetic: 'audiobook.voicePoolWorkbench.options.magnetic', soft: 'audiobook.voicePoolWorkbench.options.soft', slightly_husky: 'audiobook.voicePoolWorkbench.options.slightly_husky',
  husky: 'audiobook.voicePoolWorkbench.options.husky', airy: 'audiobook.voicePoolWorkbench.options.airy', audiobook: 'audiobook.voicePoolWorkbench.options.audiobook', dialogue: 'audiobook.voicePoolWorkbench.options.dialogue', suspense: 'audiobook.voicePoolWorkbench.options.suspense',
  romance: 'audiobook.voicePoolWorkbench.options.romance', historical: 'audiobook.voicePoolWorkbench.options.historical', fantasy: 'audiobook.voicePoolWorkbench.options.fantasy', children: 'audiobook.voicePoolWorkbench.options.children', documentary: 'audiobook.voicePoolWorkbench.options.documentary',
  commercial: 'audiobook.voicePoolWorkbench.options.commercial', self_voice: 'audiobook.voicePoolWorkbench.options.self_voice', licensed_voice: 'audiobook.voicePoolWorkbench.options.licensed_voice',
  synthetic_source: 'audiobook.voicePoolWorkbench.options.synthetic_source', synthetic_design: 'audiobook.voicePoolWorkbench.options.synthetic_design',
}

const optionLabel = (value: string, t: TFunction) => (OPTION_LABEL_KEYS[value] ? t(OPTION_LABEL_KEYS[value]) : value)

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
  const { t } = useTranslation()
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
      setNotice(response.data.cache_hit ? t('audiobook.voicePoolWorkbench.materializeNoticeReused') : t('audiobook.voicePoolWorkbench.materializeNoticeGenerated'))
      await onRefresh()
    } catch (requestError: unknown) {
      setActionError(await extractApiErrorMessage(requestError, t('audiobook.voicePoolWorkbench.materializeFailed')))
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
      setActionError(t('audiobook.voicePoolWorkbench.previewRequired'))
      return
    }
    if (!publishName.trim() || timbreTags.length === 0 || scenarioTags.length === 0) {
      setActionError(t('audiobook.voicePoolWorkbench.publishFieldsRequired'))
      return
    }
    if (!['self_voice', 'licensed_voice', 'synthetic_source', 'synthetic_design'].includes(rightsBasis)) {
      setActionError(t('audiobook.voicePoolWorkbench.rightsBasisMissing'))
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
      setNotice(t('audiobook.voicePoolWorkbench.publishSubmitted'))
      await onRefresh()
    } catch (requestError: unknown) {
      setActionError(await extractApiErrorMessage(requestError, t('audiobook.voicePoolWorkbench.publishFailed')))
    } finally {
      setBusyAssetId(null)
    }
  }

  const rateVoice = async (voice: VoicePoolVoiceRecord, score: number) => {
    try {
      await apiClient.ratePublicVoice(voice.publication_id, score)
      setNotice(t('audiobook.voicePoolWorkbench.ratingUpdated'))
      await onRefresh()
    } catch (requestError: unknown) {
      setActionError(await extractApiErrorMessage(requestError, t('audiobook.voicePoolWorkbench.ratingFailed')))
    }
  }

  return (
    <Box sx={{ mt: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
        <Tabs value={tab} onChange={(_event, value) => setTab(value)}>
          <Tab label={t('audiobook.voicePoolWorkbench.myVoicesTab', { count: privateAssets.length })} />
          <Tab label={t('audiobook.voicePoolWorkbench.publicPoolTab', { count: publicVoices.length })} />
        </Tabs>
        <Tooltip title={t('audiobook.voicePoolWorkbench.refreshPool')}>
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
                    {asset.source_model || t('audiobook.voicePoolWorkbench.unknownModel')} · {asset.authorization_basis === 'synthetic_design' ? t('audiobook.voicePoolWorkbench.syntheticDesign') : t('audiobook.voicePoolWorkbench.replicaVoice')}
                  </Typography>
                </Box>
                {uri && (
                  <Tooltip title={t('audiobook.voicePoolWorkbench.previewStandardAudio')}>
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
                  {isBusy ? t('audiobook.voicePoolWorkbench.processing') : uri ? t('audiobook.voicePoolWorkbench.checkCache') : t('audiobook.voicePoolWorkbench.generatePreview')}
                </Button>
                <Button
                  size="small"
                  variant="contained"
                  startIcon={<LibraryAddIcon fontSize="small" />}
                  disabled={!uri || isBusy}
                  onClick={() => openPublish(asset)}
                >
                  {t('audiobook.voicePoolWorkbench.publish')}
                </Button>
              </ListItem>
            )
          })}
          {!loading && privateAssets.length === 0 && (
            <ListItem><Typography variant="body2" color="text.secondary">{t('audiobook.voicePoolWorkbench.noPrivateVoices')}</Typography></ListItem>
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
                    <Chip key={tag} label={optionLabel(tag, t)} size="small" sx={{ height: 20 }} />
                  ))}
                </Stack>
              </Box>
              <Tooltip title={t('audiobook.voicePoolWorkbench.preview')}>
                <IconButton component="a" href={voice.public_preview_uri} target="_blank" rel="noreferrer" size="small">
                  <PlayArrowIcon fontSize="small" />
                </IconButton>
              </Tooltip>
              <Box sx={{ display: 'flex', alignItems: 'center' }}>
                {[1, 2, 3, 4, 5].map((score) => (
                  <Tooltip key={score} title={t('audiobook.voicePoolWorkbench.scorePoint', { score })}>
                    <IconButton size="small" onClick={() => void rateVoice(voice, score)}>
                      <StarIcon fontSize="small" color={score <= Math.round(voice.average_score) ? 'warning' : 'disabled'} />
                    </IconButton>
                  </Tooltip>
                ))}
              </Box>
            </ListItem>
          ))}
          {!loading && publicVoices.length === 0 && (
            <ListItem><Typography variant="body2" color="text.secondary">{t('audiobook.voicePoolWorkbench.noPublicVoices')}</Typography></ListItem>
          )}
        </List>
      )}

      <Dialog open={Boolean(costConfirmation)} onClose={() => setCostConfirmation(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('audiobook.voicePoolWorkbench.confirmMaterializeTitle')}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2">{costConfirmation?.cost_quote?.billing_notice}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
            {costConfirmation?.preview_text}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCostConfirmation(null)}>{t('action.cancel')}</Button>
          <Button
            variant="contained"
            disabled={!pendingAsset || busyAssetId === pendingAsset.asset_id}
            onClick={() => pendingAsset && void materialize(pendingAsset, true)}
          >
            {t('audiobook.voicePoolWorkbench.confirmGenerate')}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(publishAsset)} onClose={() => setPublishAsset(null)} maxWidth="sm" fullWidth>
        <DialogTitle>{t('audiobook.voicePoolWorkbench.publishDialogTitle')}</DialogTitle>
        <DialogContent dividers>
          <Stack spacing={2}>
            <TextField label={t('audiobook.voicePoolWorkbench.publishNameLabel')} value={publishName} onChange={(event) => setPublishName(event.target.value)} required />
            <TextField label={t('audiobook.voicePoolWorkbench.descriptionLabel')} value={publishDescription} onChange={(event) => setPublishDescription(event.target.value)} multiline minRows={2} />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
              <FormControl fullWidth><InputLabel>{t('audiobook.voicePoolWorkbench.genderPresentationLabel')}</InputLabel><Select label={t('audiobook.voicePoolWorkbench.genderPresentationLabel')} value={gender} onChange={(event) => setGender(event.target.value as typeof gender)}>{optionList(taxonomy, 'gender_presentation').map((value) => <MenuItem key={value} value={value}>{optionLabel(value, t)}</MenuItem>)}</Select></FormControl>
              <FormControl fullWidth><InputLabel>{t('audiobook.voicePoolWorkbench.ageImpressionLabel')}</InputLabel><Select label={t('audiobook.voicePoolWorkbench.ageImpressionLabel')} value={age} onChange={(event) => setAge(event.target.value as typeof age)}>{optionList(taxonomy, 'age_impression').map((value) => <MenuItem key={value} value={value}>{optionLabel(value, t)}</MenuItem>)}</Select></FormControl>
            </Stack>
            <FormControl fullWidth><InputLabel>{t('audiobook.voicePoolWorkbench.primaryStyleLabel')}</InputLabel><Select label={t('audiobook.voicePoolWorkbench.primaryStyleLabel')} value={style} onChange={(event) => setStyle(event.target.value)}>{optionList(taxonomy, 'primary_style').map((value) => <MenuItem key={value} value={value}>{optionLabel(value, t)}</MenuItem>)}</Select></FormControl>
            <FormControl fullWidth><InputLabel>{t('audiobook.voicePoolWorkbench.timbreTagsLabel')}</InputLabel><Select multiple label={t('audiobook.voicePoolWorkbench.timbreTagsLabel')} value={timbreTags} onChange={(event) => setTimbreTags(event.target.value as string[])}>{optionList(taxonomy, 'timbre_tags').map((value) => <MenuItem key={value} value={value}>{optionLabel(value, t)}</MenuItem>)}</Select></FormControl>
            <FormControl fullWidth><InputLabel>{t('audiobook.voicePoolWorkbench.scenarioTagsLabel')}</InputLabel><Select multiple label={t('audiobook.voicePoolWorkbench.scenarioTagsLabel')} value={scenarioTags} onChange={(event) => setScenarioTags(event.target.value as string[])}>{optionList(taxonomy, 'scenario_tags').map((value) => <MenuItem key={value} value={value}>{optionLabel(value, t)}</MenuItem>)}</Select></FormControl>
            <FormControl fullWidth>
              <InputLabel>{t('audiobook.voicePoolWorkbench.rightsBasisLabel')}</InputLabel>
              <Select
                label={t('audiobook.voicePoolWorkbench.rightsBasisLabel')}
                value={rightsBasis}
                disabled={publishAsset?.authorization_basis === 'synthetic_design'}
                onChange={(event) => setRightsBasis(event.target.value as VoicePoolPublicationPayload['rights_basis'])}
              >
                {(publishAsset?.authorization_basis === 'synthetic_design'
                  ? ['synthetic_design']
                  : ['self_voice', 'licensed_voice', 'synthetic_source']
                ).map((value) => <MenuItem key={value} value={value}>{optionLabel(value, t)}</MenuItem>)}
              </Select>
            </FormControl>
            <Alert severity="warning">{t('audiobook.voicePoolWorkbench.publishConsentWarning')}</Alert>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPublishAsset(null)}>{t('action.cancel')}</Button>
          <Button variant="contained" onClick={() => void submitPublication()} disabled={Boolean(publishAsset && busyAssetId === publishAsset.asset_id)}>{t('audiobook.voicePoolWorkbench.submitReview')}</Button>
        </DialogActions>
      </Dialog>
    </Box>
  )
}

export default VoicePoolWorkbench
