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
import { RootState } from '@/store/store'

type PointsRuleFormState = Record<keyof AdminPointsRuleUpdatePayload, string>
type PointsRuleFieldDescriptor = {
  key: keyof AdminPointsRuleUpdatePayload
  label: string
  helperText: string
  step: string
}

const REWARD_FIELDS: PointsRuleFieldDescriptor[] = [
  {
    key: 'reusable_asset_reward',
    label: '复用资产奖励',
    helperText: '用户沉淀可复用资产时发放的积分。',
    step: '0.1',
  },
  {
    key: 'deliverable_asset_reward',
    label: '交付资产奖励',
    helperText: '交付型资产的更高奖励值。',
    step: '0.1',
  },
  {
    key: 'audiobook_completion_reward',
    label: '有声书完成奖励',
    helperText: '有声书项目完成后发放的积分。',
    step: '0.1',
  },
  {
    key: 'dreamweaver_completion_reward',
    label: '短剧完成奖励',
    helperText: '短剧生成完成后发放的积分。',
    step: '0.1',
  },
]

const FREEZE_FIELDS: PointsRuleFieldDescriptor[] = [
  {
    key: 'running_audiobook_frozen',
    label: '有声书运行冻结',
    helperText: '有声书运行中预留的冻结积分。',
    step: '0.1',
  },
  {
    key: 'running_dreamweaver_frozen',
    label: '短剧运行冻结',
    helperText: '短剧运行中预留的冻结积分。',
    step: '0.1',
  },
]

const LIFECYCLE_FIELDS: PointsRuleFieldDescriptor[] = [
  {
    key: 'reward_ttl_days',
    label: '奖励有效期（天）',
    helperText: '正向奖励积分的默认有效期。',
    step: '1',
  },
  {
    key: 'expiring_notice_days',
    label: '到期提醒窗口（天）',
    helperText: '用户中心展示“即将过期积分”的提前天数。',
    step: '1',
  },
]

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

function parsePointsRuleForm(form: PointsRuleFormState): { payload?: AdminPointsRuleUpdatePayload; error?: string } {
  const parseFloatField = (field: keyof AdminPointsRuleUpdatePayload, label: string) => {
    const value = Number(form[field])
    if (!Number.isFinite(value) || value < 0) {
      return { error: `${label}必须是大于等于 0 的数字` }
    }
    return { value: Number(value.toFixed(2)) }
  }

  const parseIntField = (field: keyof AdminPointsRuleUpdatePayload, label: string, minimum: number) => {
    const value = Number(form[field])
    if (!Number.isInteger(value) || value < minimum) {
      return { error: `${label}必须是大于等于 ${minimum} 的整数` }
    }
    return { value }
  }

  const reusableAssetReward = parseFloatField('reusable_asset_reward', '复用资产奖励')
  if (reusableAssetReward.error) return reusableAssetReward
  const deliverableAssetReward = parseFloatField('deliverable_asset_reward', '交付资产奖励')
  if (deliverableAssetReward.error) return deliverableAssetReward
  const audiobookCompletionReward = parseFloatField('audiobook_completion_reward', '有声书完成奖励')
  if (audiobookCompletionReward.error) return audiobookCompletionReward
  const dreamweaverCompletionReward = parseFloatField('dreamweaver_completion_reward', '短剧完成奖励')
  if (dreamweaverCompletionReward.error) return dreamweaverCompletionReward
  const runningAudiobookFrozen = parseFloatField('running_audiobook_frozen', '有声书运行冻结')
  if (runningAudiobookFrozen.error) return runningAudiobookFrozen
  const runningDreamweaverFrozen = parseFloatField('running_dreamweaver_frozen', '短剧运行冻结')
  if (runningDreamweaverFrozen.error) return runningDreamweaverFrozen
  const rewardTtlDays = parseIntField('reward_ttl_days', '奖励有效期', 1)
  if (rewardTtlDays.error) return rewardTtlDays
  const expiringNoticeDays = parseIntField('expiring_notice_days', '到期提醒窗口', 0)
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
      setError(await extractApiErrorMessage(err, '获取系统配置失败'))
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
    setSuccessMessage('已恢复为当前线上规则快照。')
    setError(null)
  }

  const handleSave = async () => {
    const parsed = parsePointsRuleForm(form)
    if (!parsed.payload) {
      setError(parsed.error || '积分规则校验失败')
      return
    }

    try {
      setSaving(true)
      const response = await apiClient.updateAdminPointsRules(parsed.payload)
      setRules(response.data)
      setForm(buildFormState(response.data))
      setSuccessMessage('积分规则已保存，用户中心新的积分汇总会立即按新规则计算。')
      setError(null)
    } catch (err) {
      setError(await extractApiErrorMessage(err, '保存积分规则失败'))
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
            label={field.label}
            value={form[field.key]}
            onChange={handleFieldChange(field.key)}
            helperText={field.helperText}
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
          系统配置
        </Typography>
        <Alert severity="warning">当前页面仅对超级管理员开放。</Alert>
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
          <Typography variant="h4">系统配置</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            当前阶段先将积分规则配置化，保持读模型闭环，不引入新的积分表和迁移。
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={refreshing ? <CircularProgress size={18} /> : <RefreshIcon />}
          onClick={() => void fetchPageData(true)}
          disabled={refreshing || saving}
        >
          刷新
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
                  积分规则
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  这里配置用户中心积分账户的奖励、冻结和有效期规则。保存后，新的积分汇总会立即使用最新快照。
                </Typography>
              </Box>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                <Chip
                  color={rules?.source === 'admin_log' ? 'primary' : 'default'}
                  label={rules?.source === 'admin_log' ? '管理员已覆盖' : '环境默认值'}
                />
                <Chip
                  variant="outlined"
                  label={rules?.updated_at ? `最近更新：${new Date(rules.updated_at).toLocaleString('zh-CN')}` : '尚未人工更新'}
                />
              </Stack>
            </Stack>

            <Divider sx={{ my: 3 }} />

            <Stack spacing={3}>
              {renderFieldGroup('奖励规则', REWARD_FIELDS)}
              {renderFieldGroup('冻结规则', FREEZE_FIELDS)}
              {renderFieldGroup('有效期规则', LIFECYCLE_FIELDS)}
            </Stack>

            <Alert severity="info" sx={{ mt: 3 }}>
              当前规则只作用于用户中心积分读模型。历史人工补发记录仍然生效，但不会替代未来正式积分账本。
            </Alert>

            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 3 }}>
              <Button variant="outlined" onClick={handleReset} disabled={!rules || saving || !isDirty}>
                恢复当前配置
              </Button>
              <Button variant="contained" onClick={() => void handleSave()} disabled={saving || !isDirty}>
                {saving ? '保存中...' : '保存规则'}
              </Button>
            </Stack>
          </CardContent>
        </Card>

        <Stack spacing={3}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <SettingsSuggestIcon fontSize="small" />
                系统健康
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
                    <Typography variant="subtitle2">数据库连接</Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                      {health?.timestamp ? `最近检查：${new Date(health.timestamp).toLocaleString('zh-CN')}` : '暂无检查时间'}
                    </Typography>
                  </Box>
                  <Chip
                    color={healthIsOk ? 'success' : 'error'}
                    icon={healthIsOk ? <CheckCircleIcon /> : <ErrorOutlineIcon />}
                    label={healthIsOk ? '正常' : '异常'}
                  />
                </Box>
              </Stack>
            </CardContent>
          </Card>

          <PointsPricingPolicyCard />

          <Card>
            <CardContent>
              <Typography variant="h6">规则说明</Typography>
              <Stack spacing={1.5} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  资产奖励建议继续放在用户中心统一汇总，因为它代表跨模块沉淀后的可复用价值。
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  运行冻结建议只在用户中心集中展示，避免用户在各生成模块看到多套冻结口径。
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  未来若引入充值订单、会员等级或正式积分流水，可以继续复用这套规则快照作为后台运营入口。
                </Typography>
              </Stack>
            </CardContent>
          </Card>

          <Card>
            <CardContent>
              <Typography variant="h6">最近操作</Typography>
              <Stack spacing={1} sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary">
                  更新来源：{rules?.source === 'admin_log' ? '管理员规则快照' : '环境默认配置'}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  操作人：{rules?.updated_by_username || '系统默认'}
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  生效方式：读取最新成功快照，不做数据库迁移。
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Stack>
      </Box>
    </Box>
  )
}
