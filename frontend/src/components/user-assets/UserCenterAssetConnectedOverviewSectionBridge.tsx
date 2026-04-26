import type { ReactElement } from 'react'

import type { UserCenterAssetConnectedOverviewSectionProps } from './userCenterAssetConnectedOverviewPresentation'
import UserCenterAssetConnectedOverviewSection from './UserCenterAssetConnectedOverviewSection'

export type UserCenterAssetConnectedOverviewSectionSlotBridge = {
  sectionProps: UserCenterAssetConnectedOverviewSectionProps
}

type UserCenterAssetConnectedOverviewSectionBridgeProps = {
  bridge: UserCenterAssetConnectedOverviewSectionSlotBridge
}

export function buildUserCenterAssetConnectedOverviewSectionSlot(
  bridge: UserCenterAssetConnectedOverviewSectionSlotBridge,
): ReactElement {
  return <UserCenterAssetConnectedOverviewSectionBridge bridge={bridge} />
}

export default function UserCenterAssetConnectedOverviewSectionBridge(
  props: UserCenterAssetConnectedOverviewSectionBridgeProps,
) {
  return <UserCenterAssetConnectedOverviewSection {...props.bridge.sectionProps} />
}
