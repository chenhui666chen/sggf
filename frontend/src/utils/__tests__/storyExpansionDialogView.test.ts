import { describe, expect, it } from 'vitest'

import { createStoryExpansionDialogView } from '../storyExpansionDialogView'

describe('storyExpansionDialogView', () => {
  it('展示分析返回的预计耗时区间', () => {
    const view = createStoryExpansionDialogView({
      currentChapterCount: 20,
      currentCharacterCount: 6,
      targetChapterCount: 300,
      targetCharacterCount: 18,
      expansionMode: 'total',
      totalVolumes: null,
      totalChaptersMin: null,
      totalChaptersMax: null,
      frameworkMetadata: null,
      targetVolumeIndex: null,
      volumeChaptersMin: null,
      volumeChaptersMax: null,
      volumeCharacterIncrement: null,
      analysis: {
        effective_target_chapter_count: 300,
        effective_target_character_count: 18,
        estimated_rounds: 20,
        estimated_duration_minutes_min: 45,
        estimated_duration_minutes_max: 80,
      },
    })

    expect(view.precheckChips).toEqual(expect.arrayContaining([
      {
        key: 'estimated-duration',
        label: '预计耗时 45 分钟 - 1 小时 20 分钟',
        color: 'default',
      },
    ]))
  })
  it('常规协同在目标留空且分析给出建议时展示系统估算提示', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 10,
        currentCharacterCount: 3,
        targetChapterCount: null,
        targetCharacterCount: null,
        expansionMode: 'total',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: {
          effective_target_chapter_count: 18,
          effective_target_character_count: 5,
        },
      }),
    ).toMatchObject({
      isVolumeDetailMode: false,
      isLockedToVolumeDetail: false,
      currentChapterChipLabel: '当前已细化章节 10',
      currentCharacterChipLabel: '当前已识别人物 3',
      currentCountHelperText: '当前数量按结构化内容统计：仅计算明确章节标题与已识别人物名，阶段规划、范围引用和人物关系段不计入。',
      chapterDeltaLabel: '系统估算 8',
      chapterDeltaChipLabel: '本轮新增细化章节',
      characterDeltaLabel: '系统估算 2',
      characterDeltaChipLabel: '本轮新增人物',
      hasDelta: false,
      autoEstimateHints: [
        '人物留空时系统预计补到 5 人。',
      ],
      validationMessage: '请至少填写目标细化章节数或目标人物数其中一项，留空的另一项将由系统自动估算。',
    })
  })

  it('常规协同会前置展示建议补人范围和本次任务人物目标', () => {
    const view = createStoryExpansionDialogView({
      currentChapterCount: 20,
      currentCharacterCount: 10,
      targetChapterCount: 300,
      targetCharacterCount: null,
      expansionMode: 'total',
      totalVolumes: null,
      totalChaptersMin: null,
      totalChaptersMax: null,
      frameworkMetadata: null,
      targetVolumeIndex: null,
      volumeChaptersMin: null,
      volumeChaptersMax: null,
      volumeCharacterIncrement: null,
      analysis: {
        execution_mode: 'iterative',
        effective_expansion_mode: 'total',
        effective_target_chapter_count: 300,
        effective_target_character_count: 18,
        estimated_rounds: 20,
        auto_supplement: {
          character_delta: 8,
          character_plan: {
            recommended_range_text: '38-60',
            recommended_additional_min: 28,
            recommended_additional_max: 50,
            stage_label: '首轮',
            stage_target_characters: 18,
            task_target_characters: 38,
            task_target_increment: 28,
            remaining_to_recommended_min: 20,
            follow_up_phase: '后续协同轮次',
          },
        },
      },
    })

    expect(view.autoEstimateHints).toEqual(['建议补人约 28-50 人；首轮先补到 18 人；本次任务预计补到 38 人。'])
    expect(view.precheckChips).toEqual(expect.arrayContaining([
      {
        key: 'character-suggestion',
        label: '建议补人 28-50 人',
        color: 'warning',
      },
      {
        key: 'character-task-target',
        label: '本次预计补到 38 人',
        color: 'secondary',
      },
      {
        key: 'character-auto-rounds',
        label: '点击一次后自动分轮',
        color: 'info',
      },
    ]))
    expect(view.autoSupplementText).toBe('')
  })

  it('单卷细化协同在已有框架时会保留可切换能力并显示卷级提示', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 120,
        currentCharacterCount: 18,
        targetChapterCount: null,
        targetCharacterCount: 18,
        expansionMode: 'volume_detail',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 6,
            expanded_volumes: [1, 2],
          },
        },
        targetVolumeIndex: 3,
        volumeChaptersMin: 30,
        volumeChaptersMax: 40,
        volumeCharacterIncrement: null,
        analysis: {
          volume_detail: {
            target_character_count: 22,
            character_increment: 4,
          },
          warnings: ['需要检查卷间承接'],
          auto_supplement: {
            chapter_delta: 2,
            character_delta: 1,
          },
        },
      }),
    ).toMatchObject({
      isVolumeDetailMode: true,
      isLockedToVolumeDetail: false,
      displayedTargetCharacterCount: 22,
      chapterDeltaLabel: '30-40',
      chapterDeltaChipLabel: '本卷细化章节',
      characterDeltaLabel: '系统估算 4',
      characterDeltaChipLabel: '计划补足人物',
      hasDelta: true,
      analysisWarnings: [],
      autoEstimateHints: ['本卷人物留空时，系统预计新增 4 人。'],
      validationMessage: '',
    })
  })

  it('显式填写本卷新增人物时应优先使用用户输入', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 80,
        currentCharacterCount: 10,
        targetChapterCount: null,
        targetCharacterCount: 12,
        expansionMode: 'volume_detail',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 4,
            expanded_volumes: [],
          },
        },
        targetVolumeIndex: 1,
        volumeChaptersMin: 35,
        volumeChaptersMax: 45,
        volumeCharacterIncrement: 0,
        analysis: {
          volume_detail: {
            target_character_count: 16,
            character_increment: 5,
          },
        },
      }),
    ).toMatchObject({
      characterDeltaLabel: '0',
      autoEstimateHints: [],
      validationMessage: '',
    })
  })

  it('为常规协同生成稳定的配置块与开关文案', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 20,
        currentCharacterCount: 4,
        targetChapterCount: 36,
        targetCharacterCount: null,
        expansionMode: 'total',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: null,
      }),
    ).toMatchObject({
      expansionModeHelperText: '',
      lockedModeAlertText: '',
      writtenModeInfoAlertText: '',
      autoSupplementLabel: '允许系统自动补足配套人物或承接章节',
      configBlocks: [
        {
          kind: 'fields',
          key: 'total-fields',
          fields: [
            {
              key: 'targetChapterCount',
              label: '目标细化章节数',
              helperText: '常规协同推荐总规模不超过450个细化章节；451-600章仍可执行，但更建议先切换到长篇框架协同。',
              placeholder: '留空则由系统自动估算',
              fullWidth: true,
              min: 20,
              max: 600,
            },
          ],
        },
        {
          kind: 'fields',
          key: 'total-target-character',
          fields: [
            {
              key: 'targetCharacterCount',
              label: '目标人物数',
              helperText: '留空后系统会结合章节需求分阶段自动估算角色补足量。',
              placeholder: '留空则由系统自动估算',
              fullWidth: true,
              min: 4,
              max: 200,
            },
          ],
        },
      ],
    })
  })

  it('常规协同超过上限时展示禁止提醒', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 180,
        currentCharacterCount: 12,
        targetChapterCount: 620,
        targetCharacterCount: 14,
        expansionMode: 'total',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: null,
      }),
    ).toMatchObject({
      configBlocks: [
        {
          kind: 'alert',
          key: 'total-conventional-range-alert',
          alert: {
            key: 'total-conventional-range-alert',
            severity: 'warning',
            text: '当前总规模已超过常规协同上限 600个细化章节。请改选“长篇框架协同”。',
          },
        },
        {
          kind: 'fields',
          key: 'total-fields',
        },
        {
          kind: 'fields',
          key: 'total-target-character',
        },
      ],
    })
  })

  it('为长篇框架协同生成稳定的配置块', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 120,
        currentCharacterCount: 15,
        targetChapterCount: null,
        targetCharacterCount: null,
        expansionMode: 'epic_framework',
        totalVolumes: 10,
        totalChaptersMin: 800,
        totalChaptersMax: 1200,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: null,
      }),
    ).toMatchObject({
      expansionModeHelperText: '',
      lockedModeAlertText: '',
      writtenModeInfoAlertText: '',
      chapterDeltaChipLabel: '规划总章',
      chapterDeltaLabel: '800-1200',
      characterDeltaChipLabel: '计划补足人物',
      characterDeltaLabel: '自动估算',
      autoSupplementLabel: '允许系统自动补足配套人物或承接章节',
      configBlocks: [
        {
          kind: 'alert',
          key: 'epic-framework-info',
          alert: {
            key: 'epic-framework-info',
            severity: 'info',
            text: '长篇框架协同会先规划故事总纲、阶段路线图、分卷框架和滚动细化策略，不会一次性直接铺满上千章细纲。',
          },
        },
        {
          kind: 'fields',
          key: 'epic-framework-fields',
          fields: [
            { key: 'totalVolumes', label: '总卷数', helperText: '建议 3-50 卷', min: 3, max: 50, flex: '1 1 160px' },
            { key: 'totalChaptersMin', label: '总章范围最小值', helperText: '建议 300-5000 章', min: 300, max: 5000, flex: '1 1 180px' },
            { key: 'totalChaptersMax', label: '总章范围最大值', helperText: '会作为框架规模上限', min: 300, max: 5000, flex: '1 1 180px' },
          ],
        },
        {
          kind: 'alert',
          key: 'epic-framework-character-policy',
          alert: {
            key: 'epic-framework-character-policy',
            severity: 'info',
            variant: 'outlined',
            text: '长篇框架阶段只建立核心人物骨架，不在此处直接手填全书目标人物数；卷内功能角色与细分人物会在后续单卷细化中逐步补齐。',
          },
        },
      ],
    })
  })

  it('为系统预检生成稳定的标签、适用性与模型计划展示数据', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 24,
        currentCharacterCount: 6,
        targetChapterCount: 48,
        targetCharacterCount: 10,
        expansionMode: 'total',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: {
          effective_intent: 'character_led',
          effective_strategy: 'balanced',
          execution_mode: 'iterative',
          effective_expansion_mode: 'total',
          estimated_rounds: 3,
          analysis_summary: '建议先补角色，再逐轮推进章节。',
          intent_reason: '角色冲突是当前瓶颈。',
          execution_mode_reason: '本次增量较大，建议采用分轮协同。',
          validation: { score: 87 },
          mode_suitability: {
            mode: 'total',
            request_band: 'recommended',
            request_band_label: '推荐区间',
            request_band_reason: '当前增量适合常规协同。',
            preferred_iterative_step: 8,
            single_round_delta_limit: 12,
            summary: '建议按 8 章一轮逐步推进。',
            bands: [
              {
                key: 'recommended',
                label: '推荐',
                range_text: '1-12 章',
                detail: '适合单轮或少量分轮。',
              },
            ],
          },
          written_chapter_context: {
            applied: true,
            written_chapter_count: 9,
            preserve_written_mode: 'preserve_written',
          },
          model_plan: {
            coordinator_planner_model: 'planner-x',
            coordinator_writer_model: 'writer-y',
            outline_expansion_model: 'outline-z',
            character_expansion_model: 'character-k',
            notes: ['优先复用已有设定', '避免单轮过长'],
          },
        },
      }),
    ).toMatchObject({
      hasAnalysis: true,
      precheckChips: [
        { key: 'intent', label: '系统主导 人物主导', color: 'primary' },
        { key: 'strategy', label: '执行顺序 均衡推进', color: 'success' },
        { key: 'execution-mode', label: '执行模式 分轮协同', color: 'secondary' },
        { key: 'expansion-mode', label: '扩展形态 常规协同', color: 'info' },
        { key: 'estimated-rounds', label: '预计轮次 3', color: 'default' },
        { key: 'score', label: '协同评分 87', color: 'warning' },
      ],
      analysisSummaryText: '建议先补角色，再逐轮推进章节。',
      modeSuitabilityView: {
        chips: [
          { key: 'request-band', label: '适用结论 推荐区间', color: 'success' },
          { key: 'preferred-step', label: '建议步长 8个细化章节', color: 'default' },
          { key: 'single-round-limit', label: '单轮上限 12个细化章节', color: 'default' },
        ],
        summary: '常规协同推荐总规模不超过450个细化章节；451-600章仍可执行，但更建议先切换到长篇框架协同。',
        reason: '',
        bands: [],
      },
      intentReasonText: '',
      executionModeReasonText: '',
      writtenContextText: '已检测到 9 章正文，当前按“仅保护正文”参与协同。',
      autoSupplementText: '',
      epicConfigText: '',
      volumeDetailText: '',
      volumeCharacterPlanText: '',
      modelPlanLines: [],
      validationMessage: '',
    })
  })

  it('人物留空且自动补足时，提示本轮先补到目标并隐藏远端长篇分段', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 0,
        currentCharacterCount: 10,
        targetChapterCount: 300,
        targetCharacterCount: null,
        expansionMode: 'total',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: {
          effective_intent: 'outline_led',
          effective_strategy: 'plot_first',
          execution_mode: 'iterative',
          effective_expansion_mode: 'total',
          effective_target_character_count: 18,
          auto_supplement_applied: true,
          auto_supplement: {
            character_delta: 8,
            reasons: ['按目标章节规模与题材倾向，结构化人物建议逐步靠近 34-54 人，本次同步补入 8 个配套角色承接新增情节。'],
          },
          mode_suitability: {
            mode: 'total',
            request_band: 'recommended',
            request_band_label: '推荐区间',
            request_band_reason: '当前目标仍在常规协同的稳定工作带内，适合直接进行单轮或分轮扩展。',
            preferred_iterative_step: 15,
            single_round_delta_limit: 30,
            summary: '常规协同推荐总规模不超过450个细化章节；451-600章仍可执行，但更建议先切换到长篇框架协同。',
            bands: [
              {
                key: 'recommended',
                label: '推荐区间',
                range_text: '总规模 1-450 章',
                detail: '单次新增建议按 15 章左右推进，质量和稳定性更均衡。',
              },
              {
                key: 'caution',
                label: '谨慎区间',
                range_text: '总规模 451-600 章',
                detail: '仍可继续常规协同，但更建议优先切换到长篇框架协同统一规划。',
              },
              {
                key: 'forbidden',
                label: '禁止常规协同',
                range_text: '总规模 >= 601 章',
                detail: '超过 600 章后必须改用长篇框架协同，不能继续走常规协同。',
              },
            ],
          },
        },
      }),
    ).toMatchObject({
      autoEstimateHints: ['人物留空时系统预计补到 18 人。'],
      modeSuitabilityView: {
        bands: [],
      },
    })
  })

  it('长篇框架人物留空时显示阶段补足与后续补齐提示', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 80,
        currentCharacterCount: 10,
        targetChapterCount: null,
        targetCharacterCount: null,
        expansionMode: 'epic_framework',
        totalVolumes: 18,
        totalChaptersMin: 900,
        totalChaptersMax: 1200,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: {
          effective_intent: 'outline_led',
          effective_strategy: 'plot_first',
          execution_mode: 'epic',
          effective_expansion_mode: 'epic_framework',
          effective_target_character_count: 34,
          auto_supplement_applied: true,
          auto_supplement: {
            character_delta: 24,
            reasons: ['按目标章节规模与题材倾向，全书结构化人物建议规模约为 113-180 人。当前为长篇框架协同，框架阶段先补到 34 人（本次新增 24 人），优先搭起主线、阵营与关键承接角色；剩余角色将在后续卷级细化或后续协同继续补齐。'],
            character_plan: {
              recommended_min: 113,
              recommended_max: 180,
              recommended_range_text: '113-180',
              stage_label: '框架阶段',
              suggested_increment: 24,
              stage_target_characters: 34,
              remaining_to_recommended_min: 79,
              follow_up_phase: '后续卷级细化或后续协同',
              is_phased: true,
            },
          },
          epic_config: {
            total_volumes: 18,
            chapter_range: [900, 1200],
          },
        },
      }),
    ).toMatchObject({
      autoEstimateHints: ['全书建议规模约 113-180 人；框架阶段先补到 34 人；其余人物会在后续卷级细化或后续协同继续补齐。'],
      autoSupplementText: '',
    })
  })

  it('为单卷细化预检生成补足提示与卷级说明', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 120,
        currentCharacterCount: 18,
        targetChapterCount: null,
        targetCharacterCount: 18,
        expansionMode: 'volume_detail',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 6,
            expanded_volumes: [1, 2],
          },
        },
        targetVolumeIndex: 3,
        volumeChaptersMin: 30,
        volumeChaptersMax: 40,
        volumeCharacterIncrement: null,
        analysis: {
          effective_intent: 'balanced',
          effective_strategy: 'plot_first',
          execution_mode: 'volume_detail',
          effective_expansion_mode: 'volume_detail',
          model_plan: {},
          volume_detail: {
            target_volume_index: 3,
            chapter_range: [30, 40],
            target_character_count: 22,
            character_increment: 4,
            existing_detail: true,
          },
          auto_supplement: {
            chapter_delta: 2,
            character_delta: 1,
          },
        },
      }),
    ).toMatchObject({
      precheckChips: [
        { key: 'intent', label: '系统主导 均衡协同', color: 'primary' },
        { key: 'strategy', label: '执行顺序 剧情优先', color: 'success' },
        { key: 'execution-mode', label: '执行模式 单卷细化', color: 'secondary' },
        { key: 'expansion-mode', label: '扩展形态 单卷细化协同', color: 'info' },
        { key: 'estimated-rounds', label: '预计轮次 1', color: 'default' },
        { key: 'score', label: '协同评分 0', color: 'warning' },
      ],
      modeSuitabilityView: null,
      autoSupplementText: '系统会自动补足 2 个承接章节。 系统会自动补足 1 个配套人物。',
      volumeDetailText: '单卷细化目标：第3卷 / 第30-40章（将覆盖原有细纲）',
      volumeCharacterPlanText: '本卷人物计划：新增不超过 4 人，对齐后的全书人物目标为 22 人。',
      modelPlanLines: [],
      validationMessage: '',
    })
  })

  it('为单卷细化协同生成可重选模式提示与配置块', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 120,
        currentCharacterCount: 18,
        targetChapterCount: null,
        targetCharacterCount: 18,
        expansionMode: 'volume_detail',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: {
          has_framework: true,
          metadata: {
            total_volumes: 6,
            expanded_volumes: [1, 2],
          },
        },
        targetVolumeIndex: 3,
        volumeChaptersMin: 30,
        volumeChaptersMax: 40,
        volumeCharacterIncrement: null,
        analysis: {
          volume_detail: {
            target_character_count: 22,
            character_increment: 4,
          },
        },
      }),
    ).toMatchObject({
      expansionModeHelperText: '当前项目已有长篇框架，可继续单卷细化，也可以切回长篇框架协同重新生成。',
      lockedModeAlertText: '',
      writtenModeInfoAlertText: '单卷细化协同会直接继承现有长篇框架和正文上下文，本轮不再单独配置"已写章节处理"模式。',
      autoSupplementLabel: '允许系统自动补足本卷承接人物或桥接章节',
      configBlocks: [
        {
          kind: 'alert',
          key: 'volume-framework-status',
          alert: {
            key: 'volume-framework-status',
            severity: 'info',
            text: '已检测到长篇框架，可直接细化单卷。当前框架共 6 卷，已展开卷：1、2。',
          },
        },
        {
          kind: 'fields',
          key: 'volume-detail-fields',
          fields: [
            { key: 'targetVolumeIndex', label: '目标卷编号', helperText: '范围 1-6', min: 1, max: 6, flex: '1 1 160px' },
            { key: 'volumeChaptersMin', label: '本卷最少章节', helperText: '建议 60-80 章', min: 20, max: 120, flex: '1 1 180px' },
            { key: 'volumeChaptersMax', label: '本卷最多章节', helperText: '建议尽量控制在 80 章内；必要时可放宽到 120 章', min: 20, max: 120, flex: '1 1 180px' },
          ],
        },
        {
          kind: 'alert',
          key: 'volume-character-info',
          alert: {
            key: 'volume-character-info',
            severity: 'info',
            variant: 'outlined',
            text: '下方只读人物字段仅作全书角色规模参考；系统会优先补齐与当前卷剧情承接相关的人物。若本轮人物留空，请将“本卷新增人物上限”留空，由系统自动估算。',
          },
        },
        {
          kind: 'fields',
          key: 'volume-character-fields',
          fields: [
            { key: 'displayedTargetCharacterCount', label: '全书目标人物数（只读）', helperText: '仅作全书角色规模参考，单卷细化模式下不直接编辑。', readOnly: true, flex: '1 1 220px' },
            { key: 'volumeCharacterIncrement', label: '本卷新增人物上限', helperText: '留空则由系统结合本卷剧情承接自动估算。', placeholder: '留空则由系统自动估算', min: 0, max: 30, flex: '1 1 220px' },
          ],
        },
      ],
    })
  })

  it('已有框架时切回长篇框架协同会显示重生成清理提示', () => {
    const view = createStoryExpansionDialogView({
      currentChapterCount: 120,
      currentCharacterCount: 18,
      targetChapterCount: null,
      targetCharacterCount: null,
      expansionMode: 'epic_framework',
      totalVolumes: 10,
      totalChaptersMin: 600,
      totalChaptersMax: 900,
      frameworkMetadata: {
        has_framework: true,
        metadata: {
          total_volumes: 6,
          expanded_volumes: [1, 2],
        },
      },
      targetVolumeIndex: 3,
      volumeChaptersMin: 30,
      volumeChaptersMax: 40,
      volumeCharacterIncrement: null,
      analysis: null,
    })

    expect(view).toMatchObject({
      expansionModeHelperText: '当前项目已有长篇框架，可继续单卷细化，也可以切回长篇框架协同重新生成。',
      lockedModeAlertText: '',
    })
    expect(view.configBlocks).toEqual(expect.arrayContaining([
      {
        kind: 'alert',
        key: 'epic-framework-info',
        alert: {
          key: 'epic-framework-info',
          severity: 'info',
          text: '长篇框架协同会先规划故事总纲、阶段路线图、分卷框架和滚动细化策略，不会一次性直接铺满上千章细纲。',
        },
      },
      {
        kind: 'alert',
        key: 'epic-framework-regenerate-warning',
        alert: {
          key: 'epic-framework-regenerate-warning',
          severity: 'warning',
          variant: 'outlined',
          text: '当前项目已存在长篇框架。重新生成成功后会覆盖现有框架，并清空已展开卷的细纲，后续需要按新框架重新做单卷细化。',
        },
      },
    ]))
  })

  it('为不同扩展模式给出稳定的不可执行提示', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 60,
        currentCharacterCount: 12,
        targetChapterCount: null,
        targetCharacterCount: 12,
        expansionMode: 'volume_detail',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: 30,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: null,
      }).validationMessage,
    ).toBe('单卷细化协同需要先选择有效卷编号，并填写完整的本卷细化章节范围。')

    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 60,
        currentCharacterCount: 12,
        targetChapterCount: null,
        targetCharacterCount: null,
        expansionMode: 'epic_framework',
        totalVolumes: 8,
        totalChaptersMin: 300,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: null,
      }).validationMessage,
    ).toBe('长篇框架协同需要有效的总卷数和总章节范围。')
  })
  it('超长篇推荐项目切到常规协同时展示模式偏差提醒', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 42,
        currentCharacterCount: 8,
        recommendedMode: 'epic_framework',
        targetChapterCount: 57,
        targetCharacterCount: 8,
        expansionMode: 'total',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: null,
      }),
    ).toMatchObject({
      configBlocks: [
        {
          kind: 'alert',
          key: 'total-epic-recommendation-alert',
          alert: {
            key: 'total-epic-recommendation-alert',
            severity: 'warning',
            text: '当前项目按篇幅规划更适合“长篇框架协同”。若本轮只是补少量细化章节或人物，且总规模仍不超过450章，可以继续常规协同；若准备推进 451 章及以上主线，请优先切换到长篇框架协同。',
          },
        },
        {
          kind: 'fields',
          key: 'total-fields',
        },
        {
          kind: 'fields',
          key: 'total-target-character',
        },
      ],
    })
  })

  it('常规协同进入 451-600 章谨慎区间时展示切换建议', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 320,
        currentCharacterCount: 12,
        targetChapterCount: 520,
        targetCharacterCount: 14,
        expansionMode: 'total',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: null,
      }),
    ).toMatchObject({
      configBlocks: [
        {
          kind: 'alert',
          key: 'total-conventional-caution-alert',
          alert: {
            key: 'total-conventional-caution-alert',
            severity: 'warning',
            text: '常规协同推荐总规模不超过450个细化章节；451-600章仍可执行，但更建议先切换到长篇框架协同。',
          },
        },
        {
          kind: 'fields',
          key: 'total-fields',
        },
        {
          kind: 'fields',
          key: 'total-target-character',
        },
      ],
    })
  })
  it('章节留空时会提示目标总章数与相对当前的新增量', () => {
    expect(
      createStoryExpansionDialogView({
        currentChapterCount: 3,
        currentCharacterCount: 25,
        targetChapterCount: null,
        targetCharacterCount: 38,
        expansionMode: 'total',
        totalVolumes: null,
        totalChaptersMin: null,
        totalChaptersMax: null,
        frameworkMetadata: null,
        targetVolumeIndex: null,
        volumeChaptersMin: null,
        volumeChaptersMax: null,
        volumeCharacterIncrement: null,
        analysis: {
          effective_target_chapter_count: 13,
          effective_target_character_count: 38,
        },
      }).autoEstimateHints,
    ).toEqual(['章节留空时，系统预计先补到 13 章（较当前新增 10 章）。'])
  })
})
