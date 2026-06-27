export const WORKFLOW_GENERATION_MODEL_STORAGE_KEY = 'workflowGenerationModel'

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

interface WorkflowModelLike {
  id: string
}

interface ChooseWorkflowGenerationModelOptions {
  models: WorkflowModelLike[]
  currentModel: string
  storedModel: string | null
  defaultModel: string
}

function getBrowserStorage(): StorageLike | null {
  if (typeof localStorage === 'undefined') {
    return null
  }
  return localStorage
}

export function readStoredWorkflowGenerationModel(
  storage: StorageLike | null = getBrowserStorage(),
): string | null {
  try {
    return storage?.getItem(WORKFLOW_GENERATION_MODEL_STORAGE_KEY)?.trim() || null
  } catch {
    return null
  }
}

export function writeStoredWorkflowGenerationModel(
  modelId: string,
  storage: StorageLike | null = getBrowserStorage(),
): void {
  const normalizedModelId = modelId.trim()
  if (!normalizedModelId) return

  try {
    storage?.setItem(WORKFLOW_GENERATION_MODEL_STORAGE_KEY, normalizedModelId)
  } catch {
    // Ignore unavailable or full storage.
  }
}

export function chooseWorkflowGenerationModel({
  models,
  currentModel,
  storedModel,
  defaultModel,
}: ChooseWorkflowGenerationModelOptions): string {
  const modelIds = new Set(models.map((model) => model.id))
  const candidates = [storedModel, currentModel, defaultModel]

  for (const candidate of candidates) {
    const normalizedCandidate = candidate?.trim()
    if (normalizedCandidate && modelIds.has(normalizedCandidate)) {
      return normalizedCandidate
    }
  }

  return models[0]?.id || defaultModel || currentModel
}
