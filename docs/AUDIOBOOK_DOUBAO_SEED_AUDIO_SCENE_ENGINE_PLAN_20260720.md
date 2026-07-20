# 有声小说：豆包 Seed-Audio 场景级音频生成引擎落地方案

> 版本：1.1
> 日期：2026-07-20
> 状态：方案评审中（已完成代码基线与接口约束复核，未开始主流程编码）
> 适用范围：有声书章节音频生成链路（`backend/app/services/audiobook/**`）、火山引擎/豆包音频适配器（`adapters/volcengine/**`）

---

## 1. 背景与结论

### 1.1 背景

当前有声书链路采用"多模型分轨生成 + 时间线后期混音"：

- 语音：按项目/角色选择的 TTS 模型逐段合成，当前支持 Qwen、CosyVoice、MiniMax、MiMo、StepAudio、Seed-TTS 2.0 等，不是固定使用 Seed-TTS 2.0。
- 音效：`SoundEffectDesigner` 优先匹配允许来源的素材；缺失素材由 Vidu Timing2Audio 等生成，再注册入库并按时间线叠加。
- 配乐：`MusicComposer` 通过 Mureka O1 等独立生成 BGM。
- 合成：`AudioMixer.mix_chapter()` 拼接语音并插入段间停顿，再由 `_apply_sound_effects()` / `_apply_background_music()` 叠加音效和配乐。

问题的本质不是"音效模型不够好"，而是**结构决定上限**：音效/配乐与人声不同源、情绪不同步、时间点靠估算，无法复现"音效嵌在台词中间、拟声与情绪同源"的效果（如台词中途的金属"唰"声、压在句子里的脚步声）。

豆包 `seed-audio-1.0`（音频生成 HTTP 接口 `/api/v3/tts/create`）能在**同一次推理**中联合生成"对白 + 音效 + 音乐 + 节奏情绪"，正是用户实测效果显著更好的根因。项目已注册该适配器 `DoubaoSeedAudio10Adapter`（`adapters/volcengine/audio_generation.py`），但目前只接入"资产工作台/音频场景"，未进入有声书主链路。

### 1.2 结论

采用 **方案 B 的工程化版本：以 `seed-audio-1.0` 为主要成品渲染器的"场景级统一音频引擎"**。渲染粒度是场景，不是整章；现有逐段 TTS + 分轨混音链路作为自动回退、局部修复和纯旁白路径长期保留，不能在新链路未稳定前下线。

其它 TTS 模型承担两类职责：

1. 用户已选定非豆包音色时，生成一次性、可缓存的干净角色参考录音，供 Seed Audio 通过 `audio_data`/`audio_url` 引用。
2. 场景统一生成未通过台词完整性或声音质量闸门时，作为可靠的逐段 TTS 回退。

同账号下的豆包 Seed-TTS 2.0 系统音色或豆包声音复刻音色优先直接作为 `references[].speaker` 使用。任何其它供应商的 `voice_id` 都不能直接传给豆包。

**不推荐方案 A（仅把音效模型替换为 `seed-audio-1.0`、其余不变）作为最终架构**：它可以作为 A/B 基线验证 Seed Audio 的孤立音效能力，但不会改善逐句 TTS 的情绪连续性、对白与动作同步、电话失真、喘息/哭腔等语言与音效交界问题，也无法获得用户样例中最有价值的统一声场效果。

---

## 2. 目标与非目标

### 2.1 目标

1. 引入"场景级统一渲染"能力：将章节切为目标 `45-75s` 的声场单元，在同一次推理中生成对白、旁白、环境声、动作音效和配乐。
2. 保留现有 `ScriptSegment[]` 作为唯一剧本事实源；生成提示词时逐字复制已审定台词，不允许模型在提示词编译阶段改写台词。
3. 建立模型无关的角色声音身份层，把豆包 `speaker`、用户参考录音和其它 TTS 生成的标准参考片段统一为稳定资产。
4. 利用 Seed Audio 返回字幕和必要时的 ASR，对生成音频执行台词覆盖、增词、漏词、顺序和音频技术质量检查。
5. 复用任务追踪、进度、检查点和产物保存骨架，但修正当前场景音频计费与响度处理缺口。
6. 通过 `legacy_stems / seed_scene / auto` 三种模式实现灰度、自动回退和可观测对比。

### 2.2 非目标

- 不在第一阶段删除任何现有 TTS、音效、配乐或混音实现。
- 不承诺整章只调用一次 Seed Audio；120 秒、3000 字符和最多 3 条 references 决定必须分场景。
- PoC 阶段不强制数据库迁移；进入生产前必须有稳定的角色参考音色资产，不能把 Base64 长期写入 `Project.audio_config`。
- 不在第一阶段实现对白、音效、音乐分轨导出；Seed Audio 返回的是完整混合音频。
- 不把现有 `pydub` 的 dBFS 增益近似当作真正 EBU R128。生产响度标准化需单独验证或引入 FFmpeg `loudnorm`。
- 不改变现有剧本编辑和章节选择语义；新元数据以兼容字段接入。

---

## 3. 关键事实：`seed-audio-1.0` 能力与硬约束

来源：豆包语音《音频生成 HTTP》文档，接口 `POST https://openspeech.bytedance.com/api/v3/tts/create`。

| 维度 | 约束 | 架构影响 |
|---|---|---|
| 单次输出时长 | 最长 **120s** | 必须按场景切块，规划值不能贴近硬上限 |
| `text_prompt` | 最长 **3000 字符**（提示词 + 待合成文本合计）| 每场景提示词需受控在 3000 字符内 |
| `references` | 最多 **3 条**；音频引用每条 **≤30s、≤10MB**，支持 wav/mp3/pcm/ogg_opus | 旁白也占一条；需要稳定绑定的声音最多 3 个 |
| 参考图片 | 仅 1 张、≤10MB、jpeg/png/webp；图片与音频参考互斥 | 有声书场景默认不使用图片参考 |
| `speaker` | 可传"豆包语音合成 2.0 的音色 ID"或"声音复刻音色 ID"；`speaker`/`audio_data`/`audio_url` 三者互斥 | **音色绑定核心**：预置/复刻音色确定性强、可跨场景复用 |
| 多角色 | 未绑定音色的角色可按文字描述生成 | 角色数量可超过 3，但未绑定角色不承诺跨场景声纹一致 |
| `model` | `seed-audio-1.0`（中/英）；`seed-audio-1.0-multilingual`（多语种 + 时间轴控制）| 中文有声书用 `seed-audio-1.0`；如需时间轴/多语种可切多语种版 |
| `audio_config` | 支持格式、采样率、语速、响度、音调和字幕开关 | 字幕必须开启，用于台词完整性检查和章节字幕 |
| 返回 | Base64 音频和/或约 2 小时有效 URL，并可返回句/词级时间戳 | 收到响应后立即落盘；临时 URL 不得进入长期项目状态 |

### 3.1 本方案采用的保守口径

- 所有 `references` 条目统一按最多 3 条治理，不依赖“speaker 是否另算”的未验证假设。
- 旁白若要求全书声音一致，必须计入绑定声音数量。
- `seed-audio-1.0-multilingual`、时间轴格式、字幕响应结构和 WAV 输出在进入主流程前做真实接口契约测试。
- 用户示例证明模型具备统一声场能力，但不等于已经证明长篇跨场景音色一致性、逐字准确率和多次生成稳定性；这些必须通过阶段 0 的重复实验确认。

---

## 4. 现有链路事实（改造基线）

### 4.1 引擎与组件

- 引擎入口：`AudiobookEngine`（`backend/app/services/audiobook/engine_pkg/__init__.py`），由多个 Mixin 组合。
- 核心流水线：`GenerationMixin.generate_chapter_audio()`（`engine_pkg/_generation_mixin.py:50`），依次执行策略、剧本改编、并行设计、剧本质量评审、音频提示词审阅、TTS 合成、混音、最终评审、保存和统计。
- 组件初始化：`AudiobookEngineBase.__init__()`（`engine_pkg/_base.py:62`）实例化 `audio_director`/`script_adapter`/`voice_designer`/`sound_effect_designer`/`music_composer`/`audio_quality_reviewer`/`voice_manager`/`tts_engine`/`audio_mixer`。
- 后台任务：`background_jobs_full.py:generate_audiobook_background()`、`background_jobs_audio.py`（已有剧本生成音频）、`background_jobs_scripts.py`（仅生成剧本）。

### 4.2 关键数据结构

- `ScriptSegment`（`script_adapter_pkg/_dataclasses.py:160`）：`type`(narration/dialogue/monologue)、`text`、`speaker`、`emotion`、`performance_notes`、`pause_before/after`、`voice_params`、`instruct_*` 等。
- `ChapterStructure`：嵌套段落结构，`_flatten_chapter_structure()` 可扁平化为 `ScriptSegment` 列表。

### 4.3 音色体系

- `create_voice_manager()`（`voice_manager_factory.py`）按 `tts_model` 生成对应管理器；Seed 系为 `SeedTTSVoiceManager`（`voice_manager_seed_tts.py`），从 `seed_tts_2_0_voices.json` 加载音色，`speaker` 即"豆包 2.0 音色 ID"——**可直接作为 `seed-audio-1.0` 的 `speaker`**。
- 项目级音色映射：`apply_project_voice_mapping()` 承接 `Project.audio_config` 中按 TTS 模型保存的角色配置。
- 当前 API 最终只持久化角色的 `character_id/name/voice_id/tts_model`。虽然运行时识别 `voice_clone_data_url`、`voice_design_prompt` 等字段，但 `projects.py` 的持久化白名单会将它们排除，因此现有配置不能直接承担 Seed Audio 参考音色资产层。

### 4.4 `seed-audio-1.0` 现有调用范式（资产工作台）

`backend/app/api/v1/asset_studio_api/routes_audio.py:123-149`：

```python
from adapters.registry import registry
adapter = registry.get_adapter(resolved_model_id)  # "seed-audio-1.0"
result = await asyncio.to_thread(
    adapter.generate,
    prompt=cleaned_prompt,
    references=references or None,   # [{"speaker": "<音色ID>"}, ...]
    audio_config={"format": "mp3", "sample_rate": 48000, "pitch_rate": 0, "speech_rate": 0, "loudness_rate": 0},
    watermark={},
)
# result.outputs[0] 为带 2h 有效期的 URL
output_path = _materialize_output_reference(result.outputs[0], kind="audio", subdir="audio/scene")
```

新引擎可以复用该"registry → adapter.generate → 下载 URL 落盘"范式，但不能直接复用当前能力边界：

1. `routes_audio.py` 目前只接受逗号/换行分隔的 `speaker_id`，不接收 `audio_data`/`audio_url`。
2. `DoubaoSeedAudio10Adapter` 只解析 URL、`duration` 和 `original_duration`，尚未保留 Base64 音频与字幕。
3. 当前适配器只注册 `seed-audio-1.0`，没有 multilingual 模型路由和模型级能力校验。
4. 当前请求没有针对 429、5xx、超时和临时 URL 下载失败的专用重试策略。
5. `estimate_asset_studio_basis_yuan()` 没有 `text_to_audio` 专用价格分支；资产工作台又未传预计时长，当前冻结金额实际会按默认 1 秒估算，不能原样用于章节计费。
6. `AudioMixer._normalize_loudness()` 使用 dBFS 近似目标响度，不是严格的 EBU R128 综合响度测量。

---

## 5. 目标架构：场景级音频渲染引擎

### 5.1 总体数据流

```
章节文本
  → [策略] AudioDirector.formulate_strategy()（复用）
  → [剧本改编] AudiobookScriptAgent.adapt_chapter() → ScriptSegment[]（复用并保持为唯一台词事实源）
  → [剧本质量闸门] 原文保真、对白归属、可听性评审（复用）
  → [场景规划] ScenePlanner：ScriptSegment[] → SceneRenderPlan[]
  → [音色解析] VoiceReferenceResolver：角色声音身份 → references（≤3）
  → [提示词编译] ScenePromptCompiler：确定性复制台词并编译声场、表演、停顿、音效和音乐描述
  → [计划校验] 字符、时长、reference、角色、台词哈希和资源可用性检查
  → [场景渲染] SeedAudioSceneRenderer：调用 Seed Audio → 立即落盘音频 + 字幕 + 元数据
  → [质量闸门] SceneAudioQualityGate：字幕/ASR 对齐 + 技术质量检查
  → [重试/拆分/回退] 强化提示词 → 拆分场景 → legacy_stems
  → [章节装配] SceneAudioAssembler：按场景边界拼接、留白、连续环境过渡和真实响度处理
  → [最终评审 / 保存 / 统计]（复用）
```

### 5.2 核心数据模型

不修改 `ScriptSegment` 的职责，新增场景渲染计划。建议最小字段如下：

```python
@dataclass(frozen=True)
class SceneRenderPlan:
    scene_id: str
    source_segment_indices: list[int]
    expected_text: str
    expected_duration_s: float
    speaker_names: list[str]
    references: list[dict]
    prompt: str
    prompt_hash: str
    reference_hashes: list[str]
    boundary_before: str
    boundary_after: str
    render_mode: str = "seed_scene"
```

运行态结果单独保存，避免把供应商响应写回不可变计划：

```python
@dataclass
class SceneRenderResult:
    scene_id: str
    status: str
    audio_path: str | None
    subtitle_payload: dict | list | None
    duration_s: float | None
    original_duration_s: float | None
    attempt_count: int
    quality_report: dict
    provider_metadata: dict
```

检查点以 `prompt_hash + reference_hashes + model + audio_config` 为签名。剧本、提示词、音色或模型参数未变化时可复用已成功场景；任何一项变化只使对应场景失效。

### 5.3 场景切分（ScenePlanner）

职责：把扁平的 `ScriptSegment[]` 聚合为 `Scene[]`，每个 Scene 满足双重上限。

- **目标时长**：`45-75s`，兼顾情绪连续性与局部重生成成本。
- **软上限**：`90s`；超过后优先寻找最近语义边界切分。
- **硬规划上限**：`105s`，为模型生成波动预留至少 15 秒，不允许按 120 秒贴边规划。
- **字符预算**：目标 `≤2600`，硬规划上限 `≤2800`，为转义、重试约束和模型版本差异预留空间。
- **切分优先级**：时间/地点转场 > 主要说话人集合变化 > 情绪阶段变化 > 音乐段落变化 > 段落边界 > 时长/字符硬切。
- **音色上限**：一个场景最多 3 个 references，旁白计入。超限时优先拆场景；只有一句话且后续无需保持声音一致的次要角色才允许降为文字描述。
- **连续性**：计划需保存前后场景的环境、音乐和情绪状态，供提示词结尾与下一场景开头保持一致。
- **禁止切分点**：同一句台词内部、问答紧邻的关键反应之间、动作原因与直接结果之间。

### 5.4 角色声音身份与参考资产（VoiceReferenceResolver）

目标：跨场景一致性来自"同一角色在每个场景绑定同一音色标识"。

- 声音来源优先级：
  1. **豆包 Seed-TTS 2.0 系统音色或豆包声音复刻 ID**：直接使用 `references[].speaker`。
  2. **用户上传且已确认授权的干净参考录音**：使用稳定 `audio_url` 或请求时编码为 `audio_data`。
  3. **其它 TTS 音色生成的标准参考片段**：仅在用户明确选择该音色时生成一次并缓存，不能传原供应商 `voice_id`。
  4. **文字声音描述**：仅用于不要求复现的临时角色。
- 标准参考片段建议 `10-20s`，单人、干声、无音乐、无环境声、无混响、发音清晰，最长不得超过 30 秒。
- 同一角色在全书维度锁定同一个声音身份；场景只选择当前需要的最多 3 个 reference。
- Prompt 中通过 `@音频1`、`@音频2`、`@音频3` 引用对应的音频 reference；数组顺序必须由编译器固定并进入签名。
- 参考资产至少保存：`asset_id/source_type/source_model/source_voice_id/storage_uri/sha256/duration/content_type/authorization_scope`。
- 不把 Base64 长期写入项目 JSON。PoC 可临时使用现有存储，生产阶段应新增通用角色参考音色资产，或扩展现有专用 voice asset 体系；当前共享 `AudioLibraryAsset` 仅支持 `sfx/music`，不能直接承载角色声音身份。

### 5.5 提示词编译（ScenePromptCompiler）

提示词编译采用**确定性模板优先**，不让 LLM 自由重写整段场景：

1. **场景声学块**：地点、时间、空间大小、远近关系、环境底噪和总体情绪。
2. **角色声音块**：角色名、年龄、性别、口音、音色特征，以及明确的 `@音频N` 对应关系。
3. **全局约束块**：对白始终清晰位于前景；音乐/环境声不得遮挡；严格朗读引号内原文；禁止增删、改写或产生额外可辨识台词。
4. **顺序事件块**：按 `ScriptSegment` 顺序逐项输出。台词直接从 `segment.text` 复制；`emotion/performance_notes/instruct_*` 编译为表演说明；`sound_effects/music_cue` 编译为台词前、中、后的声场事件。
5. **收尾连续性块**：描述场景结尾保留或停止的环境、音乐和人物状态，供章节装配及下一场景延续。

LLM 只允许补充非台词的声场描述和压缩重复说明；调用后必须重新校验所有原台词逐字存在且顺序不变。若校验失败，直接使用纯模板结果，不对 LLM 结果做猜测性修补。

示例骨架：

```text
场景：深夜宫殿内殿，空间空旷，人物距离较近，整体压抑、紧张。

角色与声音：
- 旁白的声音参考 @音频1，沉稳克制，保持叙述者身份。
- 太后的声音参考 @音频2，55岁左右，端庄优雅、威严冷酷。
- 御医的声音参考 @音频3，中年男性，浑厚、略微沙哑、谦逊。

生成要求：
对白始终清晰位于前景。环境声和音乐不得遮挡台词。
严格朗读引号中的原文，不新增、删减或改写台词，不产生额外可辨识人声。

按顺序生成：
1. 低沉弦乐和轻微宫殿室内底噪进入。
2. 太后缓慢、冷酷且不容置疑地说：“把头抬起来。”
3. 短暂停顿约0.5秒，近处传来两声轻微布鞋脚步。
4. 御医恭敬、正式地回应：“遵旨。”
5. 音乐降低，保留紧张低频，场景在短暂静默中结束。
```

现有 `chapter_cadence` 继续作为场景内部与边界的节奏信号：内部停顿编译为表演指令，不再由后期重复插静音；只有场景边界由章节装配器决定留白或过渡。

### 5.6 场景渲染（SeedAudioSceneRenderer）

- 扩展适配器同时支持 `seed-audio-1.0` 和经契约验证后的 `seed-audio-1.0-multilingual`，不能在适配器内部固定模型 ID。
- 对 references 做结构化校验：最多 3 条；每条 `speaker/audio_data/audio_url` 三选一；音频格式、大小、时长可验证时必须在请求前验证。
- `audio_config` 默认 `mp3/48000Hz/enable_subtitle=true`。WAV 作为生产中间格式需先实测确认，再决定是否切换以减少重复编码损失。
- 同时解析 URL、Base64 音频、字幕、`duration`、`original_duration` 和供应商请求标识。
- 响应成功后立即原子落盘并计算 SHA-256，再把稳定路径写入检查点；临时 URL 只作为下载来源。
- 对连接超时、429、可重试 5xx 和临时 URL 下载失败使用有上限的指数退避；内容质量失败由质量闸门治理，不与网络重试混在一起。

### 5.7 场景音频质量闸门（SceneAudioQualityGate）

完整混合音频不可分轨修复，因此质量闸门是生产必需能力，不是最终抽检：

1. 规范化剧本台词与供应商字幕，按场景逐句对齐，检查漏句、增句、改词和顺序错误。
2. 字幕缺失或结构不可用时调用已有 ASR 辅助能力；供应商字幕与 ASR 结果都需保留来源标记。
3. 检测空音频、截断、时长异常、削波、异常长静音、采样率/声道和文件可解码性。
4. 初始自动门槛：关键台词缺失数 `0`、未在剧本或声场计划中声明的额外可辨识台词数 `0`、规范化文本覆盖率 `≥99%`。已明确计划的笑声、哭声、喘息和“嗯”等非完整词语单独标记，不误判为增词。门槛需通过 PoC 数据校准，不能只凭单个样例定值。
5. 音色相似度和音乐是否遮挡对白在第一阶段先人工评分；有可靠声纹/源分离能力后再转自动指标。
6. 失败恢复顺序：同场景强化“精确台词/前景对白”约束重试一次 → 在语义边界拆成两个场景各重试一次 → 回退 `legacy_stems`。不得无限重试。

质量报告至少包含 `transcript_coverage/missing_lines/extra_lines/order_valid/audio_decodable/clipping/silence/duration/status/fallback_reason`。

### 5.8 章节装配与字幕（SceneAudioAssembler）

- 新增专用 `SceneAudioAssembler` 或让 `AudioMixer` 增加明确的 `concat_scenes()`，只处理顺序装配、边界留白、必要的环境过渡和最终编码，不再叠加外部 SFX/BGM。
- 同一连续场景默认使用短边界或相同房间底噪；时间/地点转场可使用约 `500-1050ms` 留白。不得无条件交叉淡化，以免重叠两侧对白。
- 章节字幕由每个场景字幕按实际装配偏移合并，并复用现有 SRT/VTT/ASS/Audacity Labels 产物链路。
- 真正的目标响度应通过 FFmpeg `loudnorm` 两遍分析或等价 LUFS 实现；当前 pydub dBFS 方法只允许作为降级近似。建议目标值先采用有声书常见的 `-16 LUFS`，最终以试听和平台规范确认。
- 输出继续支持 mp3/wav/m4b；内部尽量只解码和编码一次。

---

## 6. 与现有引擎的集成方式

采用"独立领域服务 + 薄 Mixin 接入 + 场景路由"，避免继续扩大现有 Mixin 的业务职责：

- 新增 `backend/app/services/audiobook/scene_engine/`：包含计划、音色解析、提示词编译、渲染、质量闸门和装配服务。
- 新增薄层 `SceneRenderMixin`，只负责把现有 `AudiobookEngine` 的策略、剧本、任务追踪、配置和保存能力交给 `SceneRenderService`，不在 Mixin 内重复实现领域逻辑。
- `generate_chapter_audio()` 与 `generate_chapter_audio_from_script()` 必须调用同一个场景渲染服务，避免完整生成与已有剧本生成出现两套实现。

项目级配置：

| `audio_engine_mode` | 行为 |
|---|---|
| `legacy_stems` | 现有逐段 TTS + 独立音效/配乐 + 混音，作为上线初期默认和总回退 |
| `seed_scene` | 所有可规划场景优先 Seed Audio；单场景质量失败仍允许自动回退 |
| `auto` | 按场景选择 `seed_scene` 或 `legacy_stems`，推荐稳定后作为默认 |

`auto` 的初始路由规则保持简单：

- 强情绪对白、动作高潮、明确环境/音乐设计的场景优先 `seed_scene`。
- 纯长旁白、要求逐句可编辑、无法在 3 条 references 内保持主要声音一致的场景优先 `legacy_stems`。
- 能通过语义切分满足 reference 上限时先拆场景，不因角色总数多就让整章回退。
- Seed Audio 网络失败或质量闸门失败时仅回退当前场景，不能让已成功场景整体作废。

任务追踪新增 `SCENE_PLANNING`、`SCENE_RENDER`、`SCENE_QUALITY_GATE`；对前端未知阶段提供中文标签和兼容映射。场景进度使用 `completed_scene_count / total_scene_count`，同时保留每个场景的尝试次数和回退原因。

计费不能沿用当前资产工作台实现：冻结阶段按 `expected_duration_s` 累计估算，结算阶段按供应商确认的 `original_duration` 或正式计费字段累计，多退少补；`points_usage_pricing.py` 需增加 `text_to_audio` 专用费率和最低计费规则。价格与供应商账单字段在阶段 0 核实。

---

## 7. 模块处置清单（保留 / 改造 / 退役）

| 模块 | 处置 | 说明 |
|---|---|---|
| `AudioDirector` | 保留 | 提供章节风格和密度策略 |
| `AudiobookScriptAgent` / `ScriptSegment` | 保留 + 小幅增强 | 继续作为剧情、台词、角色、停顿、音效和音乐事实源 |
| `chapter_cadence` | 保留 + 改映射 | scene 内编译成表演停顿，场景边界交给装配器 |
| `AudioQualityReviewer` | 保留 | 继续负责生成前的剧本质量；不替代新的音频台词完整性闸门 |
| `SoundEffectDesigner` / Vidu | 保留 | 仅 `legacy_stems` 与回退场景使用 |
| `MusicComposer` / Mureka | 保留 | 仅 `legacy_stems` 与回退场景使用 |
| 所有现有 TTS 模型 | 保留 | 参考音色来源、纯旁白和失败回退，不限于 Seed-TTS 2.0 |
| `_apply_sound_effects` / `_apply_background_music` | 保留 | 只用于 `legacy_stems`，禁止对 Seed 完整场景重复叠加 |
| `AudioMixer.mix_chapter` | 保留 | 旧链路继续使用；场景装配使用独立入口 |
| `temp_segment_store` / resume | 保留 + 扩展 | 旧链路按片段；新链路按场景签名复用 |
| `SeedTTSVoiceManager` | 保留 + 复用 | 豆包 `speaker` 的首选来源 |
| `DoubaoSeedAudio10Adapter` | 扩展 | 完整模型、reference、字幕、响应和重试契约 |
| `points_usage_pricing` | 扩展 | 增加 `text_to_audio` 预计时长冻结与实际时长结算 |
| **新增** `scene_engine/*` | 新建 | 场景规划、提示词编译、参考解析、渲染、质量闸门、装配 |

---

## 8. 一致性、成本、时延与失败恢复

- **角色一致性**：需要跨场景复现的角色必须绑定稳定声音身份。没有 reference 的文字描述只能用于临时角色，不能作为主角方案。
- **场景连续性**：相邻计划携带环境、音乐和情绪状态；章节装配不能用统一静音或统一交叉淡化抹掉场景差异。
- **生成随机性**：同一 Prompt 的多次结果可能不同。检查点复用成功音频，不因章节后续重试而重新抽样。
- **并发**：初始并发设置为 1，验证供应商限流后再提高到 2-3；重试必须带抖动，避免场景并发放大 429。
- **成本**：在真实价格和账单字段核实前不预设“必然更贵/更便宜”。PoC 同时记录输入字符、输出时长、调用次数、重试次数、积分和供应商成本。
- **时延**：静态目录中的 `avg_latency_seconds` 只用于展示，不作为容量规划依据；以阶段 0 完整样本矩阵的 P50/P95 为准。
- **失败恢复**：场景落盘后写检查点，重跑只处理签名变化或未成功场景。场景内部没有逐句续传，但回退的 `legacy_stems` 仍复用现有逐片段检查点。
- **编辑成本**：修改一句台词只使所属 `45-75s` 目标场景失效；这也是不能按 100-120 秒规划常规场景的原因。
- **临时 URL**：响应后立即下载并验证，不把 URL 有效期当作可恢复机制。

---

## 9. 分阶段实施计划

### 阶段 0：真实接口契约与 A/B 基线

- 验证两个模型 ID、references 三种载荷、3 条上限、字幕结构、Base64/URL、格式、120 秒/3000 字符错误行为、鉴权、限流、计费字段和临时 URL 下载。
- 选择四类真实章节场景：纯旁白、双人情感对白、强动作声场、旁白加三人以上群戏。
- 每类比较三条路径：现有链路、只把音效改为 Seed Audio 的过渡方案、Seed Audio 场景统一生成；每条路径独立生成 3 次，避免以一次偶然结果决策。
- 产出接口契约样本、盲评结果、台词完整率、P50/P95 时延、调用/重试/成本基线和是否继续的决策记录。

### 阶段 1：适配器与参考音色资产

- 先以测试驱动扩展 `DoubaoSeedAudio10Adapter`：模型选择、references 校验、字幕和 Base64/URL 响应、请求标识、可重试错误分类。
- 建立稳定参考音色资产接口，打通 Seed `speaker`、用户上传参考和其它 TTS 标准参考片段。
- 修复 `text_to_audio` 计费预估；真实调用仍只在显式集成测试中执行。

### 阶段 2：场景计划、提示词编译与质量闸门

- 实现 `ScenePlanner`、`VoiceReferenceResolver`、`ScenePromptCompiler`、签名和静态计划校验。
- 实现字幕/ASR 对齐、音频技术检查及“重试一次 → 拆分一次 → 回退”的有限状态机。
- 以用户示例提炼提示词规则和回归断言，但测试不得依赖 LLM 文本完全一致。

### 阶段 3：章节级 `seed_scene`

- 实现 `SceneRenderService`、场景检查点、任务阶段、WebSocket 进度、章节字幕合并和 `SceneAudioAssembler`。
- 同时接入“完整生成”和“已有剧本生成音频”两个入口，运行 legacy 全量回归。
- 首轮仅对测试项目开放，默认仍为 `legacy_stems`。

### 阶段 4：`auto` 路由与灰度

- 启用按场景路由和自动回退，记录每种路由的质量、成本、时延和失败原因。
- 验收指标稳定后将新项目默认切到 `auto`；`legacy_stems` 始终保留为显式回退。
- 是否停用 Vidu/Mureka 另行决策，不能与 Seed 场景引擎上线绑定。

---

## 10. 测试计划

### 10.1 自动化测试

- **单元**：ScenePlanner 的时长/字符/reference/禁止切点；VoiceReferenceResolver 的跨供应商 ID 隔离与资产顺序；ScenePromptCompiler 的台词逐字保留、顺序、`@音频N` 映射、字符预算和停顿去重。
- **适配器契约**：扩展 `tests/test_doubao_audio_generation_adapter.py`，覆盖 speaker/audio_data/audio_url 互斥、最多 3 条、两个模型 ID、字幕、Base64/URL、请求元数据和错误分类。
- **质量闸门**：覆盖标点差异、同音字、漏句、增句、乱序、字幕缺失、ASR 回退、空音频、截断、削波和有限重试状态机。
- **集成**：mock 场景渲染器返回固定音频/字幕，验证任务阶段、场景进度、积分冻结/结算/释放、原子落盘、检查点复用、单场景回退和章节字幕偏移。
- **装配**：验证场景边界停顿、禁止对白重叠、字幕偏移、输出格式和只编码一次的主路径；真正 LUFS 处理使用可检查的工具输出测试。
- **回归**：`legacy_stems` 的完整生成、已有剧本生成、试听、字幕、导出、断点续作和前端进度行为不变。

真实网络测试必须显式标记，不进入默认单元测试；运行前展示预计调用次数和成本，并避免使用生产项目数据。

### 10.2 人工盲评

每类场景、每条路径各 3 个独立结果，随机隐藏模型与方案。至少评价：

1. 台词是否完整、清楚、容易理解剧情。
2. 角色声音是否可区分且跨场景一致。
3. 情绪是否连续、强弱是否符合剧情。
4. 音效和动作是否同步、是否存在错误或多余声音。
5. 音乐/环境是否遮挡对白，空间关系是否自然。
6. 场景连接是否突兀，停顿是否合理。

### 10.3 首期验收门槛

| 维度 | 首期门槛 |
|---|---|
| 台词完整性 | 关键台词缺失 `0`，未声明的额外可辨识台词 `0`，规范化覆盖率 `≥99%` |
| 产物可靠性 | 所有成功响应均在临时 URL 失效前落盘、校验并写检查点 |
| 失败恢复 | 网络错误有限重试；内容失败可拆分；最终可只回退当前场景 |
| 断点续作 | 未变化的成功场景复用率 `100%` |
| 主观质量 | 戏剧化场景平均分不低于 `4/5`，且相对 legacy 至少提升 `0.5/5` |
| 对白清晰度 | 盲评中“音乐/音效明显遮挡对白”的场景占比为 `0` |
| 可观测性 | 每场景可追踪 Prompt、references、模型、尝试、质量、成本和回退原因 |

数值门槛是首期决策线，阶段 0 后可按真实字幕误差和盲评分布调整，但不得取消“关键台词零缺失”和“未声明额外台词为零”两条硬要求。

---

## 11. 风险与回退

| 风险 | 影响 | 缓解/回退 |
|---|---|---|
| 3000 字符/120s 限制导致场景过碎 | 连贯性下降、调用数增加 | 45-75s 目标；语义边界优先；模板压缩重复描述；保存前后状态 |
| 最多 3 条 references | 旁白加多人群戏无法全部绑定 | 旁白计入规划；拆场景；临时角色文字描述；无法治理时回退旧链路 |
| 黑盒混合结果漏词/增词 | 剧情错误且无法分轨修复 | 字幕/ASR 强制闸门；有限重试；拆分；单场景回退 |
| 音乐或音效压住对白 | 可懂度下降 | Prompt 前景约束；人工盲评；失败场景回退；后续评估源分离检测 |
| 跨场景音色漂移 | 主角身份感被破坏 | 稳定声音身份资产；reference 哈希锁定；未绑定声音不承担主角 |
| 跨供应商参考音色授权不清 | 合规与下架风险 | 保存来源与授权范围；用户确认；无授权不生成跨模型参考 |
| 临时 URL 失效 | 音频丢失、续传失效 | 响应后立即原子落盘、校验并计算哈希 |
| 当前积分估算不足 | 少冻结、结算不准 | 新增 text_to_audio 费率；预计时长冻结；实际时长结算 |
| 当前 dBFS 被误当 LUFS | 平台响度不一致 | FFmpeg loudnorm/等价实现；pydub 仅降级 |
| 成本/时延波动 | 用户等待和预算不可控 | P50/P95 与实际账单观测；auto 路由；并发/重试上限 |
| 新阶段破坏前端进度 | 页面卡在未知状态 | 阶段标签与兼容映射测试；旧模式回归 |

整体回退开关：`audio_engine_mode=legacy_stems`。自动路由还必须支持场景级回退，不能只有整章级开关。

---

## 12. 待决策项（阶段 0/1 收敛）

1. **模型路由**：普通中文默认 `seed-audio-1.0`；哪些场景触发 multilingual，时间轴提示的官方格式与账号权限是什么。
2. **参考音色资产载体**：新增通用表，还是扩展现有专用声音资产体系。无论选择哪种，都必须以稳定 `asset_id` 引用并记录授权，不能只依赖 `Project.audio_config`。
3. **标准参考文案**：用于其它 TTS 生成角色参考片段的中性文本、时长和语言覆盖范围。
4. **场景模式入口**：首轮只开放测试项目，还是在有声书页面提供显式实验开关；生产默认仍为 `legacy_stems`。
5. **真实计费口径**：供应商按哪个时长字段计费、失败调用是否计费、最低计费单位和积分换算比例。
6. **授权策略**：用户上传录音和跨供应商生成音色作为 Seed Audio 参考时，需要哪些确认、审计和删除能力。
7. **旧音效/配乐链路去留**：在至少一个灰度周期的数据完成前不做下线决策。

---

## 附录 A：关键文件索引

- 引擎流水线：`backend/app/services/audiobook/engine_pkg/_generation_mixin.py`
- 引擎初始化：`backend/app/services/audiobook/engine_pkg/_base.py`
- 音效叠加：`backend/app/services/audiobook/engine_pkg/_sfx_mixin.py`
- 配乐叠加：`backend/app/services/audiobook/engine_pkg/_music_mixin.py`
- 混音器：`backend/app/services/audiobook/audio_mixer.py`
- 片段结构：`backend/app/services/audiobook/script_adapter_pkg/_dataclasses.py`
- 音色管理：`backend/app/services/audiobook/voice_manager_seed_tts.py`、`voice_manager_factory.py`
- Seed-TTS 合成：`backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`
- 豆包场景适配器：`adapters/volcengine/audio_generation.py`
- 现有 scene 调用范式：`backend/app/api/v1/asset_studio_api/routes_audio.py`
- 适配器测试：`tests/test_doubao_audio_generation_adapter.py`
- 项目音色配置持久化：`backend/app/api/v1/projects.py`
- 项目音频运行时配置：`backend/app/services/audiobook/project_audio_runtime.py`
- 计费估算：`backend/app/services/points_usage_pricing.py`
- 字幕产物：`backend/app/services/audiobook/background_jobs_shared.py`

---

## 附录 B：架构决策摘要

| 决策 | 选择 | 原因 |
|---|---|---|
| 主渲染粒度 | 场景级，不是整章 | 满足硬限制，控制重生成成本，保留情绪连续性 |
| 默认常规场景时长 | 45-75s | 100-120s 黑盒片段局部修改代价过高 |
| 剧本事实源 | `ScriptSegment[]` | 已具备台词、角色、表演、停顿、音效和音乐结构 |
| 提示词生成 | 确定性模板优先 | 防止 LLM 在生成前改写、漏掉或新增台词 |
| 角色音色 | 稳定声音身份资产 | 跨供应商 voice_id 不可直接互通，Base64 不适合长期配置 |
| 质量策略 | 字幕/ASR 自动闸门 | 完整混合音频无法通过分轨后期修复漏词 |
| 回退粒度 | 单场景 | 避免一个失败场景导致整章重做 |
| 运行模式 | legacy_stems / seed_scene / auto | 支持灰度、对照、自动路由和总回退 |
| 旧链路 | 保留 | 纯旁白、多人超限、精确编辑和失败恢复仍需要 |
| 音效模型仅替换 | 只用于 A/B 基线 | 无法解决表演连续性和统一声场问题 |

## 附录 C：Prompt 编译不变量

1. 所有可辨识台词必须来自已评审的 `ScriptSegment.text`。
2. 编译前后台词数量、内容和顺序必须一致；只允许规范化引号和转义。
3. `@音频N` 与 references 数组使用同一确定性顺序，并进入缓存签名。
4. Prompt 总长度不得超过规划上限；超限必须拆场景，不能删除台词。
5. 场景内部停顿只描述一次；不能同时要求模型停顿并让后期再次插入同一停顿。
6. Seed 完整场景不得再次叠加 legacy 音效或配乐。
7. 未通过台词完整性闸门的音频不得进入章节装配。
8. 临时供应商 URL 不得写入长期项目状态。
