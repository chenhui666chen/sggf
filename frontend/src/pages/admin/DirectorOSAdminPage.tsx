// AI Director OS 管理后台页面（Phase 3/4 数据展示）
// 展示：知识治理 / 修复成功率 / 调用审计 / 预算管控 / AM-15 统计

import React from 'react'
import {
  Box, Card, CardContent, CardHeader, Chip, CircularProgress,
  Grid, LinearProgress, Paper, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Typography,
} from '@mui/material'
import AssessmentIcon from '@mui/icons-material/Assessment'
import BuildIcon from '@mui/icons-material/Build'
import SecurityIcon from '@mui/icons-material/Security'
import StorageIcon from '@mui/icons-material/Storage'

import type {
  KnowledgeGovernanceSummary, RepairStats, AuditStats, BudgetStatus,
} from '@/types/directorOS'

interface GovernanceData {
  knowledge: KnowledgeGovernanceSummary
  repair: RepairStats
  audit: AuditStats
  budget: BudgetStatus
  stage_handoffs: Array<{ stage: string; status: string }>
  am15_latest: {
    verdict: string
    cheap_intercept_rate: number
    persona_status: string
  } | null
}

function StatCard({ title, value, sub, icon, color }: {
  title: string; value: string | number; sub?: string
  icon: React.ReactNode; color?: string
}) {
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          {icon}
          <Typography variant="caption" color="text.secondary">{title}</Typography>
        </Box>
        <Typography variant="h4" color={color || 'primary'}>
          {value}
        </Typography>
        {sub && <Typography variant="caption" color="text.secondary">{sub}</Typography>}
      </CardContent>
    </Card>
  )
}

function RepairSuccessBar({ rate }: { rate: number }) {
  const pct = Math.round(rate * 100)
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <Box sx={{ flex: 1 }}>
        <LinearProgress
          variant="determinate"
          value={pct}
          color={pct >= 60 ? 'success' : pct >= 40 ? 'warning' : 'error'}
          sx={{ height: 8, borderRadius: 4 }}
        />
      </Box>
      <Typography variant="body2" fontWeight={600}>{pct}%</Typography>
    </Box>
  )
}

function GovernanceTable({ knowledge }: { knowledge: KnowledgeGovernanceSummary }) {
  const total = knowledge.verified + knowledge.pending + knowledge.deprecated
  const rows = [
    { label: 'verified（A 级）', count: knowledge.verified, color: 'success' },
    { label: 'pending（B/C 级）', count: knowledge.pending, color: 'warning' },
    { label: 'deprecated', count: knowledge.deprecated, color: 'error' },
    { label: 'stale（>180天）', count: knowledge.stale, color: 'default' },
  ]
  return (
    <TableContainer component={Paper} variant="outlined">
      <Table size="small">
        <TableHead>
          <TableRow>
            <TableCell>验证状态</TableCell>
            <TableCell align="right">数量</TableCell>
            <TableCell align="right">占比</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map(r => (
            <TableRow key={r.label}>
              <TableCell>
                <Chip label={r.count} size="small" color={r.color as 'success' | 'warning' | 'error' | 'default'} sx={{ height: 18, mr: 1 }} />
                {r.label}
              </TableCell>
              <TableCell align="right">{r.count}</TableCell>
              <TableCell align="right">
                {total > 0 ? Math.round((r.count / total) * 100) : 0}%
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  )
}

function BudgetPanel({ budget }: { budget: BudgetStatus }) {
  const used = budget.accumulated
  const cap = budget.project_total_cap
  const pct = cap > 0 ? Math.min(100, Math.round((used / cap) * 100)) : 0
  return (
    <Card variant="outlined">
      <CardHeader
        avatar={<SecurityIcon color={budget.blocked ? 'error' : 'primary'} />}
        title={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Typography variant="subtitle2">预算管控</Typography>
            {budget.blocked && <Chip label="已熔断" size="small" color="error" sx={{ height: 20 }} />}
          </Box>
        }
        subheader={`已消耗 ¥${used.toFixed(2)} / 上限 ${cap > 0 ? `¥${cap.toFixed(2)}` : '不限'}`}
      />
      <CardContent sx={{ pt: 0 }}>
        {cap > 0 && <LinearProgress variant="determinate" value={pct} color={pct > 80 ? 'error' : 'primary'} sx={{ height: 8, borderRadius: 4, mb: 1 }} />}
        <Typography variant="caption" color="text.secondary">
          三档管控：总额上限 / 单步阈值 / 超限熔断（不静默扣费）
        </Typography>
      </CardContent>
    </Card>
  )
}

export default function DirectorOSAdminPage() {
  const [data, setData] = React.useState<GovernanceData | null>(null)
  const [loading, setLoading] = React.useState(true)

  React.useEffect(() => {
    // TODO: 接入后端 admin API 后替换
    // 目前展示骨架，数据源由 knowledge_hub + commercial_hooks 产出
    const mock: GovernanceData = {
      knowledge: { verified: 8, pending: 11, deprecated: 0, stale: 0 },
      repair: { total_repair_attempts: 0, success_count: 0, success_rate: 0 },
      audit: { total_calls: 0, stages: [], knowledge_ids_used: 0 },
      budget: { project_total_cap: 100, accumulated: 0, blocked: false },
      stage_handoffs: [],
      am15_latest: null,
    }
    setData(mock)
    setLoading(false)
  }, [])

  if (loading) return <CircularProgress />
  if (!data) return null

  return (
    <Box sx={{ p: 3 }}>
      <Typography variant="h5" gutterBottom>
        AI Director OS · 知识治理看板
      </Typography>

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="已验证知识" value={data.knowledge.verified}
            sub={`${data.knowledge.pending} 待验证`} icon={<StorageIcon color="success" />}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="修复成功率"
            value={data.repair.success_rate > 0 ? `${Math.round(data.repair.success_rate * 100)}%` : '—'}
            sub={`${data.repair.total_repair_attempts} 次修复`}
            icon={<BuildIcon color="primary" />}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="知识调用" value={data.audit.total_calls}
            sub={`${data.audit.knowledge_ids_used} 个知识单元`}
            icon={<AssessmentIcon color="info" />}
          />
        </Grid>
        <Grid item xs={12} sm={6} md={3}>
          <StatCard
            title="AM-15 最新"
            value={data.am15_latest?.verdict || '—'}
            sub={data.am15_latest ? `拦截率 ${Math.round(data.am15_latest.cheap_intercept_rate * 100)}%` : '尚无数据'}
            icon={<AssessmentIcon color="secondary" />}
          />
        </Grid>
      </Grid>

      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Card variant="outlined">
            <CardHeader title="知识验证状态分布" subheader="verification_status 流转（pending→verified→deprecated）" />
            <CardContent>
              <GovernanceTable knowledge={data.knowledge} />
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={6}>
          <Card variant="outlined">
            <CardHeader title="修复成功率" subheader="Learning Loop 统计回写（目标 ≥60%）" />
            <CardContent>
              {data.repair.total_repair_attempts > 0 ? (
                <RepairSuccessBar rate={data.repair.success_rate} />
              ) : (
                <Typography variant="body2" color="text.secondary">
                  尚无修复记录——需要运行短剧管线后产生数据
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12}>
          <BudgetPanel budget={data.budget} />
        </Grid>
      </Grid>
    </Box>
  )
}
