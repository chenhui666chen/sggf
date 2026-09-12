import StarsOutlinedIcon from '@mui/icons-material/StarsOutlined'
import {
  Card,
  CardContent,
  Stack,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

import type { UserCenterAssetConnectedOverviewCardProps } from './userCenterAssetConnectedOverviewPresentation'

export default function UserCenterAssetConnectedOverviewCard(
  props: UserCenterAssetConnectedOverviewCardProps,
) {
  const { t } = useTranslation()
  const { items } = props

  return (
    <Card variant="outlined" sx={{ height: '100%', borderRadius: 3 }}>
      <CardContent>
        <Stack direction="row" spacing={1} alignItems="center">
          <StarsOutlinedIcon color="primary" />
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            {t('userAsset.connected.overviewTitle')}
          </Typography>
        </Stack>
        <Stack spacing={1.25} sx={{ mt: 2 }}>
          {items.map((item) => (
            <Typography key={item.key} variant="body2" color="text.secondary">
              {t('userAsset.connected.itemLine', { label: item.label, value: item.value })}
            </Typography>
          ))}
        </Stack>
      </CardContent>
    </Card>
  )
}
