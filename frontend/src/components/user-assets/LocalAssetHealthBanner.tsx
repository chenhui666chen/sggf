import { useEffect, useState, useCallback } from 'react'
import { Alert, AlertTitle, Box, Button, Collapse, IconButton } from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import { useTranslation } from 'react-i18next'
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
  const { t } = useTranslation()
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
    title = t('userAsset.banner.unsupportedTitle')
    description = t('userAsset.banner.unsupportedDescription')
  } else if (kind === 'permission_prompt') {
    severity = 'info'
    title = t('userAsset.banner.promptTitle')
    description = t('userAsset.banner.promptDescription')
    actionLabel = t('userAsset.banner.grantNow')
  } else if (kind === 'permission_denied') {
    severity = 'error'
    title = t('userAsset.banner.deniedTitle')
    description = t('userAsset.banner.deniedDescription')
    actionLabel = t('userAsset.banner.grantAgain')
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
                    {busy ? t('userAsset.common.processing') : actionLabel}
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
