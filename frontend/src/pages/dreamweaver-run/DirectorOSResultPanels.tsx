// AI Director OS 复合结果面板——从 RunResult 直接消费新字段
// 挂载到 createRunPageResultRenderer 的 storyboard 与 audit 阶段视图

import { Box, Typography } from '@mui/material'

import type { RunResult } from '@/types/dreamweaver'
import type {
  Am15Report, ShotContract, StateEngineTrack, StageHandoff,
  SynthesisChannels,
} from '@/types/directorOS'
import {
  Am15ReportPanel,
  ShotContractList,
  StateEnginePanel,
  StageHandoffsPanel,
  SynthesisChannelsPanel,
} from './directorOSPanels'

export function DirectorOSResultPanels({ result }: { result: RunResult | null }) {
  if (!result) return null

  const contracts = (result.shot_contracts || []) as ShotContract[]
  const am15 = result.am15_report as unknown as Am15Report | null
  const cameraStates = (result.camera_states || []) as unknown as StateEngineTrack[]
  const handoffs = (result.stage_handoffs || []) as StageHandoff[]
  const synthesis = result.synthesis_channels as unknown as SynthesisChannels | null

  const hasAny = contracts.length > 0 || am15 || cameraStates.length > 0 || handoffs.length > 0 || synthesis

  if (!hasAny) return null

  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="overline" color="primary">
        AI Director OS
      </Typography>
      {contracts.length > 0 && <ShotContractList contracts={contracts} />}
      {am15 && <Am15ReportPanel report={am15} />}
      {cameraStates.length > 0 && <StateEnginePanel tracks={cameraStates} />}
      {handoffs.length > 0 && <StageHandoffsPanel handoffs={handoffs} />}
      {synthesis && <SynthesisChannelsPanel channels={synthesis} />}
    </Box>
  )
}
