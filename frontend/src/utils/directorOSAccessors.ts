// AI Director OS 工具函数：从 contract_json.runtime_config 提取新功能字段

import type {
  Am15Report,
  CostLedgerSummary,
  ShotContract,
  StageHandoff,
  StateEngineTrack,
  SynthesisChannels,
  ScriptDocument,
  StoryGraph,
  RepairKnowledge,
} from '@/types/directorOS'

type Contract = Record<string, unknown> | null | undefined

function rc(contract: Contract): Record<string, unknown> | null {
  if (!contract || typeof contract !== 'object') return null
  const runtime = (contract as Record<string, Record<string, unknown>>).runtime_config
  return runtime && typeof runtime === 'object' ? runtime : null
}

export function getShotContracts(contract: Contract): ShotContract[] {
  const r = rc(contract)
  const list = r?.shot_contracts
  return Array.isArray(list) ? (list as ShotContract[]) : []
}

export function getAm15Report(contract: Contract): Am15Report | null {
  const r = rc(contract)
  const report = r?.am15_report
  return report && typeof report === 'object' ? (report as Am15Report) : null
}

export function getCameraStates(contract: Contract): StateEngineTrack[] {
  const r = rc(contract)
  const list = r?.camera_states
  return Array.isArray(list) ? (list as StateEngineTrack[]) : []
}

export function getScriptDocument(contract: Contract): ScriptDocument | null {
  const r = rc(contract)
  const doc = r?.script_document
  return doc && typeof doc === 'object' ? (doc as ScriptDocument) : null
}

export function getStoryGraph(contract: Contract): StoryGraph | null {
  const r = rc(contract)
  const graph = r?.story_graph
  return graph && typeof graph === 'object' ? (graph as StoryGraph) : null
}

export function getStageHandoffs(contract: Contract): StageHandoff[] {
  const r = rc(contract)
  const list = r?.stage_handoffs
  return Array.isArray(list) ? (list as StageHandoff[]) : []
}

export function getCostLedger(contract: Contract): { summary: CostLedgerSummary; entries: unknown[] } | null {
  const r = rc(contract)
  const ledger = r?.cost_ledger
  if (!ledger || typeof ledger !== 'object') return null
  return ledger as { summary: CostLedgerSummary; entries: unknown[] }
}

export function getSynthesisChannels(contract: Contract): SynthesisChannels | null {
  const r = rc(contract)
  const ch = r?.synthesis_channels
  return ch && typeof ch === 'object' ? (ch as SynthesisChannels) : null
}

export function getRepairKnowledge(contract: Contract): RepairKnowledge | null {
  const r = rc(contract)
  const autoqc = r?.autoqc
  if (!autoqc || typeof autoqc !== 'object') return null
  const route = (autoqc as Record<string, unknown>).route
  if (!route || typeof route !== 'object') return null
  const patch = (route as Record<string, Record<string, unknown>>).patch
  if (!patch || typeof patch !== 'object') return null
  const rk = patch.repair_knowledge
  return rk && typeof rk === 'object' ? (rk as RepairKnowledge) : null
}

export function getShotSizeColor(size: string): string {
  const map: Record<string, string> = {
    LS: '#1976d2',
    FS: '#2e7d32',
    MS: '#ed6c02',
    CU: '#d32f2f',
    ECU: '#7b1fa2',
  }
  return map[size] || '#757575'
}

export function getRLevelColor(r: string): string {
  const map: Record<string, string> = {
    R0: '#4caf50',
    R1: '#2196f3',
    R2: '#ff9800',
    R3: '#f57c00',
    R4: '#d32f2f',
    R5: '#b71c1c',
    R6: '#7b1fa2',
  }
  return map[r] || '#757575'
}
