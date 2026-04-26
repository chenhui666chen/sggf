import { useEffect, useState, useCallback } from 'react'
import { Alert, AlertTitle, Box, Button, Collapse, IconButton } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import {
  getLocalAssetExternalDirectoryStatus,
  isLocalAssetExternalDirectorySupported,
  requestLocalAssetExternalDirectoryAccess,
  type LocalAssetExternalDirectoryStatus,
} from '@/utils/localAssetExternalDirectory'

type BannerKind = 'unsupported' | 'permission_prompt' | 'permission_denied' | null

const DISMISS_STORAGE_KEY = 'novel-writing-agent:local-asset-health-banner:dismiss'

function readDismissed(kind: BannerKind): boolean {
  if (!kind) return true
  try {
    const raw = window.localStorage.getItem(DISMISS_STORAGE_KEY)
    if (!raw) return false
    const parsed = JSON.parse(raw) as Record<string, number>
    const ts = parsed?.[kind]
    if (typeof ts !== 'number') return false
    return Date.now() - ts < 24 * 60 * 60 * 1000
  } catch {
    return false
  }
}

function markDismissed(kind: BannerKind): void {
  if (!kind) return
  try {
    const raw = window.localStorage.getItem(DISMISS_STORAGE_KEY)
    const parsed = raw ? (JSON.parse(raw) as Record<string, number>) : {}
    parsed[kind] = Date.now()
    window.localStorage.setItem(DISMISS_STORAGE_KEY, JSON.stringify(parsed))
  } catch {
    // 忽略 localStorage 写入失败
  }
}

function resolveBannerKind(status: LocalAssetExternalDirectoryStatus | null): BannerKind {
  if (!status) return null
  if (!status.supported) return 'unsupported'
  if (!status.configured) return null
  if (status.permission === 'denied') return 'permission_denied'
  if (status.permission === 'prompt') return 'permission_prompt'
  return null
}

export default function LocalAssetHealthBanner() {
  const [status, setStatus] = useState<LocalAssetExternalDirectoryStatus | null>(null)
  const [dismissedKind, setDismissedKind] = useState<BannerKind>(null)
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const next = await getLocalAssetExternalDirectoryStatus()
      setStatus(next)
    } catch {
      setStatus(null)
    }
  }, [])

  useEffect(() => {
    void refresh()
    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        void refresh()
      }
    }
    document.addEventListener('visibilitychange', onVisibility)
    const id = window.setInterval(refresh, 60_000)
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      window.clearInterval(id)
    }
  }, [refresh])

  const kind = resolveBannerKind(status)
  const effectivelyHidden = !kind || dismissedKind === kind || readDismissed(kind)

  const handleGrant = useCallback(async () => {
    if (busy) return
    setBusy(true)
    try {
      await requestLocalAssetExternalDirectoryAccess()
    } finally {
      setBusy(false)
      void refresh()
    }
  }, [busy, refresh])

  const handleDismiss = useCallback(() => {
    markDismissed(kind)
    setDismissedKind(kind)
  }, [kind])

  const supported = isLocalAssetExternalDirectorySupported()

  let severity: 'warning' | 'error' | 'info' = 'warning'
  let title = ''
  let description = ''
  let actionLabel: string | null = null

  if (kind === 'unsupported') {
    severity = 'warning'
    title = '当前浏览器不支持外部目录访问'
    description = '本地副本将回退到浏览器内置存储（OPFS / legacy）。建议使用最新版 Chrome / Edge 以获得完整本地优先体验。'
  } else if (kind === 'permission_prompt') {
    severity = 'info'
    title = '需要重新授权外部本地目录'
    description = '你已配置外部目录，但本次会话尚未获得读写授权。授权后本地资产才能写入该目录。'
    actionLabel = '立即授权'
  } else if (kind === 'permission_denied') {
    severity = 'error'
    title = '外部本地目录授权被拒绝'
    description = '本地资产当前无法写入外部目录，将回退到 OPFS 兜底。可重新授权或在"用户中心 → 本地存储"里更换目录。'
    actionLabel = '重新授权'
  }

  return (
    <Collapse in={!effectivelyHidden && supported !== null}>
      {kind ? (
        <Box sx={{ position: 'sticky', top: 0, zIndex: 1300 }}>
          <Alert
            severity={severity}
            variant="filled"
            sx={{ borderRadius: 0 }}
            action={
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                {actionLabel ? (
                  <Button
                    color="inherit"
                    size="small"
                    onClick={handleGrant}
                    disabled={busy}
                  >
                    {busy ? '处理中…' : actionLabel}
                  </Button>
                ) : null}
                <IconButton
                  size="small"
                  color="inherit"
                  onClick={handleDismiss}
                  aria-label="dismiss local asset health banner"
                >
                  <CloseIcon fontSize="small" />
                </IconButton>
              </Box>
            }
          >
            <AlertTitle>{title}</AlertTitle>
            {description}
          </Alert>
        </Box>
      ) : null}
    </Collapse>
  )
}
