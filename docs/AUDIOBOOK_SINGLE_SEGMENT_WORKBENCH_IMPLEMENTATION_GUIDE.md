# 有声小说单片段工作台与整章音频链路实施指南

> 状态：实施参考与验收基线，不等同于所有条目均已上线。
>
> 代码基线核对日期：2026-08-05。
>
> 目标读者：有声书产品、前端、后端、音频算法、测试、运维与安全评审人员。
>
> 相关设计：`docs/AUDIOBOOK_VOICE_PROFILE_AND_CHARACTER_MATCHING_GUIDE.md`。

## 1. 文档目的

本指南把“单片段工作台提示编辑”与此前发现的全链路问题放在同一个实施边界内。目标不只是增加三个弹窗，而是保证用户在剧本审核、片段试听、候选保存、管线合成、整章重混和章节产物删除之间始终使用同一份、最新且可验证的片段资产。

最终用户流程应满足：

1. 用户在剧本审核阶段选中某个片段，并进入该章节的单片段工作台。
2. 点击“人声提示”“音效提示”或“配乐提示”后，在独立弹窗中输入自然语言描述。
3. 人声描述可由模型整理为供应商中立的表演意图；用户也可以录下口述要求，由 ASR 转成文字后继续编辑。
4. 音效和配乐既可以输入描述，也可以搜索、试听并选择素材库资产。
5. 用户生成的是候选音频。只有试听后明确“保存/应用候选”，候选才成为该片段的持久资产。
6. 已保存且签名仍匹配的工作台人声音频在“按已批准剧本生成音频”时直接复用，不重复调用 TTS。
7. 任一片段的人声、音效、配乐或完整混音更新后，旧整章音频立即视为过期；重新混音必须使用最新持久资产。
8. 删除章节有声书产物时，整章文件、字幕、四类片段资产、分块资产和临时候选一并清理。

本指南同时定义当前能力边界：ASR 能可靠转写“用户口述了什么要求”，但不能单独判断或复刻“苍老、沙哑、空灵、浑厚”等音色质感。示范朗读的韵律分析和音频理解模型属于后续能力，不能包装成当前已完成能力。

## 2. 状态标识与实现概览

本文使用四种状态：

- **已实现**：当前代码已有实现和针对性测试；发布前仍需执行第 20 节完整回归。
- **部分实现**：主链路已存在，但仍有明确缺口或能力降级。
- **待补齐**：本轮目标内必须修复或完成验收的项目。
- **后续能力**：需要新的模型评测、产品决策或独立项目，不阻塞本轮基础链路上线。

| 能力 | 状态 | 当前代码事实或剩余问题 |
|---|---|---|
| 从剧本审核打开章节工作台 | 已实现 | `selectedSegmentIndex` 作为一次性 `initialSegmentIndex` 传入工作台，消费后清除，避免后续刷新覆盖用户选择 |
| 三类提示弹窗 | 已实现 | `frontend/src/pages/audiobook/SegmentCueEditorDialog.tsx` 支持 `voice/sfx/bgm`，由 `frontend/src/pages/audiobook/ScriptEditorDialog.tsx` 三个提示面板打开 |
| 人声文字描述与智能整理 | 已实现 | 描述写入 `performance_notes`；后端可选 LLM，失败回退规则解析 |
| 音效/配乐文字描述与素材库选择 | 已实现 | `frontend/src/pages/audiobook/AudioPicker.tsx` 支持搜索、试听和选择；音效按 `asset_id` 去重 |
| 音效/配乐未填写字段的结构化 LLM 补全 | 已实现，带降级 | 后端按受控白名单补全 `sound_effects` / `music_cue` 的时长、音量、淡入淡出和时间属性；模型失败或输出不合规时保留用户输入并回退到 `sound_effects_simple` / `music_cue_simple`，素材 `asset_id` 仍只能由用户从库中选择 |
| 用户朗读录音分析 | 已实现 | 人声弹窗顶部静态展示要朗读的台词；前端最长 30 秒录音，后端上限 10MB；固定使用 qwen3.5-omni 音频理解校验朗读文本与片段台词一致，不一致返回 400 并提示重录；一致后朗读特点归一为供应商中立语义补丁，由合成编译阶段按目标 TTS 模型能力适配；关闭或切换片段后以会话代次忽略迟到响应 |
| 朗读节奏、停顿和重音转化为 TTS 指令 | 已实现 | omni 输出 intent/patch 语义层，`build_delivery_plan` + `build_model_style_control` 在合成编译时按模型 `style_control_modes` 适配（自然语言/director/audio_tags/basic），不依赖模型直接生成供应商指令 |
| 示范录音的音色质感识别或声音复刻 | 后续能力 | 需要声学特征或音频理解模型的音色建模能力，当前只提取韵律与表演特征，不分析或克隆用户音色 |
| 普通试听与候选生成统一编译 | 已实现 | `backend/app/api/v1/audiobook_api/routes_segment_preview.py`、`backend/app/api/v1/audiobook_api/routes_segment_regen.py` 使用 `compile_segment_synthesis_input()`；显式片段音色和片段模型优先 |
| 候选 token、登记、指纹绑定与安全 apply | 已实现 | `backend/app/services/audiobook/segment_candidate_token.py`、`backend/app/services/audiobook/segment_candidate_registry.py` + `ChapterAudioRun(run_type="segment_candidate")` + 不可变 effective segment |
| 同片段不同轨候选并存 | 已实现 | 候选登记保存 `candidate_preview_type`，只顶替同一 `(chapter, segment_index, preview_type)` 的旧候选；每次生成使用独立 nonce 命名空间，避免并发请求在登记前互删文件 |
| 四类片段持久资产 | 已实现 | `audio_path`、`sfx_audio_path`、`bgm_audio_path`、`mix_audio_path` |
| 重排后的物理资产归属 | 已实现 | `segment_key` 映射为稳定高位存储槽；片段数组位置变化不会让新保存动作清理到其他片段的历史索引文件 |
| 工作台人声音频进入管线缓存复用 | 已实现 | 普通管线多 chunk 资产按 `audio_chunk_cache_paths` 复用；工作台固化片段由服务端写入 `audio_render_mode=whole_segment`，长片段按一个完整 render chunk 复用，不重复调用 TTS |
| 整章过期状态 | 已实现 | apply 返回 `chapter_audio_stale=true`；读取/保存剧本时服务端按签名与完成时间派生 |
| 最新片段重新混合整章 | 已实现 | `backend/app/services/audiobook/background_jobs_remix.py` 支持完整 mix 优先、stem 叠加、旧 checkpoint 过滤和时间线重锚定 |
| 删除章节产物时统一清理 | 已实现 | `DELETE .../output` 先取消 full/script/audio/remix/candidate run 并写不可恢复墓碑，再清理整章、字幕、显式持久资产、chunk 和候选登记；尚无 `ChapterAudio` 的首次生成也可取消成功 |
| 素材文件路径限制在素材库根目录 | 已实现 | `SegmentPreviewService`、`SfxMixin` 和 `MusicMixin` 统一经过 `resolve_audio_library_file_path()`；绝对路径、目录穿越、UNC 路径和素材库外符号链接目标会被拒绝 |

上线前必须重新核对本表；任何“待补齐”项目未完成时，应在发布说明中明确降级范围。

## 3. 不可破坏的业务约束

以下约束是实现和代码审查的共同基线：

1. **提示应用不等于音频保存。** “应用到片段”只修改当前剧本草稿；“应用候选”才把试听音频固化并写回 `script_json`。
2. **批准剧本不隐式生成音频。** 批准只改变剧本状态，音频生成由独立动作触发。
3. **客户端不能指定服务器音频路径。** 所有 `*_audio_path` 和缓存字段均由服务端生成、校验和保留；普通试听、候选生成和 apply 入口都先清洗这些字段。
4. **LLM 只能建议语义字段。** 供应商参数、音色 ID、模型 ID、素材 ID、音频路径、缓存签名和运行时快照不得由 LLM 编造。
5. **试听、候选和保存必须使用相同的有效片段。** 不能出现“文本 A 生成的音频被保存到文本 B”或“试听音色 A、保存音色 B”。
6. **片段显式绑定优先。** `voice_params.speaker` 和片段 `tts_model` 优先于角色默认音色及页面级模型回退。
7. **已保存资产只有签名匹配时才可复用。** 文本、音色、模型、情绪或影响合成的语义发生变化后，不得复用旧人声。
8. **完整混音是一个快照。** 任何非 `mix` 轨更新都必须清除旧 `mix_audio_path`，避免把旧完整混音误当成最新结果。
9. **已登记但丢失的轨道不能静默回退。** 应返回缺失原因并要求用户确认，而不是悄悄使用旧 checkpoint 内容。
10. **章节产物删除必须覆盖所有来源。** 工作台手工保存和管线自动固化使用同一清理边界。
11. **ASR 结果必须声明范围。** 当前录音入口只代表口述要求转写，不代表声音画像、韵律模仿或声音克隆。
12. **同一页面只允许一个受控播放器发声。** 素材试听、片段试听和整章播放之间需要播放仲裁。
13. **片段资产归属不能依赖数组位置。** 逻辑迁移和物理覆盖均以服务端 `segment_key` 为稳定身份；旧数据无 key 才允许受控回退。
14. **删除墓碑不可被后台进度覆盖。** 被章节产物删除取消的 run 必须保持 `cancelled + resumable=false + chapter_output_deleted`，后续 worker 事件不能重新写成 running/completed。

## 4. 用户工作流

### 4.1 从审核阶段进入工作台

目标交互：

1. 用户在“剧本质量评审”中选中片段 `N`。
2. 点击“打开剧本编辑器”。
3. 关闭审核弹窗，打开既有 `ScriptEditorDialog`，并将 `selectedSegmentIndex` 初始化为 `N`。
4. 只创建一个完整工作台 Dialog，不在审核 Dialog 内嵌套第二个编辑器。
5. 初始定位只在打开/章节切换时应用一次；轮询或外部数据刷新不得覆盖用户随后手工选择的片段。

当前实现涉及：

- `frontend/src/pages/audiobook/ScriptQualityReviewDialog.tsx`
- `frontend/src/pages/audiobook/useAudiobookScriptEditorActions.ts`
- `frontend/src/pages/audiobook/useAudiobookScriptEditorState.ts`
- `frontend/src/pages/audiobook/ScriptEditorDialog.tsx`

建议最小合同为：

```ts
onOpenScriptEditor(chapterId: number, initialSegmentIndex?: number): Promise<void> | void
```

工作台收到 `initialSegmentIndex` 后必须做边界夹取；片段不存在时回退到 `0`。

当前实现已经采用该可选参数，并在工作台成功消费初始索引后调用 `onInitialSegmentIndexConsumed` 清除一次性状态。对应回归位于 `frontend/src/pages/audiobook/__tests__/scriptEditorInitialSegmentFocus.test.ts`。

### 4.2 编辑三类提示

`frontend/src/pages/audiobook/ScriptEditorDialog.tsx` 的人声、音效、配乐面板承担摘要展示和弹窗入口。折叠按钮独立处理事件；面板使用 `role="group"`，避免外层按钮与内部 `IconButton` 构成嵌套交互控件。

弹窗行为：

- **人声提示**：多行描述、智能整理、模型能力提示、麦克风口述转写、应用到片段。
- **音效提示**：多行描述、素材库搜索与试听、选择一个或多个音效后写回结构化列表。
- **配乐提示**：多行描述、素材库搜索与试听、选择配乐后写回结构化对象。

弹窗打开时从当前片段初始化；用户输入后，即使外部轮询刷新了同一片段对象，也不能重置尚未应用的文本。关闭弹窗时停止录音并释放麦克风轨道；已经发出的 ASR 请求即使随后返回，也必须因会话代次失效而忽略，不能写入后来打开的片段。

### 4.3 从描述到候选音频

推荐操作顺序：

1. 用户编辑提示并点击“应用到片段”。
2. 用户点击对应轨道的“重新生成”，服务端以当前草稿作为客户端覆盖生成候选。
3. 候选只保存在临时候选空间，返回 `candidate_id`。
4. 用户通过候选试听接口播放，不使用客户端传回的任意路径。
5. 用户满意后点击“保存/应用候选”；不满意则在前端取消候选或重新生成。
6. apply 成功后服务端返回已保存片段和 `chapter_audio_stale=true`。

注意：候选生成时的服务端存储片段为 A，带草稿覆盖的有效片段为 B。候选 apply 前不要先把草稿另行保存成 C；只要当前服务端片段不再等于 A，apply 会返回 `409`，要求重新生成候选。这是防止跨标签页错绑的有意行为。

### 4.4 进入管线和整章重混

- 对 `audio_from_scripts` 管线，签名匹配的持久化人声音频注入 resume checkpoint，TTS 跳过该 render chunk。
- 其他未保存或签名过期的片段正常生成。
- 管线生成的片段也会在 run 临时资产清理前固化到同一持久前缀，并回写 `script_json`。
- `sfx_audio_path`、`bgm_audio_path` 和 `mix_audio_path` 在整章 remix 中消费。
- 片段变更后用户应触发 `POST .../remix`；完成后整章音频、时长、字幕和时间线一起更新。

## 5. 架构与数据流

```text
剧本审核
  -> 打开章节工作台并定位片段
  -> 编辑 voice / sfx / bgm 语义提示
       -> 可选 direction-assist（LLM，失败回退规则）
       -> 可选 direction-audio/analyze（用户朗读录音，qwen-omni 音频理解，含文本一致性校验）
       -> 可选 AudioPicker（登记素材 asset_id）
  -> 更新前端片段草稿
  -> 统一编译 effective segment
       -> delivery_plan
       -> provider_prompt_snapshot
       -> effective / synthesis fingerprint
  -> 生成临时候选 + HMAC candidate_id + registry contract
  -> 受控候选试听
  -> apply 校验 base/effective/synthesis/content 指纹
  -> 固化 voice / sfx / bgm / mix 资产并更新 script_json
       -> audio_from_scripts 按 render 签名复用人声
       -> chapter remix 使用最新完整 mix 或分轨资产
  -> 删除章节产物时统一回收
```

关键模块：

| 职责 | 当前实现 |
|---|---|
| 提示弹窗 | `frontend/src/pages/audiobook/SegmentCueEditorDialog.tsx` |
| 工作台集成 | `frontend/src/pages/audiobook/ScriptEditorDialog.tsx` |
| 候选前端状态 | `frontend/src/pages/audiobook/useAudiobookSegmentReviewActions.ts` |
| API 客户端 | `frontend/src/services/api.ts` |
| 提示整理与 ASR 路由 | `backend/app/api/v1/audiobook_api/routes_segment_direction.py` |
| 提示语义服务 | `backend/app/services/audiobook/segment_direction_service.py` |
| 普通单段试听 | `backend/app/api/v1/audiobook_api/routes_segment_preview.py` |
| 候选生成与 apply | `backend/app/api/v1/audiobook_api/routes_segment_regen.py` |
| 统一编译合同 | `backend/app/services/audiobook/segment_synthesis_contract.py` |
| 候选凭证与登记 | `backend/app/services/audiobook/segment_candidate_token.py`、`backend/app/services/audiobook/segment_candidate_registry.py` |
| 片段持久资产与签名 | `backend/app/services/audiobook/chapter_segment_assets.py` |
| 工作台资产注入管线 | `backend/app/services/audiobook/background_jobs_shared.py` |
| 整章重混 | `backend/app/services/audiobook/background_jobs_remix.py` |
| 删除清理 | `backend/app/api/v1/audiobook_api/routes_delete.py` |

## 6. 数据分层与术语

### 6.1 用户语义字段

用户、编辑器或受控 LLM 可以表达的持久意图，例如：

- `text`、`type`、`speaker`、`emotion`
- `performance_notes`
- `instruct_emotion`、`instruct_scene`、`instruct_role`、`instruct_identity`
- `pause_before`、`pause_after`
- 用户明确选择的 `voice_params.speaker`、`voice_params.tts_model`
- 用户可编辑的 `volume`；固定音色片段禁止 `pitch`、`pitch_ratio`、`pitch_semitones`
- 语速的权威语义是 `performance_notes` 以及由其整理出的 `intent.pace` / `delivery_plan.pace`。支持指令控制的模型禁止持久化或透传片段级 `rate`、`speed`、`character_base_speed`；只有明确列入 basic 数值降级清单的 MiniMax Speech 2.8 HD/Turbo 可以显示数值语速兼容控件
- `sound_effects_simple` / `sound_effects`
- `music_cue_simple` / `music_cue`

### 6.2 Effective segment

`effective segment` 是“服务端当前持久片段 + 已清洗客户端草稿覆盖”的结果。候选音频必须以它为唯一语义输入；候选登记中保存其不可变深拷贝。

### 6.3 服务端派生字段

以下字段由当前语义和模型能力在合成前重新计算，不是用户事实：

- `delivery_plan`
- `provider_prompt_snapshot`
- `provider_prompt`
- `resolved_tts_model`
- `use_instruct_mode`
- `audio_tags`、`inline_tags`、`style_tags`
- `context_texts`、`instructions`、`messages`、`text_prefix`
- `timeline_pause_after_ms`、`cadence_profile`、`cadence_reason`

这些字段可以在详情面板中只读展示和诊断，但不得被客户端或 LLM 当作新的持久输入回写。`backend/app/services/audiobook/segment_synthesis_contract.py` 会删除旧派生值后重新编译。

### 6.4 服务端资产字段

以下字段只能由服务端写入：

- `audio_path`
- `sfx_audio_path`
- `bgm_audio_path`
- `mix_audio_path`
- `audio_cache_key`
- `audio_chunk_cache_paths`
- `audio_render_chunk_max_chars`
- `audio_render_mode`（当前工作台人声固化值为 `whole_segment`）

剧本保存路由按服务端维护的稳定 `segment_key` 找回原片段后保留这些字段，并拒绝客户端路径覆盖；旧剧本缺少 key 时只按可唯一确认的语义指纹迁移，无法确认则清除资产。候选覆盖清洗同样移除客户端提供的资产字段。`audio_render_mode` 不是用户可编辑语义，只有服务端在整段音频固化时写入；人声语义变化时必须连同音频路径和签名一起清除。

### 6.5 Candidate、persistent asset 与 stale

- **Candidate**：供试听、可过期、尚未成为章节事实的临时音频。
- **Persistent asset**：apply 或管线固化后位于 `chapter_segments_persistent_*` 命名空间的片段资产。
- **Stale**：最新片段事实晚于整章产物，或持久人声签名与当前渲染输入明确不匹配。

`stale` 是服务端可推导状态，不应只依赖某个前端会话内的布尔值。前端可立即显示 apply 返回的 `true`，重新加载时必须以服务端返回为准。

## 7. 人声提示的语义合同

### 7.1 标准示例

用户输入：

```text
语速缓慢，语气沉重压抑，重读'痛'字，句尾逐渐减弱并拖长，营造痛苦氛围。
```

推荐的供应商中立意图：

```json
{
  "pace": "slow",
  "stress_words": ["痛"],
  "ending_style": "lengthened",
  "emotion_primary": "sad",
  "intensity": "medium"
}
```

当前实现中，`intent` 主要用于展示、能力判断和后续编译提示；稳定持久事实仍是用户原始 `performance_notes`。受控 LLM 还可以只在用户未填写时建议 `instruct_*`、停顿或有限的音量参数。LLM 不得输出 `rate`、`speed` 或 `character_base_speed`；语速只能通过 `intent.pace` 和原始表演描述传递。例如：

```json
{
  "performance_notes": "语速缓慢，语气沉重压抑，重读'痛'字，句尾逐渐减弱并拖长，营造痛苦氛围。",
  "instruct_emotion": "sad",
  "voice_params": {
    "volume": 47
  }
}
```

### 7.2 两组必须明确区分的概念

**句尾拖长不等于 `pause_after`。**

- `ending_style="lengthened"` 表示最后一个音节或词的发声时长倾向。
- `pause_after=0.5` 表示片段说完之后，在时间线上留 0.5 秒静音。
- 二者可以同时存在，但不能互相代替。
- 当前 `backend/app/services/audiobook/tts_delivery_plan.py` 已分别提取 `stress_words` 和 `ending_style`；逐词或尾音控制不受模型支持时降级为自然语言指导。

**压低语气不等于降低音高或改变音色。**

- `pitch="lower"`、数值 `pitch=0.9` 以及任何半音偏移都不得进入固定音色片段请求。
- “低沉、苍老、空灵、磁性、童声、男声、女声”等属于声音身份或音色质感，应通过选音解决，不能由片段提示改变。
- 用户描述“压低语气”时，系统应编译为语势、强弱、节奏和情绪控制，不得偷偷转换成 pitch。
- 只有原文或用户明确给出感冒、生病、受伤、重伤、失血、缺水、哭喊后等临时状态时，才允许规范化为“因相应状态，仅在原音色基础上轻微、短暂表现沙哑”。
- 画像冲突检测接入后，若用户要求的常驻质感与所选音色明显冲突，应提示换音色，而不是静默修改基础声音。

### 7.3 模型能力降级

模型能力由 `get_audiobook_tts_style_capabilities()` 解析。输出至少包括：

- `model_family`
- `style_control_modes`
- `supports_audio_tags`
- `supports_word_level_control`

降级规则：

- 支持逐词控制：按供应商合同传递重音、尾音或标签。
- 不支持逐词控制：保留 `performance_notes`，在自然语言提示中表达“重读‘痛’字”和“句尾拖长”，同时展示不能保证精确落点的警告。
- 支持 `audio_tags`：由服务端映射受控标签。
- 只支持自然语言：使用 `style_instruction` / `director_guidance`。
- 支持自然语言、导演模式、上下文、音频标签或 voice design 等指令控制的模型：在构建 `delivery_plan` 之前删除旧 `speed/rate/character_base_speed`，`pace` 只能由当前 `performance_notes`、`instruct_*` 或已重新编译的语义计划得出。
- MiniMax Speech 2.8 HD/Turbo：作为当前唯一 basic 数值降级模型，将最终 `delivery_plan.pace` 确定性映射为 `slow=0.9`、`medium=1.0`、`fast=1.1`；不得再与历史 `speed/rate` 相乘。
- 未识别模型不得因为“不属于已知指令模型”而自动获得数值语速编辑能力；前端和后端都必须按显式 basic 清单判断。
- 模型整理失败：返回规则解析结果，用户仍可直接应用原始描述。

### 7.4 与音色画像的关系

音色画像和片段表演提示是两个层次：画像描述“这个音色通常是什么听感”，提示描述“这一句希望怎样演”。实现时应复用 `docs/AUDIOBOOK_VOICE_PROFILE_AND_CHARACTER_MATCHING_GUIDE.md` 的受控 taxonomy，不在工作台临时创造同义标签。

- 画像可用于选择器筛选、模型能力展示和质感冲突警告。
- `texture_target=["deep", "husky"]` 只能用于推荐其他音色或显示冲突，不能进入当前固定音色的片段提示；未绑定临时状态的 `husky` 必须从运行时表演要求中移除。
- 画像与提示冲突时，默认保留用户选择并显示可解释警告；系统不得静默换音色。
- 当前工作台尚未接入完整的画像冲突评分和自动替换，后续应在服务端完成，不应由前端关键词硬编码。

## 8. LLM 可写字段与合并规则

### 8.1 当前白名单

| 提示类型 | 当前可写语义字段 | 规则 |
|---|---|---|
| `voice` | `performance_notes` | 永远保留用户原文，不接受 LLM 改写覆盖 |
| `voice` | `instruct_emotion/scene/role/identity` | 仅在当前片段没有用户值时采用 |
| `voice` | `pause_before/pause_after` | 仅接受 `0..10` 的有限数值，且不覆盖已有值 |
| `voice` | `voice_params.volume` | 只允许有限数值范围，不覆盖已有用户值；`rate/speed/character_base_speed` 和所有 pitch 字段拒绝写入 |
| `sfx` | `sound_effects[].name/layer/volume/timing/position_3d/duration/fade_in/fade_out/delay` | 最多 8 项，枚举和数值均做边界校验；无有效结构化结果时回退 `sound_effects_simple` |
| `bgm` | `music_cue.style/mood/volume/fade_in/fade_out/duration/start_time/emotion_follow` | 只补缺失的受控语义；无有效结构化结果时回退 `music_cue_simple` |

`SegmentDirectionAssistRequest` 使用 `extra="forbid"`，`description` 去空白后长度限制为 1 到 1000 个字符。

### 8.2 禁止 LLM 写入

至少包括：

- `speaker`、`voice_id`、`tts_model`
- `asset_id`、`file`、`audio_file`
- 四类 `*_audio_path`
- `audio_cache_key`、`audio_chunk_cache_paths`
- `delivery_plan`、`provider_prompt_snapshot`、`resolved_tts_model`
- 供应商请求正文、鉴权参数、缓存键和运行 ID

音色、模型和素材可以由用户通过受控选择器明确选择，但不能由 LLM 编造。

### 8.3 用户值优先级

合并顺序固定为：

```text
用户已明确填写的值
  > 用户本次自然语言描述
  > 受控 LLM 对缺失语义字段的建议
  > 确定性规则回退
  > 系统默认值
```

LLM 返回无法解析、超出枚举、超出数值范围或包含禁止字段时，丢弃相应值；不能让整次编辑失败。服务端编译运行时产物时，必须从最新语义重新生成，不能复用 LLM 或客户端提供的旧快照。

### 8.4 当前结构化智能补全合同

用户期望“详情中未输入的其他内容由大模型判断填充”已经按受控白名单落地。服务端不接受完整详情 JSON，而是分别规范化 `voice/sfx/bgm` 的有限语义 schema；模型失败、输出无法解析、字段越界或包含禁写字段时，只丢弃不合规建议并回退用户原始描述。

当前可建议的音效字段：

```json
{
  "name": "水滴声",
  "layer": "bottom",
  "volume": 0.1,
  "timing": "continuous",
  "position_3d": "center",
  "duration": 5,
  "fade_in": 1,
  "fade_out": 0,
  "delay": 0
}
```

当前可建议的配乐字段：

```json
{
  "style": "低沉弦乐",
  "volume": 0.2,
  "fade_in": 2,
  "fade_out": 2,
  "duration": null,
  "start_time": 0,
  "emotion_follow": true
}
```

其中 `asset_id` 不属于 LLM 输出合同，只有用户从素材库选择或受控检索层返回真实登记资产时才写入。既有素材身份和用户已填写的数值/时序参数优先保留；`speaker`、`tts_model`、原文和角色身份必须继承现有上下文，不由模型创造。后续若扩展字段，必须提升 schema/taxonomy 版本并补兼容测试，不能直接放开模型输出任意详情字段。

### 8.5 详情面板字段归属

用户示例中的“详细信息”可能同时包含持久语义、编辑记录和运行快照，不能把整段 JSON 当成一个可写对象：

| 详情字段 | 权威来源 | 当前写入规则 |
|---|---|---|
| `performance_notes` | 用户原始描述 | 保留原文 |
| `original_text` | 剧本原文 | 只读，LLM 不得改写 |
| `adaptation_reason` | 编辑/编剧记录 | 当前不由提示整理自动生成 |
| `pause_before/after` | 用户或受控缺失字段建议 | 有范围校验，不能把 `ending_style` 偷换成 `pause_after` |
| `instruct_emotion/scene/role/identity` | 用户或缺失字段建议 | 用户已有值优先 |
| `voice_params.volume` | 用户或有限建议 | 数值范围校验；支持指令控制的模型不展示或写入数值语速，所有固定音色不展示或写入 pitch |
| `delivery_plan` | 服务端编译 | 每次合成前重建 |
| `provider_prompt_snapshot` | 服务端编译 | 只读诊断快照 |
| `speaker/tts_model` | 项目配置或用户选择 | LLM 不得覆写 |
| `sound_effects` / `music_cue` | 用户素材选择或受控 LLM 补全 | 语义参数可由白名单补全；`asset_id` 必须来自登记素材 |

这样可以让详情面板展示完整信息，同时保持“可编辑事实”和“运行时产物”的边界。

建议详情面板按两层展示，而不是把所有字段混成一个可编辑表单：

```json
{
  "semantic": {
    "performance_notes": "语速缓慢，语气沉重压抑，重读'痛'字，句尾逐渐减弱并拖长，营造痛苦氛围。",
    "original_text": "痛。像是有人用烧红的铁钎，生生凿穿了肩胛骨，将滚烫的铅水灌入骨髓。",
    "adaptation_reason": "开篇用短句和停顿突出痛苦，音效和配乐奠定压抑基调。",
    "pause_before": 0.3,
    "pause_after": 0.5,
    "instruct_emotion": "neutral",
    "instruct_scene": "水牢囚禁场景",
    "instruct_role": "有声书旁白",
    "instruct_identity": "故事讲述者"
  },
  "compiled": {
    "delivery_plan": "server-generated",
    "provider_prompt_snapshot": "server-generated",
    "timeline_pause_after_ms": 500,
    "cadence_profile": "explicit",
    "timeline_boundary_managed": true
  }
}
```

上例中的 `compiled` 只是诊断占位，真实返回由当前模型能力和服务端编译合同决定。详情面板可以显示类似 `delivery_plan.model`、`provider_prompt.mode`、`warnings` 等信息，但保存动作只能提交 `semantic` 层的允许字段。

## 9. 录音与 ASR 能力边界

### 9.1 当前实现：口述要求转写

人声提示弹窗中的麦克风按钮用于用户直接说出要求，例如：

```text
这段读慢一点，痛字加重，最后一句拖长。
```

链路为：

```text
浏览器 MediaRecorder
  -> 最长 30 秒自动停止
  -> multipart 上传
  -> PromptAudioAsrProvider 转写
  -> 返回 transcript
  -> 追加到描述文本框
  -> 用户校对
  -> 智能整理或直接应用
```

接口固定返回：

```json
{
  "analysis_scope": "spoken_instruction_transcription",
  "transcript": "痛字重读，语速慢一点",
  "supports_timestamps": true,
  "warnings": ["ASR 仅转写口述要求，不分析或克隆用户音色。"]
}
```

后端单次上传上限为 10MB，只接受音频内容类型或 `application/octet-stream`。临时文件在成功或失败后均立即删除。

### 9.2 当前不能承诺的能力

| 用户录音内容 | 当前能力 | 说明 |
|---|---|---|
| 用户口述“请慢一点、重读痛字” | 支持 | ASR 转文字，再进入提示整理 |
| 用户示范朗读原文，识别说了哪些字 | ASR 可做基础转写 | 当前入口没有做原文对齐或一致性评分 |
| 从示范朗读提取语速、断句、停顿、重音 | 尚未实现 | 需要时间戳对齐、韵律特征提取和单独验收 |
| 判断声音“苍老、沙哑、空灵、浑厚” | ASR 不支持 | 需要声学分析或音频理解模型 |
| 复刻用户的声音身份 | 不支持 | 属于声音克隆及授权合规流程，不是提示 ASR |

即使 ASR provider 支持时间戳，`supports_timestamps=true` 也不代表系统已经完成韵律分析。

### 9.3 与真人配音候选的区别

工作台还有一个独立的 `regeneration-candidate/upload-voice` 接口，用于把用户真人配音直接作为人声候选：

- 它不做 ASR，也不把录音转成提示词。
- 当前后端文件上限为 100MB。
- apply 后录音本身成为 `audio_path`。
- 它和“口述要求转写”是两个不同的按钮、数据目的和隐私语义，UI 文案不得混淆。

### 9.4 后续示范朗读方案

后续如要实现“我这样读一遍，系统模仿表达方式”，建议分层：

1. ASR 做原文对齐和字/句时间戳。
2. 韵律分析提取语速曲线、停顿位置、重音候选、句尾走势和能量变化。
3. 音频理解模型只输出受控音色标签候选，并带置信度。
4. 将可执行韵律映射到目标 TTS 模型能力；不支持的部分降级为自然语言。
5. 用户确认最终提示，不自动改变角色基础音色或启用声音克隆。

模型选择和音色画像边界参见 `AUDIOBOOK_VOICE_PROFILE_AND_CHARACTER_MATCHING_GUIDE.md`。

## 10. 提示弹窗前端状态机

虽然当前组件使用多个布尔状态实现，行为上应满足以下状态机：

```text
closed
  -> editing
editing
  -> recording -> transcribing -> editing
  -> assisting -> assisted
  -> applying -> closed
recording/transcribing/assisting
  -> error -> editing
任意打开状态
  -> closing -> 释放 MediaStream、停止播放器、清理临时 UI 状态
```

交互约束：

- `description` 最大 1000 字；人声必须有描述，音效/配乐可在描述为空时只选择一个已登记素材并提交。
- 录音中不能重复开始录音；转写或智能整理中禁用冲突操作。
- 关闭弹窗、切换到非人声提示或组件卸载时必须停止 `MediaRecorder` 和 `MediaStream`；迟到的 `onstop` 事件不得继续上传已取消录音。
- 每次打开、关闭、切换章节/片段或提示类型都推进 `transcriptionSessionRef`；ASR 响应、错误和 `finally` 只有在会话 ID 仍匹配时才能更新 UI，避免旧请求污染新弹窗。
- 智能整理失败时，人声原始描述仍可直接应用。
- 外部片段对象刷新不得覆盖用户正在输入的描述。
- 音效选择保留已有结构化音效、兼容旧 simple 值，并按 `asset_id` 去重；重选同一素材执行更新。
- 配乐选择写入单一 `music_cue`，并清理 `music_cue_simple`；纯描述则反向写 simple。
- `AudioPicker`、片段候选和整章音频通过 `frontend/src/pages/audiobook/useAudiobookAudioPlayback.ts` 仲裁，同一页面只播放一个受控 `Audio` 实例。

## 11. API 合同

所有项目/章节接口均需通过 `get_owned_audiobook_project` 或等价依赖校验用户归属，并验证章节属于源项目。

### 11.1 剧本读取与保存

```text
GET /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/script
PUT /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/script
```

保存只持久化语义剧本和可选状态；服务端按稳定 `segment_key` 保留已有资产字段。仅补 key 或修改审核状态不属于音频语义变化，不得推进产物时间戳并误报 stale；响应返回服务端派生的 `chapter_audio_stale`。

### 11.2 普通单段试听

```text
POST /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/segments/preview
```

请求：

```json
{
  "segment": {"text": "痛。", "voice_params": {"speaker": "voice-001"}},
  "tts_model": "seed-tts-2.0-expressive",
  "preview_type": "voice"
}
```

`preview_type` 支持 `voice/sfx/bgm/mix`。普通试听不落库，但必须先走统一编译合同。

### 11.3 提示整理

```text
POST /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/segments/{segment_index}/direction-assist
```

请求：

```json
{
  "cue_type": "voice",
  "description": "语速缓慢，语气沉重压抑，重读'痛'字，句尾逐渐减弱并拖长，营造痛苦氛围。",
  "segment": {
    "text": "痛。像是有人用烧红的铁钎，生生凿穿了肩胛骨。",
    "instruct_scene": "水牢囚禁场景"
  },
  "tts_model": "seed-tts-2.0-expressive"
}
```

前端发送前必须移除四类音频路径；服务端只把受控上下文字段交给 LLM，并对白名单输出再次过滤。

### 11.4 用户朗读录音分析

```text
POST /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/segments/{segment_index}/direction-audio/analyze
Content-Type: multipart/form-data
```

表单字段：`file`（用户朗读片段台词的录音），可选 `tts_model`。

服务端用片段台词作为期望文本交给 qwen3.5-omni 音频理解：朗读内容不一致时返回 400；
一致时返回 `source="omni_reading"` 的语义补丁（intent/patch 白名单与 direction-assist 相同），
由合成编译阶段按目标 TTS 模型的 `style_control_modes` 适配为具体指令形式。

### 11.5 候选生成与真人配音

```text
POST /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/segments/{segment_index}/regeneration-candidate
POST /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/segments/{segment_index}/regeneration-candidate/upload-voice
```

候选生成请求可包含：

```json
{
  "reason": "人声候选重新生成",
  "tts_model": "seed-tts-2.0-expressive",
  "segment": {"text": "痛。", "performance_notes": "语速缓慢……"},
  "preview_type": "voice",
  "voice_id": "zh_male_yuanboxiaoshu_uranus_bigtts",
  "emotion": "sad"
}
```

`sfx/bgm` 候选以静音底轨生成，不应强制要求 TTS 音色。真人配音上传允许没有音色 ID。

### 11.6 候选试听和 apply

```text
GET  /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/segments/{segment_index}/regeneration-candidate/audio?candidate_id=...
POST /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/segments/{segment_index}/regeneration-candidate/apply
```

新客户端 apply 只发送：

```json
{
  "candidate_id": "server-signed-token",
  "reason": "应用人声候选版本",
  "preview_type": "voice"
}
```

后端 schema 暂时保留已弃用的 `segment` 兼容字段，但服务端忽略它；前端类型已删除该字段。不得恢复“apply 时再次上传片段 B”的旧行为。

读取已保存片段时，候选音频接口也支持 `audio_path + preview_type`，但服务端必须验证该引用等于 `script_json` 中对应字段，不能作为通用文件读取接口。

候选试听不是“拿到未过期 token 就一定可读”。GET 接口在签名和 TTL 校验后，还必须通过 `segment_candidate` registry 查找当前仍为 `resumable=true` 的登记，并确认 `asset_ref`、片段索引、章节和 `preview_type` 完全一致。候选被同轨新候选顶替、apply 完成或章节删除后，即使 token 尚未到期，也必须拒绝试听并返回候选已失效；前端应刷新候选状态而不是继续重试旧 URL。

### 11.7 整章重混

```text
POST /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/remix
GET  /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/remix-status
```

请求：

```json
{
  "force": false,
  "output_format": "mp3",
  "generate_subtitle": true
}
```

存在缺失时，`force=false` 返回 `requires_confirmation=true` 和缺失列表；用户确认 `force=true` 后跳过缺失片段。

### 11.8 删除章节有声书产物

```text
DELETE /api/v1/audiobook/projects/{audiobook_project_id}/chapters/{chapter_id}/output
```

该接口语义是删除本章节全部有声书产出，保留小说原始章节内容。它先取消本章节的 `full`、`script_only`、`audio_from_scripts`、`chapter_remix` 和活跃 `segment_candidate` run，再执行物理资产清理；请求中的 `delete_files` 只为兼容旧客户端保留。

首次生成期间可能尚未创建 `ChapterAudio`。此时只要成功取消了运行中的产出型 run，接口也返回成功，不得因查询不到 `ChapterAudio` 而返回 404。响应包含 `cancelled_generation_runs`、`cancelled_remix_runs`、`cancelled_candidate_runs` 和 `deleted_candidate_files`，供 UI 与审计展示。

## 12. 统一合成编译合同

`backend/app/services/audiobook/segment_synthesis_contract.py` 是工作台试听和候选生成的服务端权威编译层，当前 `CONTRACT_VERSION = 1`。

编译顺序固定为：

1. 深拷贝片段，移除旧服务端派生 voice params。
2. 合并经过清洗的客户端语义覆盖。
3. 解析 `preview_type`。
4. 用 `resolve_segment_tts_model()` 解析片段模型，页面模型只作回退。
5. 使用显式 `voice_params.speaker`；缺失时按普通试听相同的顺序读取项目音色映射，最后才使用模型默认策略，避免“试听音色 A、候选音色 B”。
6. 若最终音色为 `mimo_design:*`，以该 `voice_id` 为权威资产引用，按当前用户从服务端资产库重新加载固定设计配方；客户端或旧剧本中的 `mimo_voice_asset_id`、`voice_design_prompt` 不可信。
7. 解析情绪、片段类型、角色、场景、身份和表演描述。
8. `build_delivery_plan()` 生成供应商中立交付计划。
9. `build_model_style_control()` 适配模型控制模式。
10. `build_provider_prompt_snapshot()` 生成只读诊断快照。
11. 计算 effective segment fingerprint、synthesis fingerprint；固定 MiMo 设计资产额外生成包含资产 ID 与配方 SHA-1 的 `voice_identity_binding`。

伪代码：

```python
compiled = compile_segment_synthesis_input(
    effective_segment,
    tts_model=resolved_model,
    voice_id=resolved_voice_id,
    emotion=resolved_emotion,
    preview_type=preview_type,
)
audio = await preview_service.generate_preview(
    compiled["segment"],
    preview_type=preview_type,
)
```

`SegmentPreviewService` 收到完整编译合同后应原样使用其中的 `delivery_plan`、`provider_prompt_snapshot`、speaker 和 model；只有没有合同的旧调用才走 VoiceManager 回退。普通试听与候选试听必须覆盖相同的回归用例。

主章节管线仍有自己的 TTS batch 准备过程，但必须复用同一 `build_delivery_plan`、模型解析和 provider prompt 规则。禁止工作台和管线各自维护不一致的关键词转换逻辑。

### 12.1 固定音色跨入口防旁路合同

选定 `voice_id` 后，所有入口都只能传递表演方式，不得用片段级参数重塑说话人身份。允许的控制包括情绪、语气、语速、音量、强弱、语势、停顿、断句、重读、呼吸和句尾处理；其中语速必须优先表达为表演语义，而不是供应商倍率。固定音色请求必须删除 `pitch`、`pitch_ratio`、`pitch_semitones`、`character_base_pitch`、动态 `voice_description` 和片段级 `voice_design_prompt`。

对 Qwen、CosyVoice、MiMo、StepAudio、Seed-TTS 等支持指令控制的模型，自动管线、工作台普通试听、候选生成/apply、Agent 调度、通用 TTS 试听、Asset Studio 和最底层 `TTSEngine` 都必须调用同一模型感知策略，删除 `speed`、`rate`、`character_base_speed`。`build_delivery_plan()` 只能从当前表演描述或重建后的语义字段得出 `pace`，不得从旧数值反推后再叠加一次。这样，同一说话人相邻片段只有在表演提示确实改变节奏时才会改变语速。

无明确临时状态依据的“沙哑”应从运行时表演要求中移除。只有感冒、生病、受伤、重伤、失血、缺水、哭喊后等明确状态，才允许规范为“因相应状态，仅在原音色基础上轻微、短暂表现沙哑”。该例外仍不得改变性别、年龄感、基础声线或声纹身份。

| 边界 | 强制行为 | 回归保护 |
|------|----------|----------|
| 前端剧本与工作台语义序列化 | `sanitizeScriptSegmentVoiceIdentityControls()` 必须覆盖章节加载/保存、提示 patch、录音分析、候选生成响应、候选应用和真人录音回写，递归清除身份覆盖字段；对非 MiniMax basic 模型还要清除并隐藏历史 `speed/rate/character_base_speed`。服务端仍需再次净化，不能信任客户端 | `scriptSegmentCardUtils.test.ts`、`scriptEditorUtils.test.ts`、`segmentCueEditorSource.test.ts`、`segmentReviewActionsSource.test.ts` |
| MiMo 固定设计资产解析 | 最终 `voice_id=mimo_design:*` 是权威资产引用；preview、legacy regenerate、候选生成、混音和 Agent 调度必须携带所有者上下文并从服务端资产库重载配方。客户端 `mimo_voice_asset_id` 不得覆盖最终 `voice_id`，资产缺失或越权必须失败，不得回退内联配方 | `test_audiobook_segment_regen_routes.py`、`test_audiobook_segment_regenerate.py`、`test_mimo_voice_assets.py` |
| 根目录 DashScope adapter | `adapters/dashscope/tts.py` 不得直接构造 MiniMax、Qwen 或 CosyVoice 供应商请求，必须委托 `synthesize_speech_sync -> TTSEngine`，保证 Agent/ExecutionEngine 等非页面入口也经过统一固定音色策略 | `test_audiobook_agent_dispatch_provider_boundary.py` 及供应商 payload 回归 |
| 模型感知语速控制 | 指令模型的前端详情不展示数值语速；管线、preview、候选合同、Agent、通用试听和底层引擎均删除 `speed/rate/character_base_speed`。只有 MiniMax HD/Turbo basic 模式按 `delivery_plan.pace` 固定映射为 `0.9/1.0/1.1` | `test_audiobook_voice_parameter_stability.py`、`test_audiobook_delivery_plan.py`、`ttsModels.test.ts`、`audioLibraryBrowserSource.test.ts` |
| Asset Studio 固定音色语音合成 | 前端不展示音调控件且不提交 `pitch`；只有 MiniMax HD/Turbo 显示并提交数值 `rate`。后端可继续接收旧 `pitch/rate` 表单字段以兼容旧客户端，但指令模型必须删除数值语速，元数据写 `pace_control=semantic` 且不回显无效 `rate`；MiniMax 元数据只记录实际应用值 | `assetStudioSeedAudioSource.test.ts`、`test_asset_studio_fixed_voice_contract.py` |

供应商协议字段不等于用户可控参数。CosyVoice 的 `rate=1.0`、Seed-TTS 的 `speech_rate=0` 是避免二次变速的协议中性值，StepAudio 指令链路不发送 `speed`；这些值不能由片段或客户端覆盖。MiniMax 的 `voice_setting.pitch=0` 同样是协议要求的中性常量，只能由 provider adapter 固定写入。显式创建全新 MiMo Voice Design 资产时允许设计提示和创建态音高参数，但仍必须删除 `speed/rate/character_base_speed`，不同旧倍率不得产生不同试听或引擎缓存键；一旦保存并作为固定资产引用，逐句链路不得再改写设计提示。

固定 MiMo 设计音色的候选登记必须保存 `voice_identity_binding`，至少包含服务端资产 ID 和权威 `voice_design_prompt` 的 SHA-1。该绑定用于审计和 checkpoint 一致性校验，不能由客户端构造；策略版本变化时，旧候选必须失效并重新生成。当前 `VOICE_IDENTITY_POLICY_VERSION=10` 已使可能含旧数值语速的音频缓存、试听缓存、候选合同和 checkpoint 自动失效，无需物理删除用户数据。

## 13. 候选凭证、登记与 apply 一致性

### 13.1 Token 绑定内容

`backend/app/services/audiobook/segment_candidate_token.py` 使用 HMAC-SHA256 签发 `candidate_id`，默认 TTL 为 24 小时。token 绑定：

- `chapter_audio_id`
- `chapter_id`
- `segment_index`
- 候选存储 `run_id`
- 音频内容 SHA-1
- 扩展名
- `preview_type`
- base segment fingerprint
- effective segment fingerprint
- synthesis fingerprint
- 过期时间

生产环境必须设置独立 `AUDIOBOOK_CANDIDATE_SECRET` 或安全的 `JWT_SECRET`，不得依赖代码中的开发回退密钥。

候选 `run_id` 不是共享的 `..._{chapter_audio_id}`。当前实现追加每次请求独立的 UUID nonce，例如 `segment_regen_candidate_voice_37_<nonce>`。两个标签页同时生成同片段同轨候选时，写文件阶段互不覆盖；哪个候选成为 registry 当前有效版本，由后续登记顶替规则决定。

### 13.2 Registry 合同

候选登记为：

```text
ChapterAudioRun.run_type = "segment_candidate"
status = "completed"
current_stage = "candidate_ready"
resumable = true
```

`checkpoint_json.candidate_contract` 保存：

- `base_segment_fingerprint`
- 不可变 `effective_segment`
- `effective_segment_fingerprint`
- `synthesis_fingerprint`
- `preview_type`

读取时返回深拷贝，调用方修改不能污染登记值。

### 13.3 A/B/C 错绑防护

定义：

- A：候选签发时数据库中的原片段。
- B：A 加上本次客户端草稿覆盖，经清洗和编译后的 effective segment。
- C：用户点击 apply 时数据库中的当前片段。

apply 必须：

1. 验证 token 签名、TTL、章节音频归属和片段索引。
2. 验证 token 中的 `preview_type` 和三类指纹完整。
3. 要求 `fingerprint(C) == fingerprint(A)`；否则返回 `409`。
4. 从 registry 读取 B，不读取客户端 `request.segment`。
5. 验证 registry 合同和 token 中的 effective/synthesis fingerprint 完全一致。
6. 重建受控候选 asset ref，读取字节并校验内容 SHA-1。
7. 固化音频，只替换目标轨道，并写入 B。
8. 提交数据库后回收候选文件并结束登记 run。

这保证了音频和语义绑定，但文件存储与数据库不是同一个事务。若在“持久化文件成功、数据库提交前”进程崩溃，仍可能产生未引用文件；正常替换会在提交后按旧引用清单回收，章节删除按已登记显式清单回收，本地前缀和维护任务作额外兜底。不能在文档中宣称跨数据库与对象存储的严格原子事务已经实现。

### 13.4 候选生命周期

- 同一候选 apply 后立即回收临时文件。
- 候选过期后由 janitor 按登记清单回收。
- 新候选顶替旧候选时立即回收旧文件；内容相同则只转移登记所有权。
- 用户在前端“取消”只移除本地引用，不需要单独 discard API。
- 删除章节产物时先按候选 run 的 checkpoint 显式清单回收，再结束登记；本地前缀清理只作额外兜底，不能作为 OSS 的唯一删除手段。

当前 registry 已按 `(chapter, segment_index, preview_type)` 顶替：`candidate_preview_type` 优先读取，旧登记缺失该字段时从 candidate contract 回退，再缺失则按 `voice` 兼容。回归测试必须持续保证片段的人声、音效、配乐和 mix 候选可以同时等待用户选择，只有同轨新候选会回收旧候选。

因此，候选 token 的“未过期”与候选的“当前有效”是两个独立条件：前者由 HMAC payload 的 `exp` 判断，后者由 registry 的 active 登记判断。任何只校验 token 而跳过 registry 的读取路径都属于安全回归。

旧版本候选如果缺少 base/effective/synthesis fingerprint、不可变 `effective_segment` 或 `preview_type`，试听和 apply 都按安全失败处理，要求重新生成候选；不得通过猜测补齐旧合同。

## 14. 持久片段资产合同

### 14.1 字段与权威语义

| `preview_type` | `script_json` 字段 | 含义 |
|---|---|---|
| `voice` | `audio_path` | 纯人声或真人配音底轨 |
| `sfx` | `sfx_audio_path` | 已渲染的片段音效 stem |
| `bgm` | `bgm_audio_path` | 已渲染的片段配乐 stem |
| `mix` | `mix_audio_path` | 已融合人声、音效、配乐的完整片段 |

统一命名空间：

```text
chapter_segments_persistent_voice
chapter_segments_persistent_sfx
chapter_segments_persistent_bgm
chapter_segments_persistent_mix
chapter_segments_persistent_chunks
```

逻辑片段索引仍用于 API 和时间线，但物理覆盖槽不能直接使用可变数组索引：

- 有 `segment_key` 时，`resolve_segment_asset_storage_index()` 以 key 的 SHA-1 前缀派生稳定高位整数槽；同一个片段重排后仍覆盖自己的旧版本。
- 历史片段没有 key 时才回退当前 `segment_index`。
- 多 chunk 使用“稳定片段槽 × 固定步长 + chunk 序号”，与完整 voice 资产保持同一身份边界。
- 保存成功并提交数据库后，目标轨旧引用、失效 mix 和旧 chunk 引用只有在不再被任何片段引用时才按显式清单回收。

因此，合同是同一 `(chapter_audio_id, preview_type, stable segment identity)` 保存新版本时清理自己的旧文件，而不是“同一数组位置”自动清理。

### 14.2 轨道替换规则

- apply `voice`：替换 `audio_path`，更新人声签名，保留 sfx/bgm，清除旧 mix。
- apply `sfx`：替换 `sfx_audio_path`，保留 voice/bgm，清除旧 mix。
- apply `bgm`：替换 `bgm_audio_path`，保留 voice/sfx，清除旧 mix。
- apply `mix`：替换 `mix_audio_path`，保留其他分轨作为后续重新编辑的来源。

所有 apply 返回 `chapter_audio_stale=true`。这表示整章产物需要重新混音，不表示候选保存失败。

### 14.3 工作台与管线同源

管线生成的片段在 run 临时资产清理前调用 `persist_generated_chapter_segment_audio()` 固化。工作台 apply 和管线固化最终都写入相同的持久存储机制与 `script_json` 字段，因此删除、分段试听和 remix 不需要区分资产来源。

## 15. 缓存签名与管线复用

### 15.1 Render 签名

`backend/app/services/audiobook/render_plan.py` 的 `RENDER_PLAN_VERSION = 1`。render chunk `cache_key` 至少覆盖：

- 文本
- 角色 speaker
- 情绪
- 影响合成的 voice params
- 片段类型
- `performance_notes`

`delivery_plan`、`provider_prompt_snapshot`、`resolved_tts_model` 等可重复编译的运行时快照不直接参与签名，避免派生 JSON 结构变化造成无意义缓存失效。它们所代表的语义必须通过稳定字段进入签名。

### 15.2 三态签名

- `current`：保存签名可按生成时分块上下文复现，且与当前片段一致。
- `stale`：有明确生成上下文，重算后不一致。
- `unverifiable`：历史数据没有足够上下文，无法安全断言过期。

remix 对 `stale` 严格报缺失；对旧 `unverifiable` 数据不误报。`repair_legacy_segment_signatures()` 会对满足条件的旧持久资产惰性补写可复现分块上下文。

历史上 `RENDER_PLAN_VERSION = 1` 保持不变，但 render 签名投影曾增加“将顶层持久语义同步到 `voice_params`”的步骤。该变化会让旧管线生成、文件仍存在且可试听的片段被新版重算误判为 `stale_audio`。当前兼容合同如下：

1. 先按当前语义同步投影和生成时记录的 `audio_render_chunk_max_chars` 验签。
2. 当前签名不匹配时，再按冻结的“语义同步前 v1 投影”精确重算；只有保存签名完全命中时才视为有效历史资产。
3. 接受旧投影前，顶层 `instruct_scene/instruct_role/instruct_identity` 必须与历史 `voice_params` 副本一致。用户只修改顶层导演语义时不得被旧投影兼容掩盖。
4. 精确命中的旧投影由 `repair_legacy_segment_signatures()` 惰性改写为当前签名，并清理失效的 chunk key 映射；文本、音色、情绪或导演提示真实变化后，新旧投影都不匹配，仍判定为 `stale`。
5. 后续任何签名输入投影变化必须增加明确的签名方案版本或迁移路径，不能只修改哈希输入而继续复用同一版本语义。

### 15.3 注入 resume checkpoint 的条件

`merge_workbench_segment_audio_into_checkpoint()` 只复用同时满足以下条件的人声音频：

1. `audio_path` 属于持久前缀且文件存在。
2. `audio_cache_key` 等于当前 render plan 的 chunk 签名或组合签名。
3. render chunk 只归属一个源片段，未和相邻片段合并。
4. 单 chunk 直接注入完整片段音频。
5. 多 chunk 管线资产必须存在按每个 chunk 签名索引的 `audio_chunk_cache_paths`，且全部文件存在。

工作台候选通常由一次请求合成完整片段，不会伪造逐 chunk 文件。人声候选 apply/legacy regenerate 固化时会由服务端写入受保护字段：

```json
{
  "audio_render_mode": "whole_segment",
  "audio_cache_key": "<按整段文本计算的 cache key>",
  "audio_render_chunk_max_chars": 360
}
```

`build_render_plan()` 看到该标记时对该片段禁用文本拆分，生成一个完整 render chunk；因此长片段也能以保存的整段音频进入 `audio_from_scripts` resume checkpoint。标记不能由客户端或 LLM 写入；剧本语义（文本、音色、模型、情绪、表演提示等）发生变化时，保存清洗逻辑同时清除 `audio_render_mode`、`audio_path`、签名和 chunk 映射，避免旧整段音频被复用。普通管线生成的多 chunk 片段仍使用逐 chunk 映射，不应把整段字节冒充某个子 chunk。

### 15.4 必须补充的语义签名审计

保存剧本时可能保留旧 `voice_params` 诊断快照。管线复用判断必须基于当前顶层语义重新规范化，不能让旧 `voice_params.instruct_scene/role/identity` 掩盖用户刚保存的新值。至少应增加以下回归：

- 只修改 `instruct_scene` 后旧人声不得复用。
- 只修改 `instruct_role` 或 `instruct_identity` 后旧人声不得复用。
- 只修改模型控制相关语义后签名必须变化。
- 只变化 `delivery_plan/provider_prompt_snapshot` 的序列化形式时签名不得变化。
- 带明确分块上下文的语义同步前 v1 签名必须可兼容并惰性迁移。
- 旧签名兼容后修改正文、音色或顶层 `instruct_scene/role/identity` 仍必须判定为 `stale`。
- 部分片段为当前签名、其余片段为可验证旧签名时，remix 缺失列表必须为空且不得在 force 模式跳过有效音频。

### 15.5 片段重排、拆分与资产归属

剧本保存不能把服务端资产单纯按新旧数组位置盲目复制。当前保存清洗逻辑采用以下合同：

1. 每个片段由服务端维护稳定 `segment_key`，该字段只表示资产归属，不参与 TTS/混音语义签名。
2. 客户端回传的已知 key 优先按 key 找回原片段；未知、重复、包含空白/路径字符或超过长度限制的 key 不继承任何旧资产。
3. 历史剧本没有 key 时，先按类型、文本、角色/说话人、原文组成的唯一语义指纹迁移并补 key。
4. 无法唯一确认归属的重复片段不按索引猜测，直接清除旧资产；只有不含身份字段的旧客户端局部 patch 才按原位置兼容。
5. 匹配成功后仍执行逐轨失效：人声语义变化清除 voice/cache/chunk/render mode，音效变化只清除 sfx，配乐变化只清除 bgm，任意相关语义变化都清除旧 mix。
6. 持久文件写入使用由 `segment_key` 派生的稳定存储槽，而不是保存时的数组索引；否则 A/B 重排后重新生成 A 会按新索引误删仍被 B 引用的旧文件。
7. `segment_key` 只决定资产归属，不参与合成签名；仅补 key、迁移 key 或修改审核状态不得推进 `ChapterAudio.updated_at` 并误报整章 stale。

拆分、合并或新增片段会得到新的 key；被删除片段不再出现在 `script_json`，其未引用物理文件由同轨覆盖、显式旧引用回收、章节产物删除和维护任务兜底。回归必须覆盖：带 key 重排、旧数据无 key 重排、前置插入、删除中间片段、重复语义歧义、重排后重新生成 A 不删除 B 的旧文件、只改音效 cue、只改配乐 cue；旧资产不得绑定到新文本或被 remix 优先采用。

## 16. 整章 stale 与重新混音

### 16.1 stale 来源

`backend/app/api/v1/audiobook_api/routes_script.py` 在读取和保存剧本时按以下事实派生：

1. 任一持久人声音频的签名明确为 `stale`；或
2. `ChapterAudio.updated_at` 晚于最近一次 `chapter_remix/audio_from_scripts/full` 完成时间。

候选 apply 还会即时返回 `chapter_audio_stale=true`，让当前会话无需等待重载即可提示用户。

### 16.2 片段音源优先级

整章 remix 对每个片段使用：

```text
有效 mix_audio_path
  > audio_path 作为底轨 + sfx_audio_path + bgm_audio_path
  > 缺失
```

有效 mix 是完整片段，不能再次叠加 stem。没有有效 mix 时，音效和配乐 stem 从片段起点叠加。临时候选路径不进入 remix。

### 16.3 缺失检查

缺失原因包括：

- `invalid_segment`
- `no_audio_path`
- `expired_temporary_audio`
- `file_missing`
- `stale_audio`

如果某个已登记的 mix、sfx 或 bgm 文件丢失，系统应把具体 `asset_type` 返回给用户；不能因为旧 checkpoint 仍有对应 cue 就静默回退。`force=true` 允许跳过缺失内容，但 `stale_audio` 的旧人声不能混入结果。

### 16.4 旧 checkpoint 的过滤与时间线重锚定

工作台持久 stem/mix 已覆盖某片段时，旧 checkpoint 中该片段的音效或配乐 cue 必须过滤，防止重复叠加。片段归属按以下字段识别：

- `segment_index`
- `source_segment_index`
- `source_index`
- `scene_N`、`climax_N`、`shift_N`
- `editor_timeline_key`，如 `sfx-3-*` 或 `music-3-*`

当片段时长变化：

- 能识别片段索引的 cue 使用“新片段起点 + 原片段内相对偏移”重锚定，保留 cue 自身 duration。
- 无法识别归属的历史 cue 才按整章新旧总时长比例缩放 timestamp/duration。

重混完成后原子写出整章音频，更新时长、文件大小、字幕和 checkpoint；输出路径变化时回收旧整章音频及字幕。

## 17. 删除与恢复语义

### 17.1 章节产物删除

`DELETE /projects/{audiobook_project_id}/chapters/{chapter_id}/output` 清理：

- ChapterAudio 整章音频
- SRT/VTT/ASS/labels 等字幕产物
- `audio_path`、`sfx_audio_path`、`bgm_audio_path`、`mix_audio_path` 指向的持久片段
- `audio_chunk_cache_paths` 中登记的多 chunk 资产
- voice/sfx/bgm/mix 与 chunk 的本地持久前缀残留
- 已登记 voice/sfx/bgm/mix 和真人录音候选的 checkpoint 资产
- 本章节的 `full`、`script_only`、`audio_from_scripts`、`chapter_remix` 与活跃 `segment_candidate` run

数据库记录执行软删除并写审计，但物理资产无条件删除。因此从回收站恢复数据库记录不等于恢复已经物理清理的音频，UI 必须避免承诺可恢复音频文件。

OSS 驱动不能依赖“列前缀后删除”。章节脚本和候选 run 必须先收集显式 ref/checkpoint 清单，再调用统一删除；前缀删除仅是本地文件系统的兜底。候选取消统计和删除文件数写入响应与审计。

### 17.2 其他删除入口

| 入口 | 物理片段清理条件 |
|---|---|
| `DELETE /chapter-audios/{chapter_audio_id}` | 仅 `delete_files=true` 时清理 |
| `DELETE /projects/{audiobook_project_id}` | 仅 `delete_files=true` 时清理全部章节片段与导出文件 |
| `DELETE .../chapters/{chapter_id}/output` | 无条件清理，`delete_files` 只作兼容 |

产品中的“删除本章节产物”必须调用第三个接口，避免走只软删除记录的旧路径。

### 17.3 并发删除

删除接口先写不可恢复 run 墓碑，再处理 `ChapterAudio`。即使首次 `full` 尚未创建 `ChapterAudio`，只要取消了运行中的产出型 run 就返回成功。

`script_only`、`full`、`audio_from_scripts` 和 remix 在关键写入前后都必须以项目、章节、可选 `ChapterAudio` 和精确 `run_id` 复核活动性。持久片段写入后才观察到删除时，只回收本次新增的 `new_refs - old_refs`，不能误删工作台先前保存的资产。后台进度更新和 job tracker 发现 `chapter_output_deleted` 墓碑后必须停止，不能把 run 重新激活。

Seed Scene 在 `output_path=None` 时会在本次 run 目录内生成整章 staging 文件。引擎读取字节后立即验证路径仍位于 run root 并删除该 staging 文件；显式 `output_path` 和场景级可恢复 checkpoint 不受影响。

## 18. 兼容与降级策略

### 18.1 Legacy `/regenerate`

```text
POST /projects/{audiobook_project_id}/chapters/{chapter_id}/segments/{segment_index}/regenerate
```

后端保留该直接覆盖端点用于旧客户端兼容，当前前端不再调用。它仍需走统一编译、清除旧 mix 并返回 stale。不得在新 UI 中重新引入。

### 18.2 Apply 兼容字段

后端 apply schema 暂留 `segment`，标记 deprecated 并完全忽略；待旧客户端淘汰后再按 API 版本移除。兼容不意味着继续信任旧字段。

### 18.3 候选取消

当前不新增 discard 端点：前端取消、同轨新候选顶替、apply 回收、24 小时 TTL janitor 和章节删除已经覆盖生命周期。新增端点只有在监控证明候选存储压力或合规要求不能接受 TTL 时再考虑。

### 18.4 旧素材描述

- 旧 `sound_effects_simple` 可在选择新素材时迁移为结构化 `sound_effects`。
- 选择音效后保留已有结构化项，按 `asset_id` 去重。
- 选择配乐后以 `music_cue` 为权威并清空 simple；纯文本输入则反向处理。
- 无真实 `asset_id` 的描述只能做匹配或生成意图，不能声称已绑定某个素材。

### 18.5 模型与轨道降级

- `sfx/bgm` 候选不依赖 TTS speaker。
- `voice/mix` 缺少显式音色时按项目映射或模型规则回退；CosyVoice 特定模式仍可要求显式复刻/设计音色。
- 不支持逐词控制时使用自然语言提示并显示警告。
- LLM 不可用时使用确定性规则。
- ASR 未配置返回 503，用户仍可手工输入描述。
- 素材未找到时必须明确提示，不得把静音候选描述成成功素材。

### 18.6 旧候选合同

升级前生成、但缺少 `base_segment_fingerprint`、`effective_segment_fingerprint`、`synthesis_fingerprint`、不可变 `effective_segment` 或 `preview_type` 的候选不做宽松迁移。试听和 apply 返回候选合同失效，用户重新生成即可。该策略会牺牲旧临时候选的短期兼容性，但避免把无法证明语义归属的音频写入当前片段。

## 19. 安全、隐私与成本

### 19.1 归属与引用安全

- 所有工作台项目接口先验证有声书项目归属，再验证章节属于源项目。
- 候选读取只接受签名 token，或与当前 `script_json` 完全一致的持久 asset ref。
- 客户端脚本和候选覆盖不能写服务端资产字段。
- `candidate_id` 绑定章节音频 ID 和片段索引，禁止跨项目、跨章节、跨片段复用。
- 内容 SHA-1 用于候选字节一致性，HMAC 用于 token 防伪；SHA-1 在这里不是认证算法。

### 19.2 素材路径约束

工作台 preview/candidate 不应接受客户端提供的任意 `file` 或 `audio_file`。安全目标：

1. 优先只接受素材库登记的 `asset_id`。
2. 如兼容相对文件引用，`resolve()` 后必须 `relative_to(audio_library_dir)` 成功。
3. 拒绝绝对路径、`..` 穿越、UNC 路径和素材库外符号链接目标。
4. 文件扩展名和实际可解码格式需要受控。

当前 `SegmentPreviewService.resolve_effect_path()` 和配乐 `file_ref` 回退均已通过 `resolve_audio_library_file_path()` 约束在素材库根目录内；按 stem 回退也只在 `sound_effects` 或 `music_cache` 子目录中搜索。必须保留 Windows/POSIX 路径、目录穿越、UNC 路径和符号链接越界回归测试，避免后续兼容改动重新引入路径注入。

### 19.3 录音隐私

- 浏览器必须在用户主动点击后申请麦克风权限。
- 口述要求录音仅用于本次 ASR，后端临时文件在 `finally` 中删除。
- UI 明确说明录音可能发送到所选 ASR provider。
- 不把口述要求录音加入声音画像库、克隆资产或训练集。
- 真人配音候选是另一种持久目的，保存前需要明确用户动作。

### 19.4 限制与成本

| 项目 | 当前限制/成本控制 |
|---|---|
| 提示描述 | 1000 字 |
| 浏览器口述要求录音 | 最长 30 秒 |
| ASR 提示录音上传 | 10MB |
| 真人配音候选上传 | 100MB |
| 候选 TTL | 24 小时 |
| LLM | 单次最多约 700 输出 token、低温度、30 秒服务超时、失败回退规则 |
| TTS 候选 | 每次重新生成都可能计费，UI 应避免重复点击并显示进行中状态 |
| SFX/BGM | 复用素材库不产生 TTS 成本；未来生成式音效/配乐需单独预算 |

## 20. 测试与验收清单

### 20.1 后端定向测试

```powershell
Set-Location "C:/Users/cuigu/novel_writing_agent/backend"
$env:PYTHONPATH='C:/Users/cuigu/novel_writing_agent/backend;C:/Users/cuigu/novel_writing_agent'
& "../.venv/Scripts/python.exe" -m pytest -q `
  "tests/test_audiobook_segment_direction.py" `
  "tests/test_audiobook_segment_direction_routes.py" `
  "tests/test_audiobook_delivery_plan.py" `
  "tests/test_segment_preview_service.py" `
  "tests/test_audiobook_script_routes.py" `
  "tests/test_audiobook_segment_regen_routes.py" `
  "tests/test_audiobook_segment_regenerate.py" `
  "tests/test_audiobook_segment_candidate_registry.py" `
  "tests/test_audiobook_segment_signature_context.py" `
  "tests/test_audiobook_remix.py" `
  "tests/test_audiobook_chapter_segment_assets.py" `
  "tests/test_audiobook_delete_routes.py" `
  "tests/test_audiobook_background_jobs_audio.py" `
  "tests/test_audiobook_runtime_truth.py" `
  "tests/test_audiobook_job_tracker.py" `
  "tests/test_audiobook_seed_scene_engine_mixin.py" `
  "tests/test_audiobook_workbench_checkpoint_merge.py" `
  --basetemp=".pytest_tmp/workbench_full"
```

必须新增或确认以下回归：

- 示例描述解析出 slow/lower/`["痛"]`/lengthened/sad/deep+husky。
- “句尾拖长”不产生 `pause_after`。
- LLM 注入 speaker、model、asset、path、snapshot 被拒绝。
- 普通试听请求中的 `audio_path`、`mix_audio_path` 等服务端字段被清洗，旧 provider snapshot 由服务端重建。
- LLM 失败仍可直接保存用户原始描述。
- 普通试听与候选生成向 runtime 传入相同 speaker、model 和 prompt snapshot。
- 片段未显式绑定 speaker 时，普通试听和候选生成都优先命中项目 voice mapping，再回退模型默认音色。
- sfx/bgm 不要求 voice。
- 同片段不同 `preview_type` 候选互不回收；同轨新候选才顶替旧候选。
- 并发候选保存使用不同 UUID 命名空间，登记前不会互删物理文件。
- A/B/C 变化、过期 token、错误轨道和错误内容哈希均拒绝 apply。
- 缺少新版三指纹或不可变 effective segment 的旧候选要求重新生成。
- apply 不读取 deprecated `request.segment`。
- 非 mix 更新清除旧 mix，四轨都返回 stale。
- 带 key/无 key 的重排、前置插入和重复语义迁移符合保守规则；重排后重新生成 A 不删除 B 的历史索引资产。
- mix 优先、stem 叠加、旧 checkpoint cue 过滤和片段级重锚定。
- 素材库外绝对路径、`..`、UNC 和符号链接引用被拒绝。
- 删除章节 output 清理四轨、显式 chunk 清单和候选 checkpoint；没有 `ChapterAudio` 时也取消首次生成 run。
- full/script_only/audio_from_scripts/remix/candidate 均写不可恢复删除墓碑，后续 worker/job tracker 不能重新激活。
- 持久化后观察到删除时只回收 `new_refs - old_refs`；Seed Scene 内部整章 staging 文件在读入后删除。
- 只修改 scene/role/identity 后旧人声不能进入管线复用。
- 普通管线缺少逐 chunk 资产时不错误复用整段文件；工作台固化的 `audio_render_mode=whole_segment` 长片段能够按整段合同复用。

### 20.2 前端检查

```powershell
Set-Location "C:/Users/cuigu/novel_writing_agent/frontend"
& "C:/Program Files/nodejs/npm.cmd" run type-check
& "C:/Program Files/nodejs/npm.cmd" run lint
& "C:/Program Files/nodejs/npm.cmd" run test -- `
  "src/pages/audiobook/__tests__/segmentCueEditorSource.test.ts" `
  "src/pages/audiobook/__tests__/segmentReviewActionsSource.test.ts" `
  "src/pages/audiobook/__tests__/scriptSegmentCardUtils.test.ts" `
  "src/pages/audiobook/__tests__/segmentPreviewSource.test.ts" `
  "src/pages/audiobook/__tests__/scriptEditorInitialSegmentFocus.test.ts"
```

前端人工验收：

- 从审核选中第 N 段进入工作台后定位第 N 段。
- 三个提示面板可点击，折叠按钮不会误开弹窗。
- 录音 30 秒自动停止，拒绝麦克风权限时可继续手输。
- 关闭后迟到的 `MediaRecorder.onstop` 不上传；已发出的 ASR 迟到响应不写入重新打开的片段。
- 智能整理失败仍可应用原文。
- 外部刷新不清空弹窗中未提交内容。
- 音效多选保留旧项且不重复，配乐重选替换单一 cue。
- 素材、片段和整章播放器不会同时发声。
- 同一片段可分别保留并试听 voice/sfx/bgm/mix 候选。
- apply 后立即显示整章已过期；重载后状态与服务端一致。
- remix 缺失确认能显示片段索引、摘要、原因和轨道类型。
- 章节删除后 remix 状态 `cancelled` 与 `canceled` 均视为终态，前端停止轮询并清理本地任务状态。

### 20.3 端到端验收场景

1. 审核阶段选中片段，打开工作台。
2. 输入标准示例并智能整理，确认警告正确。
3. 生成人声候选 A，试听但不保存；原片段资产不变。
4. 重新生成候选 B，确认同轨 A 失效而其他轨候选仍有效。
5. 应用 B，确认 `audio_path` 持久化、旧 mix 清除、整章 stale。
6. 运行 `audio_from_scripts`，确认该片段 TTS 未再次调用，其他片段正常生成。
7. 保存音效和配乐候选，运行 remix，确认只使用最新轨且无 checkpoint 重复叠加。
8. 修改片段时长并重混，确认后续片段 cue 按新起点重锚定。
9. 删除章节产物，确认整章、字幕、四轨、chunk、候选均不存在。
10. 恢复软删除记录时，UI 不宣称已恢复被物理删除的音频。
11. 首次整章生成尚未创建 `ChapterAudio` 时删除产物，确认任务被取消且后续不重新写回文件或记录。
12. 交换 A/B 片段位置后重新生成 A，确认 B 的旧音频仍可试听，A 使用自己的稳定存储槽。
13. 加载含历史 `pitch`、`voice_description` 或片段级 `voice_design_prompt` 的剧本，确认前端编辑和保存请求会清除这些身份覆盖字段，服务端编译结果也不恢复它们。
14. 使用旧客户端向 Asset Studio 固定音色接口提交 `pitch`，确认请求仍可兼容处理，但供应商参数和结果元数据均不包含该值。
15. 通过 Agent/ExecutionEngine 调用根目录 DashScope TTS adapter，确认最终进入统一 `TTSEngine`，且固定音色供应商 payload 不包含片段级 pitch 或动态声音身份描述。
16. 在 Asset Studio 选择 Qwen/CosyVoice 时确认不显示也不提交 `rate`，结果元数据为 `pace_control=semantic` 且无 `rate`；选择 MiniMax HD/Turbo 时确认数值语速仍可用。
17. 对 MiMo Voice Design 创建试听分别提交 `speed=0.8` 与 `speed=1.2`，确认设计提示和创建态 pitch 保留，但路由参数、OSS 试听缓存与底层引擎缓存均忽略这两个旧倍率。
18. 加载含 `speed=1.1` 的 Seed/Qwen/CosyVoice/MiMo/StepAudio 历史片段，确认详情不再显示该倍率，保存请求也不再带回；MiniMax HD/Turbo 片段仍保留其数值降级字段。

### 20.4 当前基线验证结果

2026-08-05 对本指南涉及的定向范围执行结果：

- 后端工作台、提示整理、候选、签名、持久资产、管线复用、删除竞态、remix、Seed Scene 与路径安全：`309 passed`。
- 后端全部 `test_audiobook*.py`：`1098 passed, 4 skipped`。
- MiMo、StepAudio、MiniMax、voice types 与 Asset Studio 补充回归：`56 passed`。
- Agent、统一引擎和最终供应商边界专项回归：`227 passed`。
- 前端 TypeScript：`npm run type-check` 通过。
- 前端 ESLint：`npm run lint` 通过，零 warning。
- 前端 7 个工作台相关测试文件：`33 passed`。
- 前端完整测试：`163 files / 838 tests passed`。
- 签名投影兼容修复后，render plan、历史签名、持久资产、候选应用与 remix 扩展回归：`102 passed`。
- 2026-08-06 语速合同最终专项回归：定向后端 `325 passed`、定向前端 `46 passed`；全部 `test_audiobook*.py` 加 Asset Studio 合同为 `1118 passed, 4 skipped`，完整前端为 `163 files / 841 tests passed`，TypeScript 与 ESLint 通过。Seed WebSocket 的 11 条 `websockets` 弃用警告与本次改动无关。
- 有声书前端完整测试目录：`66 files / 339 tests passed`；类型检查与 lint 再次通过。
- 截图对应的本地 58 段只读复算结果：`58 current / 0 stale / 0 missing`；惰性迁移只改写旧投影的 27 个签名。
- Python `compileall` 通过；11 个曾受 Windows 路径长度影响的 Seed 用例改用短 `--basetemp` 后 `19/19` 通过。
- `git diff --check` 通过；仅有仓库既有 Windows CRLF 转换提示，无空白错误。

以上测试集合存在重叠，不能相加作为总用例数。该结果是当前工作区定向验收快照，不替代发布流水线中的全仓测试、真实供应商连通性验证和人工端到端试听。另有根目录旧兼容测试 `24 passed, 1 failed`；失败项仍期待旧 Qwen 音色映射 `Jennifer`，当前目录映射为 `Bellona`，与本轮固定音色身份策略无关，应单独更新该旧契约。

## 21. 分阶段上线建议

### 阶段 0：一致性与安全门槛

- 完成普通试听统一编译回归。
- 验证素材路径越界防护及其 Windows/POSIX 回归；相关解析已统一限制在素材库根目录。
- 验证同片段跨轨候选互不回收、同轨候选正确顶替。
- 验证审核选中片段定位及一次性初始索引消费。
- 审计 scene/role/identity 对 render 签名的影响。
- 跑完第 20 节完整回归。

### 阶段 1：基础工作台上线

- 上线三类弹窗、文字描述、素材库选择。
- 上线人声规则/LLM 整理与能力警告。
- 上线口述要求 ASR，明确不是示范朗读分析。
- 上线 candidate -> preview -> apply -> persistent asset。
- 上线 stale 提示、管线单 chunk 复用、整章 remix 和统一删除。

### 阶段 2：结构化智能补全

- 已为 voice/sfx/bgm 定义受控语义 schema，并对缺失字段做 LLM 补全，用户值优先。
- 已将素材检索与 LLM 描述分离，asset ID 只由受控素材库选择提供。
- 上线前继续建立结构化输出合规率、规则回退率和人工修正率指标。
- 建立模型级提示转换质量评测和费用指标。

### 阶段 3：示范朗读韵律

- 原文-ASR 对齐。
- 字句时间戳、停顿、重音、节奏和句尾走势提取。
- 按 TTS 能力映射，无法执行的控制给出显式降级。
- 不在此阶段自动做音色身份克隆。

### 阶段 4：音频理解与音色画像联动

- 评测音频理解/声学模型对 deep、husky、aged、airy 等受控标签的准确率和校准度。
- 接入音色画像冲突警告和更适合音色推荐。
- 保持年龄感、性别呈现等敏感标签的置信度、人工审核与隐私边界。

## 22. 已知限制与明确延期项

1. 当前 ASR 只转写口述要求，不分析示范朗读的韵律或音色。
2. `supports_timestamps` 只表示 provider 能力，不代表时间戳已经转成提示词。
3. “低沉、苍老、空灵”等常驻质感不会映射为片段 pitch；无明确临时状态的“沙哑”会被过滤，存在明确状态时只允许在原音色基础上轻微、短暂表现。
4. 选定音色画像与目标质感的自动冲突检测尚未接入。
5. 音效/配乐结构化补全只覆盖当前受控白名单；LLM 不可用或输出不合规时会降级为 simple 描述，且不会自动绑定素材 ID。
6. 工作台长片段使用 `audio_render_mode=whole_segment` 作为整段复用模式；若历史记录没有该标记且没有逐 chunk 映射，只能按 `unverifiable` 处理并要求重新生成。
7. 无片段索引的旧 checkpoint cue 只能使用整章比例缩放，精度低于片段级重锚定。
8. 文件存储与数据库提交不是分布式事务；正常失败按显式 ref/checkpoint 回收，但进程在“写文件后、登记或提交前”崩溃仍可能产生未登记孤儿，需要存储生命周期策略或维护扫描兜底。
9. Legacy `/regenerate` 和 apply 的 deprecated `segment` 字段仍在后端兼容面，需在客户端淘汰后版本化移除。
10. 不提供独立候选 discard API；当前依赖顶替、apply、TTL janitor 和章节删除回收。
11. 历史剧本没有 `segment_key` 时只能按唯一语义指纹迁移；完全相同且无法区分的重复片段会保守清除旧资产，避免错误绑定。
12. 升级前缺少新版指纹与 effective segment 合同的旧候选不能继续试听或 apply，必须重新生成。
13. `mimo_design:*` 当前保存的是 `voice_design_prompt` 配方，而不是供应商稳定 `voice_id` 或参考音频。系统会按当前用户从服务端资产库重载配方并将其哈希绑定到候选合同，能够阻止客户端逐句改写或跨资产错绑，但不能消除 Voice Design 模型自身随机性；若要求严格跨片段声纹一致，必须先把设计结果物化为参考音频，再创建 `mimo-voiceclone` 或其他稳定音色资产。

## 23. 完成定义

只有同时满足以下条件，才能认为本轮“单片段工作台改造及相关问题修复”完成：

- 用户从审核阶段进入工作台时能准确定位选中片段。
- voice/sfx/bgm 弹窗均可编辑，音效和配乐可从库中搜索、试听和选择。
- 标准人声描述能得到正确意图、能力警告和安全语义 patch。
- 固定 `voice_id` 的章节、工作台、Agent、Asset Studio、adapter 和最终 provider 请求均只传递表演方式，不允许片段级 pitch、动态声音描述或其他声音身份覆盖。
- ASR 的 UI、API 和文案都明确限定为口述要求转写。
- 关闭或切换弹窗后，取消录音不会上传，已发出 ASR 的迟到结果不会污染新片段。
- 普通试听、候选试听、候选保存使用同一模型、音色、提示合同和有效片段。
- 不存在 A/B/C 错绑、跨轨候选误回收或客户端路径注入。
- 并发候选使用独立物理命名空间，片段重排后持久资产仍按稳定 `segment_key` 归属且不会串删。
- 已保存的人声在签名匹配时进入管线复用，签名不匹配时必然重生成。
- 最新 voice/sfx/bgm/mix 按权威优先级进入整章 remix，旧 cue 不重复叠加。
- 片段更新后整章 stale 可在当前会话和重新加载后正确恢复。
- 删除章节产物能够取消所有产出型 run、阻止后台重新写活，并清理所有已登记工作台和管线资产。
- 后端、前端自动测试及第 20.3 节端到端场景全部通过。

这套完成定义优先保证资产一致性、可解释降级和可恢复操作边界。在此基础上，再扩展示范朗读韵律分析、音色质感识别和生成式音效/配乐，才能避免把模型演示能力误当成稳定的生产合同。
