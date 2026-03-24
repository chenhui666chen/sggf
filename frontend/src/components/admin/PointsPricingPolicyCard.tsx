import { useEffect, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { PriceCheck as PriceCheckIcon } from '@mui/icons-material'
import {
  type AdminPointsPricingPolicy,
  type AdminPointsPricingPolicyUpdatePayload,
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'

type PricingPolicyFormState = {
  points_per_yuan: string
  user_price_basis: AdminPointsPricingPolicyUpdatePayload['user_price_basis']
  user_price_rate: string
  provider_discount_capture_rate: string
  freeze_buffer_rate: string
  margin_warning_rate: string
  negative_margin_block_enabled: boolean
}

const EMPTY_FORM: PricingPolicyFormState = {
  points_per_yuan: '',
  user_price_basis: 'public_list_price',
  user_price_rate: '',
  provider_discount_capture_rate: '',
  freeze_buffer_rate: '',
  margin_warning_rate: '',
  negative_margin_block_enabled: true,
}

function buildFormState(policy: AdminPointsPricingPolicy | AdminPointsPricingPolicyUpdatePayload): PricingPolicyFormState {
  return {
    points_per_yuan: String(policy.points_per_yuan),
    user_price_basis: policy.user_price_basis,
    user_price_rate: String(policy.user_price_rate),
    provider_discount_capture_rate: String(policy.provider_discount_capture_rate),
    freeze_buffer_rate: String(policy.freeze_buffer_rate),
    margin_warning_rate: String(policy.margin_warning_rate),
    negative_margin_block_enabled: policy.negative_margin_block_enabled,
  }
}

function parsePricingPolicyForm(
  form: PricingPolicyFormState,
): { payload?: AdminPointsPricingPolicyUpdatePayload; error?: string } {
  const pointsPerYuan = Number(form.points_per_yuan)
  if (!Number.isInteger(pointsPerYuan) || pointsPerYuan < 1) {
    return { error: '每元可兑换积分必须是大于等于 1 的整数。' }
  }

  const userPriceRate = Number(form.user_price_rate)
  if (!Number.isFinite(userPriceRate) || userPriceRate < 0) {
    return { error: '用户计价系数必须是大于等于 0 的数字。' }
  }

  const providerDiscountCaptureRate = Number(form.provider_discount_capture_rate)
  if (!Number.isFinite(providerDiscountCaptureRate) || providerDiscountCaptureRate < 0 || providerDiscountCaptureRate > 1) {
    return { error: '供应商折扣归平台比例必须在 0 到 1 之间。' }
  }

  const freezeBufferRate = Number(form.freeze_buffer_rate)
  if (!Number.isFinite(freezeBufferRate) || freezeBufferRate < 0 || freezeBufferRate > 1) {
    return { error: '冻结缓冲系数必须在 0 到 1 之间。' }
  }

  const marginWarningRate = Number(form.margin_warning_rate)
  if (!Number.isFinite(marginWarningRate) || marginWarningRate < 0 || marginWarningRate > 1) {
    return { error: '低毛利预警线必须在 0 到 1 之间。' }
  }

  return {
    payload: {
      points_per_yuan: pointsPerYuan,
      user_price_basis: form.user_price_basis,
      user_price_rate: Number(userPriceRate.toFixed(4)),
      provider_discount_capture_rate: Number(providerDiscountCaptureRate.toFixed(4)),
      freeze_buffer_rate: Number(freezeBufferRate.toFixed(4)),
      margin_warning_rate: Number(marginWarningRate.toFixed(4)),
      negative_margin_block_enabled: form.negative_margin_block_enabled,
    },
  }
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(value === 1 ? 0 : 2)}%`
}

function formatPercentMaybe(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '--'
  }
  return formatPercent(value)
}

function formatCurrency(value: number) {
  return `￥${value.toFixed(2)}`
}

function getPricingBasisLabel(basis: AdminPointsPricingPolicy['user_price_basis']) {
  if (basis === 'standard_price_table') return '内部标准价'
  return '供应商公开价'
}

function getMarginStatusLabel(status: 'healthy' | 'warning' | 'negative') {
  if (status === 'negative') return '负毛利'
  if (status === 'warning') return '低毛利预警'
  return '毛利健康'
}

function getMarginStatusColor(status: 'healthy' | 'warning' | 'negative'): 'success' | 'warning' | 'error' {
  if (status === 'negative') return 'error'
  if (status === 'warning') return 'warning'
  return 'success'
}

export default function PointsPricingPolicyCard() {
  const [policy, setPolicy] = useState<AdminPointsPricingPolicy | null>(null)
  const [form, setForm] = useState<PricingPolicyFormState>(EMPTY_FORM)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  useEffect(() => {
    void fetchPolicy()
  }, [])

  const baselineForm = policy ? buildFormState(policy) : EMPTY_FORM
  const isDirty = JSON.stringify(form) !== JSON.stringify(baselineForm)
  const operatingSnapshots = Array.isArray(policy?.operating_snapshots) ? policy.operating_snapshots : []

  const fetchPolicy = async () => {
    try {
      setLoading(true)
      const response = await apiClient.getAdminPointsPricingPolicy()
      setPolicy(response.data)
      setForm(buildFormState(response.data))
      setError(null)
    } catch (err) {
      setError(await extractApiErrorMessage(err, '获取积分定价策略失败'))
    } finally {
      setLoading(false)
    }
  }

  const handleReset = () => {
    if (!policy) return
    setForm(buildFormState(policy))
    setSuccessMessage('已恢复为当前线上定价策略。')
    setError(null)
  }

  const handleSave = async () => {
    const parsed = parsePricingPolicyForm(form)
    if (!parsed.payload) {
      setError(parsed.error || '积分定价策略校验失败')
      return
    }

    try {
      setSaving(true)
      const response = await apiClient.updateAdminPointsPricingPolicy(parsed.payload)
      setPolicy(response.data)
      setForm(buildFormState(response.data))
      setSuccessMessage('积分定价策略已保存，后续充值与消耗规则可以直接复用这份快照。')
      setError(null)
    } catch (err) {
      setError(await extractApiErrorMessage(err, '保存积分定价策略失败'))
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <Card>
        <CardContent sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress size={28} />
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <PriceCheckIcon fontSize="small" />
          积分定价策略
        </Typography>

        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
          用户侧按公开价或标准价零加价计点，平台利润来自与供应商谈下来的折扣差，而不是用户侧加价。
        </Typography>

        {error ? (
          <Alert severity="error" sx={{ mt: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        ) : null}

        {successMessage ? (
          <Alert severity="success" sx={{ mt: 2 }} onClose={() => setSuccessMessage(null)}>
            {successMessage}
          </Alert>
        ) : null}

        {policy ? (
          <Stack direction="row" spacing={1} sx={{ mt: 2, flexWrap: 'wrap', rowGap: 1 }}>
            <Chip
              size="small"
              color={policy.source === 'admin_log' ? 'primary' : 'default'}
              label={policy.source === 'admin_log' ? '后台已覆盖' : '系统默认值'}
            />
            <Chip size="small" variant="outlined" label={`用户计价基准：${getPricingBasisLabel(policy.user_price_basis)}`} />
          </Stack>
        ) : null}

        <Stack spacing={2} sx={{ mt: 3 }}>
          <TextField
            label="每元可兑换积分"
            type="number"
            value={form.points_per_yuan}
            onChange={(event) => setForm((prev) => ({ ...prev, points_per_yuan: event.target.value }))}
            inputProps={{ min: 1, step: 1 }}
            helperText="建议固定汇率，例如 1 元 = 100 积分。"
            fullWidth
          />

          <FormControl fullWidth>
            <InputLabel>用户计价基准</InputLabel>
            <Select
              value={form.user_price_basis}
              label="用户计价基准"
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  user_price_basis: event.target.value as AdminPointsPricingPolicyUpdatePayload['user_price_basis'],
                }))
              }
            >
              <MenuItem value="public_list_price">供应商公开价</MenuItem>
              <MenuItem value="standard_price_table">内部标准价</MenuItem>
            </Select>
          </FormControl>

          <TextField
            label="用户计价系数"
            type="number"
            value={form.user_price_rate}
            onChange={(event) => setForm((prev) => ({ ...prev, user_price_rate: event.target.value }))}
            inputProps={{ min: 0, step: 0.0001 }}
            helperText="1.0 表示用户完全按基准价计点，不额外加价。"
            fullWidth
          />

          <TextField
            label="供应商折扣归平台比例"
            type="number"
            value={form.provider_discount_capture_rate}
            onChange={(event) => setForm((prev) => ({ ...prev, provider_discount_capture_rate: event.target.value }))}
            inputProps={{ min: 0, max: 1, step: 0.0001 }}
            helperText="1.0 表示供应商折扣全部归平台；如未来做会员返利，可降低该比例。"
            fullWidth
          />

          <TextField
            label="冻结缓冲系数"
            type="number"
            value={form.freeze_buffer_rate}
            onChange={(event) => setForm((prev) => ({ ...prev, freeze_buffer_rate: event.target.value }))}
            inputProps={{ min: 0, max: 1, step: 0.0001 }}
            helperText="运行中先多冻结一小部分积分，任务完成后按真实结果结算。"
            fullWidth
          />

          <TextField
            label="低毛利预警线"
            type="number"
            value={form.margin_warning_rate}
            onChange={(event) => setForm((prev) => ({ ...prev, margin_warning_rate: event.target.value }))}
            inputProps={{ min: 0, max: 1, step: 0.0001 }}
            helperText="当真实毛利率低于该值时，后续可触发运营预警。"
            fullWidth
          />

          <FormControlLabel
            control={
              <Checkbox
                checked={form.negative_margin_block_enabled}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, negative_margin_block_enabled: event.target.checked }))
                }
              />
            }
            label="预计负毛利时阻断任务"
          />
        </Stack>

        {policy ? (
          <Box sx={{ mt: 3, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
            <Typography variant="subtitle2">当前策略摘要</Typography>
            <Stack spacing={0.75} sx={{ mt: 1.5 }}>
              <Typography variant="body2" color="text.secondary">
                用户汇率：1 元 = {policy.points_per_yuan} 积分
              </Typography>
              <Typography variant="body2" color="text.secondary">
                用户计价：{getPricingBasisLabel(policy.user_price_basis)} × {policy.user_price_rate}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                折扣归平台：{formatPercent(policy.provider_discount_capture_rate)}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                冻结缓冲：{formatPercent(policy.freeze_buffer_rate)}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                低毛利预警：{formatPercent(policy.margin_warning_rate)}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                负毛利阻断：{policy.negative_margin_block_enabled ? '开启' : '关闭'}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                最近更新：{policy.updated_at ? new Date(policy.updated_at).toLocaleString('zh-CN') : '尚未人工调整'}
              </Typography>
            </Stack>
          </Box>
        ) : null}

        {operatingSnapshots.length > 0 ? (
          <Box sx={{ mt: 3 }}>
            <Typography variant="subtitle2">经营结算预览</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              以下按供应商公开价 1 元做口径样本，用来判断当前“用户零加价、平台赚折扣差”的毛利空间。
            </Typography>
            <Box
              sx={{
                mt: 1.5,
                display: 'grid',
                gap: 1.5,
                gridTemplateColumns: { xs: '1fr', md: '1fr 1fr' },
              }}
            >
              {operatingSnapshots.map((snapshot) => (
                <Box
                  key={snapshot.module_key}
                  sx={{
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 2,
                    p: 2,
                  }}
                >
                  <Stack direction="row" justifyContent="space-between" spacing={1} alignItems="center">
                    <Typography variant="subtitle2">{snapshot.module_label}</Typography>
                    <Chip
                      size="small"
                      color={getMarginStatusColor(snapshot.margin_status)}
                      label={getMarginStatusLabel(snapshot.margin_status)}
                    />
                  </Stack>
                  <Stack spacing={0.75} sx={{ mt: 1.5 }}>
                    <Typography variant="body2" color="text.secondary">
                      供应商公开价：{formatCurrency(snapshot.supplier_list_price_yuan)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      用户计费：{formatCurrency(snapshot.user_billed_yuan)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      供应商折扣：{formatPercent(snapshot.supplier_discount_rate)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      折扣来源：{snapshot.supplier_discount_rate_source}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      供应商折后成本：{formatCurrency(snapshot.supplier_discounted_cost_yuan)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      平台毛利：{formatCurrency(snapshot.platform_gross_profit_yuan)} / {formatPercentMaybe(snapshot.platform_margin_rate)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      折扣分配：平台保留 {formatCurrency(snapshot.captured_discount_yuan)}，让利用户 {formatCurrency(snapshot.shared_discount_yuan)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      负毛利拦截：{snapshot.negative_margin_blocked ? '已触发' : '未触发'}
                    </Typography>
                  </Stack>
                </Box>
              ))}
            </Box>
          </Box>
        ) : null}

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 3 }}>
          <Button variant="outlined" onClick={handleReset} disabled={!policy || saving || !isDirty}>
            恢复当前配置
          </Button>
          <Button variant="contained" onClick={() => void handleSave()} disabled={saving || !isDirty}>
            {saving ? '保存中...' : '保存定价策略'}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}
