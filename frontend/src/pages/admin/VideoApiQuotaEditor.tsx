import { useState } from 'react'
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField } from '@mui/material'
import { apiClient, extractApiErrorMessage, type VideoApiApplication } from '@/services/api'
import { parseVideoApiQuota, type VideoApiQuota } from './videoApiQuota'

const fields: Array<{ key: keyof VideoApiQuota; label: string }> = [
  { key: 'rate_limit_per_second', label: '每秒创建请求' },
  { key: 'burst_capacity', label: '突发容量' },
  { key: 'max_active_jobs', label: '活动任务上限' },
  { key: 'max_parallel_attempts', label: '每个任务并行尝试上限' },
  { key: 'lifetime_task_limit', label: '累计任务额度' },
]

export default function VideoApiQuotaEditor({ item, onSaved }: {
  item: VideoApiApplication
  onSaved: (application: VideoApiApplication) => void
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [values, setValues] = useState<Record<keyof VideoApiQuota, string>>({
    rate_limit_per_second: String(item.rate_limit_per_second),
    burst_capacity: String(item.burst_capacity),
    max_active_jobs: String(item.max_active_jobs),
    max_parallel_attempts: String(item.max_parallel_attempts),
    lifetime_task_limit: String(item.lifetime_task_limit),
  })

  const show = () => {
    setValues({ rate_limit_per_second: String(item.rate_limit_per_second), burst_capacity: String(item.burst_capacity),
      max_active_jobs: String(item.max_active_jobs), max_parallel_attempts: String(item.max_parallel_attempts),
      lifetime_task_limit: String(item.lifetime_task_limit) })
    setError(null)
    setOpen(true)
  }

  const save = async () => {
    setBusy(true)
    try {
      const response = await apiClient.updateAdminVideoApiApplicationQuota(item.id, parseVideoApiQuota(values))
      onSaved(response.data)
      setOpen(false)
    } catch (saveError) {
      setError(await extractApiErrorMessage(saveError, '保存配额失败'))
    } finally {
      setBusy(false)
    }
  }

  return <>
    <Button variant="outlined" size="small" onClick={show} disabled={item.status === 'revoked'}>调整配额</Button>
    <Dialog open={open} onClose={() => { if (!busy) setOpen(false) }} fullWidth maxWidth="sm">
      <DialogTitle>{item.name} · 调整配额</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error ? <Alert severity="error">{error}</Alert> : null}
          <Alert severity="info">累计额度包含成功和失败的任务，幂等重放不重复消耗。降低额度不会取消已提交任务。</Alert>
          {fields.map((field) => <TextField key={field.key} label={field.label} type="number" value={values[field.key]}
            onChange={(event) => setValues((current) => ({ ...current, [field.key]: event.target.value }))} disabled={busy} />)}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setOpen(false)} disabled={busy}>取消</Button>
        <Button variant="contained" onClick={() => void save()} disabled={busy}>{busy ? '保存中' : '保存配额'}</Button>
      </DialogActions>
    </Dialog>
  </>
}
