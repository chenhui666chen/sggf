import { describe, expect, it } from 'vitest'

import {
  chooseWorkflowGenerationModel,
  readStoredWorkflowGenerationModel,
  writeStoredWorkflowGenerationModel,
} from '../workflowGenerationModelPreference'

function createMemoryStorage(): Storage {
  const values = new Map<string, string>()

  return {
    get length() {
      return values.size
    },
    clear() {
      values.clear()
    },
    getItem(key) {
      return values.get(key) ?? null
    },
    key(index) {
      return Array.from(values.keys())[index] ?? null
    },
    removeItem(key) {
      values.delete(key)
    },
    setItem(key, value) {
      values.set(key, String(value))
    },
  }
}

describe('workflowGenerationModelPreference', () => {
  it('prefers a stored valid model over the API default model', () => {
    expect(
      chooseWorkflowGenerationModel({
        models: [{ id: 'qwen3.7-plus' }, { id: 'deepseek-v4-pro' }],
        currentModel: 'qwen3.7-plus',
        storedModel: 'deepseek-v4-pro',
        defaultModel: 'qwen3.7-plus',
      }),
    ).toBe('deepseek-v4-pro')
  })

  it('falls back when the stored model is no longer available', () => {
    expect(
      chooseWorkflowGenerationModel({
        models: [{ id: 'qwen3.7-plus' }, { id: 'mimo-v2.5' }],
        currentModel: 'qwen3.7-plus',
        storedModel: 'removed-model',
        defaultModel: 'mimo-v2.5',
      }),
    ).toBe('qwen3.7-plus')
  })

  it('persists and reads the selected workflow generation model', () => {
    const storage = createMemoryStorage()

    writeStoredWorkflowGenerationModel('deepseek-v4-pro', storage)

    expect(readStoredWorkflowGenerationModel(storage)).toBe('deepseek-v4-pro')
  })
})
