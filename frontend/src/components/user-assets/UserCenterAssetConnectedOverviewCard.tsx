import StarsOutlinedIcon from '@mui/icons-material/StarsOutlined'
import {
  Card,
  CardContent,
  Stack,
  Typography,
} from '@mui/material'

import type { UserCenterAssetConnectedOverviewCardProps } from './userCenterAssetConnectedOverviewPresentation'

export default function UserCenterAssetConnectedOverviewCard(
  props: UserCenterAssetConnectedOverviewCardProps,
) {
  const { items } = props

  return (
    <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center">
          <StarsOutlinedIcon color="primary" />
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            已接入概览
          </Typography>
        </Stack>
        <Stack spacing={1.25} sx={{ mt: 2 }}>
          {items.map((item) => (
            <Typography key={item.key} variant="body2" color="text.secondary">
              {item.label}：{item.value}
            </Typography>
          ))}
        </Stack>
      </CardContent>
    </Card>
  )
}
