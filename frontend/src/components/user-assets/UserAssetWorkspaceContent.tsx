import UserAssetCardsGrid, {
  type UserAssetCardsGridProps,
} from './UserAssetCardsGrid'
import UserAssetWorkspaceSection, {
  type UserAssetWorkspaceSectionProps,
} from './UserAssetWorkspaceSection'

export type UserAssetWorkspaceContentProps = {
  workspaceSectionProps: Omit<UserAssetWorkspaceSectionProps, 'children'>
  cardsGridProps: UserAssetCardsGridProps
}

export default function UserAssetWorkspaceContent(props: UserAssetWorkspaceContentProps) {
  const {
    workspaceSectionProps,
    cardsGridProps,
  } = props

  return (
    <UserAssetWorkspaceSection {...workspaceSectionProps}>
      <UserAssetCardsGrid {...cardsGridProps} />
    </UserAssetWorkspaceSection>
  )
}
