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
  if (suggestions.length <= 1) {
    return null
  }

  return (
    <>
      <Divider textAlign="left">修订建议</Divider>
      <List dense>
        {suggestions.map((suggestion, idx) => (
          <ListItem key={idx} disableGutters>
            <ListItemText primary={`建议 ${idx + 1}`} secondary={suggestion} />
          </ListItem>
        ))}
      </List>
    </>
  )
}

export default ScriptReviewSuggestions
