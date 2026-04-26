import type { ReactElement, ReactNode } from 'react'

import {
  Card,
  CardContent,
  Grid,
  Typography,
} from '@mui/material'

import {
  buildUserCenterAssetConnectedOverviewSectionSlot,
  type UserCenterAssetConnectedOverviewSectionSlotBridge,
} from './UserCenterAssetConnectedOverviewSectionBridge'

export type UserCenterAssetConnectedOverviewRowSlotOptions = {
  overviewBridge: UserCenterAssetConnectedOverviewSectionSlotBridge
  companionTitle: string
  companionContent: ReactNode
}

export function buildUserCenterAssetConnectedOverviewRowSlot(
  options: UserCenterAssetConnectedOverviewRowSlotOptions,
): ReactElement {
  return <UserCenterAssetConnectedOverviewRow {...options} />
}

export default function UserCenterAssetConnectedOverviewRow(
  props: UserCenterAssetConnectedOverviewRowSlotOptions,
) {
  const {
    overviewBridge,
    companionTitle,
    companionContent,
  } = props

  return (
    <Grid container spacing={2}>
      {buildUserCenterAssetConnectedOverviewSectionSlot(overviewBridge)}
      <Grid item xs={12} md={6}>
        <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
          <CardContent>
            <Typography variant="h6" sx={{ fontWeight: 700 }}>
              {companionTitle}
            </Typography>
            {companionContent}
          </CardContent>
        </Card>
      </Grid>
    </Grid>
  )
}
