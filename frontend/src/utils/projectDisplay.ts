export interface ProjectDisplayInfo {
  id?: number | null
  display_no?: number | null
}

function normalizePositiveInt(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const normalized = Math.trunc(value)
  return normalized > 0 ? normalized : null
}

export function resolveProjectDisplayNo(
  project?: ProjectDisplayInfo | null,
  fallbackId?: number | null,
): number | null {
  return normalizePositiveInt(project?.display_no) ?? normalizePositiveInt(fallbackId)
}

export function formatProjectSequenceLabel(
  project?: ProjectDisplayInfo | null,
  fallbackId?: number | null,
): string {
  const value = resolveProjectDisplayNo(project, fallbackId)
  return value ? `项目序号: ${value}` : '项目序号'
}

export function formatProjectCompactLabel(
  project?: ProjectDisplayInfo | null,
  fallbackId?: number | null,
): string {
  const value = resolveProjectDisplayNo(project, fallbackId)
  return value ? `项目 #${value}` : '项目'
}
