export type ThreeViewCharacterView = 'front' | 'side' | 'back'
export type ThreeViewCharacterViewValue = ThreeViewCharacterView | 'default'

export interface ThreeViewCharacterChainPlan {
  forceImageEdit: boolean
  baseRole: string | null
  referenceRoles: string[]
}

const THREE_VIEW_ROLE_PREFIX: Record<ThreeViewCharacterView, string> = {
  front: 'lib_character_portrait',
  side: 'lib_character_portrait_side',
  back: 'lib_character_portrait_back',
}

const THREE_VIEW_BY_PREFIX: Record<string, ThreeViewCharacterViewValue> = {
  lib_character_portrait: 'front',
  lib_character_portrait_side: 'side',
  lib_character_portrait_back: 'back',
}

function parseLibraryRoleEntityId(role: string): number | null {
  const text = String(role || '').trim()
  if (!text.includes(':')) return null
  const parts = text.split(':', 2)
  if (parts.length < 2) return null
  const entityId = Number(parts[1])
  if (!Number.isInteger(entityId) || entityId <= 0) return null
  return entityId
}

function roleFor(view: ThreeViewCharacterView, entityId: number): string {
  return `${THREE_VIEW_ROLE_PREFIX[view]}:${entityId}`
}

export function resolveThreeViewFromRole(role: string): ThreeViewCharacterViewValue {
  const prefix = String(role || '').trim().split(':', 1)[0]
  return THREE_VIEW_BY_PREFIX[prefix] || 'default'
}

export function resolveThreeViewChainPlan(role: string): ThreeViewCharacterChainPlan {
  const view = resolveThreeViewFromRole(role)
  const entityId = parseLibraryRoleEntityId(role)
  if (!entityId || view === 'default' || view === 'front') {
    return { forceImageEdit: false, baseRole: null, referenceRoles: [] }
  }

  const frontRole = roleFor('front', entityId)
  const sideRole = roleFor('side', entityId)
  if (view === 'side') {
    return {
      forceImageEdit: true,
      baseRole: frontRole,
      referenceRoles: [frontRole],
    }
  }

  return {
    forceImageEdit: true,
    baseRole: sideRole,
    referenceRoles: [sideRole, frontRole],
  }
}

export function formatThreeViewReferenceRoleLabel(role: string): string {
  const view = resolveThreeViewFromRole(role)
  if (view === 'front') return '正面图'
  if (view === 'side') return '侧面图'
  if (view === 'back') return '背面图'
  return role
}
