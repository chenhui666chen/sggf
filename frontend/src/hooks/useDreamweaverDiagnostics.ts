import { useMemo } from 'react'

import type {
  DreamweaverRunPreflight,
  DreamweaverRunSnapshot,
  DreamweaverSmartDispatchTrace,
  DreamweaverVideoProviderShotTrace,
  DreamweaverVideoProviderTrace,
  RunResult,
} from '@/types/dreamweaver'
import {
  buildResultFromRunSnapshot,
  indexDreamweaverProviderTraceByShotId,
  mergeRunResult,
  resolveDreamweaverDiagnosticPreflight,
  resolveDreamweaverDiagnosticProviderTrace,
  resolveDreamweaverDiagnosticSmartDispatchTrace,
  summarizeDreamweaverProviderTrace,
  summarizeDreamweaverSmartDispatchTrace,
  type DreamweaverProviderTraceSummary,
  type DreamweaverSmartDispatchTraceSummary,
} from '@/utils/dreamweaver'

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

export interface UseDreamweaverDiagnosticsParams {
  persistedRunId: string | null
  result: RunResult | null
  runSnapshot: DreamweaverRunSnapshot | null
  runPreflight: DreamweaverRunPreflight | null
}

export interface UseDreamweaverDiagnosticsReturn {
  snapshotContract: Record<string, unknown> | null
  snapshotRuntimeConfig: Record<string, unknown>
  diagnosticResult: RunResult | null
  diagnosticPreflight: DreamweaverRunPreflight | null
  diagnosticProviderTrace: DreamweaverVideoProviderTrace | null
  diagnosticSmartDispatchTrace: DreamweaverSmartDispatchTrace | null
  diagnosticProviderTraceByShotId: Map<string, DreamweaverVideoProviderShotTrace>
  diagnosticProviderTraceSummary: DreamweaverProviderTraceSummary | null
  diagnosticSmartDispatchTraceSummary: DreamweaverSmartDispatchTraceSummary | null
}

export function useDreamweaverDiagnostics({
  persistedRunId,
  result,
  runSnapshot,
  runPreflight,
}: UseDreamweaverDiagnosticsParams): UseDreamweaverDiagnosticsReturn {
  const snapshotContract = useMemo(() => {
    return asRecord(runSnapshot?.contract)
  }, [runSnapshot])

  const snapshotRuntimeConfig = useMemo(() => {
    return asRecord(snapshotContract?.runtime_config) || {}
  }, [snapshotContract])

  const diagnosticResult = useMemo(() => {
    const fallback =
      persistedRunId || (typeof runSnapshot?.run_id === 'string' ? String(runSnapshot.run_id || '').trim() : '')
    const snapshotResult = runSnapshot ? buildResultFromRunSnapshot(runSnapshot, fallback || 'unknown') : null
    return mergeRunResult(result, snapshotResult)
  }, [persistedRunId, result, runSnapshot])

  const diagnosticPreflight = useMemo(() => {
    return resolveDreamweaverDiagnosticPreflight(diagnosticResult, snapshotRuntimeConfig, runPreflight)
  }, [diagnosticResult, runPreflight, snapshotRuntimeConfig])

  const diagnosticProviderTrace = useMemo(() => {
    return resolveDreamweaverDiagnosticProviderTrace(diagnosticResult, snapshotRuntimeConfig)
  }, [diagnosticResult, snapshotRuntimeConfig])

  const diagnosticSmartDispatchTrace = useMemo(() => {
    return resolveDreamweaverDiagnosticSmartDispatchTrace(diagnosticResult, snapshotRuntimeConfig)
  }, [diagnosticResult, snapshotRuntimeConfig])

  const diagnosticProviderTraceByShotId = useMemo(() => {
    return indexDreamweaverProviderTraceByShotId(diagnosticProviderTrace)
  }, [diagnosticProviderTrace])

  const diagnosticProviderTraceSummary = useMemo(() => {
    return summarizeDreamweaverProviderTrace(diagnosticProviderTrace)
  }, [diagnosticProviderTrace])

  const diagnosticSmartDispatchTraceSummary = useMemo(() => {
    return summarizeDreamweaverSmartDispatchTrace(diagnosticSmartDispatchTrace)
  }, [diagnosticSmartDispatchTrace])

  return {
    snapshotContract,
    snapshotRuntimeConfig,
    diagnosticResult,
    diagnosticPreflight,
    diagnosticProviderTrace,
    diagnosticSmartDispatchTrace,
    diagnosticProviderTraceByShotId,
    diagnosticProviderTraceSummary,
    diagnosticSmartDispatchTraceSummary,
  }
}
