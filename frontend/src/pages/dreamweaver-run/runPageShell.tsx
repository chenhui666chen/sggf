import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import { Box, Button, Container, Typography } from '@mui/material'

import { DreamweaverWorkbenchSection } from './workbenchStatusPanel'

type DreamweaverRunPageHeroProps = {
  onBack: () => void
  title: string
  description: string
  backLabel?: string
}

export function DreamweaverRunPageHero({
  onBack,
  title,
  description,
  backLabel,
}: DreamweaverRunPageHeroProps) {
  const { t } = useTranslation()
  const resolvedBackLabel = backLabel ?? t('dreamweaverRun.libraryBackToProjects')
  return (
    <>
      <Button
        variant="text"
        startIcon={<ArrowBackIcon />}
        sx={{ color: 'white', mb: 2 }}
        onClick={onBack}
      >
        {resolvedBackLabel}
      </Button>

      <Typography variant="h4" sx={{ color: 'white', fontWeight: 700, mb: 0.5 }}>
        {title}
      </Typography>
      <Typography variant="body1" sx={{ color: 'rgba(255,255,255,0.85)', mb: 3 }}>
        {description}
      </Typography>
    </>
  )
}

type DreamweaverRunPageAlertsProps = {
  errorAlert?: ReactNode
  qcWarningAlert?: ReactNode
  preflightAlert?: ReactNode
}

export function DreamweaverRunPageAlerts({
  errorAlert,
  qcWarningAlert,
  preflightAlert,
}: DreamweaverRunPageAlertsProps) {
  return (
    <>
      {errorAlert ?? null}
      {qcWarningAlert ?? null}
      {preflightAlert ?? null}
    </>
  )
}

type DreamweaverRunPageScaffoldProps = {
  onBack: () => void
  heroTitle: string
  heroDescription: string
  configDialog?: ReactNode
  alerts?: ReactNode
  workbenchCard: ReactNode
}

export function DreamweaverRunPageScaffold({
  onBack,
  heroTitle,
  heroDescription,
  configDialog,
  alerts,
  workbenchCard,
}: DreamweaverRunPageScaffoldProps) {
  return (
    <Box sx={{ minHeight: '100vh', background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', py: 4 }}>
      <Container maxWidth="lg">
        <DreamweaverRunPageHero onBack={onBack} title={heroTitle} description={heroDescription} />
        {configDialog ?? null}
        <DreamweaverWorkbenchSection alerts={alerts} card={workbenchCard} />
      </Container>
    </Box>
  )
}
