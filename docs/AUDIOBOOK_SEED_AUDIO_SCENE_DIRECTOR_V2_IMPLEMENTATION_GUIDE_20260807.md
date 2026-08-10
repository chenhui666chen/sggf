# 有声小说 Seed Audio 场景导演 V2 实施指导

> 文档状态：待实施  
> 创建日期：2026-08-07  
> 文档版本：R13（正式定稿）  
> 最近修订：2026-08-10（定稿修订 R13：统一 hash 基础设施提前到阶段 1 消除依赖倒置、§16 台词验证四类合同措辞与 §10.4 对齐；R12：append-only checkpoint 迁移归属阶段 1、实施索引补充 V2 规划模块边界；R11：阶段 4 hash 基础设施表述与 §12.2 职责分离对齐、恢复记录外部唯一键账号作用域、恢复方式判别字段与字段可选性；R10：canonical_hash 与 content_digest 职责分离、checkpoint append-only 版本迁移、恢复记录双层幂等键与状态转换、基础设施验收进入完成定义；R9：canonical hash 统一规范、checkpoint 基础设施映射到阶段 3/4/5、原始转写数据治理、checkpoint schema 版本与历史迁移、短期恢复记录状态与幂等键；R8：原始转写可重规范化持久化、规范化输出与统一 artifact hash、Seed 缓存键只用 binding_decision_hash、转写来源判别联合、临时 URL 短期恢复记录；R7：Seed 输入签名与输出分离、L0 result 移出缓存键、Omni 字幕/ASR 签名、Transcript 原始/规范化分层、场景级 voice identity hash、binding 决策/审计拆分；R6：Omni 完整期望合同签名、Seed provider 请求合同、Transcript/L0 双层签名、Director checkpoint 状态与恢复、绑定计划 hash 规范化；R5：Director 输入签名、Omni 评审签名、级联失效语义、L0 质量 checkpoint 拆分、证据字段简化、推导开关入策略；R4：semantic_only 允许消费、证据判别联合、Director 策略所有权与冻结、BOF/EOF 与无 hard 场景、checkpoint 分类完整清单、轻微停顿移出 vocalization；R3：optional 有序对齐、vocalization 结构化证据、Director 运行时保护进入阶段 3、timeline 模式分别开放、产品模式可见性；R2：统一可辨识语音事件模型、消除第二份台词事实源、vocalization 评审语义、条件式完成定义、回滚保真约束、能力合同派生；R1：模型能力合同、台词验证策略、时间轴契约验证、导演预算与失败降级、阶段顺序调整）  
> 适用范围：有声小说 `seed_scene` 模式  
> V1 基线：`docs/AUDIOBOOK_DOUBAO_SEED_AUDIO_SCENE_ENGINE_PLAN_20260720.md`

## 1. 文档定位

V1 已完成 Seed Audio 场景引擎的基础接入，包括场景规划、确定性 Prompt 编译、参考音频解析、单场景渲染、字幕/ASR 台词闸门、检查点、局部回退、章节装配、响度处理、进度和计费。V2 不推翻这些能力，而是解决上游剧本事实模型仍以逐句 TTS 和分轨合成为中心、无法充分表达统一声音场景的问题。

V2 的核心目标是建立一条专用于 Seed Audio 的场景导演路径：

```text
小说原文
  -> 公共剧情与台词事实
  -> 已审定 ScriptSegment[]
  -> Seed 场景导演计划 SeedSceneDirection[]
  -> VoiceIdentityRegistry / SceneVoiceBindingPlanner
  -> ScenePlanner
  -> SceneAudioEvent[]
  -> ScenePromptCompiler
  -> seed-audio-1.0-multilingual
  -> 确定性质量闸门
  -> Qwen Omni 音频语义评审
  -> 场景装配与章节接缝评审
```

本文是 V2 的当前实施事实源。V1 文档继续保留历史接口验证、价格事实、灰度记录和已完成修复，不在本文重复维护。

## 2. 已确认决策

### 2.1 成品生成模型

- 新创建的 `seed_scene` 任务统一默认使用 `seed-audio-1.0-multilingual`。
- `seed-audio-1.0-multilingual` 与 `seed-audio-1.0` 使用相同用户价格：`¥1.0/分钟`，即 `¥0.0166666667/秒`。
- `seed-audio-1.0` 不再作为新任务的默认或普通用户可见选项，但代码、适配器、计费识别和历史恢复能力必须保留。
- 历史 checkpoint 按其原始模型恢复，不把既有 `seed-audio-1.0` 任务静默改为 multilingual。
- 紧急回滚和受控 A/B 可以显式使用 `seed-audio-1.0`。

推荐的模型集合语义：

```python
DEFAULT_SEED_AUDIO_MODEL = "seed-audio-1.0-multilingual"
KNOWN_SEED_AUDIO_MODELS = frozenset({
    "seed-audio-1.0",
    "seed-audio-1.0-multilingual",
})
SEED_AUDIO_MODELS = KNOWN_SEED_AUDIO_MODELS
```

上游 Prompt 能力合同：

- `_analysis.py` 与 `_transform.py` 中 seed 模式说明块当前硬编码“主生成模型：seed-audio-1.0”，不得继续写死任何供应商模型 ID。
- 能力描述按已验证能力构造，不得硬编码能力状态。推荐引入 `SeedSceneCapabilityContract`（字段 `multi_speaker/sound_effects/music/acoustic_space/bounded_timeline/strict_timeline/contract_version`），字段值从阶段 1 登记的 `config/models.yaml` 条目能力派生；Prompt 只描述当前已启用能力。
- 首期最小文案：“主生成路径：Seed Audio 完整声音场景模式，支持多角色、音效、音乐和声学空间；时间轴控制仅在运行时策略已通过契约验证并启用时可用；真实模型 ID 由运行时配置决定。”
- 阶段 0 时间轴验证通过前，分析与改编 Prompt 不得把时间轴控制描述为已开放能力。
- 分析、改编、渲染、checkpoint 和账单中的模型能力口径必须一致；历史 checkpoint 按原始模型恢复时不被静态 Prompt 文案误导。
- 回归断言：seed_scene 模式的分析与改编 Prompt 不得包含过期硬编码主模型声明。

产品层只显示“场景生成”，不要求普通用户理解两个供应商模型 ID。节奏模式只展示已通过 capability contract 验证并由运行时策略启用的项：

- `natural`：始终可用；自然节奏，使用相对时序 Prompt。
- `bounded_timeline`：只为关键台词和关键事件生成时间窗；仅在对应能力通过阶段 0 验证后显示。
- `strict_timeline`：广告、卡点和固定总时长内容使用完整 `[start:end]` 时间轴；仅在对应能力通过阶段 0 验证后显示。

API 层区分三类值：schema 已知枚举值、当前可选值、历史 checkpoint 可恢复值；模式存在于 schema 枚举不代表允许新任务选择。

### 2.2 质量评审

- ASR、字幕文本一致性和本地波形检测继续作为确定性硬闸门。
- `qwen3.5-omni-flash` 作为新增的音频语义评审模型，不替代 ASR。
- Omni 首期使用影子评审，不自动重试或阻断正式成品。
- 只有经过人工盲评标定的高置信严重问题，后续版本才允许触发一次针对性重试。
- 场景级评审是主路径；章节级只评审相邻场景接缝，不默认把整章长音频一次性提交给 Omni。

### 2.3 台词事实边界

- `ScriptSegment.text` 继续作为可辨识台词和旁白的唯一审定事实源。
- Seed 场景导演层不得润色、改写、增删或重新归属台词。
- 导演计划引用 `source_segment_index`，不复制形成第二份可独立修改的台词事实。
- “对”“嗯”“啊”等内容必须区分可辨识语言与非语言人声。
- 原文或审定剧本不存在的完整插话不得为了热闹自行新增。

## 3. 当前实现差距

### 3.1 场景级上下文没有从入口贯通

`SceneRenderMixin._try_generate_seed_scene_chapter()` 调用 `ChapterScenePipeline.render()` 时只传入 `voice_mapping`、`model` 和 `checkpoints`，没有传入：

- `scene_description`
- `descriptions`
- `default_tts_model`

后果：

- Prompt 顶层场景描述使用兜底文案。
- 角色描述只能依赖 voice mapping 内部字段。
- 缺少逐角色 `tts_model` 时，Seed-TTS 2.0 原生 `speaker` 直传可能无法识别默认模型。
- 章节摘要、时间地点、整体空间声学和 AudioDirector 策略没有成为场景计划事实。

`instruct_scene` 仍会被编译为编号事件，所以不能把现状描述为“所有空间信息都丢失”；准确问题是缺少稳定、局部、可审计的场景总上下文，并且切分后的状态承接依赖 segment 重复填写。

### 3.2 Seed 专用指导仍受旧数据合同限制

剧本分析、改编和质量审查已经识别 `audio_engine_mode == "seed_scene"`，但最终仍输出旧 `ScriptSegment`：

- 单一 speaker。
- 单一 text。
- 当前 speaker 的 performance notes。
- 挂载在单个片段上的 sound effects。
- 单个 music cue。

该结构不能稳定表达：

- 其他角色在当前台词期间插话。
- 前景和背景人声。
- 两人重叠、错落或抢话。
- 连续音效蒙太奇。
- 电话、远端、混响、空间移动等声学处理。
- 音乐跨多个片段的进入、变化、停止和承接。
- 场景节拍及不可切断的问答、因果动作或情绪弧。

### 3.3 改编 Prompt 混入分轨规则

Seed 专用指导之后仍拼接共享的分轨导向规则，例如每片段最多两个音效、分轨音量、素材参数、配乐覆盖率和独立可合成片段。这些规则会诱导 LLM 把完整场景拆成多个孤立 TTS 单元，并压缩 Seed Audio 可一次完成的多人互动和音效序列。

### 3.4 场景时长估算不包含声音事件区间

当前规划只累计台词估算和前后停顿。顺序发生的音效、音乐前奏、非语言表演、背景插话和转场链没有进入时长预算，可能使计划值明显低于实际输出。

### 3.5 最终音频评审不理解声音内容

当前最终评审只检查：

- 时长和文件属性。
- 波形技术质量。
- 是否存在音频片段。
- Prompt snapshot 和手工评审占位状态。

它无法判断角色归属、情绪、音效、音乐、环境、声学空间、重叠关系和场景接缝。V2 必须增加真正消费音频的语义评审层。

## 4. 目标架构

### 4.1 公共事实层

公共层继续负责：

- 小说事实和事件顺序。
- 可辨识台词及说话人。
- 旁白文本。
- 原文证据。
- 基础角色档案。
- 审定后的 `ScriptSegment[]`。

`legacy_stems` 可以继续直接消费这一层。

### 4.2 Seed 场景导演层

新增窄职责服务 `SeedSceneDirector`，只在 `seed_scene` 模式运行。它消费已审定片段和章节上下文，输出 `SeedSceneDirection[]`，不得修改台词事实。

建议文件边界：

```text
backend/app/services/audiobook/scene_direction/
  models.py
  director.py
  parser.py
  validator.py
  context_builder.py
  event_mapper.py
```

职责划分：

- `context_builder.py`：从章节摘要、片段、角色档案和导演策略构造安全输入。
- `director.py`：调用 LLM 生成 Seed 专用结构化导演计划。
- `parser.py`：解析严格 JSON，不做猜测性文本修补。
- `validator.py`：验证 segment 引用、台词边界、事件锚点和场景覆盖。
- `event_mapper.py`：把导演计划转换为供应商中立 `SceneAudioEvent[]`。

### 4.3 SeedSceneDirector 预算、失败降级与成本归属

长章节的导演调用可能按上下文窗口或 segment 批次发生，不得预先锁死每章调用次数；必须定义四级预算作用域：

- 单次调用 token/时长上限。
- 单章调用次数上限。
- 单章 token/金额上限。
- 单任务累计预算。

有限状态机：

```text
SeedSceneDirector 首次调用
  -> 结构解析或台词事实校验失败
  -> 使用纠错 Prompt 重试一次
  -> 仍失败时按保真判定分流
     -> 审定内容可被 V1 确定性编译保真承载：降级 V1，记录 director_degraded_to_v1
     -> 审定剧本含 V1 无法承载的插话、重叠等强制事件：进入 manual_review 或配置的 terminal policy
```

规则：

- 导演失败不得导致整章任务崩溃。
- 能保真降级时回退 V1；不能保真时无声降级会丢失已审定内容，必须进入显式人工处理或终态策略。
- 导演模型调用属于场景规划成本，单独记录 provider、model、token usage、调用次数、错误和估算金额，不混入 Seed `¥1/分钟`；是否向用户收费另行决策。
- checkpoint 恢复复用有效导演计划，不重置已消费导演预算。
- 修改 Omni Prompt 不使导演计划失效；只有导演 Prompt、schema 或 policy 版本变化才使导演 checkpoint 失效。

策略所有权与冻结：

- 预算策略唯一所有权为服务端版本化 `SeedSceneDirectorPolicy`（字段 `timeout_seconds/max_attempts_per_batch/max_calls_per_chapter/max_tokens_per_chapter/max_cost_per_chapter/max_cost_per_job/version/allow_inferred_vocalizations/allowed_inferred_vocalization_types/inferred_vocalization_policy_version`）。
- 首期 `allow_inferred_vocalizations` 默认 `False`，只接受显式或已审定分析证据；获得真实评测后再开放低风险推导。
- 普通用户不能提高服务端预算；项目可以请求更低预算，有效预算取两者最小值。
- 策略在任务创建或首次运行时冻结；checkpoint 保存 policy version/hash 与已消费量。
- 恢复不得重新获得预算；单任务预算跨章节累计。

### 4.4 现有 scene_engine 的职责保持不变

`scene_engine` 继续负责确定性执行：

- `SceneVoiceBindingPlanner`：确定每场最多三条 reference 的角色优先级、降级和强制切分要求。
- `ScenePlanner`：消费绑定约束，执行合法切分、时长和字符预算。
- `ScenePromptCompiler`：把审定事实编译成 Seed Prompt。
- `SceneRenderService`：供应商调用、落盘、重试和检查点。
- `SceneAudioQualityGate`：台词和技术硬闸门。
- `SceneAudioAssembler`：场景装配、字幕偏移和响度。

禁止让 `SeedSceneDirector` 直接调用 Seed Audio 或拼装最终供应商请求。

## 5. 数据合同

### 5.1 场景上下文

```python
@dataclass(frozen=True)
class SeedSceneContext:
    time: str = ""
    location: str = ""
    acoustic_space: str = ""
    ambient_state: str = ""
    emotional_arc: str = ""
    story_beat: str = ""
    carry_in: tuple[str, ...] = ()
    carry_out: tuple[str, ...] = ()
```

字段要求：

- `time` 和 `location` 只使用原文、章节摘要或已审定分析能证明的信息。
- `acoustic_space` 描述空间大小、反射、距离和特殊处理，不新增剧情事实。
- `ambient_state` 只包含可听环境。
- `emotional_arc` 描述场景级情绪过程，不替代逐事件表演。
- `story_beat` 用于规划边界，不直接朗读。
- `carry_in/carry_out` 表示跨场景持续的环境、音乐或空间状态。

### 5.2 语音事件

```python
@dataclass(frozen=True)
class SeedSpeechDirection:
    source_segment_index: int
    speaker: str
    layer: str = "foreground"  # foreground | background
    anchor: str = "sequence"   # sequence | before | during | after | overlap
    relative_to_segment_index: int | None = None
    performance: str = ""
    acoustic: str = ""
    verification_policy: str = "hard"  # hard | soft | semantic_only
    start_s: float | None = None
    end_s: float | None = None
```

验证规则：

- `source_segment_index` 必须存在。
- `speaker` 必须等于源片段审定说话人。
- Prompt 中台词必须从源片段逐字读取，不能信任 LLM 回显文本。
- `background/overlap` 必须显式引用相对片段。
- 绝对时间只在 timeline 模式允许。
- 导演输出不携带可被信任的台词副本；Prompt 编译时按 `source_segment_index` 直接读取源片段的说话人和台词。

`verification_policy` 决定该台词在 L0 闸门的验证强度，但不改变其是否属于审定台词事实：

| 类型 | 校验策略 |
|---|---|
| 前景完整台词 | hard |
| 顺序发生、清晰可辨的背景短句 | soft，或按场景策略设为 hard |
| 与前景重叠的短插话 | soft |
| 群体呼喊中要求出现的特定词 | semantic_only |
| 非语言人声 | 不进入 transcript，进入 expected vocalizations |

背景插话可以是审定台词事实但仅接受 soft 或 semantic_only 验证；两者是独立维度，不得互相推导。

语音事件覆盖不变量：

- 每个具有可辨识文本的 `ScriptSegment` 必须且只能被一个 `SeedSpeechDirection` 消费。
- 同一片段不得同时出现在 speech 和其他语言事件集合。
- 不得遗漏、重复或被拆成未经审定的子串。
- director 输出中不携带可被信任的台词副本。
- 剧本改编阶段需要把“期间穿插‘对’”解析成独立台词时，必须在公共事实层先生成独立、审定的 `ScriptSegment`，导演层只负责把它锚定为 `during/overlap`。

### 5.3 非语言人声

可辨识语音事件统一模型：所有具有明确词义的内容——前景台词、背景短句、重叠插话、抢话、电话另一端的声音、群体中可明确辨识的台词——均通过 `SeedSpeechDirection` 表达；背景插话只是 `layer="background"` 与 `anchor="during" | "overlap"`，不是一种新的台词事实类型。不存在 `kind=speech` 的插话模型。

```python
@dataclass(frozen=True)
class SegmentEvidenceRef:
    segment_index: int
    field: str                # text | performance_notes | instruct_scene
    excerpt: str              # 必须为源字段子串，仅审计展示

@dataclass(frozen=True)
class ReviewedAnalysisEvidenceRef:
    kind: str                 # reviewed_analysis
    artifact_id: str
    artifact_version: str
    artifact_hash: str
    finding_id: str
    segment_indices: tuple[int, ...]
    excerpt: str

@dataclass(frozen=True)
class SeedVocalizationDirection:
    speaker: str
    description: str          # 笑、哭、吸气、喘息、无词惊呼等
    anchor: str               # before | during | after | overlap
    relative_to_segment_index: int
    evidence: SegmentEvidenceRef | ReviewedAnalysisEvidenceRef
    layer: str = "background"
    performance: str = ""
    acoustic: str = ""
    provenance: str = "explicit"             # explicit | inferred_performance
```

规则：

- `SeedVocalizationDirection` 只能表示非语言人声，不携带 `text` 字段，不进入 transcript。
- “对”“为什么”“金枕”等具有明确词义的内容按 speech 处理。
- “嗯”“啊”根据语境决定；作为回答或明确台词时是 speech，作为无词反应时是 vocalization。
- 没有原文或审定剧本证据的可辨识 speech 直接拒绝；改编阶段需要作为独立台词时，必须先在事实层生成独立审定的 `ScriptSegment`。

证据验证规则（结构化证据引用，禁止 LLM 自证）：

- `evidence` 为必填判别联合，二选一，不允许存在“类型合法但必然校验失败”的可选空字段。
- `SegmentEvidenceRef`：`segment_index` 必须存在，`speaker` 必须与证据片段角色兼容；`excerpt` 必须是源字段子串，不能由 LLM 自由解释；`field` 单一枚举即可表达来源，不引入与 field 存在非法组合的冗余 kind；`field=performance_notes` 时字段内容必须包含可验证的微表演证据。
- `ReviewedAnalysisEvidenceRef`：仅允许引用已版本化、可哈希的审定分析 artifact；`finding_id` 必须指向 artifact 内具体 finding；`segment_indices` 必须覆盖锚定片段；章节级分析不得作为具体 speaker 发出具体声音的证据，除非 finding 明确记录该归属。
- “符合情绪”“增强感染力”“让场景更自然”不能作为证据。
- 原文只表达“悲伤”时，不得推导生成“哭泣”；原文明确“她笑了一声”时才可生成笑声事件。
- `provenance=inferred_performance` 只允许低风险吸气、呼气、轻微喘息等非语言人声，不允许自行添加哭、笑、尖叫等改变语义的强表演；是否允许表演性推导由 `SeedSceneDirectorPolicy.allow_inferred_vocalizations` 与 `allowed_inferred_vocalization_types` 控制并进入 Director policy hash（首期默认关闭），不得伪装成原文证据。
- 轻微停顿属于 speech performance/timing，通过 `SeedSpeechDirection.performance` 或 timing 字段表达，不进入 `SeedVocalizationDirection`；气息类描述区分：吸气、呼气、轻微喘息 -> vocalization；气息平稳、气息虚弱、气息颤抖 -> speech performance。

评审语义（固定，首期不引入策略字段）：

- L0 只把预期 vocalization 用于豁免 ASR extra text，不验证 vocalization 是否真实存在。
- Omni shadow 判断其存在性、角色归属、时间位置和表现效果。
- 未经 Omni 标定，不因 vocalization 缺失自动重试。

### 5.4 声音事件

```python
@dataclass(frozen=True)
class SeedSoundDirection:
    kind: str                 # sfx | ambient | music | transition
    description: str
    anchor: str               # before | during | after | throughout | until_text | overlap
    relative_to_segment_index: int | None = None
    related_text: str = ""
    duration_s: float | None = None
    delay_s: float = 0.0
    layer: str = "background"
    sequence_group: str = ""
```

`description` 应尽量保留：

- 声源材质。
- 动作和次数。
- 距离与空间。
- 移动方向。
- 强弱和动态变化。
- 音乐配器、情绪和生命周期。

`asset_id`、本地文件和供应商私有字段不得进入 Seed Prompt，但可保留在独立回退元数据中。

### 5.5 场景导演计划

```python
@dataclass(frozen=True)
class SeedSceneDirection:
    scene_key: str
    source_segment_indices: tuple[int, ...]
    context: SeedSceneContext
    speech: tuple[SeedSpeechDirection, ...]
    vocalizations: tuple[SeedVocalizationDirection, ...]
    sounds: tuple[SeedSoundDirection, ...]
    timeline_mode: str = "natural"
    target_duration_s: float | None = None
```

导演计划必须覆盖连续 segment 区间，不允许重叠覆盖、跳过有文本片段或重排台词顺序。

## 6. Seed 专用改编 Prompt

### 6.1 与 legacy_stems 分离

`seed_scene` 不再复用包含以下内容的旧输出合同：

- 分轨音量数值。
- 每片段最多两个音效。
- 素材 ID。
- 后期混音覆盖率。
- 每句必须独立合成。
- 把复杂重叠事件强制拆成互不关联片段。

公共原文保真、角色归属和输入安全约束可以复用。Seed 专用 Prompt 只输出 §5 定义的结构。

### 6.2 改编目标

Seed 导演 Prompt 必须要求：

1. 先识别连续场景和真实转场。
2. 提取时间、地点、空间声学、持续环境和整体情绪过程。
3. 保持审定台词与说话人不变。
4. 标记前景、背景、重叠和插话关系。
5. 把非语言人声与可辨识语言分离。
6. 把音效蒙太奇按顺序分组。
7. 描述音乐进入、变化、降低、停止和延续。
8. 标记电话、远端、混响、移动等声学处理。
9. 标记不可切断的问答、因果动作和情绪弧。
10. 不为增强戏剧性新增原文不存在的台词、人物行动或具体物件。

### 6.3 Few-shot 使用原则

用户提供的电话悬疑、神话多人战斗、单人情感回忆、直播插话和广告时间轴样例只用于：

- 设计 Seed 专用结构化 few-shot。
- 建立固定评测集。
- 验证 Prompt 编译风格。

不得把所有完整样例拼入每次 Seed `text_prompt`。最终供应商 Prompt 仍由确定性编译器产生。

## 7. 场景描述构造与入口贯通

### 7.1 场景局部描述

不把整章摘要原样传给所有场景。对每个场景按以下优先级构造：

1. `SeedSceneDirection.context`。
2. 当前 source segments 的 `instruct_scene`。
3. 章节结构化摘要中的时间、地点和情绪事实。
4. AudioDirector 的章节风格兜底。
5. 最终兜底文案。

构造结果应进入：

- Prompt。
- `SceneRenderPlan`。
- Prompt hash。
- checkpoint 签名。
- Omni 期望合同。

### 7.2 角色描述和默认 TTS 模型

入口必须传递：

- `descriptions`：来自角色档案和 voice mapping 的统一描述。
- `default_tts_model`：当前项目真实逐句 TTS 模型，仅用于识别原生 Seed-TTS `speaker` 和局部回退。

有 reference 时，Prompt 不重复注入年龄、音高、沙哑度等静态声音身份；只保留角色绑定和当前表演。无 reference 的临时角色才使用可听辨的文字声音描述。

### 7.3 当前角色音色绑定链路

当前实现的声音身份来源于项目配置，而不是由 Seed 场景导演临时生成：

```text
前端为角色选择音色
  -> 项目 audio_config / character voice mapping
  -> ProjectAudioRuntimeConfig.voice_mapping
  -> VoiceReferenceResolver
  -> ChapterScenePipeline 按场景物化 reference
  -> ScenePromptCompiler 生成“角色 -> @音频N”
  -> Seed 请求 references[N-1]
```

`VoiceReferenceResolver` 当前支持三类结果：

1. 豆包 Seed-TTS 2.0 原生音色：生成 `{"speaker": voice_id}`，不需要下载音频。
2. 用户私有设计/复刻音色或已发布公共音色：先解析为 `audio_url/audio_data`，在渲染前统一物化为可提交的 `audio_data`。
3. 没有合法 reference 的角色：只保留文字声音描述；可以生成，但不承诺跨场景身份稳定。

Prompt 与请求数组必须保持严格位置对应：

```text
男主 -> @音频1 -> references[0]
女主 -> @音频2 -> references[1]
旁白 -> @音频3 -> references[2]
```

当前主要缺口不是“无法绑定”，而是“没有独立的场景槽位规划”。reference 顺序主要由场景内角色首次出现顺序决定；超过三条时倾向通过前置切场景满足限制，无法显式比较切分损失与次要角色退化为文字描述的损失。未来插话角色如果只存在于导演事件中，也可能不进入现有 `ScriptSegment.speaker` 统计。

### 7.4 三层声音决策必须分离

不得把声音身份、reference 槽位和表演指导合并为一个 LLM 决策：

| 层级 | 决定内容 | 生命周期 | 决策方式 |
|---|---|---|---|
| 项目/章节声音身份 | 角色到底绑定哪个声音 | 跨场景稳定 | 用户配置优先，确定性解析 |
| 场景 reference 槽位 | 本场哪些角色占用最多三条 reference | 单场景 | 确定性规划器 |
| 事件表演 | 当前台词的情绪、语速、远近和声学处理 | 单事件 | Seed 场景导演计划 |

`SeedSceneDirector` 只能指导角色“怎么演”，不得选择或替换角色的声音身份。`ScenePromptCompiler` 只消费已经确定的绑定计划，不再承担槽位选择策略。

### 7.5 声音身份注册表

新增只读领域视图 `VoiceIdentityRegistry`，由项目运行时配置构造，统一屏蔽前端配置、资产权限和供应商字段差异。它不复制音频数据，只保存可审计的身份元数据：

```python
@dataclass(frozen=True)
class VoiceIdentity:
    speaker: str
    source: str              # seed_speaker | user_private | public_pool | description
    source_id: str
    provider_reference: dict[str, str] | None
    description: str
    explicitly_bound: bool
    strict_stability: bool
    asset_revision: str

@dataclass(frozen=True)
class VoiceIdentityRegistry:
    identities: tuple[VoiceIdentity, ...]
    version: str
```

身份来源的选择优先级为：

1. 用户显式绑定且当前仍有权限的身份。
2. 豆包 Seed-TTS 2.0 原生 `speaker`。
3. 当前用户拥有且状态有效的私有参考录音。
4. 状态为 `published` 的公共音色池参考录音。
5. 可听辨的文字声音描述。

这里的优先级用于解决同一角色配置冲突，不允许系统静默覆盖用户显式选择。其他供应商官方 voice ID、未授权试听、失效私有资产和已下架公共资产不能作为 Seed reference。

### 7.6 场景声音绑定合同

在 `VoiceReferenceResolver` 形成合法身份注册表之后、新增纯领域服务 `SceneVoiceBindingPlanner`：

```text
项目 voice_mapping
  -> VoiceReferenceResolver / 资产权限校验
  -> VoiceIdentityRegistry
  -> SceneVoiceBindingPlanner
  -> PreviewReferenceMaterializer
  -> ScenePromptCompiler
```

规划器输出必须包含被选中和未被选中的角色，避免降级不可观测：

```python
@dataclass(frozen=True)
class SceneVoiceBinding:
    speaker: str
    identity_source: str
    reference: dict[str, str] | None
    description: str
    priority_score: int
    required_stability: bool
    slot_index: int | None
    decision: str             # reference | description | split_required | reject
    reason_code: str

@dataclass(frozen=True)
class SceneVoiceBindingPlan:
    scene_id: str
    bindings: tuple[SceneVoiceBinding, ...]
    reference_count: int
    registry_version: str
    policy_version: str
```

规划输入必须覆盖 `speech` 和 `vocalizations` 中的全部 speaker，而不只是 `ScriptSegment.speaker`。群体惊呼等没有稳定角色身份的声音事件不占 reference；具有姓名且跨场景复现的背景插话角色参与预算。

### 7.7 reference 槽位分配算法

槽位分配必须确定、稳定、可解释。推荐先计算硬约束，再使用整数评分排序；禁止用 LLM 直接挑选三名角色。

硬约束：

- 没有合法 `provider_reference` 的角色只能使用描述，不参与槽位排序。
- `strict_stability=true` 且本场有可辨识台词的角色为强候选。
- 同一 reference 身份不得重复占用多个槽位。
- 最终 `slot_index` 必须连续且与请求 `references` 数组一致。

推荐评分项：

| 条件 | 分值 |
|---|---:|
| 用户明确要求本场严格绑定 | +1000 |
| 本场主视角或核心角色 | +500 |
| 本场可辨识台词时长进入前 3 | +300 |
| 相邻场景已经使用同一身份 | +200 |
| 旁白且本场实际有旁白 | +180 |
| 有多次背景插话或重叠台词 | +120 |
| 只有一次不超过 1 秒的短插话 | +20 |

同分时依次按 `strict_stability`、本场可辨识台词时长、章节首次出场序号、规范化 speaker 名排序。评分常量和排序规则必须版本化并进入测试；不得依赖字典遍历顺序。

推荐 reason code：

- `selected_explicit_binding`
- `selected_scene_core`
- `selected_continuity`
- `selected_narrator`
- `degraded_no_legal_reference`
- `degraded_reference_budget`
- `split_required_strict_bindings`
- `rejected_identity_unavailable`

### 7.8 超过三条 reference 的决策

“最多三条 reference”不是“最多三个角色”。场景可以出现更多角色，但每场只有三名角色能获得强声音身份锚定。决策顺序如下：

1. 若合法强候选不超过三名，直接分配，其余角色使用描述。
2. 若超过三名，但存在不破坏问答、重叠、动作因果和音乐连续性的自然切点，比较切分后 Prompt/时长预算并切分。
3. 若无法安全切分，只有非严格角色可以按评分退化为文字描述。
4. 若不可切分且严格绑定角色超过三名，返回 `split_required_strict_bindings`，进入人工处理或显式回退；不得悄悄换声或忽略绑定。

切分代价至少考虑：

- 是否切断重叠、抢话或背景插话。
- 是否切断同一音效蒙太奇或连续动作。
- 是否破坏音乐、环境和空间状态承接。
- 是否让同一核心角色在相邻场景失去 reference。
- 新场景是否仍满足时长和 Prompt 字符限制。

该策略保持 KISS：首版只使用上述确定性规则，不引入全章组合优化器。真实评测证明贪心策略导致明显质量问题后，再考虑动态规划。

### 7.9 权限、物化、恢复和一致性

- 私有资产在任务启动和实际物化时都重新验证 owner、active 状态；公共资产重新验证 `published` 状态。
- `audio_url` 只作为受控物化输入，最终提交和 checkpoint 使用内容 hash，不把临时签名 URL 当身份。
- reference 物化失败不得自动退化为另一音色。严格角色返回 `rejected_identity_unavailable`；非严格角色是否允许描述降级由项目策略显式决定。
- checkpoint 至少保存 `registry_version`、每个角色的 `source/source_id/asset_revision`、绑定计划 hash、reference 内容 hash、槽位顺序和 policy version。
- 恢复时先验证绑定计划和资产修订。历史 checkpoint 已有完整可用 reference 内容时可按原模型恢复；重新生成场景时必须使用当前有效权限重新规划。
- 用户变更角色音色后，只使包含该角色且实际受绑定变化影响的场景失效，不应使整章无条件重生成。
- Omni 场景评审接收“角色 -> reference 槽位”的期望摘要，检查说话人归属；接缝评审检查相邻场景中同一 `source_id` 的声线连续性。Omni 不能自行决定新的音色绑定。

## 8. 场景规划和时间轴

### 8.1 时长区间估算

新增确定性事件区间估算器，不把所有音效 duration 简单相加。

规则：

- 台词、前后停顿形成基础时间线。
- `before/after/sequence` 的声音事件增加独占区间。
- `during/throughout/overlap` 与台词重叠，只增加超出基础区间的部分。
- `until_text` 绑定目标台词内部位置。
- `sequence_group` 内的事件顺序累计。
- duration 缺失的短触发音使用版本化保守默认值。
- 音乐和持续环境默认不增加场景总时长。
- 背景 speech 按其与前景关系计算重叠或独占区间。

估算器输出：

```python
@dataclass(frozen=True)
class SceneDurationEstimate:
    speech_s: float
    pauses_s: float
    sequential_events_s: float
    overlap_tail_s: float
    total_s: float
    confidence: str
```

### 8.2 模型硬限制

两个 Seed 模型共享当前规划硬限制：

- 单次最长输出 120 秒。
- Prompt 最大 3000 字符。
- references 最多 3 条。

V2 继续使用保守规划：

- 常规目标 45-75 秒。
- 软上限 90 秒。
- 硬规划上限 105 秒。
- 至少预留 15 秒生成波动空间。

### 8.3 multilingual 时间轴

时间轴编译必须由 `timeline_mode` 控制：

- `natural`：不输出绝对时间。
- `bounded_timeline`：只为用户指定或导演确认的关键事件输出时间窗。
- `strict_timeline`：所有主要 speech 事件输出 `[start:end]`。

绝对时间来源必须是：

- 用户输入。
- 原始广告/短剧脚本已有时间码。
- 通过事件区间调度器产生并通过总时长校验的计划。

禁止仅累加文本朗读估算后伪造高精度时间码。

验证状态：

- multilingual 的基础接口合同（请求成功、毫秒级字幕、WAV 响应、格式嗅探、临时 URL 与 Base64）已在 V1 完成真实验证。
- Prompt 时间轴控制的遵循能力和精度尚未验证，必须先在阶段 0 完成四个独立合同的实测：语法合同（`[start:end]` 合法写法、小数位、单位、空格和中文标点）、边界合同（最小/最大时间窗、总时长上限、越界与重叠时间窗行为）、遵循精度（实际台词起止与目标窗口的偏差分布）、失败行为（非法时间轴是请求失败、模型忽略、自动修正还是生成异常音频）。
- 使用固定广告样例至少重复生成 3 次，记录 `start_error_ms`、`end_error_ms`、`duration_error_ms` 和 `event_alignment_error_ms`，统计 P50/P95 与最大偏差。
- 验证通过前，`strict_timeline` 是待契约验证能力，不得写成已确认可依赖的生产能力；`bounded_timeline` 是否投产、时间轴偏差按 L0 阻断、Omni finding 还是人工提示处理，均由验证证据决定。

## 9. Prompt 编译规则

### 9.1 固定结构

```text
场景总描述
角色与声音绑定
全局音乐与环境状态
按顺序排列的 speech/vocalization/sfx/music/transition 事件
场景收尾与 carry-out
```

### 9.2 台词模板

不再统一套用“用……的方式说道”。表演应拆分成：

- 初始状态。
- 情绪变化过程。
- 韵律、音量、语速、重读和停顿。
- 说话动作。
- 声学处理。

编译器根据显式动作选择“说道、问道、回应、低语、喊道、一字一顿地说道”等；没有明确动作时才使用中性模板。

### 9.3 非语言人声兼容

显式导演事件优先。旧 `performance_notes` 的词表抽取只作为兼容路径，至少覆盖：

```text
轻笑、笑声、冷笑、苦笑、哭泣、抽泣、哽咽、呜咽、吸气、倒吸冷气、
喘息、呼喝、惊呼、呼喊、尖叫、呻吟、吞咽、咳嗽、叹气、哼、嗯、啊、诶、哎
```

兼容词表不得继续承担主要 timing 推断；新计划必须显式输出 anchor。

匹配规则（确定性正则与最长匹配，不引入 NLP）：

- 多字词优先，按最长匹配抽取（“倒吸冷气”不拆成“吸气”）。
- 单字项（嗯、啊、哼、诶、哎）只能在引号、标点、空白或显式动作模板边界内命中，如“嗯”、嗯？、先嗯了一声、发出一声“啊”。
- 单字项不得从普通形容词句中裸子串抽取；“惊讶啊”“语气啊得不自然”不应命中。
- 显式 `SeedSpeechDirection` 或 `SeedVocalizationDirection` 事件永远优先于词表抽取。
- 词表 fallback 只服务历史 `ScriptSegment.performance_notes` 兼容路径，不允许新增可辨识台词事实。

### 9.4 `until_text` 修复

现有“持续至对应台词说完某某二字”改为中性措辞：

```text
持续至对应台词中的“{related_text}”说完。
```

编译前验证 `related_text` 是目标台词子串；验证失败时降级为“持续至该句说完”。

### 9.5 字符预算

字符估算复用实际事件渲染 helper，不使用 `str(dataclass)`。估算只参与提前切分，最终仍以真实编译 Prompt 长度作为请求合法性事实。

## 10. Qwen Omni 音频语义评审

### 10.1 定位

新增 `SceneAudioSemanticReviewer`，默认模型为 `qwen3.5-omni-flash`。它不复用 ASR provider 的结果合同，也不塞进 `_final_audio_review()` 的现有大函数。

建议文件：

```text
backend/app/services/audiobook/scene_quality/
  semantic_models.py
  qwen_omni_reviewer.py
  semantic_policy.py
  calibration.py
```

可以复用现有 Qwen Omni 的鉴权、音频编码和请求传输 helper，但评审 Prompt、响应 Schema、预算和错误分类必须独立。

### 10.2 输入

每次场景评审输入：

- 场景成品音频。
- 审定台词和 speaker 顺序。
- 角色 reference 绑定摘要，不提交无关隐私元数据。
- `SeedSceneDirection` 或等价 `SceneAudioEvent[]`。
- 期望音乐、环境、音效和声学处理。
- 供应商字幕或独立 ASR 时间轴。
- 质量策略版本。

### 10.3 输出 Schema

```json
{
  "schema_version": "scene-semantic-review-v1",
  "passed": true,
  "confidence": 0.0,
  "dimensions": {
    "dialogue_fidelity": {},
    "speaker_assignment": {},
    "speaker_separation": {},
    "performance": {},
    "vocalizations": {},
    "sound_events": {},
    "music": {},
    "ambient": {},
    "acoustic_space": {},
    "mix_balance": {}
  },
  "findings": [
    {
      "code": "speaker_assignment_mismatch",
      "severity": "major",
      "confidence": 0.0,
      "start_ms": 0,
      "end_ms": 0,
      "expected": "",
      "observed": "",
      "suggested_action": "manual_review"
    }
  ],
  "recommended_action": "accept"
}
```

约束：

- 失败 finding 必须给出时间区间、期望、观察结果和置信度。
- 没有时间证据的主观意见不得触发自动重试。
- 模型不得把字幕文本本身当作已经听到对应声音事件的证据。
- Prompt 必须允许输出 `not_assessable`，不能强迫模型猜测。

### 10.4 两层质量体系

L0 确定性硬闸门：

- 音频可解码且时长合法。
- 无严重削波或近乎全静音。
- 台词验证输入拆为四个集合，而不是单一扁平 expected_texts：
  - `hard_expected_texts`：缺失、增句和乱序阻断。
  - `optional_expected_texts`：被识别出来时不计入增句；未识别出来时只记录 warning，不阻断、不触发自动重试。
  - `semantic_expected_texts`：允许出现但不参与覆盖率；缺失不触发 L0 失败；被 ASR 识别时必须允许其从 extra 候选中消费；不参与 hard coverage、缺失和顺序判定；存在性、说话人和时间位置交给 Omni；出现次数超过计划次数时，超出部分仍可判定为 extra。
  - `expected_vocalizations`：不参与台词一致性判定，仅用于豁免非语言人声的 extra 误判。
- 无漏句、增句和乱序的判定仅针对 `hard_expected_texts`。
- 重叠位置和说话人归属交给 Omni 语义评审；Omni 首期是影子评审，soft 插话缺失不能触发自动重试。
- multilingual 时间轴合法、单调且不越界（仅 timeline 模式；该合同以阶段 0 验证结果为准）。

optional 匹配的有序对齐算法（必须版本化并纳入 quality policy hash）：

1. 按事件顺序构造期望序列，每个节点标记 hard/optional/semantic_only。
2. hard 与 optional 一起参与单调序列对齐，optional 节点允许零次匹配；semantic_only 节点不进入对齐序列，进入 `semantic_expected_texts` 允许消费集合。
3. hard 节点必须匹配；optional 节点匹配不到只产生 warning。
4. optional 只能在相邻 hard 锚点限定的 transcript 区间内匹配；禁止对全 transcript 做无边界的全局查找并删除短词（反例：hard “对不起，我来晚了”会被 optional “对”破坏成“不起我来晚了”，导致误判漏句）。
5. 有时间戳时进一步限制在事件时间窗或容差窗口内；没有时间戳时使用有序文本锚点。
6. 完成期望序列对齐后，先从剩余文本中消费与 `semantic_expected_texts` 匹配的内容（不超过计划出现次数），再对未消费且不属于 vocalization 豁免的文本判定为 extra。
7. semantic_only 不参与 L0 coverage、缺失和顺序判定，仅作为 Omni expectation；缺失不触发 L0 失败，被识别时必须允许消费，避免误判为 extra。

首版可不实现完整动态规划，允许采用简化路径：先定位稳定的前后 hard 锚点，只在两者之间查找对应 optional，再计算剩余 extra。

虚拟边界与无 hard 台词场景：

- 引入 `BOF`（transcript 开始）与 `EOF`（transcript 结束）虚拟锚点。
- 首个 hard 之前的 optional 在 `[BOF, first_hard)` 内匹配；最后一个 hard 之后的 optional 在 `(last_hard, EOF]` 内匹配。
- 两个 hard 之间的 optional 以及连续多个 optional 按事件顺序在所属区间内匹配。
- 没有 hard 台词时，optional 只允许出现但不要求出现；纯音效场景仍执行技术质量检查；未被计划允许的语言文本仍可判定为 extra。
- 简化路径仅适用于存在稳定 hard 锚点的场景；无 hard 锚点场景必须使用完整有序对齐。

L1 Omni 语义评审：

- 说话人归属和角色区分。
- 情绪、语气、韵律和微表演。
- 背景插话和重叠关系。
- 音效、音乐、环境是否兑现。
- 电话、混响、远近和空间移动。
- 对白是否清晰位于前景。

L0 失败直接进入既有有限恢复状态机。L1 在影子阶段只记录，不改变生成结果。

### 10.5 章节接缝评审

不默认提交整章。对每个相邻场景构造：

```text
前一场景末尾 5-10 秒 + 后一场景开头 5-10 秒
```

评审：

- 同一角色声线是否突变。
- 环境是否无理由中断或重启。
- 音乐是否突兀跳变。
- 固定静音是否破坏问答或动作承接。
- 响度、空间和混响是否突变。

纯技术响度差仍由本地分析器判定，Omni 只负责语义连续性。

### 10.6 灰度阶段

阶段 A，影子评审：

- 评审结果只保存和展示。
- 不自动重试、不阻断、不改变用户账单。
- 与人工盲评逐项对比。

阶段 B，人工辅助：

- 高置信 major/critical finding 进入人工复核队列。
- 人工确认后才能重生成。

阶段 C，有限自动恢复：

- 只有经过标定的错误代码可以自动触发一次针对性重试。
- 主观风格问题不得自动阻断。
- Omni 触发的 Seed 重试每场景最多一次。
- 重试成本按真实 Seed 成功响应继续计费和审计。

### 10.7 模型目录一致性

当前 Qwen Omni 音频理解 provider 默认使用 `qwen3.5-omni-flash`，但通用模型目录主要登记 `qwen3.5-omni-plus`。实施前必须补齐并统一：

- `qwen3.5-omni-flash` 模型登记。
- audio understanding 能力。
- 音频输入格式和时长限制。
- API endpoint 和鉴权。
- 输入/输出计费事实。
- 超时、重试、并发和预算。
- 运行时模型 ID、日志和账单记录。

## 11. 渲染、重试和回退

### 11.1 有限状态机

保留 V1 的有界恢复原则：

```text
首次 Seed 生成
  -> L0 失败时针对性强化重试一次
  -> 在合法语义边界拆分一次
  -> 仍失败时执行配置的终态策略
```

终态策略必须产品化，不得静默：

- `manual_review`：保持 Seed-only，等待人工处理。
- `legacy_fallback`：允许当前场景进入逐句 TTS 分轨回退。

如果产品宣称“成品只使用 Seed Audio”，必须选择 `manual_review`；启用 `legacy_fallback` 时，结果和 UI 必须明确标记回退场景及成本组成。

### 11.2 针对性重试

不再对所有失败只追加同一个 Prompt 后缀。至少区分：

- `missing_dialogue`
- `extra_dialogue`
- `dialogue_order_invalid`
- `speaker_assignment_mismatch`
- `foreground_masked`
- `required_sound_event_missing`
- `acoustic_treatment_missing`
- `invalid_timeline`
- `provider_or_technical_error`

只有具有可靠证据的错误才能生成针对性重试提示。

### 11.3 延迟生成 legacy 回退素材

Seed 主路径不提前生成真实 SFX/BGM 素材。只保留结构化计划。某场景确定进入 `legacy_fallback` 后，才针对该场景的 source segments 生成：

- 逐句 TTS。
- 所需 SFX。
- 所需 BGM。
- 局部混合成品。

回退产物继续进入 checkpoint artifact 校验，避免重启后重复生成。

## 12. 配置、API 和持久化

### 12.1 项目配置

建议新增或调整：

```json
{
  "audio_engine_mode": "seed_scene",
  "seed_audio_model": "seed-audio-1.0-multilingual",
  "seed_timeline_mode": "natural",
  "seed_terminal_policy": "manual_review",
  "semantic_review_enabled": true,
  "semantic_review_mode": "shadow"
}
```

约束：

- 新项目缺省模型为 multilingual。
- 历史配置为空时，新任务解析为 multilingual，但恢复 checkpoint 仍服从 checkpoint 原模型。
- API 可以保留模型字段用于管理员、测试和回滚；普通 UI 不必暴露。
- timeline mode 必须进入 Prompt 和 checkpoint 签名。
- terminal policy 必须进入任务摘要和用户可见结果。

### 12.2 检查点

checkpoint 签名按四类分别完整列出（不是“至少包含”）：

Hash API 职责分离（本节全部 hash 统一遵循）：

结构化语义身份与二进制完整性是两个 helper，不得由同一 API 混担，模块不得自行实现“稳定 hash”：

- `canonical_hash(value, *, contract_name, contract_version)`：结构化对象的语义身份，hash 输入包含 contract_name/version。用于 DirectorInputSignature、SeedGenerationInputSignature、binding decision/audit、expectation contract、policy/schema/request contract、normalized structured timeline。
- `content_digest(data: bytes)`：对原始字节直接 SHA-256，不随签名合同版本变化。用于音频文件、reference 音频、原始字幕 artifact 字节、持久化 JSON artifact 的实际文件完整性、下载内容校验。若同一 JSON artifact 需要两个 hash，同时保存 semantic_hash（判断语义是否相同）与 content_digest（判断实际持久化字节是否损坏），便于与 OSS ETag/本地文件 digest 对比、内容去重与历史迁移。

`canonical_hash` 最低规则：

- 使用 UTF-8；Unicode 统一为 NFC。
- JSON 序列化并排序 key；不得使用 dataclass repr。
- None 语义按合同显式定义：统一省略或统一保留为 null，不得混用。
- tuple 与 list 在元素相同时序列化等价。
- 浮点时间统一量化（毫秒整数或固定三位小数），1.2 与 1.200 必须得到相同 hash。
- 语义文本 hash 前先把换行 CRLF/LF 归一为 LF；二进制内容一律走 `content_digest`。
- 有顺序语义的数组（台词序列、时间轴窗口、事件区间）保持顺序；无顺序语义的集合先按稳定 key 排序再哈希。
- hash 输入包含 contract_name 与 contract_version，避免跨合同碰撞。
- 不把瞬时 URL、时间戳、请求 ID 混入语义 hash。
- 首选 SHA-256 或项目已有稳定 hash helper。

导演计划 checkpoint：

输入签名（DirectorInputSignature，唯一缓存键）：

- `source_segments_hash` 与 `source_segment_range`；按批次或场景输入范围签名，只改无关章节片段时不应使全章导演计划无条件失效。
- `reviewed_analysis_artifact_hashes`。
- `scene_context_source_hash`（章节上下文与 SeedSceneContext 来源）。
- `character_profiles_hash`。
- SeedSceneCapabilityContract version/hash。
- `director_model_id`（记录真实 provider/model ID）。
- `director_prompt_hash` 与 `director_schema_hash`。
- SeedSceneDirectorPolicy version/hash。

输出与账本：

- SeedSceneDirection schema/version/hash（属于输出校验，不是输入缓存键）。
- Director attempt ledger 引用与已消费次数、token、金额。
- `status`（completed | retryable_failed | terminal_failed）：只有解析、事实校验和覆盖校验全部通过的计划才能成为可复用的 completed checkpoint。
- `next_action`（reuse | corrective_retry | degrade_v1 | manual_review）。
- `validated_plan_hash`（非 completed 时为 None）与 `last_error_code`。

恢复规则：

- completed 且输入签名一致：复用计划。
- retryable_failed：沿用已消费预算，只执行尚未使用的纠错机会。
- terminal_failed：复用终态决定，不重新获得重试次数。
- attempt ledger 始终保留，不因输入变化而删除历史计费事实；输入变化后可创建新计划 checkpoint，历史 attempt ledger 仍作为账本事实存在。

失效规则：输入签名任一变化使对应 Director checkpoint 失效；Omni 评审 Prompt 修改不使其失效。

Seed artifact checkpoint（输入签名与输出校验分离）：

SeedGenerationInputSignature（唯一生成缓存键）：

- model_id。
- timeline_mode。
- prompt_hash。
- reference_hashes。
- scene_voice_identity_hash（场景范围）与 binding_decision_hash；`binding_audit_hash` 不进入生成缓存键，只进入 checkpoint payload、日志和审计记录。
- provider_id 与 provider_resource_id。
- provider_request_schema_hash 与 adapter_contract_version。
- requested_audio_format、requested_sample_rate、requested_channels；只对会改变成品音频或解析合同的规范化请求参数签名，API Key、临时 URL、Request ID、超时值等不进入生成缓存键。

SeedGenerationOutput（输出校验，不进入缓存键）：

- audio_artifact_hash。
- provider_request_id。
- actual_audio_format、actual_sample_rate、actual_channels。
- duration_s。
- provider_metadata_hash。

恢复规则：

- 输入签名一致且输出 artifact 存在、内容 hash 一致、可解码：复用。
- 输入签名一致但 artifact 缺失、损坏或 hash 不一致：进入 artifact 恢复策略。
- 下载失败但供应商可能已成功生成时，优先恢复同一 provider 成品地址，不得直接重新调用 Seed。
- 恢复中间载体：长期 checkpoint 只保存 provider_request_id 和安全过滤后的恢复状态；供应商支持通过 Request ID 查询结果时优先用 Request ID 恢复。若只能依赖临时 URL，URL 放入加密、TTL 受限的短期恢复记录，不进入长期 checkpoint；短期记录过期后不得假设生成失败并立即重调 Seed，应先查询 provider 状态、账单或进入人工处理，避免重复计费。临时 URL 不进入缓存签名，也不得出现在普通日志和用户可见错误中。
- 短期恢复记录最小状态（ProviderRecoveryRecord）：provider_id、provider_request_id、generation_input_hash、encrypted_result_url、expires_at、status、last_checked_at、check_attempts、recovery_method。幂等键采用双层唯一约束：内部 attempt 幂等键为 generation_input_hash + attempt_number（始终存在，请求提交前可能尚无 provider_request_id）；外部 provider 唯一键为 provider_id + provider_account_scope_hash + provider_request_id（仅在 request ID 存在时建立，作为外部事实身份；同一 generation input 的合法重试不得被错误合并）。`provider_account_scope_hash` 只能是不可逆标识（由 provider 配置记录 ID、tenant 级 credential record ID 或 endpoint/resource namespace 生成的稳定 hash），不得保存 API Key 或账号密钥；若当前产品确认所有任务永久共享单一 provider 账号，可暂以空作用域实现，但必须保留该字段并在多账号接入前完成迁移。恢复方式按 `recovery_method` 判别字段区分可选性：request_query 时 provider_request_id 必填、encrypted_result_url 与 expires_at 可空；temporary_url 时 encrypted_result_url 与 expires_at 必填、provider_request_id 在供应商返回时保存否则可空。状态至少包括：pending、downloadable、downloaded、expired_unverified、confirmed_failed、manual_review。状态迁移使用条件更新/CAS：pending → downloadable → downloaded；pending/downloadable → expired_unverified；expired_unverified → downloaded | confirmed_failed | manual_review；confirmed_failed → 新 attempt。禁止 downloaded → pending、confirmed_failed → pending、expired_unverified → 直接新 Seed attempt；并发下载时只有一个 worker 能把状态推进为 downloaded，其他 worker 复用结果。只有明确 confirmed_failed 且恢复策略允许时才可考虑重新生成；expired_unverified 不得直接调用 Seed。
- 输出 artifact hash 变化属于输出完整性或生成结果变化，不是“输入签名变化”。
- 失效规则：输入签名任一项变化触发 Seed 重新生成；确定性质量策略不在此列。

声音身份范围：全局 VoiceIdentityRegistry version 只用于审计和重新规划触发，不直接进入生成缓存键；生成输入使用场景范围的 `scene_voice_identity_hash`，只包含本场实际参与规划的角色身份；是否重新生成最终由 prompt_hash + binding_decision_hash + reference_hashes 以及其他 SeedGenerationInputSignature 字段共同决定，完整 SceneVoiceBindingPlan hash 不作为生成缓存键。无关角色变化可以重新检查 registry，但不得直接重烧本场 Seed。

SceneVoiceBindingPlan hash 拆分为决策层与审计层：

- `binding_decision_hash`（用于 Seed 生成，只有实际变化才重新生成）：speaker、slot_index、reference_content_hash、description、decision、required_stability。
- `binding_audit_hash`（用于审计）：policy_version、priority_score、reason_code、registry_version、asset_revision、identity source、source_id。

其中 `slot_index` 必须进入决策 hash（`@音频N` 与 references 数组位置映射依赖顺序，集合不变但顺序变化即改变 Prompt 映射）；临时签名 URL 不进入身份 hash，下载后的 reference 内容 hash 进入；权限状态用于重新验证，不把瞬时查询时间写入 hash。策略变化后先重新规划，只有 `binding_decision_hash` 实际变化才重新生成 Seed；审计信息变化但生成输入不变时不重烧音频。资产 revision 变化但内容 hash 相同时：重新验证绑定计划，但不重烧 Seed。SceneVoiceBindingPlan 可保留一个整体 artifact hash 用于完整性校验与审计，但不得同时作为生成缓存键；实施者不得把完整 BindingPlan hash 放入 SeedGenerationInputSignature。

L0 质量 checkpoint（三层签名，输入与结果分离）：

RawTranscriptArtifact：

原始转写签名（按来源建立判别联合，避免强制填空字符串引入无效状态）：

ProviderSubtitleInputSignature（provider 原生字幕）：

- source = "provider_subtitle"。
- audio_artifact_hash。
- provider_id。
- provider_output_artifact_hash。
- subtitle_extraction_contract_hash。

AsrTranscriptInputSignature（独立 ASR）：

- source = "asr"。
- audio_artifact_hash。
- asr_provider_id 与 asr_model_id。
- asr_request_contract_hash（ASR Prompt 或识别参数）。
- 音频预处理 hash。

TranscriptSelectionPolicy（上层选择签名，与两种输入签名分开管理）：

- prefer_provider_timeline。
- require_timestamps。
- fallback_to_asr。
- policy_version。

来源选择语义：provider 字幕提取规则变化只重新提取字幕；ASR 合同变化才重新调用 ASR；来源选择从 provider 改为 ASR 时生成新的 transcript artifact；provider 没有时间轴但有文本时是否仍调用 ASR，由选择策略决定。

原始输出（必须保存可重新规范化的内容载体，仅存 hash 无法支撑“normalization 变化不重调 ASR”）：

- 内容载体二选一：直接保存经安全过滤的 raw_transcript 与 raw_timeline；或保存 raw_transcript_artifact_uri 与 raw_timeline_artifact_uri，URI 必须指向项目控制的持久化 artifact（不是供应商临时 URL），内容 hash 与 artifact 一致。
- raw_transcript_hash 与 raw_timeline_hash。
- filtered_provider_metadata（敏感字段继续过滤，不保存完整供应商原始响应；API Key、请求 header、临时签名、未经筛选的 debug 字段不落盘）。

恢复规则：原始 artifact 缺失或 hash 不一致时，才判断是否需要重新调用 ASR。

原始转写数据治理（原始转写属于用户内容，不是普通中间产物）：

- 按 tenant/project 隔离；不跨用户去重，禁止跨项目缓存复用。
- 内容静态加密（at-rest encryption）；checkpoint 只保存 artifact ID/hash，不保存正文。
- 访问控制跟随项目权限；人工审核可访问范围由项目策略显式定义。
- 日志禁止记录转写正文，只记录 hash、长度和状态。
- 保存期限跟随章节或任务生命周期；项目删除时级联清理，删除前检查 checkpoint 引用。
- 外部 ASR provider metadata 只按允许字段白名单保存。
- 内容存数据库还是对象存储由实现选择，两种路径均必须满足以上约束。

NormalizedTranscriptArtifact（必须同时定义规范化输出与统一 artifact 身份）：

规范化输入：

- raw_transcript_hash 与 raw_timeline_hash。
- subtitle_normalization_hash 与 timeline_normalization_hash。

规范化输出：

- normalized_transcript 与 normalized_timeline。
- normalized_transcript_hash 与 normalized_timeline_hash。
- transcript_artifact_hash = hash(normalized_transcript_hash, normalized_timeline_hash, normalization contract version)。

L0 与 Omni 引用同一份规范化 artifact 身份，不得出现 L0 使用一份 normalized transcript 而 Omni 使用另一份同名但内容或 normalization 版本不同的 subtitle timeline；若 Omni 需要与 L0 不同的时间轴裁剪版本，必须显式生成独立派生 artifact hash，不得隐式替换。

L0QualityCheckpoint（输入签名与结果分离）：

L0QualityInputSignature（唯一缓存键）：

- audio_artifact_hash。
- transcript_artifact_hash（规范化后的转写 artifact）。
- expected_text_contract_hash（hard/optional/semantic/vocalization）。
- quality_policy_hash。
- alignment_algorithm_version。

Checkpoint payload（不参与缓存查找）：

- quality_result。
- evaluated_at。

失效语义：ASR provider/模型/请求合同变化 → 重新调用 ASR；normalization 算法变化 → 只重新处理原始转写；L0 对齐算法或策略阈值变化 → 只重新评估规范化 transcript，不调用 Seed；结果内容本身不参与签名。只有新策略判定失败且恢复状态机明确决定重试时才重新调用 Seed，避免无谓供应商成本；若项目决定“质量策略变化必须重新生成”，必须显式声明原因与成本影响，不得作为默认行为。

Omni 评审 checkpoint：

OmniReviewCheckpointSignature：

- `audio_artifact_hash`。
- `review_scope`（scene | seam）。
- `audio_window_start_ms` / `audio_window_end_ms`。
- `omni_expectation_contract_hash`（完整声音场景期望合同）。
- `voice_binding_summary_hash`。
- `transcript_artifact_hash`、`subtitle_timeline_hash`、`transcript_source`（Omni 输入包含字幕/ASR 时间轴，必须签名；若 Omni Prompt 实际不提交字幕，则这些字段不进入签名）。
- `omni_model_id`、`omni_prompt_hash`、`omni_schema_hash`。
- `audio_preprocessing_hash`。
- `semantic_policy_hash`。

接缝评审额外保存：`left_scene_audio_hash`、`right_scene_audio_hash`、`left_window`、`right_window`。

`omni_expectation_contract_hash` 的规范化输入必须覆盖 §10.2 的完整 Omni 输入合同：scene context、speech 与验证策略、vocalizations、声音事件及其时序、音乐/环境生命周期、声学处理（电话、混响、远近等）、performance 期望、timeline 窗口、voice binding summary、carry state、场景目标时长。规范化与字段顺序无关：不改变规范化语义、只改变字段顺序不得失效。`voice_binding_summary_hash` 独立保留供审计，但其内容同时并入期望合同；两者必须从同一规范化来源生成，避免双重字段语义不一致。

失效规则：音频、期望合同、字幕/ASR artifact、模型、Prompt、schema、预处理或策略任一变化均使评审缓存失效；Omni 变化只触发重新评审，不重新生成 Seed；音频或字幕变化必须使对应 Omni checkpoint 失效，防止质量结论对应错误音频。字幕/ASR 仅作辅助，不得被 Omni 当作已经听到音频事件的证据；Omni 必须仍然消费原始音频。

变更归因（直接失效 + 条件级联）：

| 变化 | 直接失效 | 条件级联 |
|---|---|---|
| Director Prompt/schema/policy | Director checkpoint | 新计划 hash 变化时失效 Seed；新音频产生后失效 Omni |
| 源事实（台词、speaker、performance_notes、instruct_scene、上下文） | Director checkpoint | 同上 |
| reviewed analysis artifact | Director checkpoint | 同上 |
| capability contract | Director checkpoint | 计划或 Prompt 变化时失效 Seed |
| reference/asset 修订或权限 | 绑定计划 | binding/reference hash 变化时失效 Seed |
| Seed Prompt/模型/timeline | Seed checkpoint | 新音频产生后失效 Omni |
| provider 请求合同/输出格式 | Seed checkpoint | 新音频产生后失效 Omni |
| L0 质量策略 | L0 质量 checkpoint | 通常不重新生成音频，除非新判定触发恢复状态机 |
| Omni Prompt/schema/policy/模型 | Omni checkpoint | 不失效 Director 或 Seed |
| 音频 artifact | Omni checkpoint | 不反向失效已完成的 Director |
| 字幕/ASR artifact | Omni checkpoint | 不重新生成 Seed |

级联原则：先重新计算直接受影响的派生产物，只有其内容 hash 实际变化时才级联失效下游；既避免错误复用，也避免无意义重烧 Seed 成本。

Checkpoint schema 版本与历史兼容：

每类 checkpoint 显式保存：checkpoint_type、checkpoint_schema_version、signature_contract_version、created_at、producer_version。

历史恢复原则：

- 缺字段不得静默当作命中。
- 历史 checkpoint 采用 append-only 版本迁移，不做原地覆盖：原 checkpoint 保持只读；确定性补算后创建 MigratedCheckpoint（checkpoint_schema_version、migrated_from_checkpoint_id、migration_version、migration_input_hash、migration_status、created_at），新版本引用旧 checkpoint 与 migration version；attempt ledger、provider request ID、计费记录只引用，不复制成新的消费事件；迁移必须幂等（相同旧 checkpoint ID + migration version 只生成一个结果）；迁移失败不破坏旧 checkpoint；新版本验证通过后才成为当前恢复入口。若存储结构只能在同一行增加字段，至少保存 original_schema_version、migration_history、migrated_at、migration_version，并禁止覆盖旧签名字段。
- 能重新执行 L0/Omni 而不调用 Seed 的，优先重新评估。
- 已有音频 artifact 完整时，不因 checkpoint schema 升级直接重烧 Seed。
- 无法证明输入兼容时进入明确的 `legacy_checkpoint_incompatible` 状态。
- 历史普通 1.0 checkpoint 继续按原模型恢复。
- 迁移过程不重置 Director、ASR 或 Omni 已消费预算。

生成 checkpoint 与评审 checkpoint 分离，避免只修改 Omni 评审 Prompt 就重新产生 Seed 成本。

### 12.3 计费

- 两个 Seed 模型使用相同公开后付费单价。
- 每条 provider attempt 保存真实模型 ID。
- 供应商已成功生成但质量失败的音频仍按实际输出时长计费。
- Omni 评审成本单独记录为平台质量成本；是否向用户收费必须另行决策，不能混入 Seed `¥1/分钟`。
- 导演层 LLM 调用成本单独记录为场景规划成本（provider、model、token usage、调用次数、错误和估算金额），不混入 Seed `¥1/分钟`；是否向用户收费另行决策。
- checkpoint 恢复不得重置已消费评审预算，也不得重置已消费导演预算。
- 影子评审上线前设置单场景、单章和单任务 Omni 调用/金额预算。

## 13. 测试策略

### 13.1 单元测试

- SeedSceneDirection 严格解析和非法字段拒绝。
- segment 引用完整、连续、有序。
- speech 不改写台词。
- 验证策略分配：前景 hard、重叠短插话 soft、群体词 semantic_only；soft 台词进入 optional 集合且缺失只记 warning。
- checkpoint 失效级联：台词/speaker/performance_notes/reviewed analysis artifact hash 变化使 Director checkpoint 失效；Omni Prompt 变化不使其失效；无关场景变化不失效当前场景；音频变化使 Omni checkpoint 失效；L0 策略变化只重评质量不直接调用 Seed。
- Omni 期望合同签名：只修改音效期望、电话滤波期望、角色表演期望或音乐停止位置均使 Omni checkpoint 失效；不改变规范化语义、只改变字段顺序不失效。
- Seed 请求合同：请求音频格式或采样率变化使 Seed checkpoint 失效；API Key、临时 URL、超时变化不失效。
- Transcript 签名：ASR 模型变化重新转写；只修改 L0 阈值复用已有转写；对齐算法变化不调用 Seed。
- Director checkpoint 状态：只有 completed 可复用；retryable_failed 沿用已消费预算只执行未用纠错机会；terminal_failed 复用终态决定；输入变化后 attempt ledger 不删除。
- 绑定计划 hash：槽位顺序变化使 Seed 失效；资产 revision 变化但内容 hash 相同时重新验证计划但不重烧 Seed。
- 缓存键与输出分离：provider 输出 artifact hash 不进入缓存键；输入一致但 artifact 损坏时进入恢复策略而非直接重调 Seed。
- Seed 生成键唯一性：policy_version、priority_score、reason_code、registry_version 变化但 binding_decision_hash 不变时不得重烧 Seed；完整 BindingPlan hash 不得作为生成缓存键。
- 原始转写持久化：normalization 算法变化时能仅用已持久化的原始转写重新规范化，不重新调用 ASR；原始 artifact 缺失或 hash 不一致时才允许重调 ASR。
- 规范化 artifact 统一身份：L0 与 Omni 使用同一 transcript_artifact_hash；Omni 使用不同裁剪版本时必须显式生成独立派生 artifact hash。
- 转写来源判别联合：provider 原生字幕来源不要求 ASR provider/model 字段；provider 字幕提取变化只重新提取字幕；来源切换生成新 transcript artifact。
- 临时 URL 恢复记录：短期恢复记录过期后不得直接重调 Seed，必须先查询 provider 状态或账单；临时 URL 不出现在缓存签名、普通日志和用户可见错误中。
- canonical hash：字段顺序变化不改变 hash；CRLF/LF 不改变文本语义 hash；timeline 1.2 与 1.200 得到相同 hash；事件顺序变化会改变 hash；slot_index 变化会改变 binding decision hash；policy 审计字段变化不改变生成 hash。
- checkpoint schema 迁移：缺字段不静默命中；schema 升级不直接重烧已有完整音频；无法证明输入兼容时进入 legacy_checkpoint_incompatible；迁移不重置已消费预算。
- 转写数据治理：日志不含转写正文；artifact 按项目隔离；项目删除级联清理前检查 checkpoint 引用。
- 恢复记录状态：expired_unverified 不得调用 Seed；只有 confirmed_failed 且恢复策略允许时才可考虑重新生成。
- hash API 分离：同一音频文件 content_digest 不随签名合同版本变化；canonical_hash 的 contract_version 变化使语义签名失效但不改变 content_digest；JSON artifact 可同时保存 semantic_hash 与 content_digest。
- checkpoint 迁移审计：原地覆盖历史 checkpoint 被禁止；迁移生成引用旧 checkpoint 的新版本；相同旧 checkpoint + migration version 幂等；attempt ledger 与计费只引用不复制。
- 恢复记录并发：并发下载只有一个 worker 能推进为 downloaded，其他 worker 复用结果；状态迁移满足 CAS 约束且禁止非法回退。
- L0 签名：相同输入签名复用旧 quality result；result 内容不参与签名；policy 变化只重新评估；audio/transcript/期望合同变化使 L0 checkpoint 失效。
- Omni 字幕签名：字幕来源或规范化变化使 Omni checkpoint 失效，不重新生成 Seed。
- Transcript 分层：ASR 合同变化重新转写；normalization 变化只重新处理原始转写；敏感字段过滤不落盘。
- 场景级声音身份：修改本场未出现角色的音色不使本场 Seed checkpoint 失效。
- 绑定决策/审计拆分：策略版本或 reason_code 变化但决策不变时不重新生成 Seed；槽位或 reference 内容变化失效。
- semantic_only 允许消费：被识别时不计入 extra；未被识别时不触发 missing；超过计划次数部分仍可判 extra。
- optional 场景首尾与无 hard 场景：BOF/EOF 虚拟锚点匹配；无 hard 台词时 optional 只允许不要求。
- optional 台词被 ASR 识别时不计入 extra_lines；从 expected transcript 整体删除 soft 台词会导致 extra 误判，必须禁止。
- optional 有序对齐：hard “对不起”不被 optional “对”破坏；hard “正好如此”不被 optional “好”破坏；两个相同 optional 只在各自相邻 hard 锚点区间内吸收；optional 与 hard 粘连时保持 hard 完整性；无时间戳用有序文本锚点、有时间戳优先时间窗；semantic_only 不参与 coverage。
- vocalization 结构化证据：evidence 为必填判别联合；`SegmentEvidenceRef.excerpt` 必须为源字段子串；`ReviewedAnalysisEvidenceRef` 必须指向版本化 artifact 的具体 finding；情绪类自由解释被拒绝；原文仅“悲伤”不得生成“哭泣”；inferred_performance 不允许强表演。
- 可辨识语言与非语言人声分类：有词义内容一律进入 `SeedSpeechDirection`；`SeedVocalizationDirection` 不携带 text。
- 覆盖不变量：每个可辨识文本片段被且仅被一个 speech 方向消费，不重复、不遗漏、不拆成未审定子串。
- 无证据可辨识语音事件拒绝。
- carry-in/carry-out 状态。
- 事件区间时长估算。
- natural/bounded/strict timeline 编译。
- `until_text` 子串校验和中性措辞。
- 实际 Prompt 字符估算。
- VoiceIdentityRegistry 冲突优先级和失效资产拒绝。
- SceneVoiceBindingPlanner 评分、稳定同分排序和 reason code。
- speech 与 vocalization 全量角色进入 reference 预算。
- 超三条 reference 时安全切分、描述降级和严格绑定拒绝。
- reference 槽位连续且与请求数组位置一致。
- multilingual 默认模型和历史模型恢复。
- 导演层预算作用域、纠错重试一次和保真降级分流（director_degraded_to_v1 与 manual_review）。
- 导演 Prompt/schema/policy 变更才失效导演 checkpoint；Omni 变更不使其失效。
- seed_scene Prompt 不包含过期硬编码主模型声明，能力描述来自共享常量。
- 两模型同价但账单保留真实模型 ID。

### 13.2 集成测试

- 小说改编入口和已有剧本入口得到一致 Seed 场景计划。
- 场景描述、角色 descriptions 和 default TTS model 从入口贯通到 Prompt。
- Seed-TTS 2.0 原生 speaker 在只有默认模型时仍能直传。
- 用户显式绑定从项目配置贯通到绑定计划、Prompt 和 provider references。
- 私有 reference 在物化时重新验证 owner 和 active 状态，公共 reference 重新验证 published 状态。
- 绑定变化只使实际受影响的场景 checkpoint 失效。
- 相邻场景对同一角色复用相同声音身份，槽位序号可不同但映射始终正确。
- 多人背景插话进入 Prompt 和 expected transcript。
- 非语言人声只进入 expected vocalizations。
- 音效蒙太奇使超长场景提前切分。
- strict timeline 不重叠、不越界、总时长合法。
- checkpoint 模型、timeline 和导演计划变化正确失效。
- Omni 评审失败不使 Seed 生成 checkpoint 失效。
- 影子评审异常不阻断成品保存。
- legacy 回退素材只在真实回退后生成。

### 13.3 固定场景评测集

至少保留以下五类，每类两个模型历史对照、multilingual 三次重复：

1. 台湾口音电话悬疑：角色区分、电话失真、持续鸟鸣、汽车和高跟鞋。
2. 多人神话战斗：多人声线、混响、连续法术和爆炸、群体反应、音乐变化。
3. 单人伤感回忆：参考音色、轻笑、吸气、哽咽、长停顿、音乐停止和道路环境。
4. 双主播直播：前景介绍、背景附和、重叠插话、包装袋声音和热闹氛围。
5. 广告时间轴：英文品牌名、固定总时长、关键台词时间窗、水声音效对位。

评测维度：

- 台词完整性。
- 说话人归属。
- 角色可区分度与跨场景一致性。
- 情绪和微表演。
- 插话与重叠自然度。
- 音效、音乐和环境兑现。
- 声学空间与特殊处理。
- 时间轴偏差。
- 场景接缝。
- P50/P95 时延、失败率、重试率和实际成本。

### 13.4 Omni 标定

Omni 结果必须与人工盲评对比，按 finding code 统计：

- precision。
- recall。
- false positive rate。
- false negative rate。
- 置信度校准。
- 重复评审一致率。

在每类严重问题没有足够正负样本前，Omni 只能作为影子或人工辅助评审。

## 14. 分阶段实施计划

### 阶段 0：基线冻结

- 固定 V1 测试基线和五类场景样本。
- 保存普通 1.0 与 multilingual 的现有 A/B 结果。
- 明确新任务默认切换不改写历史 checkpoint。
- 时间轴控制契约验证：用固定广告时间轴样例实测语法、边界、遵循精度和失败行为四个合同，至少重复生成 3 次，记录 `start_error_ms`、`end_error_ms`、`duration_error_ms` 和 `event_alignment_error_ms` 并统计 P50/P95 与最大偏差；验证结果分别输出 `bounded_timeline_eligible` 与 `strict_timeline_eligible`，并决定各自是否投产以及偏差处置方式。

验收：现有 `legacy_stems` 和 V1 Seed 回归均通过；时间轴验证报告包含四项合同的证据或明确的不可用结论。

### 阶段 1：multilingual 默认化与模型能力合同

- 开放后端模型集合和 API 类型（含 `app/api/v1/projects.py` 的 Literal 约束）。
- 更新前端类型和配置保存（`useAudiobookSceneVoicePool.ts`、`projectAudioConfigUtils.ts` 及 API 类型定义）。
- 新任务默认 multilingual。
- 两模型统一价格目录。
- 补齐 `config/models.yaml` 的 multilingual 登记：独立目录项或变体映射（含 `api_config.request_format.model` 的模型 ID 决策）、capability 登记 timeline_control 与多语种、价格继承普通 1.0、账单记录真实模型 ID、模型目录校验不判为未知模型。
- 更新分析与改编 Prompt 的模型能力合同：统一使用共享能力描述常量，不硬编码供应商模型 ID。
- checkpoint、账本和恢复测试覆盖历史普通模型。
- 实现统一 hash 基础设施（§12.2 Hash API 职责分离）：版本化 `canonical_hash` 与稳定 `content_digest`，以及 checkpoint schema registry 与 checkpoint contract version 定义；append-only 迁移与后续所有结构化合同均依赖它，必须先于迁移器完成，禁止迁移器临时自实现 hash。
- 实现 append-only migration runner（§12.2 历史恢复原则）：migration_input_hash 使用 canonical_hash；覆盖普通 1.0 历史 checkpoint、缺字段 checkpoint 和旧签名 checkpoint；迁移失败进入 `legacy_checkpoint_incompatible`；不重烧已有完整音频，不重置任何账单、ASR、Director 或 Omni 预算。

验收：新任务只请求 multilingual；旧 checkpoint 仍请求原模型；账单单价相同且模型 ID 正确；分析、改编、渲染、checkpoint 和账单的模型能力口径一致；上游 Prompt 不含过期硬编码主模型声明；canonical_hash 与 content_digest 通过基础稳定性测试（字段顺序、CRLF/LF、浮点量化、事件顺序敏感，content_digest 不随 contract version 变化）；历史 checkpoint 经 append-only 迁移后可恢复，迁移不覆盖旧版本且幂等，无法证明兼容时进入 legacy_checkpoint_incompatible。

### 阶段 2：入口上下文修复

- 贯通场景描述、角色 descriptions 和 default TTS model。
- 构造每场景局部描述。
- 场景描述进入计划、Prompt 和签名。

验收：固定样例 Prompt 顶层不再使用泛化兜底，且切分后的每个场景具有正确局部上下文。

### 阶段 3：Seed 场景导演合同

- 新增 §5 数据模型、解析器和验证器。
- 建立独立 Seed 改编 Prompt。
- 不再让分轨参数主导 Seed 输出。
- ScriptSegment 台词事实保持不变。
- 实现 Director 单次/单章/单任务预算策略与统一超时。
- JSON/Schema/事实校验失败时每批次最多一次纠错重试。
- 实现 `director_degraded_to_v1` 与 manual_review 保真分流。
- 持久化 Director attempt ledger 与导演计划 checkpoint；恢复时累计已消费次数、token 和金额，不重置预算。
- 实现 `SeedSceneDirectorPolicy` 作为服务端版本化策略（唯一配置所有权，字段与冻结规则见 §4.3）；默认值可在真实调用标定后确定，字段与超预算拒绝行为必须进入合同。
- 实现 DirectorInputSignature 作为导演计划 checkpoint 唯一缓存键，与 completed/retryable_failed/terminal_failed 三态恢复语义（见 §12.2）。

验收：背景插话与重叠人声统一由 `SeedSpeechDirection` 表达，非语言人声由 `SeedVocalizationDirection` 表达；音效蒙太奇、音乐生命周期和声学处理均能结构化表示；JSON/Schema/事实校验失败最多纠错一次；超预算不继续调用；可保真场景降级 V1 并记录 reason code；不可保真场景进入 terminal policy；恢复任务不会重新获得 Director 预算；导演计划输入签名命中时不产生任何导演调用。

### 阶段 4：声音绑定规划、事件映射与 Prompt V2

- 建立 `VoiceIdentityRegistry` 只读领域视图。
- 新增纯领域 `SceneVoiceBindingPlanner`，从 Prompt 编译器移出槽位选择；speech 和 vocalization 全量角色统一参与 reference 预算。
- 实现版本化评分、稳定排序、reason code 和超三条 reference 决策；绑定计划和 reference 内容 hash 进入 checkpoint；`binding_decision_hash` 与 `binding_audit_hash` 分离，只有决策 hash 进入 Seed 生成缓存键。
- 将各业务合同（binding decision/audit、Seed 签名、Transcript、L0、Omni）接入阶段 1 实现的统一 hash helper（§12.2 Hash API 职责分离）：所有结构化输入签名和语义合同统一使用版本化 `canonical_hash`；所有音频、reference 和持久化 artifact 字节统一使用稳定 `content_digest`；禁止各模块自行实现 hash 规则，禁止把二进制内容交给 canonical_hash。
- 实现 SeedGenerationInputSignature/Output 分离与短期 ProviderRecoveryRecord 恢复状态机（含 recovery_method 判别与双层幂等键）。
- 实现 RawTranscriptArtifact（含 §12.2 数据治理规则）与 NormalizedTranscriptArtifact；L0QualityCheckpoint 输入签名与结果分离。
- 映射显式导演事件。
- 加入事件区间时长估算。
- 加入 carry state。
- 修复 vocalization、表演模板、`until_text` 和字符估算。
- 实现 natural/bounded/strict timeline；`bounded_timeline` 与 `strict_timeline` 分别依据阶段 0 的版本化验证结论开放；任一模式未通过时只关闭该模式，不连带关闭已通过的模式。

验收：用户显式绑定不会被静默替换；最多三条 reference 与 Prompt `@音频N` 严格对应；四人以上场景能够确定性地产生安全切分、可审计降级或明确拒绝；五类固定样例均生成结构正确、台词逐字一致、时长合法的 multilingual Prompt；Seed 输入签名命中时不产生供应商调用；输出 artifact 损坏时进入恢复状态而非直接重调；normalization 变化不调用 ASR；L0 policy 变化不调用 Seed；相同音频文件的 content_digest 不随 contract version 变化；相同结构化合同在 contract version 变化时 canonical hash 变化；二进制 artifact 不进入 canonical_hash。

### 阶段 5：Omni 影子评审

- 新增独立语义评审服务和 Schema。
- 场景级评审和接缝抽检接入。
- 设置预算、超时、错误分类和评审 checkpoint。
- 实现 OmniReviewCheckpointSignature：完整 expectation contract hash、transcript/timeline 辅助输入签名、接缝评审双音频窗口签名（见 §12.2）。
- 只记录，不阻断。

验收：Omni 失败不影响成品；结果可定位到时间区间和 scene ID；重复任务复用评审缓存；Omni policy 变化只重新评审，不重新生成 Seed。

### 阶段 6：人工标定和有限自动恢复

- 使用盲评数据标定 finding code。
- 发布版本化语义质量策略。
- 仅开放高置信、可定位、严重问题的一次自动重试。

验收：自动处置集合有明确 precision/recall 门槛、成本上限和一键关闭开关。

### 阶段 7：延迟回退资产和生产收敛

- Seed 主路径不再提前生成真实分轨素材。
- 回退时按场景生成并持久化 artifact。
- UI 明确展示 Seed、人工处理和 legacy fallback 状态。

验收：Seed 全通过章节不产生 SFX/BGM 回退素材成本；回退章节只生成失败场景所需素材。

## 15. 发布和回滚

必须提供独立开关：

- multilingual 新任务默认开关。
- V2 SceneDirector 开关。
- timeline 开关。
- Omni 影子评审开关。
- Omni 自动处置开关。
- legacy fallback 开关。

回滚原则：

- 关闭 SceneDirector 后：
  - 能由 V1 保真承载的场景回到 V1 确定性 Prompt。
  - 含 V1 无法承载的审定强制事件时，按 terminal policy 进入 manual_review 或显式 legacy fallback。
  - 禁止为了完成回滚而静默删除插话、重叠、音乐生命周期或声学事件。
- SceneDirector 开关作用范围：只影响新生成计划；不使已有有效 V2 checkpoint 无条件失效；恢复历史 checkpoint 时遵循 checkpoint 的 schema/version；关闭后是否允许新任务使用旧 V1 路径由发布策略明确。
- 关闭 Omni 不影响 L0 硬闸门。
- multilingual 供应商异常时可显式恢复普通 1.0，但不得改写历史记录。
- 任何回滚不得重新计费或重新生成已通过且签名兼容的场景。

## 16. 完成定义

V2 完成需要同时满足：

- 新 Seed 场景任务默认使用 `seed-audio-1.0-multilingual`。
- 分析、改编、渲染、checkpoint 和账单的模型能力口径一致，上游 Prompt 无过期硬编码主模型声明。
- 台词验证按 hard、optional（软校验）、semantic_only 和 vocalization 四类合同分级（四类集合定义见 §10.4，不存在 soft_expected_texts 字段）；背景插话不因 ASR 识别能力有限而误触发重试或回退。
- 普通 1.0 只承担历史兼容、A/B 和紧急回滚。
- 两模型价格一致且计费记录可区分真实模型。
- 小说到场景存在独立 Seed 导演合同，不再仅依赖旧 `ScriptSegment` 的分轨字段。
- 所有 Prompt 台词逐字来自审定事实源。
- 项目声音身份、场景 reference 槽位和事件表演三层决策相互分离。
- 声音绑定可追溯到合法来源，最多三条 reference 的选择具有稳定评分、reason code 和显式超限策略。
- 背景插话角色进入声音身份预算，严格绑定不会因槽位不足或资产失效而静默换声。
- 背景插话、非语言人声、重叠关系、连续音效、音乐生命周期和声学空间可结构化表达。
- 场景时长估算包含声音事件区间。
- 时间轴能力已完成真实契约验证并形成版本化结论；只有验证通过的 timeline 模式才能开放；strict 未通过时保持关闭，不阻塞 natural 模式下的 V2 发布；产品和 API 不得暴露尚未通过验证的模式。
- SeedSceneDirector 具有四级预算作用域、纠错重试一次、保真降级判定和独立成本记录。
- L0 硬闸门与 L1 Omni 语义评审职责分离。
- Omni 结果可审计、可定位、受预算控制，未标定前不自动阻断。
- 相邻场景接缝具备语义连续性评审。
- Seed 成功路径不提前产生不必要的分轨素材。
- 两个真实章节入口共享同一导演、规划、渲染和质量服务。
- `legacy_stems` 行为保持兼容，且所有回退对用户和账单明确可见。
- 所有结构化签名使用统一版本化 canonical hash；二进制 artifact 使用稳定 content digest，不随签名合同版本变化。
- Director、Seed、Transcript、L0、Omni checkpoint 均完成输入签名与输出校验分离。
- 历史 checkpoint 迁移可审计（append-only、可追溯来源版本），且不直接重烧已有完整音频。
- normalization 变化不重新调用 ASR；L0 policy 变化不直接调用 Seed；Omni policy 变化不重新生成音频。
- 原始转写按项目隔离、静态加密并受生命周期管理。
- provider 恢复状态不因临时 URL 过期而重复计费。
- checkpoint 恢复不重置任何已消费预算。

## 17. 明确不做

- 不让 LLM 在 Prompt 编译阶段改写台词。
- 不让 LLM 选择 reference 槽位或覆盖用户绑定的声音身份。
- 不把整章作为单次 Seed 请求。
- 不为了使用 multilingual 而给所有小说台词伪造绝对时间。
- 不用 Omni 替代 ASR、字幕对齐或本地波形检测。
- 不在未标定时让主观 Omni 评分无限重试 Seed。
- 不把供应商临时 URL、API Key 或完整 Base64 音频写入长期 checkpoint。
- 不复制一整套与现有有声书完全独立的公共剧情事实系统。
- 不删除 `seed-audio-1.0` 的历史兼容能力。

## 18. 实施索引

V1 现有关键模块：

- 场景接入：`backend/app/services/audiobook/engine_pkg/_scene_render_mixin.py`
- 场景编排：`backend/app/services/audiobook/scene_engine/chapter_pipeline.py`
- 场景规划：`backend/app/services/audiobook/scene_engine/planner.py`
- Prompt 编译：`backend/app/services/audiobook/scene_engine/prompt_compiler.py`
- 场景渲染：`backend/app/services/audiobook/scene_engine/scene_renderer.py`
- 确定性质量闸门：`backend/app/services/audiobook/scene_engine/quality_gate.py`
- 场景装配：`backend/app/services/audiobook/scene_engine/scene_assembler.py`
- 项目运行时音色配置：`backend/app/services/audiobook/project_audio_runtime.py`
- 参考音频解析：`backend/app/services/audiobook/scene_engine/voice_reference_resolver.py`
- 参考音频物化：`backend/app/services/audiobook/scene_engine/preview_reference_asset.py`
- 前端场景音色池：`frontend/src/pages/audiobook/useAudiobookSceneVoicePool.ts`
- 前端音频配置序列化：`frontend/src/pages/audiobook/projectAudioConfigUtils.ts`
- Seed 供应商适配器：`adapters/volcengine/audio_generation.py`
- 剧本事实模型：`backend/app/services/audiobook/script_adapter_pkg/_dataclasses.py`
- 剧本分析 Prompt：`backend/app/services/audiobook/script_adapter_pkg/_analysis.py`
- 引擎模式指导：`backend/app/services/audiobook/script_render_mode.py`
- 项目音频配置 API（模型 Literal 约束）：`backend/app/api/v1/projects.py`
- 模型目录登记：`config/models.yaml`（seed-audio-1.0 条目及 multilingual 登记决策）
- 剧本改编 Prompt：`backend/app/services/audiobook/script_adapter_pkg/_transform.py`
- 剧本质量审查：`backend/app/services/audiobook/agents/audio_quality_reviewer.py`
- 当前最终音频评审：`backend/app/services/audiobook/engine_pkg/_review_mixin.py`
- Qwen Omni 音频理解基础：`backend/app/services/audiobook/prompt_audio_asr_provider.py`

V2 规划新增模块（目标职责边界，具体路径可按实际代码库命名调整，但职责不得混入其他模块）：

- 结构化 hash：`backend/app/services/audiobook/scene_engine/canonical_hash.py`；hash helper 不得散落到多个模块。
- checkpoint 合同与迁移：`backend/app/services/audiobook/scene_engine/checkpoint_contracts.py`、`backend/app/services/audiobook/scene_engine/checkpoint_migrations.py`；迁移逻辑不得混入 renderer。
- provider 恢复：`backend/app/services/audiobook/scene_engine/provider_recovery.py`；恢复状态机不得混入 scene renderer。
- Transcript artifact：`backend/app/services/audiobook/scene_quality/transcript_artifacts.py`；原始/规范化转写不得与 ASR provider 实现耦合。
- Omni 评审：`backend/app/services/audiobook/scene_quality/semantic_models.py`、`backend/app/services/audiobook/scene_quality/qwen_omni_reviewer.py`；Omni checkpoint 不得与最终质量评审大函数重新耦合。

本文档后续变更应优先更新“已确认决策、数据合同、状态机、实施阶段和完成定义”。真实供应商合同、价格和灰度证据应注明验证日期及来源；历史执行日志不持续堆叠到正文，可放入独立验证记录或附录。
