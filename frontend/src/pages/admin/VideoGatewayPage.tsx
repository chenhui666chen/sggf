import { useCallback, useEffect, useState } from 'react'
import { Alert, Button, Card, CardContent, Chip, CircularProgress, Stack, Typography } from '@mui/material'
import { apiClient, extractApiErrorMessage, type VideoApiApplication, type VideoGatewayMetrics } from '@/services/api'
import VideoApiQuotaEditor from './VideoApiQuotaEditor'

export default function VideoGatewayPage() {
  const [items, setItems] = useState<VideoApiApplication[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [metrics, setMetrics] = useState<VideoGatewayMetrics | null>(null)
  const [metricsError, setMetricsError] = useState<string | null>(null)
  const [savingId, setSavingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [applicationsResult, metricsResult] = await Promise.allSettled([
        apiClient.listAdminVideoApiApplications(),
        apiClient.getAdminVideoGatewayMetrics(),
      ])
      if (applicationsResult.status === 'rejected') throw applicationsResult.reason
      setItems(applicationsResult.value.data.items || [])
      if (metricsResult.status === 'fulfilled') {
        setMetrics(metricsResult.value.data)
        setMetricsError(null)
      } else {
        setMetrics(null)
        setMetricsError(await extractApiErrorMessage(metricsResult.reason, '监控暂不可用'))
      }
      setError(null)
    } catch (loadError) {
      setError(await extractApiErrorMessage(loadError, '读取视频网关应用失败'))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const updateStatus = async (id: number, status: 'active' | 'suspended' | 'revoked') => {
    setSavingId(id)
    try {
      const response = await apiClient.updateAdminVideoApiApplicationStatus(id, status)
      setItems((current) => current.map((item) => item.id === id ? response.data : item))
    } catch (updateError) {
      setError(await extractApiErrorMessage(updateError, '更新应用状态失败'))
    } finally {
      setSavingId(null)
    }
  }

  if (loading) return <CircularProgress />

  return (
    <Stack spacing={3}>
      <Stack direction="row" justifyContent="space-between" alignItems="center">
        <BoxTitle />
        <Button variant="outlined" onClick={() => void load()}>刷新</Button>
      </Stack>
      {error ? <Alert severity="error">{error}</Alert> : null}
      {metricsError ? <Alert severity="warning">{metricsError}</Alert> : null}
      {metrics ? (
        <Card variant="outlined"><CardContent>
          <Typography variant="subtitle1">最近 {metrics.window_hours} 小时网关概览</Typography>
          <Typography variant="body2" color="text.secondary">
            尝试成功率 {metrics.route_event_count ? `${(metrics.success_rate * 100).toFixed(2)}%` : '暂无样本'} · 活动任务 {metrics.active_jobs} · 待派发 {metrics.pending_jobs} · 事件 {metrics.route_event_count} · P50/P95 {metrics.p50_latency_seconds}/{metrics.p95_latency_seconds}s
          </Typography>
          <Typography variant="body2">已记录成本 {metrics.total_cost ?? '暂无账单'} · 成本未知的尝试 {metrics.unknown_cost_attempts}。成功率和延迟基于最近 {metrics.sampled_event_count} 条结果事件，最多 10000 条。</Typography>
          <Typography variant="body2">内部质量抽评：已完成 {metrics.quality.completed ?? 0} · 评价失败 {metrics.quality.failed ?? 0} · 正在评价 {metrics.quality.running ?? 0}。同一模型每成功 10 次抽评 1 次，结果仅用于内部路由，用户交付不等待评价。</Typography>
          {metrics.providers.map((provider) => <Chip key={provider.provider} sx={{ mr: 1, mt: 1 }} label={`${provider.provider} · ${provider.configured ? '凭据已配置' : '未配置'}`} />)}
          {metrics.routes.map((route) => (
            <Typography key={route.route_id} variant="body2" sx={{ mt: 1 }}>
              路由 {route.route_id}（{route.provider || '历史路由'}）：{route.enabled === false ? '已禁用' : route.configured === false ? '供应商未配置' : '已登记'} · 尝试成功率 {route.samples && route.success_rate !== null ? `${(route.success_rate * 100).toFixed(2)}%` : '暂无样本'} · P50/P95 {route.p50_latency_seconds ?? '—'}/{route.p95_latency_seconds ?? '—'}s · 样本 {route.samples}
              {' · 质量均分 '}{route.quality_average_score ?? '—'}{'/10 · 评价样本 '}{route.quality_samples ?? 0}
            </Typography>
          ))}
          {metrics.clients.map((client) => (
            <Typography key={client.client_id} variant="body2" sx={{ mt: 1 }}>
              客户 {client.client_id}：任务 {client.total_jobs} · 活动 {client.active_jobs} · 成功 {client.succeeded_jobs} · 失败 {client.failed_jobs}
            </Typography>
          ))}
        </CardContent></Card>
      ) : null}
      <Alert severity="info">此页面仅超级管理员可访问。这里显示的是应用状态和配额，不显示完整 API Key。</Alert>
      {items.map((item) => (
        <Card key={item.id} variant="outlined">
          <CardContent>
            <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" spacing={2}>
              <div>
                <Typography variant="h6">{item.name}</Typography>
                <Typography color="text.secondary">应用 #{item.id} · Key 前缀 {item.api_key_prefix} · 套餐 {item.plan_code}</Typography>
                <Typography variant="body2" sx={{ mt: 1 }}>速率 {item.rate_limit_per_second}/秒 · 突发 {item.burst_capacity} · 活动任务 {item.max_active_jobs} · 累计任务额度 {item.lifetime_task_limit}</Typography>
                <VideoApiQuotaEditor item={item} onSaved={(updated) => setItems((current) => current.map((entry) => entry.id === updated.id ? updated : entry))} />
                <Chip size="small" sx={{ mt: 1 }} label={item.status} color={item.status === 'active' ? 'success' : item.status === 'suspended' ? 'warning' : 'default'} />
              </div>
              <Stack direction="row" spacing={1} alignItems="flex-start" sx={{ flexWrap: 'wrap' }}>
                {item.status === 'pending' ? <Button disabled={savingId !== null} size="small" variant="contained" onClick={() => void updateStatus(item.id, 'active')}>批准开通</Button> : null}
                {item.status === 'active' ? <Button disabled={savingId !== null} size="small" color="warning" variant="outlined" onClick={() => void updateStatus(item.id, 'suspended')}>暂停</Button> : null}
                {item.status === 'suspended' ? <Button disabled={savingId !== null} size="small" color="success" variant="outlined" onClick={() => void updateStatus(item.id, 'active')}>恢复</Button> : null}
                {item.status !== 'revoked' ? <Button disabled={savingId !== null} size="small" color="error" variant="outlined" onClick={() => void updateStatus(item.id, 'revoked')}>吊销</Button> : null}
              </Stack>
            </Stack>
          </CardContent>
        </Card>
      ))}
      {items.length === 0 ? <Alert severity="info">暂无视频 API 应用。</Alert> : null}
    </Stack>
  )
}

function BoxTitle() {
  return (
    <div>
      <Typography variant="h5" sx={{ fontWeight: 800 }}>视频网关</Typography>
      <Typography color="text.secondary">API 应用、配额与运行入口管理</Typography>
    </div>
  )
}
