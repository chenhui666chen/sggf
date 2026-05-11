import { Button, List, ListItem, ListItemText, Typography } from '@mui/material'
import { useCallback, useState } from 'react'

type ShotSnapshot = {
  shot_index?: number | null
  scene_id?: unknown
  duration_s?: number | null
  head_frame?: unknown
  tail_frame?: unknown
  video_prompt_override?: unknown
}

function getShotId(shot: ShotSnapshot): string {
  return String((shot as Record<string, unknown>).shot_id || '').trim()
}

function getShotDesc(shot: ShotSnapshot): string {
  return String((shot as Record<string, unknown>).desc || '').trim()
}

function getShotFramePrompt(frame: unknown): string {
  if (!frame || typeof frame !== 'object') return ''
  const f = frame as Record<string, unknown>
  return String(f.prompt || f.generated_prompt || '').trim()
}

function getShotVideoPromptOverride(shot: ShotSnapshot): string {
  return String(shot.video_prompt_override || '').trim()
}

export interface ShotPromptSnapshotListProps {
  shots: ShotSnapshot[]
  maxItems?: number
}

export function ShotPromptSnapshotList({ shots, maxItems = 12 }: ShotPromptSnapshotListProps) {
  const [shotPromptExpanded, setShotPromptExpanded] = useState<Record<string, boolean>>({})

  const toggleShotPromptExpanded = useCallback((key: string) => {
    const safeKey = String(key || '').trim()
    if (!safeKey) return
    setShotPromptExpanded((prev) => ({ ...prev, [safeKey]: !prev[safeKey] }))
  }, [])

  return (
    <List dense sx={{ bgcolor: '#fff', border: '1px solid #eee', borderRadius: 2 }}>
      {shots.slice(0, maxItems).map((shot, idx) => {
        const shotKey = String(getShotId(shot) || shot.shot_index || idx).trim()
        const expanded = Boolean(shotPromptExpanded[shotKey])
        const headPrompt = getShotFramePrompt(shot.head_frame)
        const tailPrompt = getShotFramePrompt(shot.tail_frame)
        const overridePrompt = getShotVideoPromptOverride(shot)
        const hasPrompt = Boolean(headPrompt || tailPrompt || overridePrompt)
        const promptLines: string[] = []
        const formatPrompt = (value: string) => (expanded || value.length <= 120 ? value : `${value.slice(0, 120)}...`)
        if (headPrompt) promptLines.push(`首帧: ${formatPrompt(headPrompt)}`)
        if (tailPrompt) promptLines.push(`尾帧: ${formatPrompt(tailPrompt)}`)
        if (overridePrompt) promptLines.push(`视频覆盖: ${formatPrompt(overridePrompt)}`)
        const promptText = hasPrompt ? promptLines.join('\n') : '暂无提示词快照'
        const durationText = typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'
        return (
          <ListItem key={shotKey || String(idx)} disablePadding sx={{ px: 1, py: 0.25 }}>
            <ListItemText
              primary={`#${shot.shot_index ?? idx + 1} ${getShotDesc(shot)}`.trim()}
              secondary={
                <>
                  <Typography variant="caption" color="text.secondary" display="block">
                    场景: {shot.scene_id != null ? String(shot.scene_id) : '-'}  时长: {durationText}s
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ whiteSpace: 'pre-wrap' }}>
                    {promptText}
                  </Typography>
                  <Button
                    size="small"
                    variant="text"
                    onClick={() => toggleShotPromptExpanded(shotKey)}
                    disabled={!hasPrompt}
                    sx={{ px: 0, mt: 0.25 }}
                  >
                    {expanded ? '收起提示词' : '展开提示词'}
                  </Button>
                </>
              }
            />
          </ListItem>
        )
      })}
    </List>
  )
}
