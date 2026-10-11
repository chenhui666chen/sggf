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
        models: [{ id: 'qwen-plus' }, { id: 'deepseek-pro' }],
        currentModel: 'qwen-plus',
        storedModel: 'deepseek-pro',
        defaultModel: 'qwen-plus',
      }),
    ).toBe('deepseek-pro')
  })

  it('falls back when the stored model is no longer available', () => {
    expect(
      chooseWorkflowGenerationModel({
        models: [{ id: 'qwen-plus' }, { id: 'mimo-flash' }],
        currentModel: 'qwen-plus',
        storedModel: 'removed-model',
        defaultModel: 'mimo-flash',
      }),
    ).toBe('qwen-plus')
  })

  it('persists and reads the selected workflow generation model', () => {
    const storage = createMemoryStorage()

    writeStoredWorkflowGenerationModel('deepseek-pro', storage)

    expect(readStoredWorkflowGenerationModel(storage)).toBe('deepseek-pro')
  })
})
