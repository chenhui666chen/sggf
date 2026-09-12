import { useTranslation } from 'react-i18next'
import {
  Divider,
  List,
  ListItem,
  ListItemText,
} from '@mui/material'

interface ScriptReviewSuggestionsProps {
  suggestions: string[]
}

const ScriptReviewSuggestions = ({
  suggestions,
}: ScriptReviewSuggestionsProps) => {
  const { t } = useTranslation()
  if (suggestions.length <= 1) {
    return null
  }

  return (
    <>
      <Divider textAlign="left">{t('audiobook.scriptReviewSuggestions.title')}</Divider>
      <List dense>
        {suggestions.map((suggestion, idx) => (
          <ListItem key={idx} disableGutters>
            <ListItemText primary={t('audiobook.scriptReviewSuggestions.itemLabel', { index: idx + 1 })} secondary={suggestion} />
          </ListItem>
        ))}
      </List>
    </>
  )
}

export default ScriptReviewSuggestions
