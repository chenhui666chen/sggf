# 有声小说音色画像与角色匹配指导

> 状态：设计与实施指导，尚不等同于已上线功能。
>
> 适用范围：有声小说预置音色、供应商目录音色、AI 设计音色、经授权的用户自定义或克隆音色。
>
> 目标读者：产品、音频内容工程、后端、前端、模型评测和运营审核人员。

## 1. 背景与目标

有声小说项目中的可选音色通常数量很多，且不少供应商目录只提供名称或极简描述。用户只能反复试听，难以快速回答以下问题：

- 哪些声音适合成熟男性、少女、长者、儿童或中性角色？
- 哪些声音适合旁白、谋士、反派、将领、恋爱对白或群像角色？
- 某角色需要低沉、克制、古风感时，应该优先试听哪些音色？
- 已选角色之间是否听感过于接近，导致多人对话难以分辨？

本方案将音色目录转化为可检索的结构化声音画像库，并将角色设定转化为可解释的匹配条件。产品目标不是替用户做不可解释的最终决定，而是将几百个候选收敛为少量可试听、可比较、可编辑的候选池。

核心原则：

1. 描述声音听感和表演能力，不声称判断真实说话人的身份、年龄、健康或人格事实。
2. 音色分析在入库或目录同步阶段离线完成，不放在用户选择音色的实时路径中。
3. ASR 是分析链路的一部分，但不是声音特质分析的唯一模型。
4. 用户最终拥有选择权，模型推荐必须给出可理解的理由。
5. 受控分类优先于自由标签，避免目录再次变成不可筛选的词云。

## 2. 当前项目基线

公共音色池当前已定义以下受控字段，见 `backend/app/schemas/voice_pool.py`。它们是可复用的 taxonomy 基线，但不是当前所有可选音色的唯一数据源：

| 字段 | 当前含义 | 当前选项或约束 |
|---|---|---|
| `gender_presentation` | 声音呈现倾向 | `female`、`male`、`neutral` |
| `age_impression` | 年龄感 | `child`、`teen`、`young_adult`、`adult`、`mature`、`elder` |
| `primary_style` | 主要风格 | 如 `gentle`、`restrained`、`powerful`、`narration`、`roleplay` |
| `timbre_tags` | 音色质感 | 如 `clear`、`warm`、`deep`、`magnetic`、`slightly_husky`、`airy` |
| `scenario_tags` | 适用场景/题材 | 如 `audiobook`、`dialogue`、`historical`、`fantasy`、`suspense` |
| `emotion_tags` | 可表达的情绪倾向 | 如 `calm`、`tender`、`tense`、`angry`、`sad` |
| `description` | 面向用户的可读描述 | 最长 500 字 |

这些字段已覆盖声音画像的第一层，应复用而不是重新命名。后续需要补充的是可比较的发声维度、表演能力和角色原型，而不是再建立一套与现有字段重叠的标签系统。

### 2.1 当前运行时音色来源与边界

当前项目至少存在四类对象，不能把它们混为同一个“音色池”：

| 范围 | 当前来源 | 当前入口 | 本方案中的角色 |
|---|---|---|---|
| 供应商/预置系统音色 | `voice_catalog` 读取共享模型目录 | `GET /tts/voices?model=...` | 音色选择器的主目录；阶段一画像、筛选和描述的首要接入点 |
| 用户私有参考或复刻音色 | `VoiceReferenceAsset` | 私有音色与参考资产接口 | 只在所有者授权范围内展示、分析和使用 |
| 用户发布的公共音色 | `VoicePoolPublication` | `GET /voice-pool/public` | 已审核私有参考音色的可撤回公共视图，不等同于供应商系统目录 |
| 角色运行时配音配置 | `voice_mapping` 与 `VoiceManager.VoiceProfile` | 有声书项目创建和合成路径 | 保存角色最终选择的 `voice_id`、`tts_model` 和引用信息，不是目录画像的存储位置 |

因此，阶段一不能只扩展 `VoicePoolPublication`。应先让 `voice_catalog -> /tts/voices` 返回可筛选的画像投影；公共池和私有资产在各自授权范围内复用同一 taxonomy。`VoiceManager` 负责解析、校验和合成，只有在阶段二自动角色推荐时才消费统一的候选评分结果。

## 3. 概念边界：ASR 不等于声音画像

### 3.1 ASR 能解决什么

ASR 主要回答“说了什么、固定文本下转写是否稳定、节奏如何”。对于标准试听音频，ASR 可提供：

- 转写文本与文本一致性；
- 词级或字级时间戳；
- 语速、停顿比例和断句表现；
- 漏字、错字、吞字等固定文本条件下的可懂度代理指标；
- 在支持相关能力时，语言、口音或情绪等辅助信号。

ASR 文本一致性只能作为固定文本、固定噪声条件下的代理指标；它会受到识别器本身、口音、文本归一化和噪声的影响，不能单独等同于“咬字清晰”或“可懂度高”。这些结果可辅助支持“语速中等偏慢、停顿自然、标准样本可稳定转写”等结论。

### 3.2 ASR 不能单独解决什么

仅用 ASR 不能稳定识别或解释以下内容：

- 低沉、明亮、醇厚、磁性、气声、沙哑等音色质感；
- 音高区间、能量、共鸣、声音稳定性；
- 是否适合将领、谋士、少女、反派、旁白等角色原型；
- 角色之间的声线可区分度；
- 用户可读、可用于筛选的声音描述。

因此，ASR 应作为质量与韵律分析层，而不是“年龄感/音色质感分类器”的替代品。

## 4. 声音画像分类体系

### 4.1 硬筛选与软匹配

分类字段应分为三类：

| 类型 | 字段示例 | 使用方式 |
|---|---|---|
| 硬筛选 | 当前 TTS 模型、语言、可用状态、授权状态、可试听状态 | 不满足时不展示或不可选择 |
| 强偏好 | 性别呈现、年龄感 | 用户明确指定时优先过滤；未指定时只影响排序 |
| 软匹配 | 音色质感、气质、情绪张力、角色原型、题材、节奏 | 参与推荐评分，不宜无条件排除 |

这样可避免“用户选择成熟男性”后，系统把所有有少量反差价值的声音完全隐藏。

### 4.2 六维画像

| 维度 | 字段 | 面向用户的示例 | 数据来源 |
|---|---|---|---|
| 听感身份 | `gender_presentation`、`age_impression` | 男性呈现、成熟感、长者感 | 官方信息、模型初标、人工复核 |
| 音色质感 | `timbre_tags`、`pitch_range` | 低沉、清亮、温暖、略沙哑、中低音 | 声学特征、音频理解模型 |
| 主表达风格与角色气质 | `primary_style`、`temperament_tags` | 主风格克制；角色印象威严、神秘或亲和 | 音频理解模型、人工复核 |
| 发声方式 | `pace`、`energy`、`articulation`、`stability_score` | 偏慢、能量中等、固定文本转写稳定 | ASR、声学分析 |
| 戏剧能力与情绪 | `performance_tags`、`emotion_tags` | 擅长旁白、对白、低语、长句叙述；可稳定表达平静、紧张等情绪倾向 | 多段标准样本评估 |
| 角色与题材适配 | `role_archetypes`、`scenario_tags` | 叙述者、导师、调查者、权威角色；古风、悬疑；现代题材须经 taxonomy 扩展 | 规则与人工审核 |

建议新增字段保持受控枚举或有限标签，避免自由文本参与筛选。

`pitch_range` 是对音色资产既有听感的离线画像，只用于筛选、排序和选音解释。选定 `voice_id` 后，不得把该字段或角色偏好投影为片段级 `pitch`、`pitch_ratio`、`pitch_semitones`；逐句只允许传递情绪、语气、语速、音量、强弱、停顿、断句、重读、呼吸和句尾处理等表演要求。

### 4.3 建议补充的受控选项

以下是对现有分类的补充建议，不要求一次性全部上线。新字段的值不得与既有字段重复承担同一含义。

| 字段 | 建议选项 | 推荐数量 |
|---|---|---:|
| `pitch_range` | `low`、`low_mid`、`mid`、`mid_high`、`high` | 单选 |
| `pace` | `slow`、`medium_slow`、`medium`、`medium_fast`、`fast` | 单选 |
| `energy` | `low`、`medium_low`、`medium`、`medium_high`、`high` | 单选 |
| `articulation` | `soft`、`clear`、`crisp` | 单选 |
| `temperament_tags` | `authoritative`、`mysterious`、`playful`、`approachable`、`solemn` | 1 至 3 个 |
| `performance_tags` | `narration`、`dialogue`、`emotional`、`whisper`、`authority_delivery`、`comedy`、`long_form` | 1 至 5 个 |
| `role_archetypes` | `narrator`、`protagonist`、`romantic_lead`、`mentor`、`authority_figure`、`investigator`、`professional`、`antagonist`、`comic_relief`、`non_human` | 1 至 5 个 |

术语应以“听感”或“角色适配”表达。例如使用“长者感”或“长者角色适配”，而不是推断真实年龄；使用“男性呈现”，而不是断言真实性别。

### 4.4 标签主归属与兼容规则

每个受控值必须有唯一主归属。这样既避免管理员重复标注，也使筛选和评分语义保持稳定：

| 字段 | 唯一职责 | 不应承载的内容 |
|---|---|---|
| `primary_style` | 单一、最主要的表达/演绎风格；复用现有单选值 | 多个角色气质或具体表演能力 |
| `timbre_tags` | 声音本体的听感质地，如低沉、温暖、略沙哑 | 题材、旁白/对白能力、角色身份 |
| `temperament_tags` | 面向角色选角的印象，如威严、神秘、亲和 | 与 `primary_style` 或 `timbre_tags` 同名的值 |
| `performance_tags` | 已由标准样本验证的表演能力，如旁白、对白、长篇稳定 | 题材或职业角色 |
| `emotion_tags` | 已由标准样本验证、可稳定表达的情绪倾向，如平静、柔情、紧张 | 主表达风格、角色身份或一次性的剧情状态 |
| `scenario_tags` | 使用场景与题材，如有声书、历史、悬疑；现代题材待扩展 | `narration`、`dialogue` 等表演能力 |
| `role_archetypes` | 跨题材的叙事功能，如导师、调查者、权威角色、反派 | `CEO`、记者等无限扩张的职业列表 |

现有 taxonomy 中已经存在 `scenario_tags.narration` 和 `scenario_tags.dialogue`，为保持兼容可继续读取，但应标记为“仅兼容旧数据，不再写入”。兼容期的读写、筛选和迁移规则固定如下：

```text
effective_performance_tags =
  display_profile.performance_tags
  ∪ (legacy scenario_tags ∩ {"narration", "dialogue"})
```

- 新建或重新审核的通用画像、sidecar 和推荐投影不得再把 `narration`、`dialogue` 写入 `scenario_tags`，必须写入 `performance_tags`。
- 兼容旧版公共池输入时，服务端可暂时接受旧值，但必须在写入前归一化到 `performance_tags`；新的 `scenario_tags` 只保留场景和题材值。
- 筛选、排序和推荐一律读取 `effective_performance_tags`。因此筛选 `performance_tags=narration` 或 `dialogue` 时，必须同时命中旧 `scenario_tags` 中的兼容值。
- 已有 `VoicePoolPublication` 不要求立即批量重写。公共池接入正式画像投影时，再执行可审计的 backfill，并保留迁移前后的来源和时间记录。

同理，旧 `primary_style` 值不得自动复制进 `temperament_tags`；新画像只选择其主归属字段。taxonomy API 应将旧场景值标识为 `deprecated_compatibility`，以便调用方停止生成新值但继续正确读取历史数据。

为避免中文别名跨字段冲突，`emotion_tags=tender` 的展示名固定使用“柔情倾向”或“温情倾向”；“温柔”保留给 `primary_style=gentle` 的风格选择。两者在筛选、评分和推荐理由中不得互相命中。

现有 `primary_style=narration` 是历史上的主表达风格值，不自动等同于“已验证具备旁白能力”。它可以继续作为风格展示和风格偏好匹配，但不得同时计入 `performance_tags=narration`；只有标准样本或可信来源产生的 `performance_tags` 证据才能支持旁白能力筛选、排序和推荐理由。这样可避免同一信息在卡片、OR/AND 筛选和评分中被重复计算。

古风/玄幻专有的将领、谋士等可作为版本化题材扩展，不应替代通用原型。增加现代、科幻或其他题材值前，应在 taxonomy 版本中声明值、中文展示名、别名和适用评分规则。

## 5. 标准试听与离线预分析

### 5.1 为什么必须有统一试听样本

供应商音色名称不足以构成可用的分类依据。每个音色都应朗读相同的标准文本，且使用相同输出格式、语速参数和采样要求，才能横向比较。

建议每个音色至少有三类样本：

| 样本 | 建议时长 | 评估目标 |
|---|---:|---|
| 中性旁白 | 15 至 25 秒 | 基础音色、固定文本转写一致性、音高、节奏、稳定性 |
| 克制对白 | 8 至 15 秒 | 对白自然度、细腻度、近距离感 |
| 情绪对白 | 8 至 15 秒 | 情绪张力、能量变化、过载或失真风险 |

文本应固定并版本化。更换文本、模型版本、TTS 参数或供应商音色版本后，需要重新分析，避免新旧画像不可比较。

### 5.2 预分析流水线

```text
供应商目录或自定义音色
  -> 检查授权、可用性与模型能力
  -> 生成或获取标准试听样本
  -> VAD / 音频规范化 / 静音检测
  -> ASR：转写、时间戳、语速、固定文本一致性代理指标
  -> 声学分析：音高、能量、亮度、气声、稳定性
  -> 音频理解模型：受控标签候选与可读摘要
  -> 规则校验、置信度处理、人工抽检
  -> 写入版本化声音画像与检索索引
```

该流程应运行在目录同步、音色创建或显式“重新分析”任务中，而不是在角色选择弹窗打开时同步执行。

### 5.3 各层输出职责

| 层 | 主要输出 | 不应承担的职责 |
|---|---|---|
| ASR | 转写、时间戳、语速、停顿、固定文本一致性代理指标 | 直接判定音色温暖、绝对清晰度或角色类型 |
| 声学特征 | `F0`、能量、频谱、稳定性、气声相关特征 | 直接生成面向用户的自然语言文案 |
| 说话人 embedding | 相似度、聚类、角色声线冲突检测 | 直接判断年龄感或角色适配 |
| 音频理解模型 | 受控标签候选、摘要、角色适配建议 | 无约束地断言真实个人属性 |
| 人工审核 | 修订高曝光目录项、处理低置信度项 | 手工标完全部目录 |

### 5.4 成本、任务与重分析触发条件

标准样本应优先复用供应商可合法使用的试听或已经物化的缓存音频；只有缺少可用样本时才生成新的 TTS 音频。目录级任务不得在用户打开选择器时隐式触发可计费调用。

首次批量成本应在执行前生成清单和报价：

```text
预计费用 = Σ(每个待生成样本的预计可计费单位 × 对应供应商/模型/地区的单位单价)
         + 固定请求费用 + 显式配置的重试预留
```

“可计费单位”由供应商实际合同决定，可以是字符、音频秒数、请求次数或其他单位；报价清单必须记录计价单位、币种、单价版本和适用区域，不能默认按每万字符换算。

任务必须具备预算上限、并发上限、幂等缓存键和失败可恢复能力。缓存键至少包含 `provider`、`source_model`、`source_voice_id`、`sample_type`、`sample_version` 与合成参数哈希。

以下任一变化必须使旧画像进入待重分析状态，而不是静默沿用：

- `source_model`、`source_voice_id`、供应商目录版本或正式试听音频 SHA-256 变化；
- 标准文本、语言、采样规范、情绪指令或 TTS 参数版本变化；
- ASR、声学、embedding 或音频理解分析器版本变化；
- 人工显式要求重分析。

阶段一默认不对全量供应商目录直接发起三段可计费合成。先复用现有试听和人工可读描述，经过预算批准后再分批补齐标准样本。

## 6. 可用模型与工具的定位

模型和供应商能力变化较快。接入前必须以当前官方合同、可用区域、成本、商用条款和接口行为验证为准。下表用于确定能力分工，而不是承诺某个具体版本始终可用。除现有 TTS 目录和合成能力外，下表的分析模型均为待评测候选，不能表述为项目已经接入的能力。

| 能力 | 可选技术类别 | 待评测候选 | 在本方案中的定位 | 项目状态 |
|---|---|---|---|---|
| 中文 ASR | 语音识别模型 | FunASR、SenseVoice、Whisper 类模型 | 转写、节奏、固定文本一致性基础层 | 待接入与基准评测 |
| 说话人分离/聚类 | diarization 与 speaker embedding | pyannote.audio、CAM++、SpeechBrain ECAPA、NeMo | 真人参考音频、多说话人样本、相似音色管理 | 阶段三候选 |
| 声学特征 | 特征提取工具 | openSMILE 等 | 音高、能量、稳定性等可比较指标 | 待接入与基准评测 |
| 副语言分类 | 预训练分类器或微调模型 | Wav2Vec2、WavLM、HuBERT、SpeechBrain 生态的分类器 | 情绪、年龄感/呈现倾向的候选信号 | 仅作候选证据，不直接发布 |
| 音频理解 | 音频多模态模型 | 支持音频输入、约束 JSON 输出的模型，例如 Qwen2-Audio 类架构 | 生成受控标签候选和用户可读描述 | 待独立评测 |

推荐的第一版不训练自有年龄或人格分类器，而是采用“标准样本 + ASR + 声学特征 + 受控音频理解输出 + 人工抽检”的组合。这样能较快形成可用目录，同时保留替换任一模型的能力。

## 7. 正式数据、查询、运行时与 API 合同

### 7.1 接入边界与分阶段实现

声音画像不能直接替换或复制现有 `VoicePoolPublication`，也不能把目录画像混入 `VoiceManager.VoiceProfile`。后者是“角色 -> 实际 speaker/TTS 参数”的运行时对象，不是可跨角色复用的音色目录画像。

阶段一的目标是解决音色选择困难，应以当前主目录路径为中心：

```text
共享 voice catalog / 供应商目录
  -> catalog profile adapter
  -> GET /tts/voices?model=...
  -> 音色选择器、试听与筛选
  -> 用户确认后写入 CharacterVoiceConfig / voice_mapping
  -> VoiceManager 解析、校验与合成
```

对静态供应商目录，第一阶段可使用以 `(normalized_model, voice_id)` 为稳定键的 sidecar 画像投影，并由 `voice_catalog` 合并后返回。sidecar 是目录展示画像的配置 artifact，不是 `VoiceManager` 的运行时配置，也不是 Redis 或数据库缓存；当前阶段以受版本控制的 JSON 文件随目录和服务发布。没有画像的条目返回 `profile_status=pending`，而不是伪造默认标签。这样可以在不改动各 `VoiceManager` 选择逻辑的前提下完成目录展示、描述和筛选。不得因为新画像而把分析逻辑塞进 Manager，也不得在页面请求时调用分析模型。

#### 7.1.1 阶段一 sidecar 格式、发布与失配处理

每个规范化模型由 catalog profile adapter 映射到一个 sidecar 文件。文件名不是 API 合同；稳定合同是模型映射和下列 JSON 结构。顶层必须包含：

| 字段 | 含义 |
|---|---|
| `schema_version` | sidecar JSON 结构版本 |
| `profile_version` | 画像规则和展示字段版本 |
| `taxonomy_version` | 受控枚举和别名版本 |
| `catalog_revision` | 生成时所对应的供应商目录版本、内容哈希或等价指纹 |
| `profile_snapshot_version` | 当前 `normalized_model` 可筛选画像快照的确定性哈希；用于绑定 cursor，不是 schema 或规则版本 |
| `default_analysis_locale` | 未指定 `language` 时使用的默认 BCP-47 画像变体；必须存在于对应音色的变体集合 |
| `generated_at` | 生成候选画像的时间 |
| `generated_by`、`reviewed_by`、`reviewed_at` | 生成任务、批准责任和审核时间的可追溯标识 |
| `voice_profiles` | 以目录 `voice_id` 为键的展示画像；每项包含 `profile_status`、受控标签、来源摘要和当前画像版本 |

`profile_snapshot_version` 由 catalog profile adapter 计算。它必须由 `catalog_revision`、sidecar artifact/content hash，以及按稳定顺序排列的 `(owner_scope, voice_id, analysis_locale, profile_status, current projection/content revision)` 共同确定。静态 sidecar 阶段可使用“规范化 JSON 内容（排除该字段自身）的 SHA-256 + `catalog_revision`”；持久化阶段可改为当前 projection 集合的确定性摘要。任何影响筛选、排序、unknown 分组或可选性的目录/画像变化都必须改变该值；不得仅使用 `schema_version`、`profile_version` 或 `generated_at` 作为该值。

sidecar 的多语言结构固定为 `voice_profiles[voice_id].profiles_by_locale[analysis_locale]`。`profiles_by_locale` 的键必须是规范化 BCP-47 值，每个语言变体独立保存 `analysis_locale`、`profile_status`、受控画像字段和 `projection_revision`；不能用一个无语言的 `profile_status` 覆盖所有语言。未指定 `language` 时使用 `default_analysis_locale`；指定语言时先做 BCP-47 规范化和供应商别名归一化，再执行精确变体匹配。第一版不做隐式跨语言借用；请求语言没有合格变体时，该音色在该语言下进入 `unknown/pending`，不得使用其他语言画像冒充命中。若未来需要语言回退，必须由目录显式声明等价变体并在响应中返回实际使用的 `analysis_locale`。

其结构示意如下（省略未变化的画像字段）：

```text
voice_profiles[voice_id] = {
  profiles_by_locale: {
    "zh-CN": {
      analysis_locale: "zh-CN",
      profile_status: "ready",
      projection_revision: "sha256:...",
      display_profile: { ... }
    },
    "en-US": { ... }
  }
}
```

如果 `/tts/voices` 合并私有音色，API 层的快照还必须纳入当前调用者可见的 `owner_scope` 集合、授权范围哈希和私有画像内容修订；不同调用者不得复用同一 cursor。若暂时无法生成调用者范围快照，阶段一应只返回系统目录和已审核公共音色，私有音色通过独立的用户作用域查询返回。

sidecar 的生成和发布遵循以下职责边界：

1. 目录同步或离线分析任务生成候选文件；用户打开选择器、搜索或试听时不得改写 sidecar。
2. 目录维护责任人核验候选中的来源、高影响字段和公开摘要；非可信来源的高影响字段必须人工批准，满足第 7.4 节条件的直接官方元数据可标为 `trusted_source` 后发布。
3. CI 必须校验模型映射、目录 `voice_id`、受控枚举、版本兼容性和 `catalog_revision`；静态目录中的 orphan sidecar 条目必须作为发布检查问题处理。
4. 服务发布或目录缓存显式失效后重新加载 sidecar；不能依赖进程内旧缓存无限期保留画像。

sidecar schema 不兼容、`catalog_revision` 不匹配，或当前目录 `voice_id` 的画像无效/无法解析时必须阻断发布。供应商正常下架导致的 orphan sidecar 条目首次出现时为 warning，并记录指标和要求明确处置；运行时继续忽略该条目，维护者可删除、归档，或在发布清单中显式标记为 `retired`。orphan 的稳定身份为 `(normalized_model, voice_id, sidecar_lineage)`；发布检查记录必须保存 `first_seen_catalog_revision`、`last_seen_catalog_revision` 和 `disposition`，据此判断同一条目是否连续两个目录发布版本未处置。`retired` 是 orphan 处置状态，不是可返回给运行时的 `profile_status` 值。达到连续两个版本仍未处置时升级为阻断发布，避免历史条目长期遗留。

阶段一的 `/tts/voices` 响应以 `display_profile` 作为唯一标准画像字段。现有目录中名称为 `voice_profile` 的历史 sidecar 必须仅由 catalog profile adapter 映射为该字段；调用方不得同时读取、合并或长期维护两套画像真相。

`profile_status` 的状态转换固定为：目录中存在但没有合格画像时为 `pending`；画像已审核且与当前目录、样本和规则版本一致时为 `ready`；任一重分析触发条件发生后由 `ready` 进入 `stale`，旧画像可供审计和卡片说明但不得参与严格筛选或推荐；新分析审核完成后回到 `ready`。授权、模型能力或目录可用性被撤销时进入 `unavailable`。sidecar 中存在而目录已经移除的音色必须被运行时忽略，不能出现在选择、推荐或合成结果中；同时记录 orphan 指标，要求维护者删除、归档或显式标记该条目。目录移除不应由 sidecar 反向恢复。

阶段二才引入自动角色推荐：统一推荐服务从画像投影读取候选并输出可解释的选择，再写入现有角色配置。各 Manager 的 `select_voice_for_character()` 在迁移期间仅作为画像缺失或服务不可用时的兼容兜底。

```text
角色画像 + 当前模型范围 + 已选角色
  -> VoiceRecommendationService
  -> RecommendationDecision { voice_id, tts_model, voice_source_ref, subject_id, analysis_locale, catalog_revision, profile_snapshot_version, projection_revision, reasons, profile_version, scoring_config_version }
  -> 用户确认 + 运行时配置转换与授权校验
  -> CharacterVoiceConfig / voice_mapping
  -> 现有 VoiceManager / provider adapter
```

`RecommendationDecision` 不是运行时 `VoiceManager.VoiceProfile`，也不得原样塞入 `voice_mapping`。其中 `voice_source_ref` 必须是结构化对象，不得退化为不可解析的自由字符串：

| `voice_source_ref.kind` | 必填身份字段 | 适用来源 |
|---|---|---|
| `provider_catalog` | `provider`、`normalized_model`、`source_voice_id`、`owner_scope=system` | 供应商或预置目录音色 |
| `reference_asset` | `voice_reference_asset_id`、所有者作用域 | 私有参考或复刻音色 |
| `pool_publication` | `voice_pool_publication_id` | 已审核的公共发布音色 |

`voice_source_ref` 与标签证据的 `provenance_ref` 是不同语义的字段。确认选择前，配置转换层必须验证 `voice_id + tts_model` 仍在当前目录可用、来源对象仍处于授权状态，并将 `voice_source_ref` 映射为现有允许的运行时来源引用。运行时配置只保存合成所需的最终音色和来源字段；`subject_id`、`analysis_locale`、`catalog_revision`、`profile_snapshot_version` 和 `projection_revision` 用于复现推荐依据，`reasons`、`profile_version`、`scoring_config_version`、回退原因和用户是否采纳应写入独立推荐审计记录。`profile_version` 是规则版本，不能替代具体投影的 `projection_revision`。

阶段一不调用 `VoiceRecommendationService`，也不改变既有自动分配。阶段二以显式功能开关和用户确认启用新的推荐路径：已确认的角色音色优先使用该选择，不再被自动分配静默覆盖；没有确认选择或推荐服务不可用时才回退既有规则。任何跨模型回退都必须展示模型、能力和费用差异并取得用户确认，不能由现有自动分配在后台隐式完成。

### 7.2 音色身份、分析记录与投影

预置供应商音色、公共发布音色和私有用户音色共享“可被分析”的能力，但可见性、授权和生命周期不同。持久化阶段必须显式区分以下逻辑对象；为避免与现有运行时 `VoiceProfile` 混淆，建议数据库实体使用 `VoiceCatalog*` 前缀：

| 层 | 建议实体 | 职责 | 生命周期 |
|---|---|---|---|
| 音色身份 | `VoiceCatalogSubject` | 一个可分析音色的稳定身份：`source_kind`、`provider`、`normalized_model`、`source_voice_id`、`owner_scope` 和可选资产引用；不以语言拆分身份 | 目录或资产存在期间稳定；不随一次分析覆盖 |
| 标准样本 | `VoiceCatalogSample` | 样本类型、`analysis_locale`、文本/参数版本、音频 URI、SHA-256、时长与生成时间 | 可追加；同一身份可有多段、多语言样本 |
| 不可变分析 | `VoiceCatalogAnalysisRun` | 对一段样本的一次分析：分析器版本、原始声学/ASR 指标、标签候选 | 只追加，不覆盖历史 |
| 标签证据 | `VoiceCatalogTagEvidence` | 单个标签的维度、值、置信度、来源、审核状态，以及可选的分析运行或外部来源引用 | 可追加；由当前画像选择性采用 |
| 当前画像 | `VoiceCatalogProfileProjection` | 聚合样本、规则与人工审核后的当前可展示画像 | 可重建；保留画像版本 |
| 现有实体/API 投影 | `voice_catalog` sidecar、`VoiceReferenceAsset`、`VoicePoolPublication` | 在各自可见性与授权范围内投影允许展示的字段 | 遵循来源生命周期 |

`VoiceCatalogSubject` 不应强制外键到 `VoiceReferenceAsset`：供应商系统音色可能只有 `(provider, normalized_model, source_voice_id)` 而没有用户资产；私有和公共来源则可选关联到资产。`VoicePoolPublication` 只表示用户资产的公共发布状态，不能成为供应商系统目录的画像主表。

实体关系固定为：`Subject 1:N Sample 1:N AnalysisRun 1:N TagEvidence`，且 `Subject 1:N ProfileProjection`。样本和 projection 必须携带 `analysis_locale`，因为同一音色在不同语言、文本和合成参数下可能表现不同。一个 projection 只可引用与该 subject、语言和版本范围相符，并满足审核规则的证据；不应修改旧分析运行来“修正”历史结果。

`VoiceCatalogSubject` 的自然唯一性至少覆盖：

```text
source_kind + provider + normalized_model + source_voice_id + owner_scope
```

其中 `owner_scope` 仅用于私有或账号级自定义音色；供应商系统音色使用稳定的系统范围值。`supported_languages`、`accent`、模型能力、可用性、授权状态、可试听状态和目录版本属于能力或可用性投影，不属于声音身份。`analysis_locale` 使用规范化的 BCP 47 值；当前 API 的单个 `language` 筛选可映射到支持语言集合或当前画像变体。

当前 `VoiceCatalogProfileProjection` 以 `subject_id + analysis_locale` 作为当前画像范围，并通过 `is_current=true` 保证每个范围至多一个当前投影；`profile_version` 记录生成该投影的规则版本，`projection_revision` 记录当前投影内容的不可变版本或确定性内容哈希，历史版本保留为可追溯记录。若未来确实要把“同一音色在不同语言下的表现”当成独立对象，应新增明确命名的 `VoiceCatalogProfileVariant`，而不是把 `language` 偷渡进 `Subject` 的身份键。

`VoicePoolPublication` 当前扁平字段与画像投影的关系如下：

| 当前字段 | 画像投影字段 | 规则 |
|---|---|---|
| `publication_id`、`source_asset_id` | `subject_ref` | 公共发布视图关联其私有资产对应的音色身份；不等同于所有供应商的 `voice_id` |
| `source_model`、`voice_origin` | `source_model`、`provider`、`origin` | 保持当前来源、授权与撤销语义 |
| `language`、`accent` | `supported_languages`、`analysis_locale`、`accent` | `language` 作为兼容 API 筛选条件；分析和评分读取对应语言画像变体，不能遗漏 |
| `gender_presentation`、`age_impression`、`primary_style` | 同名 `display_profile` 字段 | 复用现有枚举 |
| `timbre_tags`、`scenario_tags`、`emotion_tags` | 同名的扁平展示标签 | 保持当前 `list[str]` API 合同 |
| `description` | `display_profile.summary` | 公开 API 继续返回 `description`，避免双文案来源 |
| 无对应字段 | `pitch_range`、`pace`、`energy`、`articulation`、`stability_score`、`temperament_tags`、`performance_tags`、`role_archetypes` | 先存入通用画像投影；是否扩展公共表由后续迁移决定 |

### 7.3 样本、证据与展示画像合同

每段标准样本必须独立记录指标和标签来源。聚合画像不得只保存一组无法追溯的平均值，也不得让公开标签的类型从 `list[str]` 变成对象数组。标签证据与用户读取的扁平画像必须分层：

```json
{
  "subject": {
    "subject_id": "vcs_01H...",
    "source_kind": "provider_catalog",
    "provider": "example_provider",
    "normalized_model": "example_tts_model",
    "source_voice_id": "provider_voice_001",
    "owner_scope": "system",
    "supported_languages": ["zh-CN", "en-US"],
    "voice_reference_asset_id": null
  },
  "sample": {
    "sample_type": "neutral_narration",
    "analysis_locale": "zh-CN",
    "sample_version": "catalog-calibration-v1",
    "synthesis_params_hash": "...",
    "audio_sha256": "...",
    "generated_at": "2026-08-02T00:00:00Z"
  },
  "analysis_run": {
    "analyzer_version": "voice-analysis-v1",
    "taxonomy_version": "voice-taxonomy-v1",
    "metrics": {
      "asr_text_match": 0.96,
      "speech_rate_chars_per_second": 4.2,
      "pause_ratio": 0.17,
      "stability_score": 0.89
    }
  },
  "tag_evidence": [
    {
      "dimension": "timbre_tags",
      "value": "deep",
      "confidence": 0.88,
      "source": "audio_model",
      "provenance_ref": {
        "entity_type": "analysis_run",
        "entity_id": "var_01H...",
        "locator": null
      },
      "source_revision": "voice-analysis-v1",
      "analyzer_version": "voice-analysis-v1",
      "review_status": "approved"
    }
  ],
  "display_profile": {
    "profile_version": "voice-profile-v1",
    "projection_revision": "sha256:...",
    "taxonomy_version": "voice-taxonomy-v1",
    "analysis_locale": "zh-CN",
    "profile_status": "ready",
    "gender_presentation": "male",
    "age_impression": "mature",
    "primary_style": "restrained",
    "timbre_tags": ["deep", "warm"],
    "scenario_tags": ["audiobook", "historical", "suspense"],
    "emotion_tags": ["calm", "tense"],
    "pitch_range": "low_mid",
    "pace": "medium_slow",
    "energy": "medium",
    "articulation": "clear",
    "stability_score": 0.89,
    "temperament_tags": ["authoritative", "mysterious"],
    "performance_tags": ["narration", "dialogue", "long_form"],
    "role_archetypes": ["narrator", "mentor", "authority_figure"],
    "summary": "中低音区，音色温暖、低沉，略带沙哑质感；节奏稳定，适合成熟角色与克制型旁白。"
  }
}
```

`subject_id` 是不透明标识；`source_kind`、`provider`、`normalized_model`、`source_voice_id` 和 `owner_scope` 分别返回，不应再用易歧义的字符串 `subject_key` 拼接身份。若内部需要派生自然键，必须使用完整的五元组、固定转义规则和不可向客户端泄露的所有者标识。

`tag_evidence.provenance_ref` 是标签证据的结构化溯源引用，固定包含 `entity_type`、`entity_id` 和可空的 `locator`。其 `entity_type` 与引用规则如下：

- `analysis_run`：`entity_id` 是 `VoiceCatalogAnalysisRun` 的不透明 ID；
- `catalog_artifact`：`entity_id` 是目录 artifact 或同步记录，`source_revision` 保存供应商目录版本/内容哈希，`locator` 可选为供应商 URL；
- `review_decision`：`entity_id` 是审核决定或工单 ID；审核人、时间和理由仍使用 `reviewed_by`、`reviewed_at`、`decision_reason`；
- `user_override`：`entity_id` 是私有覆盖记录 ID，仅在所有者可见范围内使用。

要求：

- `tag_evidence` 中的每个自动标签都记录 `dimension`、`value`、`confidence`、`source`、`provenance_ref`、`source_revision`、`analyzer_version` 和 `review_status`；不限于 `timbre_tags`。`source` 至少区分 `provider_catalog`、`audio_model`、`acoustic_rule`、`manual_review` 和 `user_allowed_override`；
- `display_profile` 是筛选、排序和推荐的唯一读取层，展示标签固定为受控字符串；
- 质量指标按标准样本保存，并定义单位、静音阈值、文本一致性算法与聚合规则；跨语言指标不得直接混合聚合；
- 每次重分析必须记录样本版本、分析器版本、参数哈希和生成时间；
- 用户可以覆盖私有音色的可读描述和已允许的软标签，但不能覆盖来源、授权或可用性事实；
- 画像摘要可以使用中文自然语言别名，例如“醇厚”，但推荐理由只能引用实际存在的受控值或其 taxonomy 显示名。

`review_status` 的受控状态为 `candidate`、`trusted_source`、`approved`、`rejected`、`revoked` 和 `superseded`。模型、声学规则和用户输入首先作为 `candidate`；只有直接供应商声明且满足第 7.4 节条件的证据可为 `trusted_source`；人工确认后为 `approved`。`rejected`、`revoked` 和 `superseded` 只保留审计记录，不得进入当前 `display_profile`。进入人工状态的证据还必须记录 `reviewed_by`、`reviewed_at` 和 `decision_reason`；`candidate` 可为空。

同一字段冲突时，公共投影按“人工 `approved` > 合格 `trusted_source` > 已审核的模型/规则证据”选择当前值；未审核模型候选不参与公开投影。私有 `user_allowed_override` 只可覆盖所有者可见的软标签和摘要，并须保留原始证据；它不得直接进入公共 `VoicePoolPublication`，公共发布前必须由管理员重新审核。可信官方元数据或人工证据不依赖音频分析样本时，`analysis_run` 可以为空，但 `provenance_ref` 和来源版本不得为空。

### 7.4 置信度、审核与校准合同

置信度是“当前分析器对该标签的校准后可信度”，不是模型输出的原始概率。第一版先采用以下可配置的默认策略，并按 `analyzer_version`、语言和样本类型记录校准版本：

| 条件 | 展示与匹配行为 | 审核动作 |
|---|---|---|
| `confidence < 0.60` | 不进入用户可见标签、不参与筛选或评分 | 进入低置信度队列 |
| `0.60 <= confidence < 0.80` | 可作为内部或所有者私有候选；若获准私有展示，仅弱参与软评分并标记待复核，不进入公共投影或硬筛选 | 按曝光和争议优先复核 |
| `confidence >= 0.80` 且已审核通过，或证据为可信官方元数据 | 可进入展示和软评分；评分可按置信度系数降权 | 正常抽检 |
| `gender_presentation`、`age_impression` 等高影响听感标签 | 不因模型高置信度自动成为公开事实 | 公共展示前必须人工批准，或满足“可信官方元数据”条件 |

“可信官方元数据”必须是供应商目录或接口对该音色直接声明的字段，并在 `tag_evidence` 中保留 `source=provider_catalog`、来源 URL/标识、目录版本和一对一的枚举归一化记录。仅从音色名称、营销文案、旧 sidecar 或项目人员理解中推导出的值，不属于可信官方元数据。无法满足这些条件的模型推断和用户提交值，必须走人工审核。即使来源可信，公开文案仍使用“男性呈现”“长者感”等听感表达，不把它表述为真人事实。

模型分析得到的标签永远不是可用性、授权、模型兼容或语言等硬筛选事实。人工复核优先级不应只按置信度排序，而应综合 `目录曝光量 × (1 - confidence) × 模型/人工分歧`。阈值必须在有人工标注的校准集上验证后才能调整，不能以单次样本观感直接修改。

校准集的建立分阶段进行：阶段一的人工标签和可信官方元数据可以先上线，不依赖自动分析器校准；阶段三必须建立首个版本化校准集；阶段四开放自动初标前，对每个计划公开的 `(标签字段, 主语言)` 组合，至少纳入 50 个经两名审核人独立复核的独立音色；这 50 个样本合计必须覆盖该组合实际使用的标准样本类型。多值标签中每个计划自动公开的值还必须满足版本化发布准入所要求的最小支持量。分歧必须仲裁并保留结果。长尾语言或样本量不足的字段只能作为内部候选或维持人工/官方来源，不得自动公开。每次分析器、taxonomy 或样本规范变更后，均须在固定留出集上重新记录精确率、修正率和置信度校准结果。

### 7.5 筛选 API、数据源与性能策略

公共音色池 API 只覆盖审核通过的用户发布音色；有声书选择器的主目录是 `/tts/voices`。阶段一应先扩展主目录接口，而不是只给 `/voice-pool/public` 增加过滤：

```text
GET /api/v1/audiobook/tts/voices
  ?model=<required>
  &language=<optional, BCP-47>
  &gender_presentation=<optional>
  &age_impression=<optional>
  &primary_style=<optional>
  &pitch_range=<repeatable>
  &pace=<repeatable>
  &energy=<repeatable>
  &articulation=<repeatable>
  &timbre_tags=<repeatable>
  &temperament_tags=<repeatable>
  &performance_tags=<repeatable>
  &scenario_tags=<repeatable>
  &emotion_tags=<repeatable>
  &role_archetypes=<repeatable>
  &include_unknown=<optional, default=false>
  &limit=<optional>
  &cursor=<optional>
```

返回项必须包含 `profile_status`，即 `ready`、`pending`、`stale` 或 `unavailable`。`language` 先过滤音色的 `supported_languages`，有对应语言画像变体时再选择该 `analysis_locale` 的 `display_profile`。未分析的新目录或私有音色不能伪造画像标签。

调用方提供任一画像标签筛选时，主结果集只能包含已验证命中的 `ready` 条目。`pending` 和 `stale` 都属于 `unknown`：前者没有可用画像，后者画像已失效等待重分析；二者不得被标记为匹配或不匹配。`include_unknown=true` 时，接口将它们分别作为“待分析候选”和“待重分析候选”单独返回，不计入命中数量、不参与主结果排序或推荐。未筛选画像标签时，调用方也只能在 `ready` 主列表之后展示 unknown 分组。`unavailable` 条目不可作为可选择的合成候选。`model` 是必填筛选范围，默认不跨模型混合候选。公共池接口可采用同一参数与返回语义，但仍须执行其独立的审核和授权过滤。

当 `include_unknown=true` 时，响应必须分别提供 ready 主结果、`pending` 待分析结果和 `stale` 待重分析结果的分页游标：`next_cursor`、`unknown.pending_next_cursor`、`unknown.stale_next_cursor`。unknown 分组只应用模型、语言、授权、可用性和可试听等硬条件；画像标签条件不能把 unknown 项判为命中或不命中，也不能生成标签命中理由。每个分组使用自己的稳定排序和游标，不能让 unknown 项占用 ready 主结果的分页位置。

taxonomy API 应为每个受控值发布稳定的 `value`、中文 `label`、`aliases`、`taxonomy_version` 和兼容状态。别名可用于自然语言映射，不得成为存储值。

`pitch_range`、`pace`、`energy` 与 `articulation` 均为受控离散字段，和其他可重复参数一样采用“同字段 OR、跨字段 AND”的筛选语义。UI 应将 `energy` 命名为“发声能量/力度”；“情绪张力”不等同于 `energy`，应由 `emotion_tags` 或 `performance_tags=emotional` 表达。阶段一允许这些字段参与目录筛选，但不引入阶段二的角色评分或个性化排序。

筛选语义固定为：

| 场景 | 语义 |
|---|---|
| 同一多选字段内 | OR，例如选择 `deep` 或 `warm` 时任一命中即可 |
| 不同字段之间 | AND，例如“成熟感 + 低沉 + 古风”须同时命中 |
| 显式标签筛选时标签缺失 | `ready` 条目不命中；`pending`、`stale` 条目进入各自 unknown 分组，不伪造匹配 |
| 仅进行推荐排序时软标签缺失 | 保留为较低排序候选，不伪造匹配；按实际参与评分的权重归一化 |
| 缺失硬条件 | 不展示或不可选择 |
| 自然语言无法映射的词 | 保留为全文检索词或提示用户改用受控标签 |

`performance_tags` 的筛选、排序和推荐必须读取第 4.4 节定义的 `effective_performance_tags`，从而兼容历史 `scenario_tags.narration/dialogue` 数据。`scenario_tags` 参数只面向场景和题材；调用方不得再用它写入新的旁白或对白能力。

对当前“数百个”的静态目录，缓存后的 `voice_catalog` 内存筛选和实时规则评分足够，不能为了六维评分预先构建音色-原型矩阵。引入预计算、向量索引或离线排序的条件应是实测容量或 p95 延迟超出目标，而不是预先猜测。

公共池或通用画像进入数据库检索时，必须二选一并保持单一真相来源：

1. 对既有扁平标签字段采用 PostgreSQL `JSONB`、GIN 索引和包含/重叠查询；迁移必须显式完成类型和索引变更，不能假设通用 `JSON` 自动获得 `JSONB` 索引能力。
2. 对需要标签级置信度、来源和审核状态的新画像，采用受控标签关联表；现有 `list[str]` JSON 字段仅作为兼容 API 投影。

无论采用哪种方案，都必须补齐 repository、API 参数校验、cursor 稳定排序和测试。至少覆盖同字段 OR、跨字段 AND、跨模型隔离、未分析项降级、公共/私有授权隔离和分页稳定性。若使用 PostgreSQL 专属 `JSONB + GIN`，还必须补 PostgreSQL 集成验证，不能只依赖 SQLite 仓储测试。

响应元数据必须返回当前 `catalog_revision`、`profile_snapshot_version` 和 cursor。cursor 是不透明值，除绑定 `catalog_revision`、`profile_snapshot_version` 外，还必须绑定规范化后的 `query_fingerprint`、固定的 `sort_spec`、分页分组和最终稳定的 tie-breaker。`query_fingerprint` 至少覆盖 `model`、`language`、所有画像筛选参数、`include_unknown` 和 `limit`；第一版 `sort_spec` 固定为 `display_name ASC, voice_id ASC`，`voice_id` 是最终 tie-breaker。若结果包含私有音色，cursor 还必须绑定调用者的授权范围哈希，不得跨用户复用。分页期间若目录、画像状态、授权范围或查询条件发生变化，服务端不得在同一 cursor 链路中混用新旧快照；应返回“快照已过期或查询条件已变化、请重新查询”的可处理错误，或按已固定的快照继续返回，二者只能选择一种并在 API 合同中保持一致。第一版推荐前者，以避免 `pending/stale/ready` 状态变化导致重复、遗漏或排序漂移。

## 8. 角色画像与音色匹配

### 8.1 角色画像

角色侧至少需要提供可选的、可编辑的声音偏好：

```json
{
  "character_name": "陆衍",
  "gender_presentation": "male",
  "age_impression": "mature",
  "voice_preferences": {
    "primary_style_preferences": ["restrained"],
    "temperament_tags": ["authoritative", "mysterious"],
    "pitch_range": ["low", "low_mid"],
    "pace_preferences": ["medium_slow"],
    "energy_preferences": ["medium"],
    "articulation_preferences": ["clear"],
    "stability_min": 0.80,
    "timbre_tags": ["deep", "warm", "slightly_husky"],
    "performance_tags": ["dialogue", "authority_delivery"],
    "emotion_tags": ["calm", "tense"]
  },
  "scenario_tags": ["historical", "suspense"],
  "role_archetypes": ["mentor", "authority_figure"]
}
```

`primary_style_preferences` 是角色对单选 `primary_style` 的可选偏好列表，不创建另一套音色字段。`pace_preferences`、`energy_preferences` 和 `articulation_preferences` 分别匹配画像中的 `pace`、`energy` 和 `articulation`；`stability_min` 是可选的质量下限，取值范围为 0 到 1。上述发声偏好、`temperament_tags`、`performance_tags` 和 `emotion_tags` 均可由用户编辑，未填写的维度不参与评分归一化，不由 LLM 擅自补默认值。`temperament_tags` 表示角色需要呈现的选角印象；`performance_tags` 表示需要完成的演绎能力；`emotion_tags` 表示需要稳定表达的情绪倾向。三者不得互相代写，也不得与合成阶段逐句控制的运行时情绪参数混用。

角色描述可以由小说设定或 LLM 提取为初始建议，但用户应能修改。角色没有明确设定时，不应虚构性别、年龄感或性格硬条件。小说职业、题材词或人物关系可以作为 LLM 提示上下文，不能自动膨胀为不受控的 `role_archetypes` 值。`non_human` 角色默认不填写年龄感和性别呈现；未填写的维度不参与评分归一化，而不是得到零分。用户显式指定某种呈现时，仍应按普通角色规则参与匹配。

### 8.2 评分逻辑

第一版采用固定、版本化的规则评分，保持可解释性。`scoring_config_version` 必须随推荐结果保存；在积累足够反馈前，不按题材预设多套权重。

| 项目 | 建议权重 | 说明 |
|---|---:|---|
| 年龄感匹配 | 25% | 用户明确时权重更高 |
| 性别呈现匹配 | 20% | 用户明确时可作为强偏好 |
| 音色质感匹配 | 20% | 标签交集与权重匹配 |
| 主表达风格与角色气质匹配 | 8% | `primary_style` 对 `primary_style_preferences`，以及 `temperament_tags` 的交集；前者如 `restrained`、`gentle`、`cold`，后者如 `authoritative`、`mysterious`、`approachable`、`solemn` |
| 表演能力与情绪匹配 | 7% | `performance_tags` 与 `emotion_tags` 的交集；如旁白、对白、长篇稳定、平静、紧张 |
| 角色原型匹配 | 10% | 如旁白、导师、调查者、权威角色、反派 |
| 场景/题材匹配 | 5% | 如古风、悬疑、玄幻 |
| 节奏与能量匹配 | 5% | `pace_preferences`、`energy_preferences`、`articulation_preferences` 与 `stability_min` 对应的语速、能量、吐字和长篇稳定性 |

“克制、温柔、清冷”等表达风格只匹配 `primary_style`；“威严、神秘、亲和、庄重”等选角印象只匹配 `temperament_tags`；旁白、对白等只匹配 `performance_tags`；平静、紧张等只匹配 `emotion_tags`。这四类值不得通过自然语言近似而跨字段命中。UI 可显示中文别名，但别名必须由 taxonomy 明确映射到唯一受控值。

推荐算法按以下固定顺序执行：

```text
1. 过滤：当前模型、语言、可用状态、授权状态和可试听状态不满足时剔除。
2. 强偏好：用户明确填写年龄感或性别呈现时，优先保留命中项；命中项不足 6 个才降级为软分。
3. 软评分：只读取 `profile_status=ready` 且满足置信度/审核策略的已知标签；`primary_style`、`temperament_tags`、`performance_tags` 和 `emotion_tags` 分别按其定义字段匹配。未知软标签不命中，不补造默认值。
4. 归一化：按实际参与评分的权重归一化，避免缺失字段使候选被不合理惩罚。
5. 回退：候选不足 6 个时，按“减少题材 -> 减少气质 -> 减少年龄感/呈现强偏好”的顺序放宽，并记录回退原因。
6. 可解释性：推荐原因只引用实际命中的标签和质量指标。
```

推荐计算只消费当前且可审核的 `ready` 画像。`pending`、`stale` 和 `unavailable` 都不是“零分的已知不匹配”：前两者只能作为待分析或待重分析候选单独说明，后者不得进入候选池。对某个显式筛选条件，结果状态必须区分 `ready-match`、`ready-nonmatch` 和 `unknown`，推荐理由只能从 `ready-match` 的实际证据生成。

第一版的范围是当前 TTS 模型内的推荐，不自动为某个角色切换模型。现有运行时若保留跨模型自动分配，必须把模型变更、费用差异、模型能力差异和用户确认作为独立产品流程，不能在一次隐式评分后自动发生。按题材配置权重属于后续优化，前提是已有可校准的采纳、跳过和人工修正数据。

筛选后应返回：

- 最匹配：6 个候选；
- 可替代：6 个候选；
- 风格反差：最多 3 个候选；
- 全部结果：供用户主动展开。

每个候选必须展示推荐原因，例如：

> 成熟感与中低音匹配角色设定；具备低沉、温暖、主风格克制和长句旁白能力，适合古风导师型角色。

### 8.3 角色间可区分度

多人有声小说仅做单角色匹配不够，还应检查角色声线是否过于相近：

1. 使用说话人 embedding 或声学画像计算候选音色相似度；
2. 已绑定角色的音色与新候选过近时降低推荐分；
3. 不阻止用户选择，但显示“与角色 X 听感接近”的提示；
4. 旁白与高频主角色应优先保证可区分度。

## 9. 用户体验设计

用户不应面对几十个技术标签。建议按角色选角的自然顺序组织：

### 9.1 角色入口预设合同

“旁白、少女、长者、反派”等是用户入口，不是可直接写入数据库的标签。阶段一只提供目录筛选，不展示角色预设或个性化排序；阶段二由后端或 taxonomy API 以版本化 `CharacterVoicePreferencePreset` 返回 `preset_id`、默认偏好、强偏好、可编辑字段和 `taxonomy_version`。该概念不能与现有“直接选择 `voice_id`”的运行时预设混用。前端不得各自硬编码映射，预设只初始化用户可修改的偏好，不替代角色设定。

| 用户入口 | 默认偏好 | 不自动推断的内容 |
|---|---|---|
| 旁白 | `role_archetypes=[narrator]`，`performance_tags=[narration]` | 年龄感、性别呈现、具体题材 |
| 主角 | `role_archetypes=[protagonist]` | 性别、年龄感、恋爱关系 |
| 少女 | `gender_presentation=female`，`age_impression=[teen, young_adult]` | `romantic_lead`、具体性格 |
| 少年 | `gender_presentation=male`，`age_impression=[teen, young_adult]` | `protagonist`、具体性格 |
| 成熟角色 | `age_impression=[mature]` | 性别、职业、权威身份 |
| 长者 | `age_impression=[elder]` | `mentor`、性别、职业 |
| 儿童 | `age_impression=[child]` | 性别、可爱或活泼风格 |
| 反派 | `role_archetypes=[antagonist]` | 性别、年龄感、冷峻或阴沉气质 |
| 非人类 | `role_archetypes=[non_human]`，年龄感和性别呈现留空 | 机器人、精灵、系统提示音等具体类型 |

除用户明确锁定的条件外，预设中的年龄感和性别呈现默认属于强偏好，可按第 8.2 节的回退策略放宽。

### 9.2 阶段二角色选角与筛选流程

1. 选择角色类别：旁白、主角、少女、少年、成熟角色、长者、儿童、反派等；这是面向用户的组合入口，不直接等同于 `role_archetypes` 的存储值。
2. 选择声音气质或表达能力：温柔、沉稳、清冷、威严、热血、神秘、喜剧演绎等。
3. 选择音色质感：清亮、低沉、磁性、温暖、沙哑、气声等。
4. 必要时展开高级筛选：语速、音高、发声能量/力度、吐字方式、情绪倾向、题材、模型和语言。
5. 对候选使用同一试听文本，支持 A/B 对比和设为角色音色。

### 9.3 候选卡片与自然语言输入

候选卡片至少展示：

```text
音色名称
成熟感 · 男性呈现 · 中低音
低沉 / 温暖 / 略沙哑
威严 / 神秘 / 旁白能力强
适合：导师、权威角色、古风旁白
[试听] [设为角色音色] [查看相似音色]
```

自然语言搜索可以作为增强功能，将“老年男声，古风，威严，低沉”映射到受控标签，而不依赖名称模糊搜索。

界面中的自然语言词必须映射到单一主归属字段，例如“温柔”映射到 `primary_style=gentle`，“清冷”映射到 `primary_style=cold`，“威严”映射到 `temperament_tags=authoritative`。无法唯一映射的词只能作为全文检索或二次选择提示，不能直接写入画像。

“诙谐”是歧义输入，不能直接写入画像。用户选择“擅长喜剧/诙谐演绎”时，映射到 `performance_tags=comedy`；用户选择“人物气质活泼、俏皮”时，映射到 `temperament_tags=playful`。用户没有作出该二次选择时，“诙谐”仅作为全文检索词或二次选择提示，不根据旁白、反派等角色入口自动猜测，也不直接生成画像标签或推荐理由。

## 10. 质量、隐私与授权边界

### 10.1 描述边界

允许展示：

- “长者感”“少年感”“成熟男性呈现”；
- “略带气声”“清亮”“低沉”“情绪张力强”；
- “适合长者、旁白、谋士、反派等角色”。

避免展示：

- 真实年龄、真实性别、健康状态、职业、人格等事实性断言；
- “长期吸烟”“患有某疾病”等无关且不可验证的推断；
- 对真人参考音频的身份识别或超出授权范围的分析。

### 10.2 授权与数据处理

- 仅分析已获授权的音频或平台可用的预置 TTS 输出；
- 原始克隆录音不因创建声音画像而自动进入公共音色池；
- 公共池沿用当前 `rights_basis`、授权版本和审核机制；
- 用户应能查看、编辑或删除其自定义音色的展示描述；
- 对低置信度和争议性标签提供人工修订入口。

### 10.3 质量验收指标

第一版应同时评估技术质量和产品质量：

| 指标 | 建议目标 |
|---|---|
| 已分析的可用目录覆盖率 | 大于等于 95% |
| 标准试听 ASR 文本一致性 | 低于阈值的音色进入人工复核 |
| 标签校准质量 | 按字段、主语言、样本类型和分析器版本持续记录人工标注集的精确率、修正率与置信度校准结果；自动公开前满足第 7.4 节最小复核量 |
| sidecar 一致性 | 每次发布均通过模型映射、目录键、taxonomy、版本和 orphan 校验 |
| 画像状态质量 | `pending`、`stale`、`unavailable` 不进入严格命中或推荐理由；状态转变可审计 |
| 用户从筛选到首次试听的候选数 | 明显低于全量浏览方式 |
| 推荐结果被直接采用或加入候选的比例 | 持续记录并用于调权 |
| 用户人工修改标签的比例 | 识别错误分类和缺失标签 |
| 高曝光音色人工抽检覆盖率 | 100% |

每次 taxonomy、样本、分析器、sidecar schema 或目录版本变更后，都应使用固定的标注样本集做回归验证。验收测试至少覆盖：标签主归属、新旧 `scenario_tags` 兼容映射、置信度阈值和来源优先级、标签筛选 OR/AND（包含 `pitch_range`、`pace`、`energy`、`articulation` 参数）、跨模型和语言隔离、授权撤销、`pending/stale` 三值语义、推荐理由只引用真实命中项，以及绑定快照的 cursor 分页稳定性。

## 11. 分阶段实施建议

### 阶段一：目录可筛选化

- 将画像首先接入 `voice_catalog -> /tts/voices`，而非只接入公共发布池；
- 复用现有 taxonomy，并为静态供应商目录建立包含 schema、画像、taxonomy、目录版本和来源责任的 sidecar 展示画像；
- 为预置音色和公共音色补充可读描述、现有标签和可复用试听；是否批量生成三段标准样本受预算门控；
- 在音色选择器增加模型范围、语言、年龄感、质感、主要风格、场景、表演能力、情绪倾向、音高、语速、发声能量/力度和吐字方式筛选，以及绑定目录/画像快照的稳定分页；
- 采用服务端/目录适配层筛选，静态数百条目录允许使用缓存内存筛选；
- 对 `pending`、`stale` 只提供独立 unknown 分组，不把它们混入严格匹配或伪造标签；
- 只提供筛选与稳定排序，不做角色预设、角色个性化排序、自动角色推荐、自动跨模型切换或 embedding 差异度计算。

### 阶段二：角色候选池

- 引入角色声音偏好；
- 引入版本化 `CharacterVoicePreferencePreset`，将角色入口预填为可编辑偏好；
- 引入 `VoiceRecommendationService`，将统一画像评分结果转换为现有 `voice_mapping` 可消费的音色选择；
- 基于版本化规则评分返回最匹配、可替代和风格反差候选；
- 展示推荐理由；
- 保存用户的最终选择、回退原因和手动调整到独立推荐审计记录，形成反馈数据；
- 通过显式功能开关和用户确认写入运行时配置；仅在当前 TTS 模型内推荐。跨模型推荐需要另行设计成本、能力差异和用户确认流程。

### 阶段三：目录质量与角色差异度

- 接入标准样本的说话人 embedding；
- 在多角色项目中检测声线相似度；
- 建立低置信度、低质量、需复核的音色工作队列；
- 建立按字段和主语言分层、双人复核的校准集，并用留出集校验分析器版本；
- 用用户试听、选用和跳过数据校准推荐权重。

### 阶段四：自动初标与运营闭环

- 对新增或变更音色自动生成试听和初始画像；
- 引入音频理解模型生成受控标签候选；样本量或校准不达标的字段只保留为内部候选；
- 管理端审核高曝光、低置信度或异常标签；
- 对分析器、样本和目录版本建立回归评估。

## 12. 实施前需确认的决策与推荐默认值

以下默认值用于消除“全部待定”造成的启动阻塞。产品或合规要求不同时，应修改对应决策并提升版本号。

| 优先级 | 决策 | 推荐默认值 | 原因 |
|---|---|---|---|
| P0 | 阶段一接入位置 | 先接入 `voice_catalog -> /tts/voices`；公共池只作为附加来源 | 这是当前选择器主目录，改动最小且不混淆授权模型 |
| P0 | 标准试听成本 | 不对全量目录自动产生可计费三段试听；先复用可用试听，批处理必须有清单、报价和预算确认 | 防止目录同步隐式消耗预算 |
| P0 | 画像存储 | 静态目录先用受版本控制的 JSON sidecar；`/tts/voices` 只暴露 `display_profile`，分析历史、审核和多来源再引入 `VoiceCatalog*` 实体 | 避免双画像真相和阶段一过早迁移全部目录 |
| P0 | sidecar 生命周期 | 强制 schema/profile/taxonomy/catalog 版本与 `profile_snapshot_version`、CI 校验、分级 orphan 处置和 `pending -> ready -> stale/unavailable` 状态语义 | 使目录变化、重分析和缓存刷新可追踪 |
| P0 | 分页快照 | 响应和 cursor 同时绑定 `catalog_revision + profile_snapshot_version`；快照变化时返回“快照已过期、请重新查询” | 防止画像状态变更造成重复、遗漏或排序漂移 |
| P0 | taxonomy 主归属 | 采用第 4.4 节规则；通过 `effective_performance_tags` 兼容旧 `scenario_tags.narration/dialogue`，新数据不再写旧值 | 防止新旧标签系统再次重叠 |
| P0 | 阶段一筛选范围 | 目录筛选包含音高、语速、发声能量/力度和吐字方式；情绪张力用 `emotion_tags` 或 `performance_tags=emotional` 表达 | 让筛选 UI、taxonomy 与 API 参数一致，且不把能量误当情绪 |
| P0 | 未知画像筛选 | 主结果只包含 `ready` 已验证命中项；`pending/stale` 仅按 `include_unknown` 单独返回，cursor 绑定 `catalog_revision + profile_snapshot_version` | 保持筛选、排序和分页语义可信 |
| P0 | 角色画像来源 | 用户可编辑为准，LLM 仅生成草案 | 避免从小说文本虚构硬条件 |
| P0 | 推荐范围 | 阶段一不做推荐；阶段二仅在当前模型内、经功能开关和用户确认后写入运行时配置 | 保持能力、费用和合成路径可预测 |
| P0 | 自动标签审核 | 高影响公开标签必须人工审核，或采用带直接来源、版本和一对一归一化记录的可信官方元数据；其他标签执行第 7.4 节置信度策略 | 保持描述边界和可解释性 |
| P1 | 公共与私有可见性 | 私有画像只对所有者可见；公共展示遵循 `VoicePoolPublication` 审核与撤销状态 | 不把目录分析能力等同于公开授权 |
| P1 | 语言身份 | `VoiceCatalogSubject` 表示音色本体；语言作为 `analysis_locale` 画像变体和支持能力，不进入 Subject 唯一键 | 避免多语言音色重复建身份 |
| P1 | 角色入口预设 | 阶段二由 `CharacterVoicePreferencePreset` 提供版本化映射，不由前端硬编码 | 避免用户入口与存储 taxonomy 混淆 |
| P1 | 题材扩展 | 先使用通用原型；现代、科幻等值按 taxonomy 版本和评分规则扩展 | 防止职业枚举无限增长 |

## 13. 结论

音色库的可用性瓶颈不是缺少更多试听按钮，而是缺少可检索、可解释、可比较的声音画像。实现时应将 ASR 定位为固定文本一致性代理和节奏分析组件，与声学特征、音频理解、受控 taxonomy 和人工复核共同组成离线预分析链路。

第一优先级应是让当前 `voice_catalog` 中已有的音色拥有稳定、可读、可筛选、可追溯的画像，并通过 `/tts/voices` 进入现有选择器；公共池和私有资产在各自授权边界内复用同一 taxonomy、画像投影和审核语义。完成后再做经用户确认的角色自动匹配和角色间声线差异优化。这样能以最小风险解决用户“音色过多、名称无意义、必须逐个试听”的核心问题。
