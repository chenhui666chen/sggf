import { Grid } from '@mui/material'

import UserCenterAssetConnectedOverviewCard from './UserCenterAssetConnectedOverviewCard'
import type { UserCenterAssetConnectedOverviewSectionProps } from './userCenterAssetConnectedOverviewPresentation'

export default function UserCenterAssetConnectedOverviewSection(
  props: UserCenterAssetConnectedOverviewSectionProps,
) {
  return (
    <Grid item xs={12} md={6}>
      <UserCenterAssetConnectedOverviewCard {...props} />
    </Grid>
  )
}
