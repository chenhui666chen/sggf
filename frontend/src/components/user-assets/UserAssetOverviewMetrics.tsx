import {
  Card,
  CardContent,
  Grid,
  Typography,
} from '@mui/material'

import type { UserAssetOverviewMetricSpec } from './userAssetOverviewPresentation'

type UserAssetOverviewMetricsProps = {
  metrics: UserAssetOverviewMetricSpec[]
}

export default function UserAssetOverviewMetrics(props: UserAssetOverviewMetricsProps) {
  const { metrics } = props

  return (
    <Grid container spacing={2}>
      {metrics.map((metric) => (
        <Grid key={metric.key} item xs={12} md={4}>
          <Card variant="outlined" sx={{ height: '100%', borderRadius: 3, borderColor: 'divider' }}>
            <CardContent>
              <Typography variant="body2" color="text.secondary">
                {metric.title}
              </Typography>
              <Typography variant="h4" sx={{ mt: 1, fontWeight: 700, color: metric.color }}>
                {metric.value}
              </Typography>
              <Typography variant="body2" sx={{ mt: 1, color: 'text.secondary' }}>
                {metric.helper}
              </Typography>
            </CardContent>
          </Card>
        </Grid>
      ))}
    </Grid>
  )
}
