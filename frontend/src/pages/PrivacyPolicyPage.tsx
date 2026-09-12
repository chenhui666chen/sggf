import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router-dom'
import { Container, Divider, Link, Paper } from '@mui/material'

import PrivacyPolicyContent from '@/components/PrivacyPolicyContent'

// P2-5.5：隐私政策展示页（深链直达入口；正文在 PrivacyPolicyContent 中
// 与同意勾选处的页内弹窗共用，政策文本变更时只需改一处）
export default function PrivacyPolicyPage() {
  const { t } = useTranslation()
  return (
    <Container maxWidth="md" sx={{ py: 5 }}>
      <Paper elevation={2} sx={{ p: { xs: 3, md: 5 } }}>
        <PrivacyPolicyContent />

        <Divider sx={{ my: 3 }} />
        <Link component={RouterLink} to="/register" variant="body2">
          {t('register.backToRegister')}
        </Link>
      </Paper>
    </Container>
  )
}
