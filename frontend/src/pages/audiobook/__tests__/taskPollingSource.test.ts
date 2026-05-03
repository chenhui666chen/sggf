import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(
  new URL('../useAudiobookTaskPolling.ts', import.meta.url),
  'utf8',
)

const extractStreamEffectDependencies = () => {
  const streamEffectAnchor = source.indexOf('void startTaskProgressStream()')
  expect(streamEffectAnchor).toBeGreaterThan(-1)

  const dependencyStart = source.indexOf('  }, [', streamEffectAnchor)
  expect(dependencyStart).toBeGreaterThan(-1)

  const dependencyEnd = source.indexOf('  ])', dependencyStart)
  expect(dependencyEnd).toBeGreaterThan(dependencyStart)

  return source.slice(dependencyStart, dependencyEnd)
}

describe('useAudiobookTaskPolling source guards', () => {
  it('keeps task status updates out of the SSE effect dependencies', () => {
    expect(source).toContain('const taskStatusesRef = useRef(taskStatuses)')
    expect(source).toContain('taskStatusesRef.current = taskStatuses')
    expect(source).toContain('selectNextActiveTaskAfterUpdate(taskStatusesRef.current, normalized)')
    expect(source).toContain('selectNextActiveTask(taskStatusesRef.current, currentTaskId)')

    const dependencies = extractStreamEffectDependencies()
    expect(dependencies).not.toContain('taskStatuses,')
    expect(dependencies).toContain('setTaskStatusesAndRef,')
  })
})
