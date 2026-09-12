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
import PriceCheckIcon from '@mui/icons-material/PriceCheck'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { useFormats } from '@/i18n'
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
  t: TFunction,
): { payload?: AdminPointsPricingPolicyUpdatePayload; error?: string } {
  const pointsPerYuan = Number(form.points_per_yuan)
  if (!Number.isInteger(pointsPerYuan) || pointsPerYuan < 1) {
    return { error: t('admin.pricingPolicy.validation.pointsIntMin') }
  }

  const userPriceRate = Number(form.user_price_rate)
  if (!Number.isFinite(userPriceRate) || userPriceRate < 0) {
    return { error: t('admin.pricingPolicy.validation.rateNotNegative') }
  }

  const providerDiscountCaptureRate = Number(form.provider_discount_capture_rate)
  if (!Number.isFinite(providerDiscountCaptureRate) || providerDiscountCaptureRate < 0 || providerDiscountCaptureRate > 1) {
    return { error: t('admin.pricingPolicy.validation.captureRange') }
  }

  const freezeBufferRate = Number(form.freeze_buffer_rate)
  if (!Number.isFinite(freezeBufferRate) || freezeBufferRate < 0 || freezeBufferRate > 1) {
    return { error: t('admin.pricingPolicy.validation.freezeRange') }
  }

  const marginWarningRate = Number(form.margin_warning_rate)
  if (!Number.isFinite(marginWarningRate) || marginWarningRate < 0 || marginWarningRate > 1) {
    return { error: t('admin.pricingPolicy.validation.marginRange') }
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

function getPricingBasisLabel(basis: AdminPointsPricingPolicy['user_price_basis'], t?: TFunction) {
  if (basis === 'standard_price_table') return t ? t('admin.pricingPolicy.fields.basisStandard') : '内部标准价'
  return t ? t('admin.pricingPolicy.fields.basisPublic') : '供应商公开价'
}

function getMarginStatusLabel(status: 'healthy' | 'warning' | 'negative', t?: TFunction) {
  if (status === 'negative') return t ? t('admin.pointsBilling.status.negative') : '负毛利'
  if (status === 'warning') return t ? t('admin.pointsBilling.status.warning') : '低毛利预警'
  return t ? t('admin.pointsBilling.status.healthy') : '毛利健康'
}

function getMarginStatusColor(status: 'healthy' | 'warning' | 'negative'): 'success' | 'warning' | 'error' {
  if (status === 'negative') return 'error'
  if (status === 'warning') return 'warning'
  return 'success'
}

export default function PointsPricingPolicyCard() {
  const { t } = useTranslation()
  // 只解构 formatDateTime：本文件另有 formatPercent / formatCurrency 等本地 helper。
  const { formatDateTime } = useFormats()
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
      setError(await extractApiErrorMessage(err, t('admin.pricingPolicy.messages.fetchFailed')))
    } finally {
      setLoading(false)
    }
  }

  const handleReset = () => {
    if (!policy) return
    setForm(buildFormState(policy))
    setSuccessMessage(t('admin.pricingPolicy.messages.resetDone'))
    setError(null)
  }

  const handleSave = async () => {
    const parsed = parsePricingPolicyForm(form, t)
    if (!parsed.payload) {
      setError(parsed.error || t('admin.pricingPolicy.messages.validationFailed'))
      return
    }

    try {
      setSaving(true)
      const response = await apiClient.updateAdminPointsPricingPolicy(parsed.payload)
      setPolicy(response.data)
      setForm(buildFormState(response.data))
      setSuccessMessage(t('admin.pricingPolicy.messages.saved'))
      setError(null)
    } catch (err) {
      setError(await extractApiErrorMessage(err, t('admin.pricingPolicy.messages.saveFailed')))
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
          {t('admin.pricingPolicy.title')}
        </Typography>

        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
          {t('admin.pricingPolicy.subtitle')}
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
              label={policy.source === 'admin_log' ? t('admin.pricingPolicy.sourceOverridden') : t('admin.pricingPolicy.sourceDefault')}
            />
            <Chip
              size="small"
              variant="outlined"
              label={t('admin.pricingPolicy.basisPrefix', {
                basis: getPricingBasisLabel(policy.user_price_basis, t),
              })}
            />
          </Stack>
        ) : null}

        <Stack spacing={2} sx={{ mt: 3 }}>
          <TextField
            label={t('admin.pricingPolicy.fields.pointsPerYuan')}
            type="number"
            value={form.points_per_yuan}
            onChange={(event) => setForm((prev) => ({ ...prev, points_per_yuan: event.target.value }))}
            inputProps={{ min: 1, step: 1 }}
            helperText={t('admin.pricingPolicy.fields.pointsPerYuanHelp')}
            fullWidth
          />

          <FormControl fullWidth>
            <InputLabel>{t('admin.pricingPolicy.fields.basis')}</InputLabel>
            <Select
              value={form.user_price_basis}
              label={t('admin.pricingPolicy.fields.basis')}
              onChange={(event) =>
                setForm((prev) => ({
                  ...prev,
                  user_price_basis: event.target.value as AdminPointsPricingPolicyUpdatePayload['user_price_basis'],
                }))
              }
            >
              <MenuItem value="public_list_price">{t('admin.pricingPolicy.fields.basisPublic')}</MenuItem>
              <MenuItem value="standard_price_table">{t('admin.pricingPolicy.fields.basisStandard')}</MenuItem>
            </Select>
          </FormControl>

          <TextField
            label={t('admin.pricingPolicy.fields.userPriceRate')}
            type="number"
            value={form.user_price_rate}
            onChange={(event) => setForm((prev) => ({ ...prev, user_price_rate: event.target.value }))}
            inputProps={{ min: 0, step: 0.0001 }}
            helperText={t('admin.pricingPolicy.fields.userPriceRateHelp')}
            fullWidth
          />

          <TextField
            label={t('admin.pricingPolicy.fields.captureRate')}
            type="number"
            value={form.provider_discount_capture_rate}
            onChange={(event) => setForm((prev) => ({ ...prev, provider_discount_capture_rate: event.target.value }))}
            inputProps={{ min: 0, max: 1, step: 0.0001 }}
            helperText={t('admin.pricingPolicy.fields.captureRateHelp')}
            fullWidth
          />

          <TextField
            label={t('admin.pricingPolicy.fields.freezeBuffer')}
            type="number"
            value={form.freeze_buffer_rate}
            onChange={(event) => setForm((prev) => ({ ...prev, freeze_buffer_rate: event.target.value }))}
            inputProps={{ min: 0, max: 1, step: 0.0001 }}
            helperText={t('admin.pricingPolicy.fields.freezeBufferHelp')}
            fullWidth
          />

          <TextField
            label={t('admin.pricingPolicy.fields.marginWarning')}
            type="number"
            value={form.margin_warning_rate}
            onChange={(event) => setForm((prev) => ({ ...prev, margin_warning_rate: event.target.value }))}
            inputProps={{ min: 0, max: 1, step: 0.0001 }}
            helperText={t('admin.pricingPolicy.fields.marginWarningHelp')}
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
            label={t('admin.pricingPolicy.fields.blockNegative')}
          />
        </Stack>

        {policy ? (
          <Box sx={{ mt: 3, p: 2, border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
            <Typography variant="subtitle2">{t('admin.pricingPolicy.summary.title')}</Typography>
            <Stack spacing={0.75} sx={{ mt: 1.5 }}>
              <Typography variant="body2" color="text.secondary">
                {t('admin.pricingPolicy.summary.exchangeRate', { points: policy.points_per_yuan })}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('admin.pricingPolicy.summary.userPricing', {
                  basis: getPricingBasisLabel(policy.user_price_basis, t),
                  rate: policy.user_price_rate,
                })}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('admin.pricingPolicy.summary.discountToPlatform', { rate: formatPercent(policy.provider_discount_capture_rate) })}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('admin.pricingPolicy.summary.freezeBuffer', { rate: formatPercent(policy.freeze_buffer_rate) })}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('admin.pricingPolicy.summary.marginWarning', { rate: formatPercent(policy.margin_warning_rate) })}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {t('admin.pricingPolicy.summary.blockNegative', {
                  status: policy.negative_margin_block_enabled
                    ? t('admin.pricingPolicy.summary.blockOn')
                    : t('admin.pricingPolicy.summary.blockOff'),
                })}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {policy.updated_at
                  ? t('admin.pricingPolicy.summary.recentUpdate', { time: formatDateTime(policy.updated_at) })
                  : t('admin.pricingPolicy.summary.notAdjusted')}
              </Typography>
            </Stack>
          </Box>
        ) : null}

        {operatingSnapshots.length > 0 ? (
          <Box sx={{ mt: 3 }}>
            <Typography variant="subtitle2">{t('admin.pricingPolicy.preview.title')}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
              {t('admin.pricingPolicy.preview.hint')}
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
                      label={getMarginStatusLabel(snapshot.margin_status, t)}
                    />
                  </Stack>
                  <Stack spacing={0.75} sx={{ mt: 1.5 }}>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pricingPolicy.preview.supplierListPrice', { amount: formatCurrency(snapshot.supplier_list_price_yuan) })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pricingPolicy.preview.userBilled', { amount: formatCurrency(snapshot.user_billed_yuan) })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pricingPolicy.preview.supplierDiscount', { rate: formatPercent(snapshot.supplier_discount_rate) })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pricingPolicy.preview.discountSource', { source: snapshot.supplier_discount_rate_source })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pricingPolicy.preview.supplierCost', { amount: formatCurrency(snapshot.supplier_discounted_cost_yuan) })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pricingPolicy.preview.platformProfit', {
                        profit: formatCurrency(snapshot.platform_gross_profit_yuan),
                        rate: formatPercentMaybe(snapshot.platform_margin_rate),
                      })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pricingPolicy.preview.discountAlloc', {
                        captured: formatCurrency(snapshot.captured_discount_yuan),
                        shared: formatCurrency(snapshot.shared_discount_yuan),
                      })}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {t('admin.pricingPolicy.preview.blockStatus', {
                        status: snapshot.negative_margin_blocked
                          ? t('admin.pricingPolicy.preview.blocked')
                          : t('admin.pricingPolicy.preview.notBlocked'),
                      })}
                    </Typography>
                  </Stack>
                </Box>
              ))}
            </Box>
          </Box>
        ) : null}

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mt: 3 }}>
          <Button variant="outlined" onClick={handleReset} disabled={!policy || saving || !isDirty}>
            {t('admin.pricingPolicy.actions.reset')}
          </Button>
          <Button variant="contained" onClick={() => void handleSave()} disabled={saving || !isDirty}>
            {saving ? t('admin.pricingPolicy.actions.saving') : t('admin.pricingPolicy.actions.savePricing')}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}
