export type CharacterView = 'front' | 'bust_front' | 'side' | 'bust_three_quarter' | 'bust_side' | 'back'
export type CharacterViewValue = CharacterView | 'default'
export type LibraryEntityType = 'character' | 'scene' | 'prop' | 'unknown'

export interface ParsedLibraryRole {
  entityType: LibraryEntityType
  entityId: number | null
  view?: CharacterView
}

export interface CharacterViewChainPlan {
  forceImageEdit: boolean
  baseRole: string | null
  referenceRoles: string[]
}

export const CHARACTER_VIEW_BY_PREFIX: Record<string, CharacterViewValue> = {
  lib_character_portrait: 'front',
  lib_character_portrait_bust: 'bust_front',
  lib_character_portrait_side: 'side',
  lib_character_portrait_bust_three_quarter: 'bust_three_quarter',
  lib_character_portrait_bust_side: 'bust_side',
  lib_character_portrait_back: 'back',
}

export const CHARACTER_PREFIX_BY_VIEW: Record<CharacterView, string> = {
  front: 'lib_character_portrait',
  bust_front: 'lib_character_portrait_bust',
  side: 'lib_character_portrait_side',
  bust_three_quarter: 'lib_character_portrait_bust_three_quarter',
  bust_side: 'lib_character_portrait_bust_side',
  back: 'lib_character_portrait_back',
}

export const CHARACTER_VIEW_LABEL: Record<CharacterView, string> = {
  front: '正面图',
  bust_front: '半身正面图',
  side: '侧面图',
  bust_three_quarter: '半身3/4图',
  bust_side: '半身侧面图',
  back: '背面图',
}

export const CHARACTER_VIEW_LABEL_SHORT: Record<CharacterView, string> = {
  front: '正面',
  bust_front: '半身正面',
  side: '侧面',
  bust_three_quarter: '半身3/4',
  bust_side: '半身侧面',
  back: '背面',
}

export const CHARACTER_VIEW_RANK: Record<CharacterView, number> = {
  front: 0,
  bust_front: 1,
  side: 2,
  bust_three_quarter: 3,
  bust_side: 4,
  back: 5,
}

export const CHARACTER_VIEW_ORDER: ReadonlyArray<CharacterView> = [
  'front',
  'bust_front',
  'side',
  'bust_three_quarter',
  'bust_side',
  'back',
]

export function isCharacterLibraryRole(role: string): boolean {
  const text = String(role || '').trim()
  return text.startsWith('lib_character_portrait')
}

export function parseLibraryRoleEntityId(role: string): number | null {
  const text = String(role || '').trim()
  if (!text.includes(':')) return null
  const parts = text.split(':', 2)
  if (parts.length < 2) return null
  const entityId = Number(parts[1])
  if (!Number.isInteger(entityId) || entityId <= 0) return null
  return entityId
}

export function resolveCharacterViewFromRole(role: string): CharacterViewValue {
  const prefix = String(role || '').trim().split(':', 1)[0]
  const view = CHARACTER_VIEW_BY_PREFIX[prefix]
  if (view) return view
  if (prefix.startsWith('lib_character_portrait')) return 'front'
  return 'default'
}

export function parseLibraryRole(role: string): ParsedLibraryRole {
  const text = String(role || '').trim()
  if (!text) return { entityType: 'unknown', entityId: null }

  const [prefix, rawId] = text.split(':', 2)
  const entityId = Number.parseInt(String(rawId || '').trim(), 10)
  if (!Number.isFinite(entityId) || entityId <= 0) {
    return { entityType: 'unknown', entityId: null }
  }

  const view = CHARACTER_VIEW_BY_PREFIX[prefix]
  if (view && view !== 'default') {
    return { entityType: 'character', entityId, view }
  }

  // 兼容遗留角色前缀（仍归类为人物，默认正面）。
  if (prefix.startsWith('lib_character_portrait')) {
    return { entityType: 'character', entityId, view: 'front' }
  }

  if (prefix === 'lib_scene_card') return { entityType: 'scene', entityId }
  if (prefix === 'lib_prop_card') return { entityType: 'prop', entityId }
  return { entityType: 'unknown', entityId: null }
}

export function characterViewRole(view: CharacterView, entityId: number): string {
  return `${CHARACTER_PREFIX_BY_VIEW[view]}:${entityId}`
}

export function characterViewLabel(view: CharacterView, style: 'short' | 'long' = 'short'): string {
  return style === 'long' ? CHARACTER_VIEW_LABEL[view] : CHARACTER_VIEW_LABEL_SHORT[view]
}

export function resolveCharacterViewChainPlan(role: string): CharacterViewChainPlan {
  const parsed = parseLibraryRole(role)
  if (parsed.entityType !== 'character' || !parsed.view || parsed.view === 'front' || !parsed.entityId) {
    return { forceImageEdit: false, baseRole: null, referenceRoles: [] }
  }

  const roleFor = (view: CharacterView) => characterViewRole(view, parsed.entityId as number)
  const frontRole = roleFor('front')
  const bustFrontRole = roleFor('bust_front')
  const sideRole = roleFor('side')
  const bustThreeQuarterRole = roleFor('bust_three_quarter')

  const planByView: Record<Exclude<CharacterView, 'front'>, CharacterViewChainPlan> = {
    bust_front: {
      forceImageEdit: true,
      baseRole: frontRole,
      referenceRoles: [frontRole],
    },
    side: {
      forceImageEdit: true,
      baseRole: frontRole,
      referenceRoles: [frontRole, bustFrontRole],
    },
    bust_three_quarter: {
      forceImageEdit: true,
      baseRole: bustFrontRole,
      referenceRoles: [bustFrontRole, frontRole, sideRole],
    },
    bust_side: {
      forceImageEdit: true,
      baseRole: bustThreeQuarterRole,
      referenceRoles: [bustThreeQuarterRole, sideRole, bustFrontRole],
    },
    back: {
      forceImageEdit: true,
      baseRole: sideRole,
      referenceRoles: [sideRole, frontRole, bustFrontRole],
    },
  }

  const picked = planByView[parsed.view]
  const dedupedRefs = Array.from(new Set((picked.referenceRoles || []).map((item) => String(item || '').trim()).filter(Boolean)))
  return {
    forceImageEdit: true,
    baseRole: String(picked.baseRole || '').trim() || null,
    referenceRoles: dedupedRefs,
  }
}

export function formatReferenceRoleLabel(role: string, options?: { short?: boolean }): string {
  const view = resolveCharacterViewFromRole(role)
  if (view === 'default') return role
  return options?.short ? CHARACTER_VIEW_LABEL_SHORT[view] : CHARACTER_VIEW_LABEL[view]
}
