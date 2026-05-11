import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const readSource = (relativePath: string) =>
  readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('useAudiobookTaskPolling source guards', () => {
  it('splits orchestration into dedicated polling and SSE hooks', () => {
    const wrapperSource = readSource('../useAudiobookTaskPolling.ts')
    const listPollingSource = readSource('../useAudiobookTaskListPolling.ts')
    const streamPollingSource = readSource('../useAudiobookTaskStreamPolling.ts')

    expect(wrapperSource).toContain('useAudiobookTaskListPolling(')
    expect(wrapperSource).toContain('useAudiobookTaskStreamPolling(')

    expect(listPollingSource).toContain('listAudiobookTasks')
    expect(listPollingSource).toContain('buildTrackedTaskPollResult')
    expect(listPollingSource).toContain('selectActiveProjectTasks')
    expect(listPollingSource).toContain('focusAudiobookTask')
    expect(listPollingSource).not.toContain('getSSEStreamUrl')
    expect(listPollingSource).not.toContain('AbortController')
    expect(listPollingSource).not.toContain('consumeSseEventBuffer')

    expect(streamPollingSource).toContain('getSSEStreamUrl')
    expect(streamPollingSource).toContain('consumeSseEventBuffer')
    expect(streamPollingSource).toContain('setStreamStatus')
    expect(streamPollingSource).toContain('refreshTaskStatusFromStream')
    expect(streamPollingSource).not.toContain('listAudiobookTasks')
  })

  it('keeps task status updates out of the SSE effect dependencies', () => {
    const wrapperSource = readSource('../useAudiobookTaskPolling.ts')
    const streamPollingSource = readSource('../useAudiobookTaskStreamPolling.ts')
    expect(wrapperSource).toContain('const taskStatusesRef = useRef(taskStatuses)')
    expect(wrapperSource).toContain('taskStatusesRef.current = taskStatuses')
    expect(streamPollingSource).toContain('selectNextActiveTaskAfterUpdate(taskStatusesRef.current, normalized)')
    expect(streamPollingSource).toContain('selectNextActiveTask(taskStatusesRef.current, currentTaskId)')

    const dependencyStart = streamPollingSource.indexOf('void startTaskProgressStream()')
    expect(dependencyStart).toBeGreaterThan(-1)
    const dependencies = streamPollingSource.slice(
      streamPollingSource.indexOf('  }, [', dependencyStart),
      streamPollingSource.indexOf('  ])', dependencyStart),
    )
    expect(dependencies).not.toContain('taskStatuses,')
    expect(dependencies).toContain('setTaskStatusesAndRef,')
  })

  it('keeps SSE stream fallback observability wired into the polling hook', () => {
    const streamPollingSource = readSource('../useAudiobookTaskStreamPolling.ts')
    expect(streamPollingSource).toContain('TaskProgressStreamConnectionStatus')
    expect(streamPollingSource).toContain("console.debug('[audiobook-task-stream]'")
    expect(streamPollingSource).toContain("setStreamStatus('connecting'")
    expect(streamPollingSource).toContain("setStreamStatus('connected'")
    expect(streamPollingSource).toContain("setStreamStatus('fallback'")
    expect(streamPollingSource).toContain("setStreamStatus('closed'")

    const dependencyStart = streamPollingSource.indexOf('void startTaskProgressStream()')
    const dependencies = streamPollingSource.slice(
      streamPollingSource.indexOf('  }, [', dependencyStart),
      streamPollingSource.indexOf('  ])', dependencyStart),
    )
    expect(dependencies).toContain('setStreamStatus,')
  })

  it('keeps terminal task handling shared across polling and SSE updates', () => {
    const streamPollingSource = readSource('../useAudiobookTaskStreamPolling.ts')
    expect(streamPollingSource).toContain('let terminalHandled = false')
    expect(streamPollingSource).toContain('if (terminalHandled)')
    expect(streamPollingSource).toContain('pendingStreamRefresh && !cancelled && !terminalHandled')
    expect(streamPollingSource).toContain('shouldFallbackPollAfterStreamClose({')
  })
})
