import { describe, expect, it } from 'vitest'
import { resolveRestoredRunningTask } from '../restoreRunningWorkflowTask'

describe('resolveRestoredRunningTask', () => {
  it('restores generate_next_chapter tasks that workflow stages would ignore', () => {
    expect(
      resolveRestoredRunningTask({
        task_id: 'd21646de-4ea1-413c-81b9-ebef9dd52c80',
        task_type: 'generate_next_chapter',
        age_minutes: 12.2,
        chapter_number: 16,
      }),
    ).toEqual({
      kind: 'generate_next_chapter',
      taskId: 'd21646de-4ea1-413c-81b9-ebef9dd52c80',
      chapterNumber: 16,
      ageMinutes: 12.2,
    })
  })

  it('restores workflow stage tasks from workflow_stage_ prefixes', () => {
    expect(
      resolveRestoredRunningTask({
        task_id: 'stage-task',
        task_type: 'workflow_stage_review',
        age_minutes: 3,
      }),
    ).toEqual({
      kind: 'workflow_stage',
      taskId: 'stage-task',
      stageType: 'review',
      ageMinutes: 3,
    })
  })


  it("does not treat generate_next_chapter as a workflow stage task", () => {
    const restored = resolveRestoredRunningTask({
      task_id: "gen-4",
      task_type: "generate_next_chapter",
    })
    expect(restored?.kind).toBe("generate_next_chapter")
    expect(restored).not.toHaveProperty("stageType")
  })
  it('ignores unknown task types and blank task ids', () => {
    expect(
      resolveRestoredRunningTask({
        task_id: 'x',
        task_type: 'expand_story',
      }),
    ).toBeNull()
    expect(
      resolveRestoredRunningTask({
        task_id: '   ',
        task_type: 'generate_next_chapter',
      }),
    ).toBeNull()
  })
})