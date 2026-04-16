import { describe, expect, it } from 'vitest'

import type { StoryExpansionDialogFormState } from '@/types/storyExpansionDialog'
import {
  confirmStoryExpansionSubmitPreflight,
  getStoryExpansionFrameworkRegenerateConfirmDialog,
  getStoryExpansionFrameworkRegenerateConfirmMessage,
  createStoryExpansionSubmitPayload,
  createStoryExpansionSubmitPreflight,
  getStoryExpansionFrameworkResetConfirmDialog,
  getStoryExpansionFrameworkResetConfirmMessage,
  getStoryExpansionVolumeOverwriteConfirmDialog,
  getStoryExpansionVolumeOverwriteConfirmMessage,
} from '../storyExpansionSubmission'

function createBaseForm(overrides: Partial<StoryExpansionDialogFormState> = {}): StoryExpansionDialogFormState {
  return {
    targetChapterCount: 24,
    targetCharacterCount: 6,
    expansionMode: 'total',
    totalVolumes: 8,
    totalChaptersMin: 600,
    totalChaptersMax: 900,
    frameworkMetadata: null,
    targetVolumeIndex: 2,
    volumeChaptersMin: 30,
    volumeChaptersMax: 40,
    volumeCharacterIncrement: 2,
    autoSupplementEnabled: true,
    preserveWrittenMode: 'extract_extend',
    ...overrides,
  }
}

describe('storyExpansionSubmission', () => {
  it('returns a validation error when story context is missing', () => {
    expect(
      createStoryExpansionSubmitPreflight({
        content: {
          worldSetting: '',
          plotOutline: '',
          characters: '',
        },
        currentChapterCount: 12,
        currentCharacterCount: 4,
        form: createBaseForm(),
      }).validationError,
    ).toBe('请先准备好世界观和情节大纲，再执行协同扩展')
  })

  it('builds structured overwrite dialog copy for volume detail regeneration', () => {
    expect(getStoryExpansionVolumeOverwriteConfirmDialog(2)).toMatchObject({
      title: '覆盖现有细纲',
      description: '第 2 卷已存在细纲。重新协同生成会覆盖当前卷的现有内容。',
      detail: '确认后将按当前配置重新生成第 2 卷细纲，不影响其他卷。',
      confirmLabel: '继续覆盖',
      cancelLabel: '取消',
      message: getStoryExpansionVolumeOverwriteConfirmMessage(2),
    })
  })

  it('builds structured framework reset dialog copy for regular expansion', () => {
    expect(getStoryExpansionFrameworkResetConfirmDialog()).toMatchObject({
      title: '重置长篇框架状态',
      description: '当前项目已存在长篇框架与卷细纲。继续使用“常规协同”补细化章节，会清空现有框架状态。',
      detail: '后续将以新的章节大纲为准，原有卷级细纲需要重新协同生成。',
      confirmLabel: '继续重置',
      cancelLabel: '取消',
      message: getStoryExpansionFrameworkResetConfirmMessage(),
    })
  })

  it('builds structured framework regenerate dialog copy for epic regeneration', () => {
    expect(getStoryExpansionFrameworkRegenerateConfirmDialog()).toMatchObject({
      title: '重新生成长篇框架',
      description: '当前项目已存在长篇框架与卷细纲。继续重新生成会覆盖现有框架，并清空已展开卷的细纲。',
      detail: '成功后将以新的分卷框架为准，原有单卷细化内容需要按新框架重新生成。',
      confirmLabel: '继续重生成',
      cancelLabel: '取消',
      message: getStoryExpansionFrameworkRegenerateConfirmMessage(),
    })
  })

  it('requests overwrite confirmation for regenerating an expanded volume', () => {
    expect(
      createStoryExpansionSubmitPreflight({
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 80,
        currentCharacterCount: 10,
        form: createBaseForm({
          expansionMode: 'volume_detail',
          frameworkMetadata: {
            has_framework: true,
            metadata: {
              total_volumes: 5,
              expanded_volumes: [1, 2],
            },
          },
          targetVolumeIndex: 2,
          targetChapterCount: null,
          targetCharacterCount: 10,
          volumeCharacterIncrement: null,
        }),
      }),
    ).toMatchObject({
      validationError: null,
      confirmDialogs: [
        getStoryExpansionVolumeOverwriteConfirmDialog(2),
      ],
    })
  })

  it('requests framework reset confirmation for regular chapter expansion', () => {
    expect(
      createStoryExpansionSubmitPreflight({
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 20,
        currentCharacterCount: 5,
        form: createBaseForm({
          frameworkMetadata: {
            has_framework: true,
          },
          targetChapterCount: 30,
          targetCharacterCount: 5,
        }),
      }),
    ).toMatchObject({
      validationError: null,
      confirmDialogs: [
        getStoryExpansionFrameworkResetConfirmDialog(),
      ],
    })
  })

  it('requests framework regenerate confirmation for epic framework regeneration', () => {
    expect(
      createStoryExpansionSubmitPreflight({
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 120,
        currentCharacterCount: 18,
        form: createBaseForm({
          expansionMode: 'epic_framework',
          frameworkMetadata: {
            has_framework: true,
            metadata: {
              total_volumes: 6,
              expanded_volumes: [1, 2],
            },
          },
          targetChapterCount: null,
          targetCharacterCount: null,
          totalVolumes: 10,
          totalChaptersMin: 600,
          totalChaptersMax: 900,
        }),
      }),
    ).toMatchObject({
      validationError: null,
      confirmDialogs: [
        getStoryExpansionFrameworkRegenerateConfirmDialog(),
      ],
    })
  })

  it('runs confirmations in order', async () => {
    const confirmMessages: string[] = []
    const result = await confirmStoryExpansionSubmitPreflight({
      confirmDialogs: [
        getStoryExpansionVolumeOverwriteConfirmDialog(2),
        getStoryExpansionFrameworkRegenerateConfirmDialog(),
      ],
    }, (confirmDialog) => {
      confirmMessages.push(confirmDialog.message)
      return true
    })

    expect(result).toBe(true)
    expect(confirmMessages).toEqual([
      getStoryExpansionVolumeOverwriteConfirmMessage(2),
      getStoryExpansionFrameworkRegenerateConfirmMessage(),
    ])
  })

  it('stops follow-up confirmations after cancellation', async () => {
    const confirmMessages: string[] = []
    const result = await confirmStoryExpansionSubmitPreflight({
      confirmDialogs: [
        getStoryExpansionVolumeOverwriteConfirmDialog(3),
        getStoryExpansionFrameworkRegenerateConfirmDialog(),
      ],
    }, (confirmDialog) => {
      confirmMessages.push(confirmDialog.message)
      return false
    })

    expect(result).toBe(false)
    expect(confirmMessages).toEqual([
      getStoryExpansionVolumeOverwriteConfirmMessage(3),
    ])
  })

  it('builds submit payload with analysis overrides when both targets are explicit', () => {
    expect(
      createStoryExpansionSubmitPayload({
        projectId: 9,
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 20,
        currentCharacterCount: 5,
        form: createBaseForm({
          targetChapterCount: 36,
          targetCharacterCount: 8,
        }),
        requestControls: {
          strategy: 'auto',
          intent: 'outline_led',
        },
        analysis: {
          effective_strategy: 'balanced',
          effective_intent: 'character_led',
          effective_target_chapter_count: 40,
          effective_target_character_count: 9,
        },
      }),
    ).toMatchObject({
      project_id: 9,
      current_outline: 'outline',
      world_setting: 'world',
      characters: 'characters',
      current_chapter_count: 20,
      current_character_count: 5,
      target_total_chapters: 40,
      target_total_characters: 9,
      strategy: 'balanced',
      intent: 'character_led',
      enable_auto_supplement: true,
      expansion_mode: 'total',
      preserve_written_mode: 'extract_extend',
    })
  })

  it('keeps blank character target out of submit payload when total mode will auto-continue across rounds', () => {
    expect(
      createStoryExpansionSubmitPayload({
        projectId: 11,
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 20,
        currentCharacterCount: 7,
        form: createBaseForm({
          targetChapterCount: 300,
          targetCharacterCount: null,
        }),
        requestControls: {
          strategy: 'auto',
          intent: 'outline_led',
        },
        analysis: {
          effective_target_chapter_count: 300,
          effective_target_character_count: 15,
          effective_expansion_mode: 'total',
          auto_supplement: {
            character_delta: 8,
            character_plan: {
              stage_target_characters: 15,
              task_target_characters: 35,
            },
          },
        },
      }),
    ).toMatchObject({
      project_id: 11,
      target_total_chapters: 300,
      target_total_characters: undefined,
      enable_auto_supplement: true,
      expansion_mode: 'total',
    })
  })

  it('does not send total chapter target for volume detail mode', () => {
    expect(
      createStoryExpansionSubmitPayload({
        projectId: 12,
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 120,
        currentCharacterCount: 18,
        form: createBaseForm({
          expansionMode: 'volume_detail',
          frameworkMetadata: {
            has_framework: true,
            metadata: {
              total_volumes: 6,
              expanded_volumes: [1, 2],
            },
          },
          targetChapterCount: null,
          targetCharacterCount: 18,
          targetVolumeIndex: 3,
          volumeCharacterIncrement: null,
        }),
        requestControls: {
          strategy: 'auto',
          intent: 'outline_led',
        },
        analysis: {
          effective_target_chapter_count: 300,
          effective_target_character_count: 22,
        },
      }),
    ).toMatchObject({
      expansion_mode: 'volume_detail',
      target_total_chapters: undefined,
      target_total_characters: 22,
      target_volume_index: 3,
    })
  })

  it('sends the analysis-derived character target for volume detail mode when the form leaves characters blank', () => {
    expect(
      createStoryExpansionSubmitPayload({
        projectId: 13,
        content: {
          worldSetting: 'world',
          plotOutline: 'outline',
          characters: 'characters',
        },
        currentChapterCount: 120,
        currentCharacterCount: 18,
        form: createBaseForm({
          expansionMode: 'volume_detail',
          frameworkMetadata: {
            has_framework: true,
            metadata: {
              total_volumes: 6,
              expanded_volumes: [1, 2],
            },
          },
          targetChapterCount: null,
          targetCharacterCount: null,
          targetVolumeIndex: 3,
          volumeCharacterIncrement: null,
        }),
        requestControls: {
          strategy: 'auto',
          intent: 'outline_led',
        },
        analysis: {
          effective_target_chapter_count: 300,
          effective_target_character_count: 22,
          volume_detail: {
            character_increment: 4,
            target_character_count: 22,
          },
        },
      }),
    ).toMatchObject({
      expansion_mode: 'volume_detail',
      target_total_chapters: undefined,
      target_total_characters: 22,
      target_volume_index: 3,
      volume_character_increment: undefined,
    })
  })
})
