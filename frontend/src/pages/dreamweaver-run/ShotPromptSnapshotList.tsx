import { Button, List, ListItem, ListItemText, Typography } from '@mui/material'
import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
  const [shotPromptExpanded, setShotPromptExpanded] = useState<Record<string, boolean>>({})

  const toggleShotPromptExpanded = useCallback((key: string) => {
    const safeKey = String(key || '').trim()
    if (!safeKey) return
    setShotPromptExpanded((prev) => ({ ...prev, [safeKey]: !prev[safeKey] }))
  }, [])

  return (
    <List dense sx={{ bgcolor: 'background.paper', border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
      {shots.slice(0, maxItems).map((shot, idx) => {
        const shotKey = String(getShotId(shot) || shot.shot_index || idx).trim()
        const expanded = Boolean(shotPromptExpanded[shotKey])
        const headPrompt = getShotFramePrompt(shot.head_frame)
        const tailPrompt = getShotFramePrompt(shot.tail_frame)
        const overridePrompt = getShotVideoPromptOverride(shot)
        const hasPrompt = Boolean(headPrompt || tailPrompt || overridePrompt)
        const promptLines: string[] = []
        const formatPrompt = (value: string) => (expanded || value.length <= 120 ? value : `${value.slice(0, 120)}...`)
        if (headPrompt) promptLines.push(t('dreamweaverRun.pendingHeadFrame', { text: formatPrompt(headPrompt) }))
        if (tailPrompt) promptLines.push(t('dreamweaverRun.pendingTailFrame', { text: formatPrompt(tailPrompt) }))
        if (overridePrompt) promptLines.push(t('dreamweaverRun.pendingVideoOverride', { text: formatPrompt(overridePrompt) }))
        const promptText = hasPrompt ? promptLines.join('\n') : t('dreamweaverRun.pendingNoPromptSnapshot')
        const durationText = typeof shot.duration_s === 'number' ? shot.duration_s.toFixed(1) : '-'
        return (
          <ListItem key={shotKey || String(idx)} disablePadding sx={{ px: 1, py: 0.25 }}>
            <ListItemText
              primary={`#${shot.shot_index ?? idx + 1} ${getShotDesc(shot)}`.trim()}
              secondary={
                <>
                  <Typography variant="caption" color="text.secondary" display="block">
                    {t('dreamweaverRun.spSceneDuration', { scene: shot.scene_id != null ? String(shot.scene_id) : '-', duration: durationText })}
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
                    {expanded ? t('dreamweaverRun.spCollapsePrompts') : t('dreamweaverRun.spExpandPrompts')}
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
