# 有声小说 TTS 音频提示词优化指导文档

> 适用平台：耳畔星河（novel_writing_agent）
> 范围：章节→有声小说生成的完整链路，重点为「音频提示词生成策略」的差异化设计
> 关联代码：[backend/app/services/audiobook/](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/)
> 关联文档：[docs/AUDIOBOOK_TTS_MODEL_CAPABILITY_TODO.md](file:///c:/Users/cuigu/novel_writing_agent/docs/AUDIOBOOK_TTS_MODEL_CAPABILITY_TODO.md)

---

## 0. 文档目的与读者

本文档对「耳畔星河」平台生成有声小说的完整工作流进行系统性梳理与分析，识别各环节的效率瓶颈、质量隐患与可优化空间，并**重点给出针对不同 TTS 模型技术特性的差异化音频提示词设计方案**。

预期读者：

- 负责有声小说生成链路的后端工程师（实施优化）
- 负责音质评测与提示词调优的算法/内容工程师（制定模板）
- 技术负责人（评估优化优先级与路线图）

阅读建议：第 1-3 章为现状诊断，第 4-6 章为方案设计（核心），第 7 章为落地路线图，附录为速查表。

### 0.1 当前产品规则

本文档以当前产品决策为边界，后续实现必须遵守：

- 用户只在“旁白”和各角色上选择 `TTS 模型 + 音色`。
- 克隆音色、设计音色和音色资产只在统一音色管理窗口管理。
- 角色声音配置只保存 `tts_model` 与 `voice_id` 引用，不保存语速、音高、音量、风格等表演参数。
- 语速、音高、情绪、停顿、强度、风格指令均为运行时参数，由剧本文本、角色、场景、叙事语境和模型能力动态决定。
- 旁白是一个角色，但不再提供“旁白风格”配置；历史 `narration_style` 字段只作为兼容输入，不能继续覆盖新链路的运行时表演计划。
- 默认生成模式为“仅剧本和评审”；音频生成应在剧本审稿通过后，从已批准剧本进入 TTS、混音和音频编辑阶段。

---

## 1. 完整工作流梳理

### 1.1 端到端链路

当前主链路由 `AudiobookEngine` 编排，但产品上应以“两阶段生成”为主，而不是一次性从文本生成到最终音频。

```
阶段一：仅剧本和评审
API create_audiobook_project(generation_mode=script_only)
  → Celery 后台任务
  → AudiobookEngine.prepare_chapter_script()
    ├─ ① 制定改编策略
    ├─ ② 剧本改编，生成 ScriptSegment[]
    ├─ ③ 并行设计音效、配乐、音色引用
    ├─ ④ 剧本质量评审与必要自动修订
    ├─ ⑤ 为片段绑定角色/旁白的 tts_model + voice_id
    └─ ⑥ 构造 delivery_plan 与可审阅提示词快照

阶段二：基于已审稿剧本生成音频
API generate_audio_from_scripts()
  → 校验 script_status == approved
  → AudiobookEngine.generate_chapter_audio_from_script()
    ├─ ① 读取已批准 ScriptSegment[]
    ├─ ② TTS 前质量闸门
    ├─ ③ 运行时 delivery_plan 刷新
    ├─ ④ 按模型能力编译 provider prompt/payload
    ├─ ⑤ 分段 TTS 合成，支持断点复用
    ├─ ⑥ 时间线对齐、音效、配乐、混音
    └─ ⑦ 保存 ChapterAudio，进入试听、字幕和音频编辑工作台
```

### 1.2 阶段产物与数据契约

| 阶段 | 输入 | 产物 | 关键字段 |
|------|------|------|----------|
| 配置 | 角色/旁白 | 运行时音色引用 | `character_name`、`tts_model`、`voice_id` |
| 剧本 | 章节全文 + 角色档案 | `ScriptSegment[]` | `text`、`type`、`speaker`、`emotion`、`performance_notes`、`pause_before/after` |
| 审稿 | `ScriptSegment[]` | 已批准剧本 | `script_status=approved`、`script_json` |
| 上下文 | 剧本片段 + 角色/场景 | `delivery_context` | `segment_type`、`scene_type`、`sentence_profile`、`script_annotations` |
| 投递 | `delivery_context` + 模型能力 | `delivery_plan` | `emotion`、`pace`、`intensity`、`pause_profile`、`micro_tags`、`style_instruction` |
| 编译 | `delivery_plan` + 能力矩阵 | `TTSStyleControl` | `mode`、`messages`、`provider_fields`、`text_prefix`、`warnings` |
| 快照 | `TTSStyleControl` | `provider_prompt_snapshot` | 最终 instructions/messages/context_texts、预算、降级说明 |
| 合成 | provider payload | 音频片段 | `model`、`voice`、`input/text`、provider-specific fields |

### 1.3 提示词相关阶段定位

「音频提示词」在本系统里不是一个单一变量，而是**贯穿运行时上下文、表演计划、模型编译、provider payload 的链式产物**：

- `delivery_context` 汇总文本、旁白/对白、角色、场景、句子结构、剧本标注和章节叙事语境。
- `build_delivery_plan` 产出**语义化表演意图**，例如情绪、节奏、停顿、强度、微表演标签。
- `build_model_style_control` 把意图**按模型能力分流**为 provider 可消费的结构。
- `reconcile_voice_description_with_selected_voice` 用**已选音色硬约束**修正软性的声音描述，避免提示词和音色资产冲突。
- `provider_prompt_snapshot` 记录最终将发送给模型的提示词、标签、上下文和降级说明，供审阅、调试和质量回写使用。
- `_build_*_payload` 把风格控制注入最终 HTTP/WebSocket 请求。

因此提示词优化不是单点修改，而是这条链路的协同优化。本文档第 5 章给出各模型的差异化设计，第 6 章给出轻量策略层来收敛这条链路。

---

## 2. 效率瓶颈识别

| 环节 | 瓶颈 | 证据 | 影响 |
|------|------|------|------|
| ①② LLM 调用 | 章节分析与剧本转化串行执行，无流水线 | [_analysis.py::_analyze_chapter](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/script_adapter_pkg/_analysis.py) 与 [_transform.py::_transform_to_script](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/script_adapter_pkg/_transform.py) 顺序调用 | 在默认两阶段流程下影响降低，但会增加剧本生成等待时间 |
| ④⑤ 风格控制重复构建 | `build_model_style_control` 在投递计划阶段与合成阶段各调用一次 | [tts_style_control.py::build_model_style_control](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) 被 [_aliyun_mixin.py::_build_qwen_instruction_payload](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) 等再次触发 | 每段重复构建指令，CPU 与 LLM(optimize) 调用浪费 |
| ⑦ TTS 合成 | `max_concurrent=2`、`request_delay=0.5s` 硬编码，未按模型 RPS 差异化 | [_base.py#L174-L176](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_base.py) | 高 RPS 模型（如 MiniMax）被限速拖慢，低 RPS 模型无保护 |
| ⑥ 冲突检测覆盖窄 | `reconcile_voice_description_with_selected_voice` 的 `_VOICE_AGE_HINTS` 仅覆盖部分音色 | [voice_description_policy.py#L39](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/voice_description_policy.py) | 非 Qwen 音色选型后声音描述无法被有效修正 |
| ② 批次边界 | 850 字固定分批，未按句号/段落语义切分 | [_transform.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/script_adapter_pkg/_transform.py) | 跨批次的对白可能被截断，角色连续性受损 |
| 提示词可观测性 | 审阅阶段缺少最终 provider prompt 快照 | AUDIO_PROMPT_REVIEW 主要返回 `delivery_plan` 与统计指标 | 难以判断不同模型最终收到了什么，也难以做质量回写 |

---

## 3. 质量隐患识别

| 隐患 | 影响 | 证据 | 严重度 |
|------|------|------|--------|
| **章节分析只采样 6000 字** | 长章节中段情感转折丢失，下游提示词基调偏离 | [_analysis.py::_build_analysis_sample](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/script_adapter_pkg/_analysis.py) head/mid/tail 各 2000 字 | 高 |
| **投递计划靠关键词推断** | "留白""长停顿"等显式词之外的语义停顿无法识别 | [tts_delivery_plan.py::_infer_pause_profile](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_delivery_plan.py) 纯字符串匹配 | 高 |
| **`_build_common_parts` 不区分模型能力** | 对 basic 模型也拼自然语言指令，虽后续被丢弃但浪费构建 | [tts_style_control.py#L74](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) 通用 parts 构建无能力门控 | 中 |
| **旁白风格旧链路仍会影响运行时参数** | 新产品规则下不应再有旁白风格配置，但旧链路仍可能写入 `speed/pitch/instructions` | [narration_styles.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/narration_styles.py)、[_script_utils_mixin.py::_apply_narration_style_to_voice_params](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_script_utils_mixin.py) | 高 |
| **情感归一化逻辑分散** | CosyVoice 情绪映射硬编码在 TTS 引擎基类，与能力矩阵割裂 | [_base.py#COSYVOICE_V3_PLUS_INSTRUCT_EMOTIONS](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_base.py) | 高 |
| **MiniMax 高级风格控制需显式降级** | MiniMax HD/Turbo 走 `basic` 模式，复杂 `delivery_plan` 会被忽略或只能转为基础参数 | [tts_model_ids.py#L107-L116](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_model_ids.py) `preferred_style_control_mode: "basic"` | 中 |
| **StepAudio instruction 截断 200 字** | 复杂场景指导被截断后语义残缺 | [_aliyun_mixin.py#L33](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) `STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS = 200` | 高 |
| **StepAudio 单段输入 1000 字** | 长段落被迫截断，上下文丢失 | [_aliyun_mixin.py#L32](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) `STEPAUDIO_TTS_MAX_INPUT_CHARS = 1000` | 中 |
| **角色区分历史上依赖 pitch/rate 微调** | 同 speaker 多角色仅 ±8% pitch 调整，听感区分度弱；新链路应改为音色资产引用 + 运行时表演计划 | [voice_designer.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/agents/voice_designer.py) | 中 |
| **无提示词质量回写** | 生成结果无提示词有效性反馈，无法闭环优化模板 | 全链路无 `provider_prompt_snapshot → audio_quality` 关联记录 | 中 |

---

## 4. TTS 模型能力差异化分析（核心）

本章是提示词设计的依据。平台当前支持 9 个 TTS 模型，分属 6 个家族，能力矩阵定义于 [tts_model_ids.py::AUDIOBOOK_TTS_STYLE_CAPABILITIES](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_model_ids.py)。

### 4.1 模型总览

| 模型 | 家族 | `preferred_style_control_mode` | 情感表达 | 语速控制 | 停顿处理 | 角色区分 |
|------|------|-------------------------------|----------|----------|----------|----------|
| qwen3-tts-instruct-flash | qwen | `natural_language` | instructions 自然语言 | rate 参数 | 无显式 | 24 预置音色 + pitch/rate |
| cosyvoice-v3.5-plus | cosyvoice | `natural_language`（短 cue 优先） | 7 类枚举 emotion + 短 instruction | rate 参数 | **pause_before/after** | 复刻/设计音色 |
| minimax-speech-2.8-hd | minimax | `basic` | 基础参数降级 | rate 参数 | 无 | voice 音色 |
| minimax-speech-2.8-turbo | minimax | `basic` | 基础参数降级 | rate 参数 | 无 | voice 音色 |
| mimo-v2.5-tts | mimo | `director` | 导演模式 + 音频标签 + 复合情绪 | 韵律控制 | 微标签 | 预置音色 + 导演指导 |
| mimo-v2.5-tts-voicedesign | mimo | `voice_design` | 声音描述优先 | 韵律控制 | 微标签 | **文本设计音色** |
| mimo-v2.5-tts-voiceclone | mimo | `director` | 导演模式 + 音频标签 | 韵律控制 | 微标签 | **音频样本复刻资产** |
| stepaudio-2.5-tts | stepaudio | `global_context` | 全局语境 + 文中语境括号 | 韵律控制 | **圆括号 inline** | 预置音色 + Zero-shot |
| seed-tts-2.0-expressive | doubao | `query_response` | Query-Response + 语音标签 | 上下文指令 | 标签 | 预置音色 + 复刻 |

### 4.2 五个关键维度的模型对照

#### 4.2.1 情感表达

- **qwen**：靠 `parameters.instructions` 自然语言描述情绪，无枚举约束。
- **cosyvoice**：硬约束 7 类枚举（`COSYVOICE_V3_PLUS_INSTRUCT_EMOTIONS`），非枚举情绪会被归一化或丢弃。
- **minimax**：basic 模式下无显式情绪参数，应把 `delivery_plan` 降级为基础 `speed/pitch/volume` 小范围调整，并记录不支持高级风格控制的 warning。
- **mimo**：支持 `emotion_mix` 复合情绪（如 "悲喜交加"），表现力最强。
- **stepaudio**：全局 instruction 定基调 + 文中圆括号逐句控制（如 `(激动)`）。
- **doubao**：靠 `additions.context_texts` 的 Query-Response 对话式上下文传递情绪，配合 `use_tag_parser` 语音标签。

#### 4.2.2 语速控制

- **qwen/cosyvoice**：`rate` 数值参数（如 `+10%`），精度高但表现平直。
- **minimax**：`rate` 参数，必要时可小范围映射 `pace`，避免用固定角色配置保存语速。
- **mimo**：韵律控制（pace/prosody），可表达"渐快""骤停"等动态变化。
- **stepaudio/doubao**：靠 instruction/上下文描述节奏，无直接数值参数。

#### 4.2.3 停顿处理（差异最大）

| 模型 | 停顿手段 | 当前实现 | 缺口 |
|------|----------|----------|------|
| cosyvoice | `pause_before`/`pause_after` 参数 | 投递计划产出 `pause_profile` 但未落到参数 | G3 |
| stepaudio | 圆括号 inline `(停顿2秒)` | 未注入 | G3 |
| mimo | 微标签 | `delivery_plan_inline_tags` 部分覆盖 | 部分 |
| qwen/minimax/doubao | 标点 + instruction 描述 | 仅标点 | 仅基础 |

#### 4.2.4 角色区分

- **mimo-voicedesign**：可**用文本设计声线**（性别/年龄/音调/特点），应在音色管理窗口用于创建音色资产。
- **mimo-voiceclone / stepaudio / doubao**：支持音频样本复刻 / Zero-shot。
- **cosyvoice**：复刻或设计音色。
- **qwen**：仅 24 预置音色 + pitch/rate ±8% 微调，区分度弱。
- **minimax**：仅 voice 音色切换。

当前 [voice_designer.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/agents/voice_designer.py) 仍保留以 pitch/rate 微调角色差异的历史设计。后续应拆分“音色资产创建策略”和“运行时表演策略”：音色克隆/设计在音色管理窗口完成；逐句表演由 `delivery_plan` 和模型编译器决定。

#### 4.2.5 提示词注入位置

| 模型 | 注入字段 | 预算 |
|------|----------|------|
| qwen | `parameters.instructions` | 600 字（`optimize_instructions` 可压缩） |
| cosyvoice | `parameters.instruction` | 100 字 |
| mimo | `messages` 的 user/assistant 角色 | 无上限 |
| stepaudio | `parameters.instruction`（全局） + 文中圆括号 | **全局 200 字** |
| doubao | `additions.context_texts` + `use_tag_parser` | 无上限 |
| minimax | 无（basic） | — |

---

## 5. 差异化音频提示词设计方案（核心）

### 5.1 现有提示词策略的差距（G1–G7）

当前 [tts_style_control.py::build_model_style_control](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) 已实现按 `preferred_style_control_mode` 分流（natural_language/basic/director/voice_design/global_context/query_response），但存在 7 个差距：

| 编号 | 差距 | 现状 | 应有 |
|------|------|------|------|
| **G1** | 投递计划→提示词映射粗放 | `delivery_plan_instruction_parts` 对所有模型输出相同结构化片段 | 应按模型能力裁剪：basic 模型不输出、instruction 受限模型压缩、标签模型转标签 |
| **G2** | 情绪表达未按模型枚举归一 | CosyVoice 情绪归一化在引擎基类硬编码，其余模型无 | 应统一到能力矩阵 `supported_emotions` 字段，在风格控制层归一 |
| **G3** | 停顿策略未模型化 | `pause_profile` 仅记录 dramatic/natural/balanced，不落到模型可用手段 | cosyvoice→pause 参数；stepaudio→圆括号注入；其余→instruction 描述 |
| **G4** | 音色资产创建与逐句表演混在一起 | VoiceDesigner 仍可能用 pitch/rate 微调模拟角色差异 | 应拆分：音色管理窗口负责 clone/design 资产；生成链路只引用 `voice_id` 并动态生成表演参数 |
| **G5** | Micro tags 注入位置不分模型 | `_build_mimo_audio_tag_prefix` 与 `_build_doubao_voice_label_prefix` 各自实现 | 应抽象为 `inline_tag_strategy`，按模型决定 prefix/inline/suffix |
| **G6** | 旁白与角色提示词模板同构 | `_build_common_parts` 对旁白/对白用相同字段 | 旁白应弱化角色身份、强化叙事节奏；对白应强化角色关系与场景张力 |
| **G7** | 无质量回写 | 生成结果无提示词有效性反馈 | 应记录 per-model prompt→audio 质量评分，反哺模板 |

### 5.2 模型特性↔提示词结构对应关系

按下表为每个模型家族定义提示词结构。该表是策略层（第 6 章）的配置依据。

#### 5.2.1 qwen（natural_language, instruction_budget≈600）

```
结构化自然语言（按顺序拼接，分号分隔）：
  ① 角色身份：{speaker}（{role_relation}）
  ② 场景氛围：{scene}
  ③ 声音描述：{voice_description}
  ④ 情绪目标：{emotion}（归一到 {neutral,happy,sad,angry,fearful,surprised,disgusted}）
  ⑤ 朗读方式：{delivery_mode}
  ⑥ 节奏与停顿：{pace}；停顿{pause_profile}
  ⑦ 微表演：{micro_tags}
  ⑧ 演绎要求：{performance_notes}

注入：parameters.instructions
约束：≤600 字，启用 optimize_instructions 自动压缩
情绪归一：是
停顿落地：仅 instruction 描述
```

#### 5.2.2 cosyvoice（natural_language，但实际是短 cue 优先，instruction_budget≈100）

```
短指令（≤100 单位，保留最高优先级 4 项）：
  ① 情绪：emotion={emotion_enum}
  ② 停顿：pause={pause_hint}
  ③ 重读：重读={stress_words}
  ④ 动作：act={performance_notes 的短 cue}

注入：parameters.instruction + parameters.emotion(枚举) + parameters.pause_before/after
约束：emotion 必须是 7 类枚举之一；instruction ≤100 字
情绪归一：强（非枚举→最近邻映射）
停顿落地：pause_before/pause_after 参数（核心优势，必须启用）
```

说明：CosyVoice 的 `instruction` 不应承载完整旁白模板、长声音画像或大段导演词。声音描述应该在上游用于音色选择、冲突修正和 `voice_description` 融合；真正进入 `instruction` 的是可以落地的短 cue，尤其是情绪、停顿、重读和动作收尾。

#### 5.2.3 minimax（basic）

```
无自然语言指令。仅靠：
  ① voice 音色 ID 切换
  ② speed/rate、pitch、volume 等基础参数的小范围映射
  ③ 标点和原剧本文本

注入：无 instruction 字段
情绪归一：不适用
停顿落地：仅标点
表现力补偿：将 emotion/pace/intensity 降级为基础参数，并在 `provider_prompt_snapshot.warnings` 中说明被忽略的高级字段
```

#### 5.2.4 mimo-director（role=user, 无上限）

```
导演 prompt（结构化多行）：
  角色：{speaker}，有声书角色
  场景：{scene}
  指导：
    - 声音：{voice_description}
    - 情绪：{emotion}（可复合 emotion_mix）
    - 朗读方式：{delivery_mode}
    - 节奏：{pace}；停顿{pause_profile}
    - 微表演：{micro_tags}
    - 演绎要求：{performance_notes}

注入：messages[0].role=user, content=导演 prompt
约束：无字数上限，可充分展开
情绪归一：否（支持复合）
停顿落地：微标签
```

#### 5.2.5 mimo-audio-tags（role=assistant）

```
文本前缀：（风格标签，情绪标签）[微标签1][微标签2]
正文：{text}

注入：assistant 消息 = 前缀 + 正文
约束：标签来自 delivery_plan_style_tags / delivery_plan_inline_tags
情绪归一：否
停顿落地：微标签
```

#### 5.2.6 mimo-voicedesign（音色资产创建，非逐句表演）

```
音色管理窗口中的声音设计 prompt：
  声音描述：性别/年龄/音调/语速/情绪/特点/用途
  {voice_description} 展开

注入：messages[0].role=user, content=voice design prompt，用于创建或预览音色资产
约束：声音描述必须完整覆盖 7 维度
情绪归一：否
停顿落地：不在音色设计阶段处理
角色区分：通过生成 `voice_id` 资产完成；正式章节合成只引用该资产，不把逐句剧情表演写入 voice design prompt
```

#### 5.2.7 stepaudio（global_context + inline, instruction≤200）

```
全局 instruction（≤200 字，智能压缩保留 4 要素）：
  ① 场景基调：{scene}
  ② 情绪基调：{emotion}
  ③ 节奏：{pace}
  ④ 角色关系：{role_relation}

文中 inline（在关键句前注入圆括号）：
  (情绪) (停顿2秒) 句子正文

注入：parameters.instruction(全局) + 文本内圆括号
约束：全局 ≤200 字；单段输入 ≤1000 字（需分段）
情绪归一：否
停顿落地：圆括号 inline（核心优势，必须启用，G3 核心落地点）
分段策略：按句号/段落切分，每段 ≤1000 字，跨段保留全局 instruction
```

#### 5.2.8 doubao（query_response, context_texts）

```
context_texts（Query-Response 对话式）：
  Q: 角色{speaker}在{scene}中，情绪{emotion}，要求{performance_notes}
  A: {text}

语音标签前缀（use_tag_parser）：
  [情绪，风格] 正文

注入：additions.context_texts + use_tag_parser=true
约束：无字数上限
情绪归一：否
停顿落地：标签
```

### 5.3 模板设计原则

1. **能力门控**：所有 parts 构建前先查能力矩阵，basic 模型不构建自然语言 parts（解决 G1）。
2. **预算感知压缩**：instruction 受限模型（cosyvoice 100 字 / stepaudio 200 字）按优先级保留要素（解决 G1）。
3. **情绪统一归一入口**：在风格控制层调用 `normalize_emotion(emotion, model)`，能力矩阵声明 `supported_emotions`（解决 G2）。
4. **停顿策略显式落地**：投递计划产出 `pause_profile` 后，由 `pause_renderer(model, pause_profile)` 转为模型可用手段（解决 G3）。
5. **音色资产与表演参数分离**：Voice Design / Voice Clone 只创建或引用音色资产；逐句表现由 `delivery_plan` 决定（解决 G4）。
6. **标签注入位置统一抽象**：`inline_tag_strategy(model)` 决定 prefix/inline/suffix（解决 G5）。
7. **旁白/对白模板分流**：`segment_type` 进入模板选择（解决 G6）。
8. **提示词快照可观测**：每段生成 `provider_prompt_snapshot`，记录最终提示词、预算、降级和丢弃字段。

---

## 6. 提示词策略层设计

### 6.1 设计目标

将 [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) 中分散的模型分支整理为轻量策略层，收敛运行时上下文、表演计划、模型能力裁剪、provider prompt 快照四个环节。策略层优先采用纯函数和小数据结构，避免一次性引入过重规则引擎。

### 6.2 模块定位

建议新增模块 `tts_prompt_strategy.py`，位于 `delivery_plan` 与 `build_model_style_control` 之间：

```
build_delivery_context
        ↓ delivery_context
build_delivery_plan
        ↓ delivery_plan
tts_prompt_strategy.resolve_prompt_strategy(model, segment_type)
        ↓ PromptStrategy / strategy functions
build_model_style_control
        ↓ TTSStyleControl
build_provider_prompt_snapshot
        ↓ provider_prompt_snapshot
_build_*_payload
```

### 6.3 核心抽象

```python
# 伪代码示意，非实际文件；落地时遵循 backend-dev-guidelines
from dataclasses import dataclass
from typing import Callable

@dataclass(frozen=True)
class PromptStrategy:
    """单个模型+段落类型的提示词装配策略。"""
    family: str
    mode: str
    instruction_budget: int | None
    inject_position: str
    emotion_normalizer: Callable[[str], str]            # G2 情绪归一
    instruction_compactor: Callable[[list[str], int | None], str]  # G1 预算压缩
    pause_renderer: Callable[[dict], PauseResult]       # G3 停顿落地
    tag_renderer: Callable[[dict], TagResult]           # G5 标签注入
    template: "PromptTemplate"                          # G6 旁白/角色模板


def resolve_prompt_strategy(model: str, segment_type: str) -> PromptStrategy:
    """根据模型能力矩阵 + 段落类型解析策略组合"""
    capabilities = get_audiobook_tts_style_capabilities(model)
    family = capabilities["model_family"]
    mode = capabilities["preferred_style_control_mode"]
    # 按 family + mode + segment_type 选择策略组合
    # 见 6.4 策略矩阵
    ...
```

### 6.4 策略矩阵

| family / mode | emotion_normalizer | instruction_compactor | pause_renderer | tag_renderer | template | inject_position |
|---------------|--------------------|-----------------------|----------------|--------------|----------|-----------------|
| qwen / natural_language | 归一到 7 类 | ≤600 优先级压缩 | instruction 描述 | 不用 | 旁白/对白分流 | field(instructions) |
| cosyvoice / natural_language | 强归一到枚举 | ≤100 保留 3 项 | **pause 参数** | 不用 | 旁白/对白分流 | field(instruction) |
| minimax / basic | 不归一 | 不压缩 | 标点 | 不改写正文 | 通用 | 无 |
| mimo / director | 不归一(支持复合) | 不压缩 | 微标签 | style_tags | 旁白/对白分流 | messages.user |
| mimo / voice_design(asset_creation) | 不归一 | 不压缩 | 不适用 | 不适用 | 声音设计模板 | 音色管理窗口 messages.user |
| mimo / director + clone_audio | 不归一 | 不压缩 | 微标签 | style_tags | 旁白/对白分流 | messages.user + audio.voice |
| stepaudio / global_context | 不归一 | **≤200 智能压缩** | **圆括号 inline** | inline_tags | 旁白/对白分流 | field(instruction)+inline |
| doubao / query_response | 不归一 | 不压缩 | 标签 | voice_label | 旁白/对白分流 | additions.context_texts |

### 6.5 与现有代码的衔接

- `build_delivery_context`：新增或内联实现，提取 `scene_type`、`sentence_profile`、`script_annotations`、`chapter_narrative_style`，不回写角色配置。
- `build_model_style_control`：先 `resolve_prompt_strategy`，再用策略函数装配 `TTSStyleControl`。短期保留现有 if-else，逐步把共性逻辑迁移到策略函数。
- `delivery_plan_instruction_parts`：改造为可按策略裁剪，instruction 受限模型按优先级组装，避免简单截断。
- `_build_*_payload`：优先消费预编译的 `TTSStyleControl` 或 `provider_prompt_snapshot`，减少重复 `build_model_style_control` 调用。
- `voice_description_policy.reconcile_voice_description_with_selected_voice`：继续作为音色硬约束修正层，但不要把逐句剧情表演混入音色设计资产。
- `narration_styles.py`：作为 legacy 兼容链路收口，不再扩展旁白风格模型支持矩阵。

### 6.6 provider_prompt_snapshot 契约

`provider_prompt_snapshot` 用于审阅、调试、质量回写，不直接作为角色配置保存。

```json
{
  "model": "mimo-v2.5-tts",
  "voice_id": "mimo_clone:asset_id",
  "mode": "mimo_director",
  "delivery_plan": {
    "emotion": "tense",
    "pace": "slightly_fast",
    "pause_profile": "dramatic",
    "intensity": "medium_high"
  },
  "provider_prompt": {
    "instructions": "语气压低，节奏略快，句尾保留紧张感",
    "messages": [
      {"role": "user", "content": "角色：..."}
    ],
    "text_prefix": "",
    "context_texts": []
  },
  "budget": {
    "limit": 600,
    "used": 118,
    "truncated": false,
    "dropped_fields": []
  },
  "warnings": []
}
```

### 6.7 旁白/对白模板分流细则（G6）

| 段落类型 | 模板侧重 | 字段优先级 |
|----------|----------|------------|
| narration（旁白） | 弱化角色身份，强化叙事节奏、信息清晰度、语气稳定 | 节奏 > 停顿 > 情绪 > 角色 |
| dialogue（对白） | 强化角色关系、场景张力、情绪强度 | 角色 > 情绪 > 场景 > 节奏 |
| inner_monologue（内心独白） | 强化心理活动、低强度情绪、近耳听感 | 情绪 > 演绎 > 角色 > 节奏 |

### 6.8 模型提示词传递策略补充

| 模型 | 提示词形态 | 优先保留 | 不应依赖的方式 |
|------|------------|----------|----------------|
| Qwen3-TTS-Instruct-Flash | `parameters.instructions` 自然语言，可开启 `optimize_instructions` | 情绪目标、停顿策略、重读词、演绎要求、导演指导 | 在正文接近 600 字输入限制时裸字符串截断 |
| CosyVoice v3.5 Plus | 短 cue `instruction` + `pause_before/after` | `emotion`、`pause`、`重读`、`act` | 大段旁白模板、长声音画像、长导演词 |
| StepAudio 2.5 TTS | `instruction` 全局语境 + 正文圆括号 inline 语境 | 情绪、停顿、重读、演绎要求；逐句停顿/低语走 `（...）` | 把 `voice_label`、MiMo 标签或长声音画像塞进 200 字预算前部 |
| MiniMax Speech 2.8 | `speed/volume/pitch` 基础参数降级 | 语速、强度、音调的保守映射 | 自然语言 instructions、正文标签 |
| MiMo V2.5 TTS | director/user message 或 assistant audio tags | 角色、场景、指导；标签模式下的整体风格和微标签 | 把 MiMo 标签污染到 Qwen/StepAudio/Seed 正文 |
| Seed-TTS 2.0 Expressive | `context_texts` + 可选方括号标签 | 上下文指令、语气/语速/音调、显式标签 | 把 context_texts 当作待朗读正文 |

---

## 7. 优化路线图与优先级

### 7.1 优先级矩阵

| 优先级 | 优化项 | 解决差距 | 预期收益 | 实施复杂度 |
|--------|--------|----------|----------|------------|
| **P0** | 旁白风格旧链路收口 | 产品边界 | 新项目不再被 `narration_style` 默认值写入固定语速、音高、风格 | 低 |
| **P0** | provider prompt 快照 | 可观测性 | 审阅阶段能看到每个模型最终 instructions/messages/context_texts 和降级说明 | 中 |
| **P0** | 情绪归一化统一到能力矩阵 | G2 | 消除 CosyVoice 硬编码，所有模型情绪可预测 | 低 |
| **P0** | 受限 instruction 智能压缩 | G1 | Qwen/CosyVoice/StepAudio 在预算内保留最高优先级信息；Qwen provider 层二次压缩不再裸截断 | 低 |
| **P1** | 停顿策略模型化落地（cosyvoice 参数 / stepaudio 圆括号） | G3 | 充分利用两个模型的停顿优势 | 中 |
| **P1** | 旁白/角色提示词模板分流 | G6 | 旁白叙事感增强，对白角色感增强 | 中 |
| **P1** | 风格控制单次构建 + 缓存（消除重复构建） | 效率 | 每段省一次重复构建 | 中 |
| **P2** | 音色资产创建与运行时表演分离 | G4 | clone/design 统一进音色管理窗口，生成链路只引用 `voice_id` | 中 |
| **P2** | MiniMax basic 降级策略 | — | 将高级表演意图可解释地降级为基础参数，并提示能力限制 | 中 |
| **P2** | 标签注入位置抽象（inline_tag_strategy） | G5 | 统一 MiMo/Doubao 标签策略 | 中 |
| **P3** | 提示词质量回写（per-model prompt→audio 评分） | G7 | 闭环优化模板 | 高 |

### 7.2 阶段化落地建议

**阶段一（P0，快速收益）**：先完成旁白风格旧链路收口、provider prompt 快照、情绪能力矩阵化、受限 instruction 优先级压缩。这些改动可以在不引入完整策略引擎的前提下完成，且能立刻提升可观测性和模型提示词稳定性。当前已完成首轮落地，详见 7.4。

**阶段二（P1，链路协同）**：引入轻量 `tts_prompt_strategy.py`，系统性收敛 G1/G3/G6 与重复构建问题。此阶段会改造 `build_model_style_control` 与 `_build_*_payload`，需配套回归测试。

**阶段三（P2，深度调优）**：完成音色资产创建与运行时表演分离、MiMo director/tags 动态选择、MiniMax basic 降级策略、标签注入位置抽象。

**阶段四（P3，闭环）**：质量回写，需要评审阶段的评分数据回流，独立于提示词链路。

### 7.3 验证策略

- **单元测试**：每个模型家族的策略函数输入输出契约测试，覆盖 narration/dialogue/inner_monologue 三类段落。
- **回归测试**：对现有章节生成快照，对比改造前后 `TTSStyleControl` 产物差异，确保非目标模型不受影响。
- **快照测试**：验证 `provider_prompt_snapshot` 对 Qwen、CosyVoice、MiniMax、MiMo、StepAudio、Seed/Doubao 均能输出正确 mode、provider prompt 和 warnings。
- **音质评测**：P0/P1 完成后，对 cosyvoice 与 stepaudio 各跑 5 段对照样本，人工评分停顿与情绪表现。
- **遵循 TDD**：涉及可测试逻辑的部分按 [test-driven-development SKILL](file:///c:/Users/cuigu/novel_writing_agent/.agent/skills/test-driven-development/SKILL.md) 先写测试。

### 7.4 实施进度（2026-06-29）

#### 7.4.1 已完成：P0 首轮落地

| 优化项 | 状态 | 实现落点 | 验证 |
|--------|------|----------|------|
| 旁白风格旧链路收口 | 已完成 | [narration_styles.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/narration_styles.py) | legacy `narration_style` 仅记录 `narration_style_legacy` / `narration_style_prompt_legacy`，不再写入 `speed`、`pitch`、`pause_multiplier`、`system_prompt`、`instructions`、`voice_description` |
| provider prompt 快照 | 已完成 | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py)、[_base.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_base.py)、[_script_utils_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_script_utils_mixin.py) | 审阅段落与实际 `_assign_voices` 均写入 `voice_params.provider_prompt_snapshot`，包含 `mode`、`provider_prompt.instructions/messages/text_prefix/context_texts`、`budget`、`warnings` |
| 情绪归一化统一到能力矩阵 | 已完成（提示词链路 + 底层入口） | [tts_model_ids.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_model_ids.py)、[tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py)、[_minimax_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_minimax_mixin.py) | Qwen / CosyVoice 声明 `supported_emotions` 与 `emotion_aliases`；`normalize_audiobook_tts_emotion` 成为能力矩阵驱动的公共入口；`normalize_emotion_for_model` 与底层 `TTSEngine._normalize_emotion` 均复用该入口，将 `tense` 等别名归一到模型可消费枚举 |
| 受限 instruction 智能压缩 | 已完成 | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | `instruction_budget` 进入风格控制层；受限模型按优先级组装并在边界裁剪，快照记录 `budget.truncated`、`dropped_fields` 和 warning |

#### 7.4.2 已完成：P1 停顿策略首轮落地

| 优化项 | 状态 | 实现落点 | 验证 |
|--------|------|----------|------|
| CosyVoice 显式停顿参数 | 已完成 | [_aliyun_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) | `_build_cosyvoice_websocket_parameters` 消费 `pause_before` / `pause_after`，并将数值限制在 `0.1-2.0` 秒范围内 |
| CosyVoice dramatic 停顿降落 | 已完成 | [_aliyun_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) | 当没有显式 `pause_after` 且 `delivery_plan.pause_profile == "dramatic"` 时，写入 `pause_after=0.8`；普通 natural/balanced 不额外扩大为 provider 参数 |
| StepAudio 圆括号 inline 停顿 | 已完成 | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py)、[_aliyun_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) | `delivery_plan.pause_profile == "dramatic"` 编译为 `（停顿0.8秒）`；`micro_tags`、`inline_audio_tags` 与 `emotion_mix` 编译为正文前缀圆括号 |
| StepAudio payload 复用风格控制产物 | 已完成（局部） | [_aliyun_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) | `_build_stepaudio_http_payload` 单次构建 `TTSStyleControl` 后同时复用 `instruction` 与 `text_prefix`，减少同一段重复构建 |
| 旁白/对白/内心独白模板分流 | 已完成（自然语言提示词链路） | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | 显式 `segment_type=narration/dialogue/monologue` 时分别按“节奏/停顿优先”“角色/情绪/场景优先”“心理活动/近耳感优先”组装 instruction；未知 `segment_type` 保持旧 generic 组装，避免污染纯 `instructions` / voice design 场景 |
| provider prompt 快照复用 | 已完成（provider payload 层） | [_aliyun_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) | Qwen / CosyVoice / Seed / StepAudio payload 优先消费 `voice_params.provider_prompt_snapshot.provider_prompt` 中的最终 `instructions`、`text_prefix`、`context_texts`；无快照时保持原有 `build_model_style_control` 构建路径 |

#### 7.4.3 已完成：P2 MiniMax basic 降级策略首轮落地

| 优化项 | 状态 | 实现落点 | 验证 |
|--------|------|----------|------|
| MiniMax basic 参数降级 | 已完成（局部） | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py)、[_aliyun_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) | `delivery_plan.pace/intensity/pitch` 在 MiniMax basic 模式下轻量映射为 `speed/volume/pitch`，provider payload 消费 `basic_voice_settings` 后写入 `voice_setting.speed/vol/pitch`；不生成自然语言 instructions、messages 或正文标签 |
| MiniMax 能力限制可审计 | 已完成（局部） | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | 当 `delivery_plan` 含 `micro_tags`、`pause_strategy`、`director_guidance` 等高级字段时，`TTSStyleControl.warnings` 记录“已降级为基础参数”和“忽略高级字段”，并随 `provider_prompt_snapshot.warnings` 进入审阅快照 |

#### 7.4.4 已完成：P2 MiMo/Doubao 标签注入位置抽象首轮落地

| 优化项 | 状态 | 实现落点 | 验证 |
|--------|------|----------|------|
| `inline_tag_strategy` 审计字段 | 已完成（局部） | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | MiMo `audio_tags` 与 Doubao/Seed `labels` 路径都会在 `provider_fields.inline_tag_strategy` 记录 `model_family`、`placement`、`style_tags`、`inline_tags` 与 `use_tag_parser`，便于审阅快照和测试定位标签注入位置 |
| 标签收集与模型渲染分层 | 已完成（局部） | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | `style_tags`、`inline_audio_tags`、`delivery_plan.micro_tags` / `inline_audio_tags` 的收集和去重逻辑收口到轻量 helper；输出格式仍按模型分流：MiMo 保持 `（风格）[微标签]`，Doubao 保持 `[标签，标签]` 并优先使用 inline 标签 |
| 快照暴露标签策略 | 已完成（局部） | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | `build_provider_prompt_snapshot` 将 `provider_fields.inline_tag_strategy` 透传到 `provider_prompt.inline_tag_strategy`，审阅阶段可直接查看标签注入位置、去重结果和 `use_tag_parser` 语义 |
| 审阅 UI 展示标签策略 | 已完成（局部） | [ScriptSegmentDetailsPanel.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/ScriptSegmentDetailsPanel.tsx)、[scriptSegmentCardUtils.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/scriptSegmentCardUtils.ts) | 脚本详情面板在存在 `voice_params.provider_prompt_snapshot.provider_prompt.inline_tag_strategy` 时展示模型家族、注入位置、Tag Parser 和去重后的标签 Chip，避免只能查看整段 JSON |
| 任务阶段 metrics 汇总标签策略 | 已完成（局部） | [_base.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_base.py)、[_generation_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_generation_mixin.py)、[_script_prep_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_script_prep_mixin.py)、[_audio_from_script_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_audio_from_script_mixin.py) | `AUDIO_PROMPT_REVIEW` 阶段 metrics 统一汇总 `inline_tag_strategy_count`、模型家族分布、注入位置分布、`use_tag_parser` 数量与段内去重后的标签总数；没有标签策略快照时保持原 metrics 字段不变 |

#### 7.4.5 验证结果

已执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" -q
```

结果：`109 passed`

补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q
```

结果：`58 passed, 3 skipped`

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`117 passed, 3 skipped`

P1 停顿策略首轮补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py" -q
```

结果：`48 passed`

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_model_ids.py" -q
```

结果：`45 passed`

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`121 passed, 3 skipped`

P1 模板分流补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" -q
```

结果：`10 passed`

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`124 passed, 3 skipped`

P1 provider prompt 快照复用补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py" -q
```

结果：`51 passed`

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`127 passed, 3 skipped`

语法检查：

```bash
python -m py_compile "backend/app/services/audiobook/tts_style_control.py" "backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py"
```

结果：无报错。

P1/P2 情绪归一入口收口补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_tts_model_ids.py::test_tts_emotion_normalization_uses_model_capability_matrix" -q
```

结果：`2 passed`

```bash
python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q
```

结果：`94 passed`

```bash
python -m py_compile "backend/app/services/audiobook/tts_model_ids.py" "backend/app/services/audiobook/tts_style_control.py" "backend/app/services/audiobook/tts_engine_pkg/_minimax_mixin.py"
```

结果：无报错。

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`128 passed, 3 skipped`

P2 MiniMax basic 降级策略补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py::test_minimax_style_control_degrades_delivery_plan_to_basic_voice_settings" "backend/tests/test_audiobook_tts_provider_payloads.py::test_minimax_http_payload_applies_basic_delivery_plan_settings" -q
```

结果：`2 passed`

```bash
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py" -q
```

结果：`53 passed`

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_tts_model_ids.py" -q
```

结果：`43 passed`

```bash
python -m py_compile "backend/app/services/audiobook/tts_style_control.py" "backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py"
```

结果：无报错。

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`130 passed, 3 skipped`

P2 MiMo/Doubao `inline_tag_strategy` 补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py::test_inline_tag_strategy_audits_mimo_and_doubao_tag_placement" "backend/tests/test_audiobook_tts_provider_payloads.py::test_doubao_inline_tag_strategy_preserves_style_fallback_with_delivery_plan_tags" -q
```

结果：`2 passed`

```bash
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_delivery_plan.py" -q
```

结果：`65 passed`

```bash
python -m py_compile "backend/app/services/audiobook/tts_style_control.py"
```

结果：无报错。

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`132 passed, 3 skipped`

P2 `provider_prompt_snapshot.inline_tag_strategy` 补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py::test_provider_prompt_snapshot_exposes_inline_tag_strategy" -q
```

结果：`1 passed`

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q
```

结果：`66 passed`

```bash
python -m py_compile "backend/app/services/audiobook/tts_style_control.py"
```

结果：无报错。

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`133 passed, 3 skipped`

P2 审阅 UI 展示 `inline_tag_strategy` 补充执行：

```bash
npm test -- "src/pages/audiobook/__tests__/scriptSegmentCardUtils.test.ts"
```

结果：`1 file passed, 8 tests passed`

```bash
npm run type-check
```

结果：无报错。

G7 章节级 ASR 转写手动队列入口补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_task_trace_contexts.py" "backend/tests/test_audiobook_prompt_audio_review_routes.py" -q
```

结果：`18 passed`

```bash
npm test -- "src/pages/audiobook/__tests__/promptAudioReviewSource.test.ts" "src/pages/audiobook/__tests__/taskUtils.test.ts" "src/pages/audiobook/__tests__/stageMetricsUtils.test.ts"
```

结果：`3 files passed, 21 tests passed`

```bash
npm run type-check
```

结果：无报错。

后端快照定向回归：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py::test_provider_prompt_snapshot_exposes_inline_tag_strategy" -q
```

结果：`1 passed`

P2 任务阶段 metrics 汇总 `inline_tag_strategy` 补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_quality.py::test_audio_prompt_review_metrics_summarize_inline_tag_strategy_snapshots" "backend/tests/test_audiobook_delivery_quality.py::test_audio_prompt_review_metrics_omit_inline_strategy_fields_when_absent" -q
```

结果：`2 passed`

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" -q
```

结果：`16 passed`

```bash
python -m py_compile "backend/app/services/audiobook/engine_pkg/_base.py" "backend/app/services/audiobook/engine_pkg/_generation_mixin.py" "backend/app/services/audiobook/engine_pkg/_script_prep_mixin.py" "backend/app/services/audiobook/engine_pkg/_audio_from_script_mixin.py"
```

结果：无报错。

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`135 passed, 3 skipped`

G7 per-model prompt→audio 质量回写骨架补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_final_audio_review.py::test_final_audio_review_includes_prompt_audio_quality_feedback_by_model" -q
```

结果：`1 passed`

```bash
python -m pytest "backend/tests/test_audiobook_final_audio_review.py" "backend/tests/test_audiobook_delivery_quality.py" -q
```

结果：`9 passed`

```bash
python -m py_compile "backend/app/services/audiobook/engine_pkg/_review_mixin.py" "backend/app/services/audiobook/engine_pkg/_generation_mixin.py" "backend/app/services/audiobook/engine_pkg/_audio_from_script_mixin.py"
```

结果：无报错。

最终合并执行：

```bash
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_final_audio_review.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_chapter_structure_templates.py" "backend/tests/test_new_features.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_smoke.py" -q
```

结果：`139 passed, 3 skipped`

G7 前端展示 `prompt_audio_quality` 摘要补充执行：

```bash
npm test -- "src/pages/audiobook/__tests__/stageMetricsUtils.test.ts"
```

结果：`1 file passed, 2 tests passed`

```bash
npm test -- "src/pages/audiobook/__tests__/stageMetricsUtils.test.ts" "src/pages/audiobook/__tests__/scriptSegmentCardUtils.test.ts" "src/pages/audiobook/__tests__/stageUtils.test.ts"
```

结果：`3 files passed, 15 tests passed`

```bash
npm run type-check
```

结果：无报错。

G7 人工验收录入与持久化补充执行：

```bash
python -m pytest "backend/tests/test_audiobook_prompt_audio_review_routes.py" "backend/tests/test_audiobook_final_audio_review.py" "backend/tests/test_audiobook_stt_verifier.py" "backend/tests/test_audiobook_route_import_hygiene.py" "backend/tests/test_audiobook_delivery_quality.py" -q
```

结果：`26 passed`

```bash
npm test -- "src/pages/audiobook/__tests__/promptAudioReviewSource.test.ts" "src/pages/audiobook/__tests__/promptAudioReviewSummarySource.test.ts" "src/pages/audiobook/__tests__/stageMetricsUtils.test.ts"
```

结果：`3 files passed, 5 tests passed`

```bash
npm run type-check
```

结果：无报错。

#### 7.4.6 执行中发现并同步优化的点

- `_assign_voices` 的调试日志默认假设 `speed` 一定存在；旁白风格收口后该字段可能为空，已改为安全格式化，避免日志阶段抛出 `TypeError`。
- Qwen 旁白即使不再使用 legacy `narration_style`，仍会通过 `reconcile_voice_description_with_selected_voice` 生成已选音色的硬约束声音描述。这是音色约束层的正确行为，不属于旁白风格覆盖。
- 底层 TTS 引擎包中仍保留历史 `COSYVOICE_V3_PLUS_INSTRUCT_EMOTIONS` / `COSYVOICE_V3_PLUS_EMOTION_ALIASES` 常量作为兼容导出和旧模块惯性引用，但实际情绪归一入口已收口到 [tts_model_ids.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_model_ids.py) 的 `normalize_audiobook_tts_emotion`；测试通过临时改写 CosyVoice 能力矩阵 alias 验证 `normalize_emotion_for_model` 与底层 `TTSEngine._normalize_emotion` 均不再依赖旧硬编码映射。
- StepAudio 的 HTTP payload 原先会在 instruction 与正文处理路径上重复构建风格控制；P1 首轮已让 `_build_stepaudio_http_payload` 复用单次 `TTSStyleControl`，同时 `prepare_text_for_style_control` 增加前缀幂等保护，避免正文已带前缀时重复注入。
- StepAudio inline 不应把普通 `instruct_emotion` 全量塞入正文圆括号；当前仅消费显式 `inline_audio_tags`、`delivery_plan.micro_tags`、`delivery_plan.emotion_mix` 与模型化停顿，普通情绪仍保留在全局 instruction 中，减少正文污染。
- 模板分流只应在 `segment_type` 明确为 `narration`、`dialogue`、`monologue/inner_monologue` 时启用；缺少段落类型的纯 provider 测试、纯 `instructions` 和 MiMo voice design 场景必须保留 generic 组装，避免把“对白模板”等系统提示注入用户只要求传递的文本。
- provider payload 层复用快照时必须只读 `provider_prompt_snapshot.provider_prompt` 的最终可投递字段，不能把整个快照作为运行时配置保存或回写；没有快照、快照缺字段或纯 provider 调用时继续走原构建路径，保证兼容性。
- MiniMax basic 降级只在存在 `delivery_plan` 时启用，避免改变普通 MiniMax preview/provider payload 的既有参数语义；降级幅度保持保守（例如 slow→`speed*0.9`、high→`volume+8`、lower→`pitch-8`），减少因过度补偿导致的听感漂移。
- MiMo 与 Doubao 的标签来源相同，但注入位置和 provider 语义不同：MiMo 标签进入 assistant 正文前缀，Doubao 标签进入 text prefix 并配合 `use_tag_parser`；因此只抽出标签收集/去重和审计字段，不把两者强行合并为同一种渲染格式。
- Doubao 的标签 fallback 需要保持旧语义：存在 inline 标签时优先只渲染 inline；没有 inline 标签时才把 `style_tags` 与 `delivery_plan.emotion_primary/emotion_mix` 合并为正文标签，避免把审计用 style 标签意外注入已有 inline 标签的正文前缀。
- `provider_prompt_snapshot` 仍只承载最终可审阅的 provider prompt 表面；`inline_tag_strategy` 放在 `provider_prompt` 下作为审计元数据，不参与 provider payload 复用路径，避免运行时把审计字段当作合成参数。
- 前端脚本详情面板原先只能通过完整 `voice_params` JSON 查看 provider prompt 快照；本轮增加了专门摘要展示，但保持 JSON 原样输出，避免影响高级调试和脚本保存结构。
- StepAudio 的 inline 圆括号同时承载停顿、微标签与情绪层次，且受 200 字全局 instruction 预算影响；本轮未纳入 `inline_tag_strategy`，继续保留专用 renderer，避免把停顿语义混入 MiMo/Doubao 的标签抽象。
- 任务阶段 metrics 只读取 `provider_prompt_snapshot.provider_prompt.inline_tag_strategy` 这个审计快照，不反向参与 provider payload 构造；没有快照或快照缺字段时不输出空的 `inline_tag_strategy_*` 字段，避免污染普通任务日志。
- G7 首轮只做“质量回写骨架”，不自动判定标签解析是否成功或是否出现正文污染；这些字段先以 `manual_review_fields` 占位，避免用不可验证的启发式替代人工听审或后续 ASR/文本比对。

#### 7.4.7 已完成：G7 per-model prompt→audio 质量回写骨架首轮落地

| 优化项 | 状态 | 实现落点 | 验证 |
|--------|------|----------|------|
| 最终音频评审携带 prompt→audio 质量回写骨架 | 已完成（局部） | [_review_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_review_mixin.py) | `_final_audio_review` 新增 `prompt_audio_quality`，按 TTS 模型汇总片段数、已产出音频片段数、缺失音频数、provider prompt 快照覆盖数、`inline_tag_strategy` 覆盖数、`use_tag_parser` 数量和段内去重标签数 |
| 生成链路传入片段与音频列表 | 已完成（局部） | [_generation_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_generation_mixin.py)、[_audio_from_script_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_audio_from_script_mixin.py) | 完整生成与已审稿生成在最终音频评审阶段传入 `script_segments` 与 `audio_list`，使质量回写能对齐“prompt 快照 → 音频片段产出” |
| 人工验收字段占位 | 已完成（局部） | [_review_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_review_mixin.py) | 对存在 `inline_tag_strategy` 的模型片段记录 `manual_review_segment_indices`，并预留 `tag_parse_success`、`text_contamination`、`score` 三个 `manual_review_fields`，后续可由人工听审或 ASR 比对回填 |
| 阶段 metrics 弹窗展示质量回写摘要 | 已完成（局部） | [StageMetricsDialog.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/StageMetricsDialog.tsx)、[stageMetricsUtils.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/stageMetricsUtils.ts) | 最终评审阶段 metrics 若包含 `prompt_audio_quality`，弹窗优先展示章节覆盖、模型分布、缺失音频、标签策略覆盖、Tag Parser 和待人工验收片段，原始 JSON 仍保留用于审计 |
| 人工验收录入与持久化 | 已完成（局部） | [routes_prompt_audio_review.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/audiobook_api/routes_prompt_audio_review.py)、[audiobook.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/schemas/audiobook.py) | 新增 `PATCH /api/v1/audiobook/chapter-audios/{chapter_audio_id}/prompt-audio-review`，按已存在的 `by_model[model]` 合并 `manual_review_fields`，记录 `tag_parse_success`、`text_contamination`、`score`、`notes`、`reviewed_at`、`reviewed_by`；沿用章节音频所有权与软删除校验，未知模型不写入 |
| 章节结果暴露质量回写摘要 | 已完成（局部） | [routes_projects.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/audiobook_api/routes_projects.py) | `get_audiobook_project` 与 `list_audiobook_projects(include_chapter_audios=true)` 的 `chapter_audios[]` 增加可选 `prompt_audio_quality`，前端无需逐章节额外请求即可打开验收面板；损坏的历史 `final_audio_review_json` 只记录 warning 并跳过该字段 |
| 前端章节结果人工验收面板 | 已完成（局部） | [ChapterAudioResultItem.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/ChapterAudioResultItem.tsx)、[PromptAudioManualReviewPanel.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/PromptAudioManualReviewPanel.tsx)、[api.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/services/api.ts)、[stageMetricsUtils.ts](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/stageMetricsUtils.ts) | 章节结果“更多操作”新增 `Prompt/Audio 验收`，按模型选择录入标签解析、正文污染、人工评分、备注与可选 ASR 转写文本；保存后用后端返回的 `prompt_audio_quality` 局部刷新当前面板 |
| 项目级人工验收汇总与 CSV 导出 | 已完成（局部） | [prompt_audio_review_summary.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_review_summary.py)、[routes_projects.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/audiobook_api/routes_projects.py)、[PromptAudioReviewSummaryPanel.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/PromptAudioReviewSummaryPanel.tsx) | 新增 `GET /api/v1/audiobook/projects/{audiobook_project_id}/prompt-audio-review-summary` 与 `.csv` 导出，按模型统计质量回写章节数、已验收模型数、标签解析成功率、正文污染率、平均人工评分、缺失音频数、ASR 辅助样本数和标签残留数；完成页展示项目级摘要并支持 CSV 下载 |
| ASR 转写辅助比对信号 | 已完成（局部） | [prompt_audio_asr_assist.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_asr_assist.py)、[routes_prompt_audio_review.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/api/v1/audiobook_api/routes_prompt_audio_review.py)、[PromptAudioManualReviewPanel.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/PromptAudioManualReviewPanel.tsx)、[stt_verifier.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/stt_verifier.py) | 人工验收接口新增可选 `asr_transcript`，由后端基于剧本文本、`manual_review_segment_indices` 与 `inline_tag_strategy` 标签计算 `asr_assist`，输出相似度、WER、命中标签、建议正文污染与建议标签解析结果；当前只消费人工粘贴或外部产出的转写文本，不在生成链路中自动调用生产 ASR |
| 章节级 ASR 转写手动队列入口 | 已完成 | [prompt_audio_transcript_queue.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_transcript_queue.py)、[prompt_audio_asr_provider.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_asr_provider.py)、[prompt_audio_transcript_runner.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_transcript_runner.py)、[prompt_audio_review_writer.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_review_writer.py)、[audiobook_tasks.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/tasks/audiobook_tasks.py)、[PromptAudioManualReviewPanel.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/PromptAudioManualReviewPanel.tsx) | `POST /api/v1/audiobook/chapter-audios/{chapter_audio_id}/prompt-audio-transcript/queue` 已支持 `provider`、`model`、`confirm_cost`；手动任务只在 `confirm_cost=true` 时调用真实 ASR，默认优先 MiMo，小米本地音频直传可直接回填，阿里/豆包 provider 保留 URL 型异步接口边界。任务完成后写回目标模型的 `manual_review_fields.asr_transcript`、`asr_provider`、`asr_provider_model` 与 `asr_assist`；未配置或未确认成本仍安全跳过，继续禁止普通生成链路自动调用生产 ASR |

#### 7.4.8 下一步建议

1. P1 轻量策略层抽取已完成：`pause_renderer`、`template_renderer`、`instruction_compactor` 已进入独立纯函数模块，仍不引入未使用的复杂策略引擎。
2. P1 验收样本已生成：CosyVoice 与 StepAudio 各 5 段 UTF-8 对照样本已产出，进入人工听审评分阶段，评分停顿自然度、留白强度、模板分流后的旁白/对白/独白贴合度和正文污染情况。
3. P2 验收样本已生成：MiMo 与 Doubao 各 5 段含 `style_tags`、`inline_audio_tags`、`delivery_plan.micro_tags` 的 UTF-8 样本已产出，并用 MiMo ASR 做辅助转写；标签是否真正被正确解析仍以人工听审为准。
4. G7 后续：真实 ASR provider 已接入手动队列，并完成 MiMo 小范围真实校准；阿里/豆包 ASR 继续保留公网 `audio_url` 异步接口边界，不把生产 ASR 自动塞入普通生成链路。

---

## 8. 附录

### 附录 A：模型能力矩阵速查表

| 模型 | family | mode | 情绪 | 停顿 | instruction 预算 | 注入字段 |
|------|--------|------|------|------|------------------|----------|
| qwen3-tts-instruct-flash | qwen | natural_language（字段级压缩） | 自然语言 | 标点 | 600 字 | parameters.instructions |
| cosyvoice-v3.5-plus | cosyvoice | natural_language（短 cue 优先） | 7 类枚举 | **pause 参数** | 100 字 | parameters.instruction |
| minimax-speech-2.8-hd | minimax | basic | 基础参数降级 | 标点 | — | 无 |
| minimax-speech-2.8-turbo | minimax | basic | 基础参数降级 | 标点 | — | 无 |
| mimo-v2.5-tts | mimo | director | 复合情绪 | 微标签 | 无上限 | messages.user |
| mimo-v2.5-tts-voicedesign | mimo | voice_design | 声音描述优先 | 微标签 | 无上限 | messages.user |
| mimo-v2.5-tts-voiceclone | mimo | director + clone_audio | 导演+标签 | 微标签 | 无上限 | messages.user + audio.voice |
| stepaudio-2.5-tts | stepaudio | global_context（cue 优先） | 全局+inline | **圆括号** | 200 字 | parameters.instruction+inline |
| seed-tts-2.0-expressive | doubao | query_response | Query-Response | 标签 | 无上限 | additions.context_texts |


#### 7.4.9 已完成：G7 真实 ASR provider 接入与回填

| 优化项 | 状态 | 实现落点 | 验证 |
|--------|------|----------|------|
| ASR provider 适配器 | 已完成 | [prompt_audio_asr_provider.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_asr_provider.py) | 新增 `PromptAudioAsrProvider`/`PromptAudioAsrResult` 抽象，默认 MiMo provider 读取 `MIMO_ASR_API_KEY` 或 `MIMO_API_KEY`，以手动任务直传本地章节音频；阿里 DashScope 与豆包火山 ASR provider 记录为需要公网 `audio_url` 的异步接口边界 |
| 成本确认边界 | 已完成 | [prompt_audio_transcript_queue.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_transcript_queue.py)、[PromptAudioManualReviewPanel.tsx](file:///c:/Users/cuigu/novel_writing_agent/frontend/src/pages/audiobook/PromptAudioManualReviewPanel.tsx) | 队列请求新增 `provider`、`model`、`confirm_cost`；任务 detail 的 `cost_control.provider_call_allowed` 仅在人工确认后为 true，未确认时不调用 provider 并写入 `asr_cost_not_confirmed` |
| transcript/asr_assist 共享回填 | 已完成 | [prompt_audio_transcript_runner.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_transcript_runner.py)、[prompt_audio_review_writer.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/prompt_audio_review_writer.py) | 真实 ASR 返回文本后，统一写回目标模型 `manual_review_fields.asr_transcript`、`asr_provider`、`asr_provider_model` 和 `asr_assist`；人工 PATCH 与后台任务复用同一写入 helper，避免 JSON 合并逻辑分叉 |
| 任务状态与失败边界 | 已完成 | [audiobook_tasks.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/tasks/audiobook_tasks.py) | provider 未配置/成本未确认保持 completed+skipped；音频缺失、provider 错误、空 transcript 标记 failed，detail 中保留 reason/message，方便人工定位 |

真实 provider 校准补充：

- MiMo ASR 首次真实调用返回 `400 Param Incorrect`，供应商提示 ASR 请求不能包含 text parts，网关会注入文本提示；已将 MiMo ASR payload 校准为仅发送 `input_audio`。
- MiMo ASR 返回结构兼容 `choices[].message.content`，已补充 `_first_text` 对 `content` 字段与 `message` dict 的递归解析。
- 真实校准音频：[stepaudio_cn_unicode_escape.mp3](file:///c:/Users/cuigu/novel_writing_agent/backend/data/tts_debug/stepaudio/stepaudio_cn_unicode_escape.mp3)，模型 `mimo-v2.5-asr`，转写结果预览：`智能机遇，十倍每一个人的可能。`
- 阿里 DashScope ASR 与豆包火山 ASR 当前仍保留 `audio_url` 型异步接口边界；本轮未把本地文件上传或公开化，也未自动接入普通生成链路。

验证命令：

```bash
python -m pytest "backend/tests/test_audiobook_prompt_audio_review_routes.py" "backend/tests/test_audiobook_task_trace_contexts.py" "backend/tests/test_audiobook_final_audio_review.py" "backend/tests/test_audiobook_stt_verifier.py" "backend/tests/test_audiobook_route_import_hygiene.py" "backend/tests/test_audiobook_delivery_quality.py" -q
cd frontend && npm test -- "src/pages/audiobook/__tests__/promptAudioReviewSource.test.ts" "src/pages/audiobook/__tests__/promptAudioReviewSummarySource.test.ts" "src/pages/audiobook/__tests__/stageMetricsUtils.test.ts" "src/pages/audiobook/__tests__/taskUtils.test.ts"
cd frontend && npm run type-check
```

下一步顺序调整：G7 provider 接入完成后，继续 P1 轻量策略层抽取；完成 P1/P2 样本生成后进入人工听审验收点，届时需要提供试听入口和评分项，不在没有人工反馈的情况下继续自动判断效果。

#### 7.4.10 已完成：P1 轻量提示词策略层抽取

| 优化项 | 状态 | 实现落点 | 验证 |
|--------|------|----------|------|
| instruction 预算压缩独立化 | 已完成 | [tts_prompt_strategy.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_prompt_strategy.py)、[tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | 新增 `compact_instruction_parts`，保留旧 `_compact_instruction_parts` 作为兼容委托；预算、截断字段、warning 输出保持现有行为 |
| StepAudio inline 停顿渲染独立化 | 已完成 | [tts_prompt_strategy.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_prompt_strategy.py) | 新增 `render_stepaudio_inline_prefix`，统一处理显式 `pause_before`、`delivery_plan.pause_profile`、`inline_audio_tags`、`micro_tags` 与 `emotion_mix` 去重 |
| 旁白/对白/独白模板分流独立化 | 已完成 | [tts_prompt_strategy.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_prompt_strategy.py) | 新增 `build_common_prompt_parts`，旁白模板优先输出韵律控制与停顿策略，再输出情绪、场景、角色设定；旧 `_build_common_parts` 保持兼容委托 |
| 策略层接入风格控制 | 已完成 | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | `build_model_style_control` 仍保持既有模型分流，短期通过薄 wrapper 调用策略纯函数，避免无必要的大范围重构 |
| StepAudio 预算优先级修正 | 已完成 | [tts_prompt_strategy.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_prompt_strategy.py)、[tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | `stepaudio` 模型族优先输出情绪、停顿、重读、演绎要求；长 `声音描述` 仅作为低优先级尾部上下文，无法完整放入 200 字预算时直接丢弃，不生成误导性的截断碎片 |
| Qwen provider 层二次压缩 | 已完成 | [_aliyun_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) | 当正文接近 DashScope 输入限制导致 `instructions` 需要缩短时，结构化字段按情绪、停顿、重读、演绎优先重新压缩；纯显式长 `instructions` 保持旧的按预算截断兼容语义 |

验证命令：

```bash
python -m pytest "backend/tests/test_audiobook_tts_prompt_strategy.py" -q
python -m pytest "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q
```

结果：`4 passed`；`75 passed`。

当前顺序：P1 轻量策略层已完成，下一步是生成 P1/P2 对照试听样本并停在人工听审验收点；验收前只做必要的样本定位、任务入口准备和真实 provider 小范围校准，不自动替代人工评分。

#### 7.4.11 已完成：P1/P2 UTF-8 真实试听样本包与人工验收入口

| 优化项 | 状态 | 实现落点 | 验证 |
|--------|------|----------|------|
| UTF-8 样本生成工具 | 已完成 | [generate_prompt_strategy_acceptance_samples.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/scripts/generate_prompt_strategy_acceptance_samples.py) | 新增本地脚本，复用 `build_delivery_plan`、`build_model_style_control`、`build_provider_prompt_snapshot` 与 `TTSEngine` 正式链路生成样本；避免 PowerShell inline 中文编码导致正文变成 `????` |
| P1 停顿/模板对照样本 | 已完成，已清理试听文件 | `backend/data/tts_debug/prompt_strategy_acceptance_utf8/` | CosyVoice 5 段、StepAudio 5 段曾用于人工听审；本次按用户确认已删除试听文件与播放页，后续需要重新生成新版样本 |
| P2 标签解析对照样本 | 已完成，已清理试听文件 | `backend/data/tts_debug/prompt_strategy_acceptance_utf8/` | MiMo 5 段、Doubao 5 段曾用于人工听审；本次按用户确认已删除试听文件与播放页 |
| MiMo ASR 辅助转写 | 已完成，历史辅助信号已随样本清理 | `backend/data/tts_debug/prompt_strategy_acceptance_utf8/manifest.json` | 历史 ASR 结果只作为听审辅助，不替代人工听感评价；样本目录已清理 |
| 人工验收入口 | 已清理 | `backend/data/tts_debug/prompt_strategy_acceptance_utf8/index.html` | 原浏览器播放页和评分表已按本次确认清除；新版策略需要重新生成验收样本 |

样本包结果：

- 输出目录：`backend/data/tts_debug/prompt_strategy_acceptance_utf8/`
- 试听页：`backend/data/tts_debug/prompt_strategy_acceptance_utf8/index.html`
- 评分表：`backend/data/tts_debug/prompt_strategy_acceptance_utf8/review_sheet.md`
- Manifest：`backend/data/tts_debug/prompt_strategy_acceptance_utf8/manifest.json`
- 总数：20；成功：20；失败：0。
- 分组：P1 CosyVoice `5/5`，P1 StepAudio `5/5`，P2 MiMo `5/5`，P2 Doubao `5/5`。
- 质量校验：20 个音频均通过输出质量校验；最终 UTF-8 文本污染检查未发现 `????`。
- ASR 辅助：10 个 P2 样本均完成 MiMo ASR 转写，标签残留候选总数为 0。

执行与验证命令：

```bash
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py::test_seed_tts_synthesis_falls_back_to_http_when_websocket_returns_no_audio" -q
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py" -q
python -m py_compile "backend/app/scripts/generate_prompt_strategy_acceptance_samples.py"
python -m app.scripts.generate_prompt_strategy_acceptance_samples --run-asr
python -m app.scripts.generate_prompt_strategy_acceptance_samples --rebuild-index
python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_tts_prompt_strategy.py" "backend/tests/test_audiobook_prompt_audio_asr_provider.py" -q
```

当前停点：进入人工听审验收。下一步需要人工在 `index.html` 试听，并按 `review_sheet.md` 记录 P1/P2 分数与备注；没有人工反馈前，不继续自动调整主观听感模板。

### 附录 B：差距清单（G1–G7）速查

| 编号 | 差距 | 解决方案 | 落地点 |
|------|------|----------|--------|
| G1 | 投递计划→提示词映射粗放 | 预算感知压缩 + 能力门控 | tts_prompt_strategy |
| G2 | 情绪未按模型枚举归一 | 能力矩阵声明 supported_emotions + 统一归一入口 | tts_prompt_strategy + tts_model_ids |
| G3 | 停顿策略未模型化 | pause_renderer 按模型分流 | tts_prompt_strategy |
| G4 | 音色资产创建与逐句表演混合 | clone/design 进音色管理窗口，生成链路只引用 `voice_id` | 音色管理窗口 + runtime voice mapping |
| G5 | 标签注入位置不分模型 | inline_tag_strategy 抽象 | tts_prompt_strategy |
| G6 | 旁白/角色模板同构 | segment_type 进入模板选择 | tts_prompt_strategy |
| G7 | 无质量回写 | per-model prompt→audio 评分回流 | 评审阶段（独立） |

### 附录 C：关键代码引用索引

| 模块 | 文件 | 关键函数/常量 |
|------|------|---------------|
| 能力矩阵 | [tts_model_ids.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_model_ids.py) | `AUDIOBOOK_TTS_STYLE_CAPABILITIES`、`get_audiobook_tts_style_capabilities` |
| 投递计划 | [tts_delivery_plan.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_delivery_plan.py) | `build_delivery_plan`、`delivery_plan_instruction_parts`、`_infer_pause_profile` |
| 提示词策略 | [tts_prompt_strategy.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_prompt_strategy.py) | `compact_instruction_parts`、`render_stepaudio_inline_prefix`、`build_common_prompt_parts` |
| 风格控制 | [tts_style_control.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_style_control.py) | `build_model_style_control`、`build_provider_prompt_snapshot`、`normalize_emotion_for_model`、`_build_common_parts` |
| 声音描述融合 | [voice_description_policy.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/voice_description_policy.py) | `reconcile_voice_description_with_selected_voice`、`_VOICE_AGE_HINTS` |
| 音色设计 | [voice_designer.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/agents/voice_designer.py) | `VoiceDesigner` |
| 引擎基类 | [_base.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_base.py) | `COSYVOICE_V3_PLUS_INSTRUCT_EMOTIONS`、`max_concurrent`、`request_delay` |
| 阿里混入 | [_aliyun_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py) | `STEPAUDIO_TTS_INSTRUCTION_MAX_CHARS=200`、`STEPAUDIO_TTS_MAX_INPUT_CHARS=1000`、`_build_qwen_instruction_payload`、`_build_stepaudio_instruction_payload` |
| 旁白风格 legacy | [narration_styles.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/narration_styles.py) | 历史旁白风格兼容链路，后续应收口而非扩展 |
| 章节分析 | [_analysis.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/script_adapter_pkg/_analysis.py) | `_analyze_chapter`、`_build_analysis_sample(6000)` |
| 两阶段剧本生成 | [_script_prep_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_script_prep_mixin.py) | `prepare_chapter_script` |
| 已审稿音频生成 | [_audio_from_script_mixin.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/services/audiobook/engine_pkg/_audio_from_script_mixin.py) | `generate_chapter_audio_from_script` |
| 验收样本生成 | [generate_prompt_strategy_acceptance_samples.py](file:///c:/Users/cuigu/novel_writing_agent/backend/app/scripts/generate_prompt_strategy_acceptance_samples.py) | `generate_samples`、`--run-asr`、`--rebuild-index` |

---

_最后更新：2026-06-30_
_本文档为优化指导，具体实施需遵循 [backend-dev-guidelines](file:///c:/Users/cuigu/novel_writing_agent/.agent/skills/backend-dev-guidelines/SKILL.md) 与 [test-driven-development](file:///c:/Users/cuigu/novel_writing_agent/.agent/skills/test-driven-development/SKILL.md) 规范_
