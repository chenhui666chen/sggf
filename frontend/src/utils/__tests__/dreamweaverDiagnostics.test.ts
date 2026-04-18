import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  buildLibraryPlanItemsFromPayload,
  buildResultFromRunSnapshot,
  clearPersistedDreamWeaverRun,
  dreamweaverRunStorageKey,
  indexDreamweaverProviderTraceByShotId,
  mergeRunResult,
  readPersistedDreamWeaverRun,
  resolveDreamweaverDiagnosticPreflight,
  resolveDreamweaverDiagnosticProviderTrace,
  summarizeDreamweaverProviderTrace,
  writePersistedDreamWeaverRun,
} from '../dreamweaver'

describe('dreamweaver diagnostics utils', () => {
  beforeEach(() => {
    const storage = new Map<string, string>()
    Object.defineProperty(globalThis, 'localStorage', {
      value: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value)
        },
        removeItem: (key: string) => {
          storage.delete(key)
        },
        clear: () => {
          storage.clear()
        },
      },
      configurable: true,
    })
  })

  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'localStorage')
  })
  it('从 snapshot runtime_config 提取 preflight 和 provider trace', () => {
    const result = buildResultFromRunSnapshot(
      {
        run_id: 'run-1',
        state: 'DONE',
        contract: {
          runtime_config: {
            chapter_ids: [101, 102],
            preflight: {
              allowed: true,
              errors: [],
              warnings: [{ level: 'warning', code: 'route_hint', message: '建议切 Kling Omni' }],
            },
            video_provider_trace: {
              provider_mode: 'auto',
              selector_mode: 'smart',
              shots: [
                {
                  shot_id: 'shot-1',
                  recommended_provider: 'kling',
                  applied_provider: 'wan',
                  shadowed: true,
                },
              ],
            },
          },
          episodes: [],
        },
      },
      'fallback-run',
    )

    expect(result).toMatchObject({
      run_id: 'run-1',
      source_chapter_count: 2,
      preflight: {
        allowed: true,
      },
      video_provider_trace: {
        provider_mode: 'auto',
        selector_mode: 'smart',
      },
    })
    expect(result?.video_provider_trace?.shots).toHaveLength(1)
  })

  it('buildResultFromRunSnapshot 会保留审核与质检快照', () => {
    const result = buildResultFromRunSnapshot(
      {
        run_id: 'run-audit',
        state: 'DONE',
        contract: {
          runtime_config: {
            chapter_ids: [1],
            audit: {
              safety_audit: {
                blocked: true,
                manual_override: true,
              },
            },
            qc_warning: {
              policy: 'warn_only',
            },
          },
          episodes: [],
        },
      },
      'fallback-run',
    )

    expect(result).toMatchObject({
      audit: {
        safety_audit: {
          blocked: true,
          manual_override: true,
        },
      },
      qc_warning: {
        policy: 'warn_only',
      },
    })
  })

  it('mergeRunResult 保留并合并诊断字段', () => {
    const prev = {
      run_id: 'run-1',
      state: 'RUNNING',
      source_chapter_count: 1,
      plan: { text: 'prev-plan' },
      preflight: {
        allowed: false,
        errors: [{ level: 'error', code: 'blocked', message: '阻断' }],
        warnings: [],
      },
      video_provider_trace: {
        provider_mode: 'wan',
        shots: [{ shot_id: 'shot-1', applied_provider: 'wan' }],
      },
    }
    const next = {
      run_id: 'run-1',
      state: 'DONE',
      source_chapter_count: 1,
      storyboard: [{ shot_id: 'shot-1' }],
      preflight: {
        allowed: true,
        errors: [],
        warnings: [{ level: 'warning', code: 'hint', message: '提示' }],
      },
      video_provider_trace: {
        provider_mode: 'auto',
        shots: [{ shot_id: 'shot-1', applied_provider: 'kling' }],
      },
    }

    expect(mergeRunResult(prev, next)).toMatchObject({
      state: 'DONE',
      plan: { text: 'prev-plan' },
      storyboard: [{ shot_id: 'shot-1' }],
      preflight: {
        allowed: true,
      },
      video_provider_trace: {
        provider_mode: 'auto',
      },
    })
  })

  it('resolveDreamweaverDiagnosticPreflight 按 result > snapshot > runPreflight 取值', () => {
    const runPreflight = {
      allowed: true,
      errors: [],
      warnings: [{ level: 'warning', code: 'run', message: 'run preflight' }],
    }
    const snapshotRuntimeConfig = {
      preflight: {
        allowed: true,
        errors: [],
        warnings: [{ level: 'warning', code: 'snapshot', message: 'snapshot preflight' }],
      },
    }
    const result = {
      preflight: {
        allowed: false,
        errors: [{ level: 'error', code: 'result', message: 'result preflight' }],
        warnings: [],
      },
    }

    expect(resolveDreamweaverDiagnosticPreflight(result, snapshotRuntimeConfig, runPreflight)).toMatchObject({
      allowed: false,
      errors: [{ code: 'result' }],
    })
    expect(resolveDreamweaverDiagnosticPreflight(null, snapshotRuntimeConfig, runPreflight)).toMatchObject({
      warnings: [{ code: 'snapshot' }],
    })
    expect(resolveDreamweaverDiagnosticPreflight(null, null, runPreflight)).toMatchObject({
      warnings: [{ code: 'run' }],
    })
  })

  it('resolveDreamweaverDiagnosticProviderTrace 按 result > snapshot 取值', () => {
    const snapshotRuntimeConfig = {
      video_provider_trace: {
        provider_mode: 'auto',
        shots: [{ shot_id: 'shot-snapshot', applied_provider: 'wan' }],
      },
    }
    const result = {
      video_provider_trace: {
        provider_mode: 'kling',
        shots: [{ shot_id: 'shot-result', applied_provider: 'kling' }],
      },
    }

    expect(resolveDreamweaverDiagnosticProviderTrace(result, snapshotRuntimeConfig)).toMatchObject({
      provider_mode: 'kling',
      shots: [{ shot_id: 'shot-result' }],
    })
    expect(resolveDreamweaverDiagnosticProviderTrace(null, snapshotRuntimeConfig)).toMatchObject({
      provider_mode: 'auto',
      shots: [{ shot_id: 'shot-snapshot' }],
    })
  })

  it('indexDreamweaverProviderTraceByShotId 仅索引有效 shot_id', () => {
    const trace = {
      shots: [
        { shot_id: 'shot-1', applied_provider: 'wan' },
        { shot_id: ' ', applied_provider: 'kling' },
        { shot_id: 'shot-2', applied_provider: 'kling' },
      ],
    }

    const indexed = indexDreamweaverProviderTraceByShotId(trace)
    expect(Array.from(indexed.keys())).toEqual(['shot-1', 'shot-2'])
    expect(indexed.get('shot-2')).toMatchObject({ applied_provider: 'kling' })
  })

  it('summarizeDreamweaverProviderTrace 汇总 Kling 推荐、应用和 shadowed 计数', () => {
    const trace = {
      shots: [
        { shot_id: 'shot-1', recommended_provider: 'kling', applied_provider: 'wan', shadowed: true },
        { shot_id: 'shot-2', recommended_provider: 'wan', applied_provider: 'kling', shadowed: false },
        { shot_id: 'shot-3', recommended_provider: 'KLING', applied_provider: 'KLING', shadowed: true },
      ],
    }

    expect(summarizeDreamweaverProviderTrace(trace)).toEqual({
      totalShots: 3,
      recommendedKling: 2,
      appliedKling: 2,
      shadowed: 2,
    })
  })

  it('buildLibraryPlanItemsFromPayload 兼容当前角色视图前缀格式', () => {
    const items = buildLibraryPlanItemsFromPayload({
      project_id: 1,
      spec: {
        characters: [{ entity_id: 12, name: '林岚' }],
      },
      review: {
        required_roles: ['lib_character_portrait_bust:12'],
      },
      assets: [
        {
          id: 9,
          role: 'lib_character_portrait_bust:12',
          uri: 'https://example.com/asset.png',
          meta: { approved: true },
        },
      ],
    })

    expect(items).toHaveLength(1)
    expect(items[0]).toMatchObject({
      role: 'lib_character_portrait_bust:12',
      entity_type: 'character',
      entity_id: 12,
      entity_name: '林岚',
      status: 'done',
      asset_id: 9,
      approved: true,
    })
    expect(items[0].label).toContain('林岚')
  })
  it('readPersistedDreamWeaverRun 鍏煎鏃ц繍琛屽瓨鍌ㄥ墠缂€', () => {
    globalThis.localStorage.setItem(
      'dreamweaver_run_7',
      JSON.stringify({
        project_id: 7,
        run_id: 'legacy-run',
        task_id: 'task-1',
        updated_at: Date.now(),
      }),
    )

    expect(readPersistedDreamWeaverRun(7)).toMatchObject({
      run_id: 'legacy-run',
      task_id: 'task-1',
    })
  })

  it('writePersistedDreamWeaverRun 鍐欏叆鏂板墠缂€骞舵竻鐞嗘棫鍓嶇紑', () => {
    globalThis.localStorage.setItem(
      'dreamweaver_run_9',
      JSON.stringify({
        project_id: 9,
        run_id: 'legacy-run',
        updated_at: Date.now(),
      }),
    )

    writePersistedDreamWeaverRun(9, {
      run_id: 'current-run',
      task_id: 'task-9',
      status: 'running',
      enable_safety_audit: true,
      safety_fail_policy: 'block',
    })

    expect(globalThis.localStorage.getItem('dreamweaver_run_9')).toBeNull()
    expect(readPersistedDreamWeaverRun(9)).toMatchObject({
      run_id: 'current-run',
      task_id: 'task-9',
      status: 'running',
      enable_safety_audit: true,
      safety_fail_policy: 'block',
    })
    expect(globalThis.localStorage.getItem(dreamweaverRunStorageKey(9))).toContain('current-run')
  })

  it('clearPersistedDreamWeaverRun 鍚屾椂娓呯悊鏂版棫鍓嶇紑', () => {
    globalThis.localStorage.setItem(
      dreamweaverRunStorageKey(11),
      JSON.stringify({ project_id: 11, run_id: 'run-11', updated_at: Date.now() }),
    )
    globalThis.localStorage.setItem(
      'dreamweaver_run_11',
      JSON.stringify({ project_id: 11, run_id: 'legacy-11', updated_at: Date.now() }),
    )

    clearPersistedDreamWeaverRun(11)

    expect(globalThis.localStorage.getItem(dreamweaverRunStorageKey(11))).toBeNull()
    expect(globalThis.localStorage.getItem('dreamweaver_run_11')).toBeNull()
  })
})
