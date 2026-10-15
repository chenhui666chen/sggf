// AI Director OS 组件（Phase 2/3/4 前端展示层）
// 挂载到 dreamweaver-run 工作台与 admin 后台

import React from 'react'
import {
  Alert, Box, Card, CardContent, CardHeader, Chip, Collapse, Divider,
  Grid, IconButton, Paper, Tab, Tabs, Tooltip, Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import MovieIcon from '@mui/icons-material/Movie'
import RateReviewIcon from '@mui/icons-material/RateReview'
import SchemaIcon from '@mui/icons-material/Schema'
import SpeedIcon from '@mui/icons-material/Speed'
import TimelineIcon from '@mui/icons-material/Timeline'
import WarningIcon from '@mui/icons-material/Warning'

import type {
  Am15Report, ShotContract, ScriptDocument, StateEngineTrack,
  StageHandoff, RepairKnowledge, SynthesisChannels, StoryGraph,
} from '@/types/directorOS'
import { getShotSizeColor, getRLevelColor } from '@/utils/directorOSAccessors'

// ============================================================
// Shot Contract 卡片
// ============================================================
export function ShotContractCard({ contract }: { contract: ShotContract }) {
  const [expanded, setExpanded] = React.useState(false)
  const sizeColor = getShotSizeColor(contract.shot_size)

  return (
    <Card variant="outlined" sx={{ mb: 1, borderLeft: `4px solid ${sizeColor}` }}>
      <CardHeader
        avatar={<MovieIcon sx={{ color: sizeColor }} />}
        title={
          <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center', flexWrap: 'wrap' }}>
            <Typography variant="body2" fontWeight={600}>
              {contract.shot_id}
            </Typography>
            <Chip label={contract.shot_size} size="small" sx={{ bgcolor: sizeColor, color: '#fff' /* sg-color-fixed：景别数据色固定深底，配白字保证双主题可读 */, height: 20 }} />
            {contract.r_pre_eligible && (
              <Tooltip title="R-pre 候选择优（高价值 beat 双候选）">
                <Chip label="R-pre" size="small" color="success" sx={{ height: 20 }} />
              </Tooltip>
            )}
            {contract.keyframe_source === 'i2v_trajectory' && (
              <Tooltip title="DC-037 迪士尼两阶段法（I2V 轨迹选帧）">
                <Chip label="I2V轨迹" size="small" color="secondary" sx={{ height: 20 }} />
              </Tooltip>
            )}
            {contract.reference_image_required && (
              <Tooltip title="低服从度项需参考图实现">
                <Chip label="参考图" size="small" variant="outlined" color="warning" sx={{ height: 20 }} />
              </Tooltip>
            )}
          </Box>
        }
        subheader={`${contract.shot_size_zh} · ${contract.camera_movement.split(' ')[0]} · ${contract.duration_s}s · ${contract.beat_id}`}
        action={
          <IconButton onClick={() => setExpanded(!expanded)} size="small">
            <ExpandMoreIcon sx={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: '0.2s' }} />
          </IconButton>
        }
        sx={{ py: 1 }}
      />
      <Collapse in={expanded} timeout="auto">
        <CardContent sx={{ pt: 0 }}>
          <Grid container spacing={1}>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">运镜</Typography>
              <Typography variant="body2">{contract.camera_movement}</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">灯光</Typography>
              <Typography variant="body2">{contract.lighting}</Typography>
            </Grid>
            <Grid item xs={12}>
              <Typography variant="caption" color="text.secondary">视觉锚点</Typography>
              <Typography variant="body2">{contract.visual_anchor}</Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">状态链</Typography>
              <Typography variant="body2" fontSize="0.75rem">
                {contract.state_before || '—'} → {contract.state_after || '—'}
              </Typography>
            </Grid>
            <Grid item xs={6}>
              <Typography variant="caption" color="text.secondary">Shot Purpose</Typography>
              <Typography variant="body2">{contract.shot_purpose}</Typography>
            </Grid>
            {contract.action && (
              <Grid item xs={12}>
                <Typography variant="caption" color="text.secondary">动作链</Typography>
                <Typography variant="body2">{contract.action}</Typography>
              </Grid>
            )}
            {contract.dispatch_dc_ids.length > 0 && (
              <Grid item xs={12}>
                <Typography variant="caption" color="text.secondary">T2 Dispatch DC</Typography>
                <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                  {contract.dispatch_dc_ids.map(id => (
                    <Chip key={id} label={id} size="small" variant="outlined" sx={{ height: 20 }} />
                  ))}
                </Box>
              </Grid>
            )}
            {contract.dialogue.length > 0 && (
              <Grid item xs={12}>
                <Divider sx={{ my: 1 }} />
                {contract.dialogue.map((d, i) => (
                  <Typography key={i} variant="body2" sx={{ fontStyle: 'italic' }}>
                    {d.speaker}：{d.line}
                  </Typography>
                ))}
              </Grid>
            )}
          </Grid>
        </CardContent>
      </Collapse>
    </Card>
  )
}

// ============================================================
// Shot Contract 列表
// ============================================================
export function ShotContractList({ contracts }: { contracts: ShotContract[] }) {
  if (!contracts.length) return null
  return (
    <Box>
      <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', mb: 1.5 }}>
        <SchemaIcon color="primary" fontSize="small" />
        <Typography variant="subtitle2">Shot Contracts（{contracts.length} 镜）</Typography>
        <Chip
          label={`R-pre ${contracts.filter(c => c.r_pre_eligible).length}`}
          size="small" color="success" sx={{ height: 20 }}
        />
      </Box>
      {contracts.map((c) => (
        <ShotContractCard key={c.shot_id} contract={c} />
      ))}
    </Box>
  )
}

// ============================================================
// AM-15 评价报告面板
// ============================================================
export function Am15ReportPanel({ report }: { report: Am15Report }) {
  const [tab, setTab] = React.useState(0)
  if (!report || report.status !== 'ok' || !report.critique) {
    return (
      <Alert severity="info" sx={{ mt: 1 }}>
        AM-15 评价报告：{report?.status || '不可用'}
      </Alert>
    )
  }
  const c = report.critique
  const verdictColor = c.verdict === 'pass' ? 'success' : c.verdict === 'fail_state' ? 'warning' : 'error'

  return (
    <Card variant="outlined" sx={{ mt: 1 }}>
      <CardHeader
        avatar={<RateReviewIcon color={verdictColor === 'success' ? 'success' : 'warning'} />}
        title={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Typography variant="subtitle2">AM-15 评价报告</Typography>
            <Chip
              label={c.verdict}
              size="small"
              color={verdictColor as 'success' | 'warning' | 'error'}
              sx={{ height: 20 }}
            />
            {c.cross_shot?.state_transition_gaps > 0 && (
              <Chip label={`状态 gap ${c.cross_shot.state_transition_gaps}`} size="small" color="warning" sx={{ height: 20 }} />
            )}
          </Box>
        }
        subheader={`廉价拦截 ${c.hybrid?.objective?.cheap?.intercepted ?? 0} | 主观 ${c.hybrid?.subjective?.status} | persona ${c.personas?.status}`}
      />
      <CardContent sx={{ pt: 0 }}>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 1 }}>
          <Tab label="Markdown" />
          <Tab label="Critique JSON" />
        </Tabs>
        {tab === 0 && (
          <Paper variant="outlined" sx={{ p: 1.5, maxHeight: 400, overflow: 'auto' }}>
            <Typography component="pre" sx={{ whiteSpace: 'pre-wrap', fontSize: '0.75rem', fontFamily: 'monospace' }}>
              {report.markdown || '（无 markdown）'}
            </Typography>
          </Paper>
        )}
        {tab === 1 && (
          <Paper variant="outlined" sx={{ p: 1.5, maxHeight: 400, overflow: 'auto' }}>
            <Typography component="pre" sx={{ whiteSpace: 'pre-wrap', fontSize: '0.7rem', fontFamily: 'monospace' }}>
              {JSON.stringify(c, null, 2)}
            </Typography>
          </Paper>
        )}
        {c.cf_hits.length > 0 && (
          <Box sx={{ mt: 1.5 }}>
            <Typography variant="caption" color="text.secondary">CF 命中（L1 直索）</Typography>
            {c.cf_hits.map((h, i) => (
              <Chip key={i} label={`${h.cf_id} ${h.title}`} size="small" color="error" variant="outlined" sx={{ m: 0.25, height: 22 }} />
            ))}
          </Box>
        )}
        {c.repair_suggestions.length > 0 && (
          <Box sx={{ mt: 1 }}>
            <Typography variant="caption" color="text.secondary">修复建议</Typography>
            {c.repair_suggestions.map((s, i) => (
              <Typography key={i} variant="body2" color="text.secondary" fontSize="0.75rem">• {s}</Typography>
            ))}
          </Box>
        )}
      </CardContent>
    </Card>
  )
}

// ============================================================
// State Engine 面板（修复后重算可视化）
// ============================================================
export function StateEnginePanel({ tracks }: { tracks: StateEngineTrack[] }) {
  const [expanded, setExpanded] = React.useState(false)
  if (!tracks.length) return null

  const totalGaps = tracks.reduce((s, t) => s + (t.transition_summary?.gaps || 0), 0)
  const totalVerified = tracks.reduce((s, t) => s + (t.transition_summary?.verified || 0), 0)

  return (
    <Card variant="outlined" sx={{ mt: 1 }}>
      <CardHeader
        avatar={<TimelineIcon color={totalGaps > 0 ? 'warning' : 'success'} />}
        title={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Typography variant="subtitle2">State Engine</Typography>
            <Chip label={`✓ ${totalVerified}`} size="small" color="success" sx={{ height: 20 }} />
            {totalGaps > 0 && <Chip label={`gap ${totalGaps}`} size="small" color="warning" sx={{ height: 20 }} />}
          </Box>
        }
        subheader="End State = Start State + Verified Transitions"
        action={
          <IconButton onClick={() => setExpanded(!expanded)} size="small">
            <ExpandMoreIcon sx={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: '0.2s' }} />
          </IconButton>
        }
        sx={{ py: 1 }}
      />
      <Collapse in={expanded} timeout="auto">
        <CardContent sx={{ pt: 0 }}>
          {tracks.map(track => (
            <Box key={track.cam_idx} sx={{ mb: 2 }}>
              <Typography variant="caption" color="text.secondary">
                Camera Track {track.cam_idx}（{track.transition_summary?.verified ?? 0}✓ / {track.transition_summary?.gaps ?? 0} gap）
              </Typography>
              {track.states.map(s => (
                <Box key={s.state_id} sx={{ display: 'flex', gap: 1, alignItems: 'center', py: 0.25 }}>
                  <Chip
                    label={s.state_id}
                    size="small"
                    sx={{ height: 18, fontSize: '0.65rem', minWidth: 70 }}
                    color={s.transition_verified ? 'success' : s.transition_gap ? 'warning' : 'default'}
                    variant="outlined"
                  />
                  <Typography variant="caption" sx={{ flex: 1 }}>
                    {s.start_state || '（空）'} → {s.end_state || '（空）'}
                  </Typography>
                  {s.transition_gap && (
                    <Tooltip title={`gap: prev_end=${s.transition_gap.prev_end_state} ≠ cur_start=${s.transition_gap.cur_start_state}`}>
                      <WarningIcon fontSize="small" color="warning" />
                    </Tooltip>
                  )}
                </Box>
              ))}
            </Box>
          ))}
        </CardContent>
      </Collapse>
    </Card>
  )
}

// ============================================================
// 修复知识面板（R0-R6 路由 + CF 命中 + 预算）
// ============================================================
export function RepairKnowledgePanel({ knowledge }: { knowledge: RepairKnowledge }) {
  if (!knowledge) return null
  const rColor = getRLevelColor(knowledge.r_level)
  return (
    <Card variant="outlined" sx={{ mt: 1, borderLeft: `4px solid ${rColor}` }}>
      <CardHeader
        avatar={<SpeedIcon sx={{ color: rColor }} />}
        title={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Typography variant="subtitle2">修复路由</Typography>
            <Chip label={knowledge.r_level} size="small" sx={{ bgcolor: rColor, color: '#fff' /* sg-color-fixed：风险等级数据色固定深底，配白字保证双主题可读 */, height: 20 }} />
            {knowledge.edit_budget?.triggered && (
              <Chip label="止损触发→R4" size="small" color="error" sx={{ height: 20 }} />
            )}
          </Box>
        }
        subheader={knowledge.dual_perspective}
        sx={{ py: 1 }}
      />
      {knowledge.cf_hits.length > 0 && (
        <CardContent sx={{ pt: 0 }}>
          {knowledge.cf_hits.map((h, i) => (
            <Box key={i} sx={{ mb: 1 }}>
              <Chip label={h.cf_id} size="small" color="error" sx={{ height: 20, mr: 0.5 }} />
              <Typography variant="body2" component="span">{h.title}</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', ml: 3 }}>
                {h.repair_model.slice(0, 120)}…
              </Typography>
            </Box>
          ))}
        </CardContent>
      )}
    </Card>
  )
}

// ============================================================
// 合成双通道面板
// ============================================================
export function SynthesisChannelsPanel({ channels }: { channels: SynthesisChannels }) {
  if (!channels) return null
  const jy = channels.jianying
  return (
    <Card variant="outlined" sx={{ mt: 1 }}>
      <CardHeader
        title={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Typography variant="subtitle2">合成双通道</Typography>
            <Chip
              label={`FFmpeg ${channels.ffmpeg?.verify?.status || '—'}`}
              size="small"
              color={channels.ffmpeg?.verify?.status === 'pass' ? 'success' : 'default'}
              sx={{ height: 20 }}
            />
            {jy && 'draft_dir' in jy && (
              <Chip label={`剪映 ${jy.shots} 镜`} size="small" color="secondary" sx={{ height: 20 }} />
            )}
          </Box>
        }
        subheader={`基线：${channels.baseline?.vcodec} CRF ${channels.baseline?.crf} ${channels.baseline?.pix_fmt} ${channels.baseline?.movflags}`}
        sx={{ py: 1 }}
      />
    </Card>
  )
}

// ============================================================
// Stage Handoffs 面板（3E 门位）
// ============================================================
export function StageHandoffsPanel({ handoffs }: { handoffs: StageHandoff[] }) {
  if (!handoffs.length) return null
  return (
    <Box sx={{ mt: 1 }}>
      <Typography variant="caption" color="text.secondary">Stage Handoffs（3E 门位）</Typography>
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
        {handoffs.map((h, i) => (
          <Tooltip key={i} title={h.missing.length ? `缺：${h.missing.join(', ')}` : '通过'}>
            <Chip
              label={`${h.stage} ${h.status === 'pass' ? '✓' : '✗'}`}
              size="small"
              color={h.status === 'pass' ? 'success' : 'error'}
              variant="outlined"
              sx={{ height: 20 }}
            />
          </Tooltip>
        ))}
      </Box>
    </Box>
  )
}

// ============================================================
// Story Graph 面板
// ============================================================
export function StoryGraphPanel({ graph }: { graph: StoryGraph }) {
  const [expanded, setExpanded] = React.useState(false)
  if (!graph || !graph.characters?.length) return null
  return (
    <Card variant="outlined" sx={{ mt: 1 }}>
      <CardHeader
        title={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Typography variant="subtitle2">Story Graph</Typography>
            <Chip label={`${graph.characters.length} 角色`} size="small" sx={{ height: 20 }} />
            <Chip label={`${graph.timeline?.length ?? 0} 事件`} size="small" sx={{ height: 20 }} />
          </Box>
        }
        action={
          <IconButton onClick={() => setExpanded(!expanded)} size="small">
            <ExpandMoreIcon sx={{ transform: expanded ? 'rotate(180deg)' : 'none', transition: '0.2s' }} />
          </IconButton>
        }
        sx={{ py: 1 }}
      />
      <Collapse in={expanded} timeout="auto">
        <CardContent sx={{ pt: 0 }}>
          <Typography variant="caption" color="text.secondary">角色-关系</Typography>
          {graph.characters.map(c => (
            <Box key={c.name} sx={{ ml: 1, mb: 0.5 }}>
              <Typography variant="body2">
                <strong>{c.name}</strong>
                <Chip label={c.importance} size="small" sx={{ height: 16, ml: 0.5, fontSize: '0.6rem' }} />
                <span style={{ color: 'text.secondary' }}> {c.description}</span>
              </Typography>
              {c.relationships?.map((r, i) => (
                <Typography key={i} variant="caption" color="text.secondary" sx={{ display: 'block', ml: 2 }}>
                  → {r.with}：{r.relation}
                </Typography>
              ))}
            </Box>
          ))}
          {graph.timeline?.length > 0 && (
            <Box sx={{ mt: 1 }}>
              <Typography variant="caption" color="text.secondary">时间线</Typography>
              {graph.timeline.slice(0, 10).map((t, i) => (
                <Typography key={i} variant="caption" sx={{ display: 'block' }}>
                  {t.order}. {t.event}
                </Typography>
              ))}
            </Box>
          )}
        </CardContent>
      </Collapse>
    </Card>
  )
}

// ============================================================
// Script Document 面板（beat 结构化视图）
// ============================================================
export function ScriptDocumentPanel({ doc }: { doc: ScriptDocument }) {
  if (!doc?.scenes?.length) return null
  return (
    <Card variant="outlined" sx={{ mt: 1 }}>
      <CardHeader
        title={
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <Typography variant="subtitle2">结构化剧本</Typography>
            <Chip label={`${doc.scenes.length} 场`} size="small" sx={{ height: 20 }} />
            <Chip
              label={`${doc.scenes.reduce((s, sc) => s + sc.beats.length, 0)} beat`}
              size="small" sx={{ height: 20 }}
            />
          </Box>
        }
        subheader={doc.logline || doc.synopsis?.slice(0, 80)}
        sx={{ py: 1 }}
      />
      <CardContent sx={{ pt: 0 }}>
        {doc.hooks?.opening_hook && (
          <Alert severity="info" sx={{ mb: 1, py: 0.5 }}>开场钩子：{doc.hooks.opening_hook}</Alert>
        )}
        {doc.scenes.map(scene => (
          <Box key={scene.scene_id} sx={{ mb: 2 }}>
            <Typography variant="body2" fontWeight={600}>
              {scene.scene_id} · {scene.location} · {scene.time_of_day}
            </Typography>
            {scene.beats.map(beat => (
              <Box key={beat.beat_id} sx={{ ml: 2, py: 0.25 }}>
                <Typography variant="body2" fontSize="0.8rem">
                  <Chip
                    label={beat.family || '未分类'}
                    size="small"
                    sx={{ height: 16, fontSize: '0.6rem', mr: 0.5 }}
                    color={beat.hook ? 'primary' : 'default'}
                    variant={beat.hook ? 'filled' : 'outlined'}
                  />
                  {beat.description}
                  {beat.duration_hint_s > 0 && (
                    <span style={{ color: 'text.secondary', marginLeft: 4 }}>({beat.duration_hint_s}s)</span>
                  )}
                </Typography>
                {beat.dialogue?.map((d, i) => (
                  <Typography key={i} variant="caption" sx={{ display: 'block', ml: 2, fontStyle: 'italic' }}>
                    {d.speaker}：{d.line}
                  </Typography>
                ))}
              </Box>
            ))}
          </Box>
        ))}
      </CardContent>
    </Card>
  )
}
