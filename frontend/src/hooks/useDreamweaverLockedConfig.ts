import { useCallback, useRef, useState } from 'react'

import { useTranslation } from 'react-i18next'

import {
  apiClient,
  extractApiErrorMessage,
} from '@/services/api'
import { toDreamweaverProjectLockedGenerationConfig } from '@/pages/dreamweaver-run/runPageHelpers'
import type { DreamweaverProjectLockedGenerationConfig } from '@/types/dreamweaver'

export interface UseDreamweaverLockedConfigReturn {
  lockedGenerationConfig: DreamweaverProjectLockedGenerationConfig | null
  lockedGenerationConfigLoading: boolean
  lockedGenerationConfigError: string | null
  refreshLockedGenerationConfig: (projectId: number) => Promise<void>
  resetLockedConfig: () => void
}

export function useDreamweaverLockedConfig(): UseDreamweaverLockedConfigReturn {
  const { t } = useTranslation()
  const [lockedGenerationConfig, setLockedGenerationConfig] = useState<DreamweaverProjectLockedGenerationConfig | null>(null)
  const [lockedGenerationConfigLoading, setLockedGenerationConfigLoading] = useState(false)
  const [lockedGenerationConfigError, setLockedGenerationConfigError] = useState<string | null>(null)
  const reqIdRef = useRef(0)

  const refreshLockedGenerationConfig = useCallback(async (projectId: number) => {
    const reqId = reqIdRef.current + 1
    reqIdRef.current = reqId
    setLockedGenerationConfigLoading(true)
    setLockedGenerationConfigError(null)
    try {
      const res = await apiClient.getDreamweaverProjectLockedConfig(projectId)
      if (reqIdRef.current !== reqId) return
      setLockedGenerationConfig(toDreamweaverProjectLockedGenerationConfig(res.data))
    } catch (e: unknown) {
      if (reqIdRef.current !== reqId) return
      setLockedGenerationConfig(null)
      setLockedGenerationConfigError(await extractApiErrorMessage(e, t('dreamweaverRun.loadLockedConfigFailed')))
    } finally {
      if (reqIdRef.current !== reqId) return
      setLockedGenerationConfigLoading(false)
    }
  }, [t])

  const resetLockedConfig = useCallback(() => {
    setLockedGenerationConfig(null)
    setLockedGenerationConfigLoading(false)
    setLockedGenerationConfigError(null)
  }, [])

  return {
    lockedGenerationConfig,
    lockedGenerationConfigLoading,
    lockedGenerationConfigError,
    refreshLockedGenerationConfig,
    resetLockedConfig,
  }
}
