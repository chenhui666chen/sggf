import { type ChangeEvent, useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import RefreshIcon from '@mui/icons-material/Refresh'
import SettingsSuggestIcon from '@mui/icons-material/SettingsSuggest'
import TuneIcon from '@mui/icons-material/Tune'
import { useSelector } from 'react-redux'
import {
  type AdminPointsRuleConfig,
  type AdminPointsRuleUpdatePayload,
  type AdminSystemHealth,
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'
import PointsPricingPolicyCard from '@/components/admin/PointsPricingPolicyCard'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { useFormats } from '@/i18n'
import { RootState } from '@/store/store'

type PointsRuleFormState = Record<keyof AdminPointsRuleUpdatePayload, string>
type PointsRuleFieldDescriptor = {
  key: keyof AdminPointsRuleUpdatePayload
  labelKey: string
  helperKey: string
  step: string
}

const REWARD_FIELDS: PointsRuleFieldDescriptor[] = [
  {
    key: 'reusable_asset_reward',
    labelKey: 'admin.system.fields.reusableAssetReward',
    helperKey: 'admin.system.fieldHelp.reusableAssetReward',
    step: '0.1',
  },
  {
    key: 'deliverable_asset_reward',
    labelKey: 'admin.system.fields.deliverableAssetReward',
    helperKey: 'admin.system.fieldHelp.deliverableAssetReward',
    step: '0.1',
  },
  {
    key: 'audiobook_completion_reward',
    labelKey: 'admin.system.fields.audiobookCompletionReward',
    helperKey: 'admin.system.fieldHelp.audiobookCompletionReward',
    step: '0.1',
  },
  {
    key: 'dreamweaver_completion_reward',
    labelKey: 'admin.system.fields.dreamweaverCompletionReward',
    helperKey: 'admin.system.fieldHelp.dreamweaverCompletionReward',
    step: '0.1',
  },
]

const FREEZE_FIELDS: PointsRuleFieldDescriptor[] = [
  {
    key: 'running_audiobook_frozen',
    labelKey: 'admin.system.fields.runningAudiobookFrozen',
    helperKey: 'admin.system.fieldHelp.runningAudiobookFrozen',
    step: '0.1',
  },
  {
    key: 'running_dreamweaver_frozen',
    labelKey: 'admin.system.fields.runningDreamweaverFrozen',
    helperKey: 'admin.system.fieldHelp.runningDreamweaverFrozen',
    step: '0.1',
  },
]

const LIFECYCLE_FIELDS: PointsRuleFieldDescriptor[] = [
  {
    key: 'reward_ttl_days',
    labelKey: 'admin.system.fields.rewardTtlDays',
    helperKey: 'admin.system.fieldHelp.rewardTtlDays',
    step: '1',
  },
  {
    key: 'expiring_notice_days',
    labelKey: 'admin.system.fields.expiringNoticeDays',
    helperKey: 'admin.system.fieldHelp.expiringNoticeDays',
    step: '1',
  },
]

const ALL_FIELDS: PointsRuleFieldDescriptor[] = [...REWARD_FIELDS, ...FREEZE_FIELDS, ...LIFECYCLE_FIELDS]

function getFieldLabel(t: TFunction, key: keyof AdminPointsRuleUpdatePayload) {
  const descriptor = ALL_FIELDS.find((field) => field.key === key)
  return descriptor ? t(descriptor.labelKey) : key
}

const EMPTY_FORM: PointsRuleFormState = {
  reusable_asset_reward: '',
  deliverable_asset_reward: '',
  audiobook_completion_reward: '',
  dreamweaver_completion_reward: '',
  running_audiobook_frozen: '',
  running_dreamweaver_frozen: '',
  reward_ttl_days: '',
  expiring_notice_days: '',
}

function buildFormState(config: AdminPointsRuleConfig | AdminPointsRuleUpdatePayload): PointsRuleFormState {
  return {
    reusable_asset_reward: String(config.reusable_asset_reward),
    deliverable_asset_reward: String(config.deliverable_asset_reward),
    audiobook_completion_reward: String(config.audiobook_completion_reward),
    dreamweaver_completion_reward: String(config.dreamweaver_completion_reward),
    running_audiobook_frozen: String(config.running_audiobook_frozen),
    running_dreamweaver_frozen: String(config.running_dreamweaver_frozen),
    reward_ttl_days: String(config.reward_ttl_days),
    expiring_notice_days: String(config.expiring_notice_days),
  }
}

function parsePointsRuleForm(form: PointsRuleFormState, t: TFunction): { payload?: AdminPointsRuleUpdatePayload; error?: string } {
  const parseFloatField = (field: keyof AdminPointsRuleUpdatePayload) => {
    const value = Number(form[field])
    if (!Number.isFinite(value) || value < 0) {
      return { error: t('admin.system.validation.notNegative', { label: getFieldLabel(t, field) }) }
    }
    return { value: Number(value.toFixed(2)) }
  }

  const parseIntField = (field: keyof AdminPointsRuleUpdatePayload, minimum: number) => {
    const value = Number(form[field])
    if (!Number.isInteger(value) || value < minimum) {
      return { error: t('admin.system.validation.integerMin', { label: getFieldLabel(t, field), minimum }) }
    }
    return { value }
  }

  const reusableAssetReward = parseFloatField('reusable_asset_reward')
  if (reusableAssetReward.error) return reusableAssetReward
  const deliverableAssetReward = parseFloatField('deliverable_asset_reward')
  if (deliverableAssetReward.error) return deliverableAssetReward
  const audiobookCompletionReward = parseFloatField('audiobook_completion_reward')
  if (audiobookCompletionReward.error) return audiobookCompletionReward
  const dreamweaverCompletionReward = parseFloatField('dreamweaver_completion_reward')
  if (dreamweaverCompletionReward.error) return dreamweaverCompletionReward
  const runningAudiobookFrozen = parseFloatField('running_audiobook_frozen')
  if (runningAudiobookFrozen.error) return runningAudiobookFrozen
  const runningDreamweaverFrozen = parseFloatField('running_dreamweaver_frozen')
  if (runningDreamweaverFrozen.error) return runningDreamweaverFrozen
  const rewardTtlDays = parseIntField('reward_ttl_days', 1)
  if (rewardTtlDays.error) return rewardTtlDays
  const expiringNoticeDays = parseIntField('expiring_notice_days', 0)
  if (expiringNoticeDays.error) return expiringNoticeDays

  return {
    payload: {
      reusable_asset_reward: reusableAssetReward.value!,
      deliverable_asset_reward: deliverableAssetReward.value!,
      audiobook_completion_reward: audiobookCompletionReward.value!,
      dreamweaver_completion_reward: dreamweaverCompletionReward.value!,
      running_audiobook_frozen: runningAudiobookFrozen.value!,
      running_dreamweaver_frozen: runningDreamweaverFrozen.value!,
      reward_ttl_days: rewardTtlDays.value!,
      expiring_notice_days: expiringNoticeDays.value!,
    },
  }
}

export default function SystemPage() {
  const { t } = useTranslation()
  const { formatDateTime } = useFormats()
  const { user } = useSelector((state: RootState) => state.auth)
  const isSuperAdmin = (user as any)?.roles?.some((role: any) => role.code === 'super_admin')

  const [health, setHealth] = useState<AdminSystemHealth | null>(null)
  const [rules, setRules] = useState<AdminPointsRuleConfig | null>(null)
  const [form, setForm] = useState<PointsRuleFormState>(EMPTY_FORM)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!isSuperAdmin) {
      setLoading(false)
      return
    }
    void fetchPageData()
  }, [isSuperAdmin])

  const baselineForm = rules ? buildFormState(rules) : EMPTY_FORM
  const isDirty = JSON.stringify(form) !== JSON.stringify(baselineForm)

  const fetchPageData = async (silent = false) => {
    try {
      if (silent) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }

      const [healthResponse, rulesResponse] = await Promise.all([
        apiClient.getAdminSystemHealth(),
        apiClient.getAdminPointsRules(),
      ])

      setHealth(healthResponse.data)
      setRules(rulesResponse.data)
      setForm(buildFormState(rulesResponse.data))
      setError(null)
    } catch (err) {
      setError(await extractApiErrorMessage(err, t('admin.system.messages.fetchFailed')))
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const handleFieldChange =
    (field: keyof AdminPointsRuleUpdatePayload) => (event: ChangeEvent<HTMLInputElement>) => {
      setForm((prev) => ({
        ...prev,
        [field]: event.target.value,
      }))
    }

  const handleReset = () => {
    if (!rules) return
    setForm(buildFormState(rules))
    setSuccessMessage(t('admin.system.messages.resetDone'))
    setError(null)
  }

  const handleSave = async () => {
    const parsed = parsePointsRuleForm(form, t)
    if (!parsed.payload) {
      setError(parsed.error || t('admin.system.messages.validationFailed'))
      return
    }

    try {
      setSaving(true)
      const response = await apiClient.updateAdminPointsRules(parsed.payload)
      setRules(response.data)
      setForm(buildFormState(response.data))
      setSuccessMessage(t('admin.system.messages.saved'))
      setError(null)
    } catch (err) {
      setError(await extractApiErrorMessage(err, t('admin.system.messages.saveFailed')))
    } finally {
      setSaving(false)
    }
  }

  const renderFieldGroup = (title: string, fields: PointsRuleFieldDescriptor[]) => (
    <Box sx={{ display: 'grid', gap: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
        {title}
      </Typography>
      <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' } }}>
        {fields.map((field) => (
          <TextField
            key={field.key}
            label={t(field.labelKey)}
            value={form[field.key]}
            onChange={handleFieldChange(field.key)}
            helperText={t(field.helperKey)}
            type="number"
            fullWidth
            inputProps={{
              min: 0,
              step: field.step,
            }}
          />
        ))}
      </Box>
    </Box>
  )

  if (!isSuperAdmin) {
    return (
      <Box>
        <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
          {t('admin.system.title')}
        </Typography>
        <Alert severity="warning">{t('admin.system.forbidden')}</Alert>
      </Box>
    )
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  const healthIsOk = health?.database === 'healthy'

  return (
    <Box>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        justifyContent="space-between"
        alignItems={{ xs: 'stretch', md: 'center' }}
        spacing={2}
        sx={{ mb: 3 }}
      >
        <Box>
          <Typography variant="h4">{t('admin.system.title')}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {t('admin.system.subtitle')}
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={refreshing ? <CircularProgress size={18} /> : <RefreshIcon />}
          onClick={() => void fetchPageData(true)}
          disabled={refreshing || saving}
        >
          {t('admin.common.refresh')}
        </Button>
      </Stack>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      ) : null}

      {successMessage ? (
        <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccessMessage(null)}>
          {successMessage}
        </Alert>
      ) : null}

      <Box sx={{ display: 'grid', gap: 3, gridTemplateColumns: { xs: '1fr', xl: 'minmax(0, 1.6fr) minmax(320px, 0.9fr)' } }}>
        <Card>
          <CardContent>
            <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={2}>
              <Box>
                <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <TuneIcon fontSize="small" />
                  {t('admin.system.pointsRules.title')}
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  {t('admin.system.pointsRules.subtitle')}
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip
                  color={rules?.source === 'admin_log' ? 'primary' : 'default'}
                  label={
                    rules?.source === 'admin_log'
                      ? t('admin.system.pointsRules.overriddenByAdmin')
                      : t('admin.system.pointsRules.envDefault')
                  }
                />
                <Chip
                  variant="outlined"
                  label={
                    rules?.updated_at
                      ? t('admin.system.pointsRules.recentUpdate', { time: formatDateTime(rules.updated_at) })
                      : t('admin.system.pointsRules.notManuallyUpdated')
                  }
                />
              </Stack>
            </Stack>

            <Divider sx={{ my: 3 }} />

            <Stack spacing={3}>
              {renderFieldGroup(t('admin.system.groups.reward'), REWARD_FIELDS)}
              {renderFieldGroup(t('admin.system.groups.freeze'), FREEZE_FIELDS)}
              {renderFieldGroup(t('admin.system.groups.lifecycle'), LIFECYCLE_FIELDS)}
            </Stack>

            <Alert severity="info" sx={{ mt: 3 }}>
              {t('admin.system.pointsRules.readModelHint')}
            </Alert>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 3 }}>
              <Button variant="outlined" onClick={handleReset} disabled={!rules || saving || !isDirty}>
                {t('admin.system.actions.reset')}
              </Button>
              <Button variant="contained" onClick={() => void handleSave()} disabled={saving || !isDirty}>
                {saving ? t('admin.system.actions.saving') : t('admin.system.actions.saveRules')}
              </Button>
            </Stack>
          </CardContent>
        </Card>

        <Stack spacing={3}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <SettingsSuggestIcon fontSize="small" />
                {t('admin.system.health.title')}
              </Typography>
              <Stack spacing={2} sx={{ mt: 2 }}>
                <Box
                  sx={{
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 2,
                    p: 2,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 2,
                  }}
                >
                  <Box>
                    <Typography variant="subtitle2">{t('admin.system.health.database')}</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                      {health?.timestamp
                        ? t('admin.system.health.lastCheck', { time: formatDateTime(health.timestamp) })
                        : t('admin.system.health.noCheck')}
                    </Typography>
                  </Box>
                  <Chip
                    color={healthIsOk ? 'success' : 'error'}
                    icon={healthIsOk ? <CheckCircleIcon /> : <ErrorOutlineIcon />}
                    label={healthIsOk ? t('admin.system.health.ok') : t('admin.system.health.error')}
                  />
                </Box>
              </Stack>
            </CardContent>
          </Card>

          <PointsPricingPolicyCard />

          <Card>
            <CardContent>
              <Typography variant="h6">{t('admin.system.notes.title')}</Typography>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  {t('admin.system.notes.note1')}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {t('admin.system.notes.note2')}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {t('admin.system.notes.note3')}
                </Typography>
              </Stack>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Typography variant="h6">{t('admin.system.recent.title')}</Typography>
              <Stack spacing={1} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  {t('admin.system.recent.source', {
                    source:
                      rules?.source === 'admin_log' ? t('admin.system.recent.adminSnapshot') : t('admin.system.recent.envDefault'),
                  })}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {t('admin.system.recent.operator', {
                    name: rules?.updated_by_username || t('admin.system.recent.systemDefault'),
                  })}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  {t('admin.system.recent.effective')}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </Box>
    </Box>
  )
}
