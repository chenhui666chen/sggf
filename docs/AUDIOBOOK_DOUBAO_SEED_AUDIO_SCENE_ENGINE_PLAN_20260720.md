# 有声小说：豆包 Seed-Audio 场景级音频生成引擎落地方案

> 版本：3.15
> 日期：2026-07-25
> 状态：实施中（生产一致性与成本恢复审计的 8 项修复已完成；显式 `seed_scene` 双入口、Seed-TTS 2.0 系统/复刻 `speaker` 直传、MiniMax Speech 2.8 HD/Turbo 百炼真实音色复刻、用户音色隔离、标准参考试听费用确认、公共音色池基础审核/评分/撤回、vocalization 豁免、回退复用、provider attempt ledger、ASR 逐句时间轴数据通路、运行时模型路由、版本化质量策略、场景级有界响度校准、两遍 LUFS、场景进度、公开后付费计价、用户公开价倍率锁定、混合模型成本聚合和 Seed + 回退 TTS 合并结算均已接入；历史测试音色已完成数据库、本地与供应商三层清理并验证零残留；全应用 OpenAPI、公共池评分正确性和集中状态机已于 2026-07-24 修复；`fun-asr-flash` 已设为首发默认时间戳 ASR，并接通安全用量审计和 ASR 失败不重复 Seed 回归；阿里云 `paraformer-v2` 与豆包 `volc.bigasr.auc` 的公网 URL 成功路径已完成真实契约验证；四条 ASR 公开后付费价格、单场景调用/金额预算、统一超时和跨重试成本聚合已落地；用户已确认独立 Seed A/B 单元的 30 个固定复测槽位均完成综合评分和全部九项评审，定性结论支持进入受控生产灰度，但单人页面仍属于半盲评，数值导出、严格盲评、声纹相似度和真实资产响度效果标定尚未完成；限流/超时/URL 失效异常分布、角色一致性量化基线、公共池治理、真实用户硬删除和整体灰度仍未完成；固定音色生命周期账本载体已落地，实际固定费用结算口径待运营决策）
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

豆包 `seed-audio-1.0`（音频生成 HTTP 接口 `/api/v3/tts/create`）能在**同一次推理**中联合生成“对白 + 音效 + 音乐 + 节奏情绪”，正是用户实测效果显著更好的根因。项目已注册该适配器 `DoubaoSeedAudio10Adapter`（`adapters/volcengine/audio_generation.py`），并接入资产工作台、独立 A/B 评审单元和有声书两个章节入口的显式实验模式。

### 1.2 结论

采用 **方案 B 的工程化版本：以 `seed-audio-1.0` 为主要成品渲染器的"场景级统一音频引擎"**。渲染粒度是场景，不是整章；现有逐段 TTS + 分轨混音链路作为自动回退、局部修复和纯旁白路径长期保留，不能在新链路未稳定前下线。

其它 TTS 模型承担两类职责：

1. 用户已选定非豆包音色时，独立评审单元使用统一中性试听文本生成或复用 OSS 试听，再将经过校验的音频作为 `audio_data` 引用；正式生产需把该试听固化为授权明确、可稳定寻址的角色声音资产。
2. 场景统一生成未通过台词完整性或声音质量闸门时，作为可靠的逐段 TTS 回退。

同账号下的豆包 Seed-TTS 2.0 系统音色或豆包声音复刻音色优先直接作为 `references[].speaker` 使用。任何其它供应商的 `voice_id` 都不能直接传给豆包。

**不推荐方案 A（仅把音效模型替换为 `seed-audio-1.0`、其余不变）作为最终架构**：它可以作为 A/B 基线验证 Seed Audio 的孤立音效能力，但不会改善逐句 TTS 的情绪连续性、对白与动作同步、电话失真、喘息/哭腔等语言与音效交界问题，也无法获得用户样例中最有价值的统一声场效果。

### 1.3 当前实施快照

| 能力 | 当前状态 | 进入章节主流程前的缺口 |
|---|---|---|
| Seed Audio 适配器 | 基础契约、运行时模型路由与 `multilingual` 真实接口契约已完成；项目路由仅开放 `seed-audio-1.0`（multilingual 暂停用） | 限流将随供应商对接调整；正式计费口径仍需真实验证 |
| 原生豆包音色 | 已完成真实调用 | 固定使用 `references[].speaker`，不得退回试听音频 reference |
| 用户自有跨供应商音色 | 私有资产、owner 隔离、授权闸门、标准试听缓存和公共池已接通 | 仍需真实用户灰度、相似度分布和滥用治理 |
| Prompt 编译 | 领域核心、剧本模式指导和 `vocalization` 质量豁免已完成 | 仍需正式时间/地点与故事节拍字段 |
| 场景规划 | 第一版语义规划与增量 Prompt 门控已完成 | 仍需正式时间/地点字段、故事节拍和禁止切点关系 |
| 单场景渲染与质量闸门 | 核心、ASR 逐句时间轴数据通路、版本化策略、三条时间戳成功路径、公开价格目录和单场景预算已完成 | ASR 临时 URL 有效期、限流/超时/任务失败和供应商异常分布仍需灰度验证 |
| 独立 A/B 评审单元 | 30 个槽位和单人页面评审已完成 | 当前结果为半盲评且只保存在浏览器；仍需数值导出、严格盲评和声纹离线指标 |
| 章节编排与基础装配 | 已接入实验链路 | 回退产物按签名、大小和 SHA-256 复用；最终评审只保留整章字节，不再同时加载所有场景字节 |
| 双入口接入 | 显式 `seed_scene`、运行时模型配置和时间轴字幕桥接已完成 | 仍需 ASR 异常/成本灰度、授权灰度和 `auto` 路由 |
| 场景进度 | 后端 WebSocket、前端动态阶段和同循环任务回收已完成 | 仍需灰度验证断线、后台标签页和多任务切换行为 |
| 按秒计费 | 预检、冻结、实际用量、结算/释放及追加式 provider attempt ledger 已接通；用户价固定为公开后付费 ¥1/分钟 | 实际采购套餐只影响供应商成本与毛利；线性折扣使用现有配置，含额度/超额价的套餐需采购档案；JSONL ledger 是否升级为数据库不可变账本由运营审计要求决定 |
| 公共音色池 | owner 隔离、主动发布、基础审核/评分/撤回、标准衍生试听、一次性测试数据清理、OpenAPI、评分状态/自评和集中状态机已完成 | 许可与管理员治理、真实用户硬删除、分页/聚合和灰度仍未完成 |

当前默认生产行为仍是 `legacy_stems`；前端“叙事与音频”中的“场景生成”必须由用户明确选择并保存到项目 `audio_engine_mode`。显式入口可用于当前本地测试，但 ASR 异常/成本灰度、授权和整体灰度完成前不能改为默认或描述为全面上线。

2026-07-22 的生产一致性审计确认了 8 项实现偏差；这些偏差已在阶段 3I 完成修复并通过自动化回归。§5.10 保留修复前问题、修复目标和验收标准作为审计记录。阶段 3 仍不等于全面上线，剩余效果阻断项是 ASR 异常/成本灰度、角色音色一致性量化基线、真实资产响度效果标定、严格盲评、授权资产灰度和整体回退演练；`multilingual` 已完成接口契约但按运营决策暂停开放，不是当前中文首发阻断项。公共音色池正式开放还必须完成 §14.9-§14.11 的 Q0 合同正确性、治理、真实用户硬删除与规模化查询。

---

## 2. 目标与非目标

### 2.1 目标

1. 引入"场景级统一渲染"能力：将章节切为目标 `45-75s` 的声场单元，在同一次推理中生成对白、旁白、环境声、动作音效和配乐。
2. 保留现有 `ScriptSegment[]` 作为唯一剧本事实源；生成提示词时逐字复制已审定台词，不允许模型在提示词编译阶段改写台词。
3. 建立模型无关的角色声音身份层，把豆包 `speaker`、用户参考录音和其它 TTS 已有试听片段统一为稳定资产。
4. 利用 Seed Audio 返回字幕和必要时的 ASR，对生成音频执行台词覆盖、增词、漏词、顺序和音频技术质量检查。
5. 复用任务追踪、进度、检查点和产物保存骨架，但修正当前场景音频计费与响度处理缺口。
6. 通过 `legacy_stems / seed_scene / auto` 三种模式实现灰度、自动回退和可观测对比。

### 2.2 非目标

- 不在第一阶段删除任何现有 TTS、音效、配乐或混音实现。
- 不承诺整章只调用一次 Seed Audio；120 秒、3000 字符和最多 3 条 references 决定必须分场景。
- PoC 阶段不强制数据库迁移；进入生产前必须把现有试听片段落为稳定的角色参考音色资产，不能把 Base64 长期写入 `Project.audio_config`。
- 不在第一阶段实现对白、音效、音乐分轨导出；Seed Audio 返回的是完整混合音频。
- 不把现有 `pydub` 的 dBFS 增益近似当作真正 EBU R128。生产响度标准化需单独验证或引入 FFmpeg `loudnorm`。
- 不改变现有剧本编辑和章节选择语义；新元数据以兼容字段接入。

---

## 3. 关键事实：`seed-audio-1.0` 能力与硬约束

来源：豆包语音《音频生成 HTTP》与用户提供的《豆包语音_音色列表》文档，接口 `POST https://openspeech.bytedance.com/api/v3/tts/create`。

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
- 每条 reference 必须且只能填写 `speaker`、`audio_data`、`audio_url` 之一；不得同时提交试听音频和 `speaker`，也不得提交三者全空的占位对象。
- 豆包语音合成 2.0 系统音色与账号级声音复刻音色一律使用 `speaker`；试听片段只用于用户选音确认，不进入该类 Seed Audio 请求。
- 旁白若要求全书声音一致，必须计入绑定声音数量。
- `seed-audio-1.0-multilingual`、时间轴格式、字幕响应结构和 WAV 输出已于 2026-07-22 完成真实接口契约测试：多语种字幕为毫秒级 `subtitle.sentences[].words[]`；请求 `format=wav` 时响应体不回显 `format` 字段但 base64 首部为 `RIFF`（真为 WAV），据此在 `DoubaoSeedAudio10Adapter._parse_response` 增加字节头嗅探（`RIFF`→wav、`OggS`→ogg、`fLaC`→flac、`ID3`/帧同步→mp3），格式判定改为「字节头优先 → 显式 `format` 字段 → 默认 mp3」并写入 `metadata["format"]`，避免误判 MIME 与落盘后缀。
- 用户示例证明模型具备统一声场能力，但不等于已经证明长篇跨场景音色一致性、逐字准确率和多次生成稳定性；这些必须通过阶段 0 的重复实验确认。

### 3.2 已观察到的音色参考边界

- `references[].speaker` 已使用 Seed-TTS 2.0 系统音色完成真实调用，供应商接受该请求；这是豆包原生音色的首选路径。
- 声音复刻 ID 是账号级不透明字符串，不能用 `zh_*`、`ICL_*`、`saturn_*` 等公开音色前缀判断。运行时以规范化后的豆包模型归属或显式 `seed_audio_reference.speaker` 为依据，保留完整 ID 并交由供应商校验。
- `seed_tts_2_0_voices.json` 只承担系统音色展示、推荐和自动分配，不是 `speaker` 允许列表。复刻 ID 不在静态目录中属于正常情况，`SeedTTSVoiceManager` 不得因此替换成默认音色。
- 跨供应商 `audio_data` reference 已完成真实调用，但音色相似度明显弱于文字声音描述的影响。当前将其定义为“软音色约束”，不是严格声音克隆。
- URL 与 Base64 只是 reference 载体，互换不会提高模型内部的音色相似度；不能把重复下载或编码优化误当成音色能力优化。
- 有 reference 时，Prompt 不再重复年龄感、口音、音高、沙哑度、磁性等静态音色词，避免文字重新定义角色声音；逐句只控制当前情绪和表演。
- 不因跨供应商音色相似度不足暂停场景引擎实施。主角严格音色锁定若成为上线阻断项，再以 `legacy_stems` 或后续混合渲染作为角色级回退，而不是立即推翻统一场景路线。

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

- `create_voice_manager()`（`voice_manager_factory.py`）按 `tts_model` 生成对应管理器；Seed 系为 `SeedTTSVoiceManager`（`voice_manager_seed_tts.py`），从 `seed_tts_2_0_voices.json` 加载系统音色，`speaker` 即“豆包 2.0 系统/复刻音色 ID”——**可直接作为 `seed-audio-1.0` 的 `speaker`**。显式复刻 ID 即使不在静态目录中也必须原样保留，不得静默回退为默认 `vivi`。
- 项目级音色映射：`apply_project_voice_mapping()` 承接 `Project.audio_config` 中按 TTS 模型保存的角色配置。
- 当前 API 最终只持久化角色的 `character_id/name/voice_id/tts_model`。虽然运行时识别 `voice_clone_data_url`、`voice_design_prompt` 等字段，但 `projects.py` 的持久化白名单会将它们排除，因此现有配置不能直接承担 Seed Audio 参考音色资产层。

### 4.4 `seed-audio-1.0` 现有调用范式（资产工作台）

`backend/app/api/v1/asset_studio_api/routes_audio.py` 的 `scene-audio` 分支：

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

新引擎复用该“registry → adapter.generate → 下载 URL 落盘”范式，但不复用资产工作台 route 作为章节入口。当前事实是：

1. `routes_audio.py` 仍只把逗号/换行分隔的 `speaker_id` 转为 `references[].speaker`，不提供 `audio_data`/`audio_url` 表单能力；这只是资产工作台 UI 边界，不是适配器边界。
2. `DoubaoSeedAudio10Adapter` 已支持两个模型 ID、三种 reference、默认字幕配置、URL/Base64 音频、字幕、时长、请求标识和结构化错误分类。
3. `SceneRenderService` 已支持供应商 URL/Base64 输出立即落盘、字幕优先与 ASR 回退接口、技术分析、有限重试和检查点复用；拆分重试仍由章节编排层实现。
4. 资产工作台 `text_to_audio` 冻结与结算不能直接代表章节计费；阶段 3 使用预计时长冻结、按供应商 `original_duration` 汇总并结算，场景检查点保留请求 ID 与计费秒数。用户基础挂牌价固定为火山引擎公开后付费 ¥1/分钟；采购套餐折扣只进入供应商实际成本和毛利，不改变用户计价；是否增加独立不可变账本表由运营审计要求决定。
5. `AudioMixer._normalize_loudness()` 使用 dBFS 近似目标响度，不是严格的 EBU R128 综合响度测量；章节装配不能把它描述为 LUFS 实现。

---

## 5. 目标架构：场景级音频渲染引擎

### 5.1 总体数据流

```
章节文本
  → [策略] AudioDirector.formulate_strategy()（复用）
  → [剧本改编] AudiobookScriptAgent.adapt_chapter() → ScriptSegment[]（复用并保持为唯一台词事实源；按 audio_engine_mode 生成不同渲染指导）
  → [剧本质量闸门] 原文保真、对白归属、可听性公共评审 + Seed/分轨模式就绪度评审
  → [场景规划] ScenePlanner：ScriptSegment[] → SceneRenderPlan[]
  → [音色解析] VoiceReferenceResolver：角色声音身份 → references（≤3）
  → [提示词编译] ScenePromptCompiler：确定性复制台词并编译声场、表演、停顿、音效和音乐描述
  → [计划校验] 字符、时长、reference、角色、台词哈希和资源可用性检查
  → [场景渲染] SceneRenderService：调用 Seed Audio → 立即落盘音频 + 字幕 + 元数据
  → [质量闸门] SceneAudioQualityGate：字幕/ASR 对齐 + 技术质量检查
  → [重试/拆分/回退] 强化提示词 → 拆分场景 → legacy_stems
  → [章节装配] SceneAudioAssembler：按场景边界拼接、留白、连续环境过渡和真实响度处理
  → [最终评审 / 保存 / 统计]（复用）
```

### 5.2 核心数据模型

不修改 `ScriptSegment` 的职责。阶段 3I 后的场景计划字段如下，文档必须与代码中的不可变 Tuple 语义保持一致：

```python
@dataclass(frozen=True)
class SceneRenderPlan:
    scene_id: str
    source_segment_indices: tuple[int, ...]
    expected_text: str
    expected_duration_s: float
    speaker_names: tuple[str, ...]
    references: tuple[dict, ...]
    prompt: str
    prompt_hash: str
    reference_hashes: tuple[str, ...]
    boundary_before: str
    boundary_after: str
    render_mode: str = "seed_scene"
    fallback_reason: str | None = None
    expected_vocalizations: tuple[str, ...] = ()
    quality_policy_hash: str = DEFAULT_SCENE_AUDIO_QUALITY_POLICY_HASH
```

运行态结果单独保存，避免把供应商响应写回不可变计划：

```python
@dataclass(frozen=True)
class SceneRenderResult:
    scene_id: str
    status: str
    action: str
    attempts: int
    audio_path: Path | None
    subtitle_payload: Any
    quality_report: SceneAudioQualityReport | None
    fallback_reason: str | None = None
    reused_checkpoint: bool = False
    metadata: dict[str, Any] | None = None
```

独立测试单元和通用 `SceneRenderService` 的缓存/检查点签名均包含 `schema_version + model + prompt_hash + reference_hashes + audio_config`；通用 renderer 额外包含 `renderer_version + scene_id + quality_policy_hash`。`audio_config` 会先与供应商默认值合并，再同时用于请求和签名比较。模型、采样配置、质量策略、schema 或 renderer 版本任一变化，以及缺少新签名字段的旧检查点，都会强制重新生成，避免错误复用旧产物。

独立测试单元的 **manifest 存储格式版本** 与上述 **生成签名版本** 分开管理。2026-07-24 起 manifest 升级为 schema 3，只保存相对于测试 `output_root` 的 `renders/...` 音频路径；该格式升级不改变现有生成签名和缓存键，不能仅因 Windows/Docker 运行环境变化而重新调用 Seed。读取 schema 1/2 旧清单时，先接受当前根目录内仍有效的绝对路径；若绝对路径来自另一环境，则只提取受控 `renders/` 后缀映射到当前根目录，并再次校验路径未越界、文件存在且为普通文件。带 `..`、绝对 `audio_relative_path` 或非 `renders/` 前缀的值一律拒绝，不能利用兼容逻辑读取测试根目录之外的文件。

`expected_vocalizations` 和 `quality_policy_hash` 已在阶段 3I 落地，并保持以下边界：

- `expected_vocalizations` 只收集 `vocalization` 事件的可辨识文本（如“啊”“嗯”、喘息、哭腔），不把完整台词或舞台说明放入豁免集合。
- `quality_policy_hash` 由覆盖率、增词豁免、削波、静音和 ASR 策略的规范化配置计算；策略改变必须使旧检查点失效。
- 回退音频路径、父场景失败原因和 provider attempt 列表属于运行态结果/检查点，不写入不可变计划；provider attempt 进入每个章节 run 的追加式 JSONL ledger，以 request ID 幂等。

运行态结果通过 renderer `attempts`、追加式 provider ledger、`fallback_status/fallback_artifact` 和 `provider_request_ids` 分开记录 Seed 调用与回退产物；不能只用一个字段隐含表达所有供应商调用。

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

当前 `ScenePlanner` 已实现按完整 `ScriptSegment` 贪心聚合、时长上限、最终 Prompt 字符预算和 reference 数量触发切分，并增加第一版确定性语义边界：累计达到目标最小时长后，在相邻非空 `instruct_scene` 变化、音乐风格变化，或“新说话人加入且情绪阶段同时变化”时切分。未达到目标最小时长时不因这些软边界切分，reference、字符和硬时长限制仍优先保证请求合法。

这只是基于现有 `ScriptSegment` 字段的第一版规则，不等同于完整语义规划。当前数据结构没有独立的时间、地点、故事节拍、段落索引和因果/问答关系字段，因此尚不能可靠实现时间与地点分别评分、问答紧邻保护、动作原因与结果保护、“最近最佳边界”回溯或跨段情绪连续性评分；这些能力必须在章节改编输出提供结构化依据后继续补齐。正式实现应在接近目标时长后对有限回溯窗口内的候选边界统一评分，优先时间/地点转场与故事节拍，在问答、因果动作和持续情绪弧之间施加禁止切分惩罚，然后选择最近的最高分合法边界；不能退回对整章进行无界 LLM 重切分。

性能实现：Planner 在候选循环中维护保守的增量 Prompt 成本估算，并单独统计稳定 references；明显低于字符预算时不再重编译整段 Prompt，达到 50% 安全门槛后才执行真实候选编译。`_build_plan()` 仍保留最终完整编译作为事实校验，增量估算不参与最终 Prompt、哈希或台词保真结论。120 个短片段的回归用例将完整编译次数从 120 次降到不超过 2 次。

### 5.4 角色声音身份与参考资产（VoiceReferenceResolver）

目标：跨场景一致性来自"同一角色在每个场景绑定同一音色标识"。

- 声音来源优先级（2026-07-23 已按授权边界收敛）：
  1. **豆包 Seed-TTS 2.0 系统音色或豆包声音复刻 ID**：直接使用 `references[].speaker`。
  2. **用户上传且已确认授权的干净参考录音**：使用稳定 `audio_url` 或请求时编码为 `audio_data`。
  3. **用户自己在其它模型设计或复刻的音色**：必须先登记为当前用户私有资产；设计音色缓存未命中时先返回公开价并弹窗确认，确认后才生成标准衍生试听并上传 OSS。
  4. **审核通过的公共音色池资产**：只使用公共衍生参考 URI，不暴露原始复刻录音或私有源资产关系。
  5. **文字声音描述**：只补充表演方向，不再单独承担需要跨场景一致性的声音身份。

| 来源 | Seed Audio 请求字段 | 稳定身份签名 | 是否使用试听音频 |
|---|---|---|---|
| Seed-TTS 2.0 系统/复刻音色 | `speaker` | `model + speaker_id` | 否，试听只供用户确认 |
| 用户授权录音 | `audio_data`（运行时） | 音频 SHA-256 + 授权版本 | 是 |
| 用户私有设计/复刻音色 | `audio_data`（运行时） | owner + 来源模型 + 音色 + 音频 SHA-256 + 授权版本 | 是，先校验 owner/授权/撤销状态 |
| 公共音色池 | `audio_data`（运行时） | publication_id + 公共衍生音频 SHA-256 | 是，只允许 `published` |
| 临时文字角色 | 无 reference | 角色描述哈希 | 否，不承诺跨场景一致 |

- **Seed-TTS 2.0 系统音色与豆包复刻音色**：试听仅供用户确认选择，场景请求直接使用 `references[].speaker=voice_id`，不得把试听音频重新物化为 `audio_data`。
- **其它供应商官方系统音色**：不得把供应商试听音频自动转成 Seed reference，也不得由前端 `category=custom` 自报所有权。当前 resolver 对这类映射直接拒绝，并提示改选豆包音色、当前用户私有设计/复刻音色或公共池音色。
- **用户私有设计/复刻音色**：使用以下统一、情绪中性、约 8-12 秒的标准文本生成衍生参考片段。探测请求只返回 `requires_cost_confirmation + cost_quote`，不调用供应商；确认后生成并按确定性缓存键上传，命中后不重复生成。

```text
清晨的风从窗外吹进来，我停下脚步，轻声说：别担心，我们会找到答案。
```

进入 Seed Audio 前仍检查单人、可解码、无明显音乐/环境声/混响、最长 30 秒和不超过 10 MB。试听文本是 reference 资产版本的一部分，修改文本会产生新缓存键，不得覆盖旧对象。
- `PreviewReferenceMaterializer` 负责把当前试听结果或共享 OSS 试听缓存物化为稳定运行时资产：优先读取 `preview_audio_url / preview_audio_data / preview.blob`，缺失时按正式试听页相同的模型、音色、默认文本和参数计算缓存键，再依次查找 MP3/WAV 缓存。缓存仍未命中时明确失败，由上层决定是否提示用户先试听；该服务本身不得同步调用 TTS。
- URL 只作为下载来源；下载采用超时、重定向和流式大小限制，落盘前检查 Base64、空内容、10 MB、可解码性、30 秒、明显削波和异常静音。校验通过后计算 SHA-256 并原子落盘，传给 Seed Audio 的是已验证 `audio_data`，不是可能过期的供应商 URL。
- 同一角色在全书维度锁定同一个声音身份；场景只选择当前需要的最多 3 个 reference。
- Prompt 中通过 `@音频1`、`@音频2`、`@音频3` 绑定按顺序排列的 references；具体 reference 字段可以是 `speaker`、`audio_data` 或 `audio_url`。数组顺序必须由编译器固定并进入签名。
- 参考资产至少保存：`asset_id/source_type/source_model/source_voice_id/storage_uri/sha256/duration/content_type/authorization_scope`。
- 不把 Base64 长期写入项目 JSON。场景渲染前优先读取现有试听缓存；云端缓存返回 `audio_url` 时下载并落盘，未配置云端时将返回的试听 `blob` 解码并落盘。已新增专用角色参考音色资产表 `voice_reference_assets`（仓储 `voice_reference_asset_repository.py`）承载角色声音身份与授权字段；共享 `AudioLibraryAsset` 仍仅支持 `sfx/music`，不承载角色声音身份。

### 5.5 提示词编译（ScenePromptCompiler）

提示词编译采用**确定性模板优先**，不让 LLM 自由重写整段场景：

1. **场景声学块**：地点、时间、空间大小、远近关系、环境底噪和总体情绪。
2. **角色声音块**：无 reference 时描述角色年龄、性别、口音和音色；有 reference 时只声明明确的 `@音频N` 对应关系，声音身份以 reference 为准，不再用文字重复定义音色。
3. **全局约束块**：对白始终清晰位于前景；音乐/环境声不得遮挡；严格朗读引号内原文；禁止增删、改写或产生额外可辨识台词。
4. **顺序事件块**：按 `ScriptSegment` 顺序逐项输出。台词直接从 `segment.text` 复制；`emotion/performance_notes/instruct_*` 编译为表演说明；`sound_effects/music_cue` 编译为台词前、中、后的声场事件。
5. **收尾连续性块**：描述场景结尾保留或停止的环境、音乐和人物状态，供章节装配及下一场景延续。

当前 `ScenePromptCompiler` 完全使用确定性模板，不调用 LLM。它会把连续片段中的 `instruct_scene` 编译为去重后的环境与空间状态事件，将结构化音效的 `before/during/after/continuous/until_text` 编译为明确相对时序，并去重连续片段中未变化的配乐提示；“音乐停止”不会再被错误编译成“音乐以音乐停止进入”。未来若引入可选 LLM 后处理，它只允许补充非台词声场描述和压缩重复说明；调用后必须重新校验所有原台词逐字存在且顺序不变。若校验失败，直接使用纯模板结果，不对 LLM 结果做猜测性修补。

示例骨架：

```text
场景：深夜宫殿内殿，空间空旷，人物距离较近，整体压抑、紧张。

角色与声音：
- 旁白的声音参考 @音频1，以参考中的声音身份为准；仅按当前剧情调整情绪、语气、音量、语速和停顿。
- 太后的声音参考 @音频2，以参考中的声音身份为准；仅按当前剧情调整情绪、语气、音量、语速和停顿。
- 御医的声音参考 @音频3，以参考中的声音身份为准；仅按当前剧情调整情绪、语气、音量、语速和停顿。

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

#### 5.5.1 用户样例是 Prompt 风格基线

用户提供的四组高质量样例不是普通 TTS instruction，而是完整的音频导演脚本。`ScenePromptCompiler` 必须参考其表达方式，但**不得把完整样例作为 few-shot 原文拼入每个 `text_prompt`**，否则会占用 3000 字符预算并污染当前场景。正确用途是：

1. 提炼稳定的 Prompt 语法和词汇约束。
2. 作为离线编译器回归样例，验证结构是否保留。
3. 作为真实 Seed Audio A/B 测试的场景类型基线。
4. 用于人工盲评“情绪、空间、音效时序、音乐动态、非语言表演”是否达到同等颗粒度。

四组样例分别覆盖以下核心能力：

| 样例类型 | 必须学习的能力 |
|---|---|
| 多人压迫、试药与挣扎 | 五类角色声音描述、连续恐惧升级、尖叫/喘息/呻吟、动作拟音、群体人声、音乐动态和混乱场面组织 |
| 台湾口音电话对话 | 口音、电话远端失真、两人质问与无奈的情绪递进、持续环境声、结尾汽车与高跟鞋连续事件 |
| 三参考音色警察争吵 | `@音频1-3` 角色绑定、多人抢话、远近变化、背景惊呼、脚步由远到近、击打和物体碰撞 |
| 单人伤感回忆 | 单参考音色、轻笑/吸气/哽咽、语速和音调渐变、明确长短停顿、音乐中止、持续道路环境和结尾刹车 |

#### 5.5.2 从样例提炼的 Prompt 语法

每个 Seed Audio 场景 Prompt 按以下顺序编译：

```text
角色定义块*
全局音乐事件?
全局环境事件?
按剧情顺序排列的语音/非语言人声/音效/音乐变化事件+
场景收尾事件
```

角色定义使用用户样例中的直接句式：

```text
角色名 是 年龄与性别，口音，音高与音色，声音质感，身份或性格。
角色名 的声音参考 @音频1，以参考中的声音身份为准；仅描述当前剧情所需的情绪和表演。
```

规则：

- 每次只声明当前场景会出现的角色，不把全书角色表塞入 Prompt。
- 有 reference 时必须写清 `角色名 → @音频N`；用户样例中的“参考录音1”在实际请求中规范化为官方引用形式 `@音频1`。
- 无 reference 时，音色描述负责“这个人是谁”；有 reference 时，reference 独占声音身份定义，角色块不得再写年龄感、口音、音高、沙哑度、磁性等静态音色词。逐句表演描述只负责“这一刻怎么说”。
- 对没有 reference 的临时角色，性别、年龄、口音、音高、沙哑度、力度和性格至少选择三项可听辨特征。

全局音乐和环境使用独立句子，明确配器、情绪、空间和持续范围：

```text
音乐开头由……引入，随后……，整体氛围……；对白出现时音乐降低，不遮挡人声。
环境中持续伴随……，直到场景结束。
```

不能把音乐简化成“紧张 BGM”或把环境简化成“有脚步声”；应尽可能保留原剧本提供的材质、远近、地面、运动方向和动态变化。

#### 5.5.3 顺序事件的表达规则

每个场景先编译为供应商无关的 `SceneAudioEvent[]`，再渲染成自然语言 Prompt：

```python
@dataclass(frozen=True)
class SceneAudioEvent:
    kind: str  # speech | vocalization | sfx | ambient | music | transition
    anchor: str  # before | during | after | throughout | until_text
    speaker: str | None
    exact_text: str | None
    performance: str | None
    acoustic: str | None
    related_text: str | None
```

事件表达遵循以下规则：

1. **可辨识台词**：`角色 + 可执行表演 + 说话动作 + “原文台词”`。引号内只能出现已评审文本。
2. **非语言人声**：笑声、哭泣、吸气、喘息、尖叫、呻吟、吞咽和“嗯/啊”等单独建 `vocalization` 事件，说明强度、情绪和与台词的先后关系，不能笼统归入 SFX。
3. **音效**：说明声源材质、动作、次数、远近、空间和锚点，例如“句首两声布鞋踏上木台阶”“说到‘三八’结束前持续快速脚步”。
4. **环境**：说明是否持续、距离和空间，例如持续鸟鸣、公路车辆噪声、室内木地板反射。
5. **音乐**：说明开始、停止、降低、渐强、配器变化和镲片/鼓点等点缀，不允许默认从头铺到尾。
6. **空间处理**：电话失真、远端人声、背景惊呼、由远到近、左右移动等写入 `acoustic`，不能只靠音量字段表达。
7. **重叠关系**：使用“其中穿插”“背景中传来”“两人错落喊道”等明确谁在前景、谁在背景；没有明确计划时禁止模型自行添加群体台词。
8. **停顿**：区分“稍有停顿”“短暂停顿”“明显停顿”“长时间停顿”，并与 `chapter_cadence` 映射；不要求模型和后期重复实现同一停顿。
9. **情绪变化**：描述变化过程，例如“语气和声量逐渐加重”“随后语调放低”“短暂平静后哽咽”，不能只给整句一个静态 emotion 标签。
10. **顺序词**：优先使用“先是、随后、紧接着、期间、句首、句中、句尾、直到结束”等相对时序；需要精确时间轴时才由 multilingual 编译器生成经过契约验证的时间格式。

#### 5.5.4 台词与表演保真约束

- Prompt 中所有完整台词从 `ScriptSegment.text` 逐字复制，编译器不能润色。
- “啊、嗯、哎”等若属于原文或明确表演计划，进入 `expected_vocalizations`，质量闸门不得当成未声明增词。
- 舞台说明不加引号，避免模型把“轻笑”“脚步声”“音乐停止”等文字读出来。
- `performance_notes` 不能作为最终唯一输入；必须拆解为语速、音高、力度、情绪变化、非语言人声、停顿和空间关系。
- 每个动作音效必须绑定到 `before/during/after/throughout/until_text` 之一；无法确定锚点时宁可不生成，也不允许随机插入。
- 对白永远是前景主信息。除剧情明确要求压迫或混乱外，音乐、环境和打斗声音必须自动降低，保证台词可懂。
- 禁止生成未声明的完整台词、旁白、歌词或可辨识群体对话。

实现状态：`ScenePromptCompiler` 将笑声、哭声、喘息、吞咽等非语言人声编译为 `vocalization` 事件；Planner 从事件中提取可辨识词写入 `SceneRenderPlan.expected_vocalizations`，renderer 显式透传给质量闸门。端到端测试已验证声明的喘息不会被判为 `extra_lines`，未声明的完整台词仍会失败。

#### 5.5.5 references 超限时如何保留样例风格

第一组样例包含超过三个角色，但没有为所有角色提供参考录音。这说明 Seed Audio 可以根据文字描述生成多人场景，不代表这些声音能跨场景稳定复现。生产规则是：

- 旁白和主要角色优先占用最多三条 references。
- 没有跨场景复现要求的卫兵、路人和短句角色可以只用声音描述。
- 超过三名必须稳定复现的角色时，在自然语义边界拆分场景；不能为了保留单次大场面而牺牲主角音色一致性。
- 拆分后继续复用样例的音乐、环境和情绪状态描述，使听感仍像同一连续场景。

### 5.6 场景渲染（SceneRenderService）

- 适配器层同时支持 `seed-audio-1.0` 和 `seed-audio-1.0-multilingual`；项目 `audio_config.seed_audio_model` 使用严格枚举，并从运行时配置贯通章节 mixin、adapter factory、pipeline、checkpoint、provider ledger 和计费摘要。multilingual 真实接口契约已于 2026-07-22 验证（毫秒级字幕、WAV 输出与格式嗅探修复），进入正式路由仍需授权与灰度。
- 对 references 做结构化校验：最多 3 条；每条 `speaker/audio_data/audio_url` 三选一；音频格式、大小、时长可验证时必须在请求前验证。
- `audio_config` 默认 `mp3/48000Hz/enable_subtitle=true`。WAV 作为生产中间格式需先实测确认，再决定是否切换以减少重复编码损失。
- 同时解析 URL、Base64 音频、字幕、`duration`、`original_duration` 和供应商请求标识。
- 响应成功后立即原子落盘并计算 SHA-256，再把稳定路径写入检查点；临时 URL 只作为下载来源。
- 对连接超时、429、可重试 5xx 和临时 URL 下载失败使用有上限的指数退避；内容质量失败由质量闸门治理，不与网络重试混在一起。

当前 `SceneRenderService` 已实现单场景生成、最多一次同 Prompt 强化重试、落盘、质量评估、检查点读取和 `legacy_stems` 结果；它没有负责在语义边界拆分失败场景。拆分会改变场景 ID、Prompt、references 和字幕偏移，必须由章节编排服务创建新计划，不能塞进 adapter 或单场景 renderer。生产 factory 已通过现有 `create_prompt_audio_asr_provider()` 注入 ASR callable；未配置 ASR 时 `needs_asr` 只调用一次 Seed，provider 调用失败归类为不可重试的 `asr_failed:<code>`。

renderer 检查点采用 `scene-render-service-v2`，签名包含 schema、renderer、模型、合并后的音频配置、Prompt、references 和 `quality_policy_hash`。`passed` 与同签名终态 `legacy_stems` 决策都可复用；后者恢复时不会再次调用 Seed。局部回退完成后写入独立 `fallback_artifact`，包含路径、大小、SHA-256、源文本、Prompt、references 和质量策略签名，全部匹配才复用。每次成功供应商响应还会立即追加到 `provider_attempts.jsonl`，按 request ID 幂等；章节费用优先从该 ledger 聚合，旧检查点计费字段仅作兼容回退。

### 5.7 场景音频质量闸门（SceneAudioQualityGate）

完整混合音频不可分轨修复，因此质量闸门是生产必需能力，不是最终抽检：

1. 规范化剧本台词与供应商字幕，按场景逐句对齐，检查漏句、增句、改词和顺序错误。
2. 字幕缺失或结构不可用时，在渲染 pipeline 显式注入已配置的 ASR provider；供应商字幕与 ASR 结果都需保留来源标记。未配置 provider 时应返回可解释的 `needs_asr`，不能假装已完成 ASR，也不能无条件重复调用 Seed。
3. 检测空音频、截断、时长异常、削波、异常长静音、采样率/声道和文件可解码性。
4. 初始自动门槛：关键台词缺失数 `0`、未在剧本或声场计划中声明的额外可辨识台词数 `0`、规范化文本覆盖率 `≥99%`。已进入 `expected_vocalizations` 的笑声、哭声、喘息和“嗯”等非完整词语单独评估，不误判为增词；该豁免必须在 `ScenePromptCompiler → SceneRenderPlan → SceneRenderService → SceneAudioQualityGate` 链路贯通后才生效。门槛需通过 PoC 数据校准，不能只凭单个样例定值。
5. 音色相似度和音乐是否遮挡对白在第一阶段先人工评分；有可靠声纹/源分离能力后再转自动指标。
6. 失败恢复顺序：同场景强化“精确台词/前景对白”约束重试一次 → 在语义边界拆成两个场景各重试一次 → 回退 `legacy_stems`。不得无限重试。

质量报告至少包含 `transcript_coverage/missing_lines/extra_lines/order_valid/audio_decodable/clipping/silence/duration/status/fallback_reason`。

实现状态：字幕优先、可选 ASR、非语言人声豁免、技术分析和逐句时间轴数据通路已贯通。ASR 结果使用 `transcript + subtitle_payload` 明确合同；只有规范化后同时具备有效文本、开始毫秒和结束毫秒的片段才能进入章节字幕。供应商已有文本但没有时间戳时，只调用声明 `supports_timestamps=True` 的 ASR；返回时间轴还必须独立通过同一台词覆盖、增词、漏词和顺序检查后才能替换无时间戳字幕。ASR 失败或时间轴不可信时保留已通过质量闸门的供应商文本，不因字幕增强失败重复 Seed。覆盖率、削波比例、削波振幅、静音比例和最小静音长度集中在不可变 `SceneAudioQualityPolicy`，其确定性 SHA-256 同时进入计划、Seed checkpoint 和 fallback artifact；策略变化会使旧产物失效。

2026-07-22 真实契约探测确认：当前默认 `mimo-v2.5-asr` 能返回有效转写，但不返回逐句时间轴，因此标记为 `supports_timestamps=False`，只在 Seed 完全缺失可用字幕时承担质量转写，不用于字幕补时轴。同日已完成 `fun-asr-flash`（DashScope）时间戳型真实契约验证：以本地文件 base64 上传、SSE 流式返回，按标点重切后 normalize 为 `segments[]`（`text`/`start_ms`/`end_ms`），对上一步生成的多语种音频转写准确（`usage.duration` 以秒计费）；该 provider 无需公网 `audio_url`，是本地文件场景下可直接使用的时间戳型 ASR。

2026-07-24 使用同一条公共 OSS 系统预置试听（WAV 约 4.5 秒，不含用户上传/设计/复刻声纹）完成两家公网 URL 成功路径实测：

| Provider | 模型 | 转写 | 规范化时间轴 | 用量时长 | 端到端耗时 |
|---|---|---|---|---:|---:|
| 阿里云 | `paraformer-v2` | `人不是慢慢变老的，而是一瞬变老的。` | `0-3740ms`，1 段 | `3.76s` | `3.896s` |
| 豆包 | `volc.bigasr.auc` | `人不是慢慢变老的，而是一瞬变老的。` | `120-3600ms`，1 段 | `3.759s` | `3.579s` |

已核实的中国内地公开后付费价如下，统一按输入音频实际时长计费：

| Provider | 模型 | 公开价 | 折算价 |
|---|---|---:|---:|
| 阿里云百炼 | `fun-asr-flash-2026-06-15` | `¥0.00022/秒` | `¥0.792/小时` |
| 阿里云百炼 | `paraformer-v2` | `¥0.00008/秒` | `¥0.288/小时` |
| 豆包录音识别 1.0 标准版 | `volc.bigasr.auc` | `¥2.3/小时` | `¥0.000638889/秒` |
| 豆包录音识别 2.0 | `volc.seedasr.auc` | `¥0.8/小时` | `¥0.000222222/秒` |

价格事实源分别为阿里云百炼官方模型价格页和豆包语音《产品计费》2026-07-24 公开奖单；不使用免费额度、资源包或平台实际采购折扣冲减用户侧公开价事实。ASR 是 Seed 字幕缺失/无时间轴时的平台质量保障调用，当前只记录为场景级供应商成本用于毛利核算，不额外叠加到用户 Seed Audio `¥1/分钟` 账单；若未来产品决定单列 ASR 用户收费，必须独立确认并接入预检、冻结和结算，不能直接复用当前元数据。

阿里云首次探测返回任务成功但本地报 `asr_empty_transcript`，根因是异步任务摘要只提供 `results[].transcription_url`；修复为下载该短时签名 JSON，从 `transcripts[].text/sentences[]` 提取正文与毫秒时间轴，并从 `properties.original_duration_in_milliseconds` 生成安全 usage。签名结果 URL 和原始响应均不持久化。

豆包此前三次 submit 均为 HTTP 400，最后一次只获得 `X-Tt-Logid=20260724175518B1D4E125614000EFDB75`。官方《录音文件识别标准版HTTP》（文档 ID `1354868`，页面标记 2026-06-26 更新）确认根因是客户端合同错误，而非账号权限：提交必须在 header 使用客户端生成并贯穿 submit/query 的 `X-Api-Request-Id`，submit 额外传 `X-Api-Sequence: -1`；body 必须包含 `audio.url/format` 与 `request.model_name=bigmodel`，时间轴需显式 `show_utterances=true`；submit 成功仅在 `X-Api-Status-Code=20000000` 表示，body 为空；query 复用同一 Request ID、body 为 `{}`，`20000001/20000002` 分别表示处理中/排队，成功正文位于 `result.text/utterances[]`，`audio_info.duration` 单位为毫秒。适配器已按该合同修复并通过真实请求。新版控制台只需要 `X-Api-Key`；旧版 App/Access Key 作为互斥兼容鉴权，不与新 Key 混发。

ASR 预算已集中为不可变策略，默认总超时 `300s`、每场景最多 `2` 次、每场景最多 `¥0.20`；可分别通过 `PROMPT_AUDIO_ASR_TIMEOUT_SECONDS`、`PROMPT_AUDIO_ASR_MAX_ATTEMPTS_PER_SCENE`、`PROMPT_AUDIO_ASR_MAX_COST_YUAN_PER_SCENE` 调整，非法值在 pipeline/provider 创建时直接拒绝。已知价格的 provider 在调用前按 Seed `original_duration` 预估金额并执行硬预算；成功后按 ASR `usage.duration` 计算实际费用。每次尝试的 provider/model、Request ID、时长、状态、公开价来源和实际费用写入安全元数据，跨 Seed 强化重试聚合；checkpoint 恢复沿用已消费次数和金额，不重新获得预算。未知价格 provider 只执行调用次数上限并标记无金额，不猜价。按单场景最长 `120s × 2` 次计算，四个已登记模型的理论上限分别为 `¥0.0528`、`¥0.0192`、`¥0.153333`、`¥0.053333`，均低于默认 `¥0.20`。

阿里云和豆包均需公网可访问 `audio_url`，可在本次渲染内接收 Seed 返回的临时 URL；该 URL 不写入 checkpoint、账本或章节结果。成功路径验证不等于生产灰度完成：短时 URL 最小有效期、限流、真实超时、任务失败、静音和过期 URL 仍需受控验证。首发默认继续使用支持本地 Base64 且已验证的 `fun-asr-flash`。

### 5.8 章节装配与字幕（SceneAudioAssembler）

- 已新增专用 `SceneAudioAssembler`，只处理顺序装配、边界留白、字幕偏移和最终编码，不再叠加外部 SFX/BGM。
- 同一连续场景默认使用短边界或相同房间底噪；时间/地点转场可使用约 `500-1050ms` 留白。不得无条件交叉淡化，以免重叠两侧对白。
- 章节字幕由每个场景字幕按实际装配偏移合并，并复用现有 SRT/VTT/ASS/Audacity Labels 产物链路。
- 最终章节使用独立 `FFmpegLoudnessNormalizer` 执行两遍 `loudnorm`：第一遍以 JSON 读取综合响度、真峰值、响度范围、阈值和偏移，第二遍带 `measured_*` 与 `linear=true` 渲染。首期目标为 `I=-16 LUFS`、`TP=-1.5 dBTP`、`LRA=11 LU`；旧 pydub dBFS 方法不进入 Seed 场景成品链路。
- 输出继续支持 mp3/wav/m4b；内部尽量只解码和编码一次。

当前基础装配器已按实际解码时长计算场景起止：同地点使用 `180ms`，明确地点变化使用 `750ms`，上下文未知使用 `350ms`；不做交叉淡化。它支持 Seed 成功音频与上层提供的 `legacy_stems` 回退路径，并将带秒或毫秒时间戳的供应商字幕裁剪到场景实际时长后偏移。正式 Seed 响应中的 `start_time/end_time` 是毫秒，不能按秒解释；规范化器优先读取 `sentences/utterances/segments`，避免被同层整段 `text` 遮蔽，再统一输出 `start_ms/end_ms`。12 份既有真实 Seed manifest 均已通过该合同解析。装配结果先写同目录临时 PCM WAV，第一遍只测量，第二遍直接编码 mp3/wav/m4b 临时成品并原子替换目标，因此 MP3/M4B 只有一次有损编码；FFmpeg 缺失、测量值非有限、任一遍失败或输出为空都会终止装配，不静默降级为伪 LUFS。

Seed 失败场景进入 assembler 前，薄接入层会先用旧 TTS 合成其 `source_segment_indices`，根据实际片段混合时间轴复制并重定位该场景对应的 SFX/BGM，再生成完整的局部回退文件。筛选只接受 `scene_N/climax_N/shift_N` 这类可证明归属到源片段的时间线项；成功 Seed 场景的素材、全章 opening/ending 以及无法定位的 ambient 项不会重复叠加。持续音和配乐会裁剪到局部回退实际时长，应用顺序与旧链路一致：先 SFX，后 BGM。assembler 仍只负责装配，不感知或二次处理这些轨道。

单元测试已覆盖两遍命令、测量值传递、非有限测量拒绝、PCM 中间产物和报告回传；本机真实 FFmpeg 验证将 3 秒 48 kHz PCM 从 `-21.95 LUFS` 调整到 `-16.05 LUFS`，生成 48,812 字节 MP3。`SceneAssemblyResult` 与章节 `audio_info` 均记录 `loudness_normalized` 和测量报告。合并后的定时字幕条目已桥接到现有 SRT/VTT/ASS/Audacity Labels 保存入口；没有时间戳且当前 ASR 不支持时间戳时，只保留场景级粗粒度字幕，不按文本长度伪造逐句时间。

### 5.9 阶段 3 唯一章节编排顺序

阶段 3 已新增章节级领域编排服务 `ChapterScenePipeline`；两个章节入口接入时只能调用这一服务，不得分别拼装流程：

1. 读取已经评审的 `ScriptSegment[]`、项目音色映射、章节节奏、输出格式和 `audio_engine_mode`。
2. 使用 `VoiceReferenceResolver` 生成角色声音身份；Seed-TTS 2.0 形成 `speaker`，其它来源形成待物化音频资产描述。
3. `ScenePlanner` 先按完整片段、语义边界、时长、字符和最多三条稳定身份规划场景拓扑。
4. 对每个场景物化当前需要的音频 reference，生成最终请求 reference 与稳定 identity hash；Base64 只存在于当前请求内存中。
5. `ScenePromptCompiler` 使用最终角色顺序编译 Prompt，随后校验台词逐字、reference 顺序、字符预算和预计时长，并生成完整检查点签名。
6. `SceneRenderService` 生成、立即落盘并执行字幕/ASR和技术质量闸门。
7. 内容失败时由章节编排层按语义边界拆分一次并生成新计划；仍失败或不可拆时，只把该场景路由到 `legacy_stems`。
8. `SceneAudioAssembler` 按实际音频时长装配成功场景和回退片段，合并字幕偏移，执行最终响度处理并输出章节产物。
9. 复用现有保存、任务完成、积分结算和下载链路；任何异常都必须释放未结算冻结并保留已完成场景检查点。

当前 `ChapterScenePipeline` 已完成第 2-7 步的领域核心：先用未物化身份规划拓扑，再按场景物化已授权的用户私有或公共池参考音频、用最终 `audio_data` 重编译 Prompt/reference 哈希，同一参考源单章只物化一次；Seed-TTS 原生 `speaker` 不进入物化器。其它供应商官方系统音色试听不属于允许来源。质量报告失败且场景含多个完整片段时只拆分一次，优先显式语义边界、否则选择最接近预计时长中点的片段边界；子场景不递归拆分。reference 物化失败和渲染回退只影响当前场景，后续场景继续。第 1、8 步及第 9 步中的保存、任务完成、字幕、按秒计费和下载骨架已接入两个真实章节入口；时间戳型 ASR 真实供应商灰度和整体灰度仍未完成。

场景检查点采用增量提交：`SceneRenderService` 在场景音频原子落盘并完成质量判定后写出检查点，`SceneRenderMixin` 将工作线程事件同步切回后台任务事件循环线程，通过既有 TTS 进度回调立即提交当前 run。`scene_checkpoints` 按 `scene_id` 与数据库中的旧值合并；每次写入都等待提交完成后才继续下一场景。这样即使章节在后续场景、局部回退或最终装配时中断，重启也能直接复用已完成场景及既有拆分拓扑。最终成功结果中的 `scene_checkpoints` 只承担完整快照校验，不再是唯一持久化时点。

生产检查点至少包含：

```text
schema_version
renderer_version
project_id / chapter_id / scene_id
source_segment_indices / source_text_hash
model / audio_config
prompt_hash / reference_hashes
status / action / attempts / fallback_reason
audio_path / audio_sha256 / duration
subtitle_payload / quality_report
billing_duration_s / provider_request_id / provider_request_ids
```

检查点不得保存 API Key、完整 Base64 reference 或临时供应商 URL。项目或剧本变化只使受影响场景失效；模型、音频配置、reference 身份或 renderer 版本变化必须使对应场景失效。

### 5.10 已确认实现偏差与修复记录

以下问题来自 2026-07-22 对 Prompt 编译、场景规划、renderer、章节 mixin、质量闸门和检查点恢复链路的代码对照。表格保留修复前事实与验收标准；8 项均已在阶段 3I 完成并通过自动化测试。

| 编号 | 优先级 | 审计发现（修复前） | 影响 | 已完成修复 | 验收测试 |
|---|---|---|---|---|---|
| 1 | P0 | 编译器已经产生 `vocalization` 事件，计划和 renderer 未携带 `expected_vocalizations`，质量闸门收到空豁免集合 | “啊/嗯/喘息/哭腔”可能被判为 `extra_lines`，触发回退，最能体现 Seed 情绪能力的场景反而不会走 Seed 成品 | 从 `ScenePromptCompileResult.events` 收集可辨识非语言人声，写入计划并透传到闸门；与完整台词、舞台说明严格分离 | 端到端构造含喘息/哽咽/“嗯”的场景，确认闸门不产生误报；未声明完整台词仍必须失败 |
| 2 | P0 | `_reuse_checkpoint()` 只复用 `passed`；`legacy_stems` 已落盘结果不复用，局部 fallback 以 `resume_checkpoint=None` 重合成 | 进程重启后会重复调用 Seed 或旧 TTS，增加等待时间和供应商费用 | 复用同签名终态 `legacy_stems` 决定；完整回退写入 `fallback_status=ready` 和可校验 artifact，同签名重启只读取产物 | 首次运行回退后重启，断言 Seed 和 fallback TTS 调用数均为 0；签名或 artifact 变化才重新生成 |
| 3 | P0 | 当前 run 能汇总 `provider_request_ids`，但没有跨运行不可变 provider attempt ledger | 旧请求可能已产生供应商费用，内部检查点/积分幂等不能阻止重启再次产生外部费用 | 以 provider request ID、Prompt 签名、场景、模型、尝试序号和 `original_duration` 建立追加式幂等记录；结算摘要从 ledger 聚合 | 相同 provider request ID 跨实例重放只落一条费用记录，并只计费一次 |
| 4 | P1 | `ScenePlanner` 候选增长阶段不断完整调用 `_compile_indices()`，最终还会再次编译 | 长章节 Prompt 构建退化为局部 O(n²)，并放大 CPU 和内存 | 用增量估算做普通门控，接近字符/时长/reference 硬上限时再完整编译，最终保留一次事实编译 | 数百片段基准比较编译次数、耗时和结果哈希；最终计划与全量编译基线一致 |
| 5 | P1 | 章节 pipeline 创建 renderer 时未注入 ASR provider | 供应商无字幕或字幕结构不可用时直接 `needs_asr`，即使系统已有 ASR 能力也会回退 | 增加可选 provider 注入和错误分类；有 provider 时执行 ASR，无 provider 时明确回退且不重复 Seed | mock ASR 转写可通过闸门；未配置 ASR 只调用一次 Seed；provider 错误归类为不可重试 |
| 6 | P1 | 最终评审同时读取整章 `audio_path.read_bytes()` 和所有场景音频 `audio_list` | 长章节内存峰值随整章和场景总时长叠加，可能造成 OOM | 用源片段 `audio_presence` 替代场景字节列表，当前返回合同只保留整章 bytes | 断言场景最终评审传入 `audio_list=None`，并按源片段得到正确存在性序列 |
| 7 | P1 | 适配器支持 multilingual，但生产 mixin 与计费摘要固定普通 Seed Audio 模型 | 配置选择可能不生效，实际模型、检查点和费用摘要不一致 | 模型从同一运行时配置传入 prompt/compiler、adapter、renderer、checkpoint 和 billing summary；未验证模型不得路由 | 设置 multilingual 配置，断言请求、检查点和账单均使用相同模型；普通模型回归不变 |
| 8 | P2 | 技术闸门仍存在削波 `>0.01`、静音 `>0.9` 等散落魔数；进度 callback 某分支 fire-and-forget | 质量策略不可审计；进度任务可能在事件循环关闭时被取消 | 集中质量阈值、版本化并写入策略 hash；同循环进度任务由章节流程统一等待，异常集中记录 | 策略变化使 checkpoint 失效；受控延迟的进度任务在章节返回前完成 |

完成结果：1-3 已阻止已知错误回退、同签名重复 Seed 调用、完整局部回退重复合成和 request ID 重复计费；4-7 已完成 Planner 增量门控、ASR 注入、最终评审内存收敛和模型配置贯通；8 已完成质量策略版本化及同循环进度任务回收。运行结果仍保留明确 `fallback_reason`，不会把能力缺失静默当作 Seed 成功。

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
- 路由输入只允许使用可解释事实：场景类型、主要角色数、reference 数量、精确编辑需求、预计时长/成本、对应场景类型的近期 Seed 失败率和是否存在可靠回退；不能根据隐藏随机分或单次偶然结果切换引擎。
- `auto` 启用前必须配置单章成本上限、场景失败率冷却阈值和回退策略，并在前端类型、项目持久化、检查点、进度与成本观测中保持同一模式值；在这些条件未完成前继续降级为 `legacy_stems`。

当前总任务追踪继续兼容复用 `tts_synthesis`，场景层通过 `audiobook_progress.stage=scene_rendering` 独立推送；每个检查点完成后按“已经做出 Seed/回退决定的源片段数 / 总源片段数”更新 `0-100` 进度，并附带 `scene_id`、场景状态、回退原因、已处理/Seed 通过/总片段数。前端加入独立 `audiobook_<id>` 房间，把该事件映射为动态“场景生成”卡片并替换旧“TTS 合成”卡片；`legacy_stems` 未收到场景事件时继续展示原卡片。页面断线时既有任务 SSE/轮询仍是兜底，WebSocket 失败不阻断生成。

Seed 场景计费已与资产工作台文字计价分离：预检按选中章节的预计朗读秒数估算，冻结直接复用预检金额；渲染按每次成功响应的 `original_duration` 累计真实计费秒数，章节汇总 `billable_duration_s`、供应商请求次数和 `actual_cost_yuan`，再复用现有项目结算与失败释放。当前用量随场景检查点和章节汇总保存，独立不可变计费账本表仍属后续增强。

2026-07-22 的统一经营计价规则是：**用户始终按供应商公开后付费最高价计价，平台实际采购套餐或订阅折扣只用于供应商成本和毛利计算**。有声书模块的有效 `user_price_rate` 固定为 `1.0`，不受后台通用倍率影响；`points_per_yuan` 仍负责人民币与积分换算，`freeze_buffer_rate` 只增加临时冻结额度，不增加最终结算。当前尚未录入任何实际套餐，故供应商成本暂时也按公开后付费价保守计算。旧 `DOUBAO_SEED_AUDIO_PRICE_PER_SECOND_YUAN` / `DOUBAO_SEED_AUDIO_PRICE_PER_MINUTE_YUAN` 不再覆盖用户费率。

后续补充真实采购套餐时，用户公开价、预检、冻结和结算公式保持不变。线性折扣可写入 `POINTS_POLICY_AUDIOBOOK_PROVIDER_DISCOUNT_RATE_*`；包含预付金额、周期额度、超额单价或阶梯价格的套餐不能只压缩成一个折扣率，必须补充 `provider/model/plan_name/billing_period/paid_yuan/included_quota/overage_rate/effective_at/source` 等采购档案，并定义额度成本分摊方式后再计算实际利润。

当前有声书 TTS 与场景音频公开价如下。纯 TTS 每小时估算按 `4.5 字/秒`，即约 `16,200 字/小时`；固定音色费用必须由音色生命周期事件单独记账，不能在每章重复收取。

| 模型 | 用户公开价 | 约每小时 | 额外音色费用 |
|---|---:|---:|---|
| Qwen3-TTS Instruct Flash | ¥0.8/万字符 | ¥1.30 | 当前运行时不涉及；Qwen-TTS 自定义音色创建 ¥0.01/个 |
| CosyVoice v3.5 Plus | ¥1.5/万字符 | ¥2.43 | 创建复刻/设计音色免费 |
| MiniMax Speech 2.8 Turbo | ¥2/万字符 | ¥3.24 | 复刻请求免费；试听按字符费；首次正式使用 ¥9.9/音色 |
| MiniMax Speech 2.8 HD | ¥3.5/万字符 | ¥5.67 | 复刻请求免费；试听按字符费；首次正式使用 ¥9.9/音色 |
| MiMo V2.5 TTS / Voice Design / Voice Clone | 限时免费 | ¥0 | 当前促销口径，不承诺永久免费 |
| StepAudio 2.5 TTS | ¥5.8/万字符 | ¥9.40 | 试听只收合成费；正式复刻成功 ¥9.9/音色 |
| Doubao Seed-TTS 2.0 Expressive | ¥3/万字符 | ¥4.86 | 后付费复刻槽位首次正式使用 ¥138/音色；试听按 ¥3/万字符；7 天未正式调用自动删除 |
| Doubao Seed Audio 1.0 | ¥1/分钟 | ¥60.00 | 按 `original_duration` 毫秒级计费；包含对白、环境、音效和配乐，不能与纯 TTS 做同能力比较 |

Seed 章节计费摘要记录 `pricing_source=volcengine_public_postpaid`、`pricing_basis=public_list_price`、`price_per_minute_yuan=1.0` 和 `price_per_second_yuan=1/60`。最低计费单位 `billing_increment_s` 默认 `0.0`（线性按秒），可经 `DOUBAO_SEED_AUDIO_BILLING_INCREMENT_S` 配置为按调用向上取整到增量整数倍（详见 §12-5 ③）。一次 60 秒成功响应按 ¥1.00 记账；供应商已成功生成但质量闸门失败的重试仍按各自 `original_duration` 累计。局部 `legacy_stems` 回退产生的普通 TTS 成本与 Seed 成本相加，并以 `cost_components.seed_audio_yuan`、`legacy_fallback_tts_yuan`、`total_yuan` 分项保存。普通章节按生成前后成本快照差额结算，避免同一引擎连续生成多章时重复累计前序章节费用；混用角色级 TTS 模型时按模型聚合，不再只统计主引擎。

MiniMax、StepAudio 和豆包固定音色费用当前只作为模型价格元数据登记，尚未进入自动冻结或最终结算。系统不能仅凭一个 `voice_id` 判断供应商是否已收费。音色生命周期账本**载体已落地**：新增表 `voice_asset_billing_ledger`（模型 `VoiceAssetBillingLedger`、迁移 `add_voice_asset_billing_ledger`、仓储 `voice_asset_billing_ledger_repository.py`），以幂等键登记“创建/试听/正式复刻成功/首次正式使用”事件，并预留 `provider_charge_id/provider_charge_receipt/charged_at` 供真实扣费后补录。`record_voice_billing_event` 只登记事件、绝不自动扣费；实际冻结/结算口径（按哪个事件计一次、失败是否计费）待运营决策后由上层在凭证齐备时调用 `mark_charge_settled` 落地。在此之前禁止按章节重复收取 ¥9.9 或 ¥138，也禁止猜测性补扣。

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
| `DoubaoSeedAudio10Adapter` | 已扩展 | 已完成模型、reference、字幕、响应和错误分类；真实限流/计费继续验证 |
| `points_task_precheck` / 积分事件 | 已扩展 | Seed 按公开后付费 ¥1/分钟和预计秒数冻结，按 `original_duration` 汇总实际金额；采购折扣只进入供应商成本与毛利 |
| **新增** `scene_engine/*` | 已接入实验链路 | 规划、Prompt、参考、渲染、质量闸门、装配、响度和计费汇总均已接入双入口 |

---

## 8. 一致性、成本、时延与失败恢复

- **角色一致性**：需要跨场景复现的角色必须绑定稳定声音身份。没有 reference 的文字描述只能用于临时角色，不能作为主角方案。
- **场景连续性**：相邻计划携带环境、音乐和情绪状态；章节装配不能用统一静音或统一交叉淡化抹掉场景差异。
- **生成随机性**：同一 Prompt 的多次结果可能不同。检查点复用成功音频，不因章节后续重试而重新抽样。
- **并发**：初始并发设置为 1，验证供应商限流后再提高到 2-3；重试必须带抖动，避免场景并发放大 429。
- **成本**：在真实价格和账单字段核实前不预设“必然更贵/更便宜”。PoC 同时记录输入字符、输出时长、调用次数、重试次数、积分和供应商成本。
- **时延**：静态目录中的 `avg_latency_seconds` 只用于展示，不作为容量规划依据；以阶段 0 完整样本矩阵的 P50/P95 为准。
- **失败恢复**：场景落盘后写检查点，重跑只处理签名变化、明确可重试错误或用户显式重生成。`passed` Seed 场景、同签名终态 Seed 失败决定和已校验局部回退文件均可复用；局部回退尚未提供“合成到一半”的逐片段续传，只有完整 artifact 写入后才进入可复用状态。
- **编辑成本**：修改一句台词只使所属 `45-75s` 目标场景失效；这也是不能按 100-120 秒规划常规场景的原因。
- **临时 URL**：响应后立即下载并验证，不把 URL 有效期当作可恢复机制。

- **外部成本与内部幂等分开**：现有积分冻结/结算和章节摘要负责内部结算；`provider_attempts.jsonl` 在每次成功响应后立即 `flush + fsync`，以 request ID 幂等记录模型、场景、尝试序号和 `original_duration`，章节费用优先从 ledger 聚合。JSONL 是否升级为数据库不可变账本由后续运营审计要求决定。
- **回退状态**：renderer 保留 `status=legacy_stems` 的兼容语义，并用 `fallback_status=ready` 与 `fallback_artifact` 表示完整回退文件可复用。只有签名变化、artifact 校验失败、用户显式重生成或供应商明确可重试错误经过冷却后，才允许重新生成对应层级。

---

## 实施进度（实时更新）

更新时间：2026-07-25

- [ ] 阶段 0：真实接口契约与 A/B 基线。基础成功契约、三次复测槽位、逐样本缓存、计费/时延记录以及 30 槽位单人页面评审已经完成；严格盲评、评审数值导出、声纹指标和统计基线尚未完成。
  - 已重新读取用户提供的本地《豆包语音_音频生成 HTTP》PDF：确认两个模型 ID、120 秒、3000 字符、三条音频参考、单条 30 秒/10 MB、reference 三选一、`enable_subtitle`、官方响应 `audio/url/subtitle` 和 `X-Tt-Logid`。这只是文档契约复核，不等同于账号权限和真实调用验证。
  - 已读取 2026-07-20 更新的火山引擎官方文档：Seed Audio 请求头是 `X-Api-Key` 与可选 `X-Api-Request-Id`，没有 Seed-TTS 使用的 `X-Api-Resource-Id`；传入参考音频时，`text_prompt` 必须用 `@音频N` 引用对应序号。
  - 初始 5 次真实请求均返回 `40402002 / TTSInvalidText:ReadableTextRatioTooLow`。复核后确认根因是 Windows PowerShell here-string 经管道传给 `python -` 时把全部中文转换为 ASCII 问号，Python 侧中文字符数为 0；这些结果属于测试工具编码失真，不能用于判断账号权限、模型能力或 Prompt 质量。
  - 修正为 Unicode 环境变量传递后，逐字使用用户提供的 555 字电话对话样例进行无 reference、不开字幕请求，返回 HTTP 200；`X-Tt-Logid=20260720230807773B765F13C1932F6575`，同时返回 Base64 音频和临时 URL，`duration/original_duration=54.7s`。
  - 通过项目 registry 和 `DoubaoSeedAudio10Adapter` 使用统一配置并开启字幕再次请求成功；`X-Tt-Logid=20260720231442B323FC3A93347A2CCDD7`，返回 URL + Base64、`73.08s` 音频、完整 256 字对白字幕和 23 条句级时间戳。由此确认账号、OpenSpeech Key、endpoint、字幕配置、请求映射和响应解析均可用。
  - 已使用现有 Qwen `Vincent` 试听片段（WAV、24kHz、单声道、12.16s）作为 `audio_data`，通过 `@音频1` 完成真实 reference 生成；结果返回音频和字幕，并由 `SceneRenderService` 下载为 48kHz 双声道 MP3。产物位于 `.test-tmp/real-seed-audio-reference-green-01/`，证明“直接复用现有试听片段”链路可行；声音相似度和多次稳定性仍需盲评。
  - 已在独立 `/audiobook-tts-test` 测试单元增加 Seed 场景 A/B 视图，与项目、章节和正式生成流程完全隔离。固定五类场景：多人压迫动作、电话悬疑对话、三参考音色争吵、单人伤感回忆、纯旁白基线；每类均提供“描述音色样本 A”和“试听 reference 样本 B”，两者逐字共享相同台词。
  - 样本 B 的每个 reference 槽位现可独立选择“供应商模型 + 音色”，通过 `/tts/preview-cached` 使用统一中性文本生成或复用试听，试听成功后立即播放并绑定到对应角色；不再要求用户先切换到 TTS 朗读模式生成一次“当前试听”。原“使用当前试听”入口保留为快捷方式，但不是唯一入口。
  - Seed-TTS 2.0 音色绑定只提交 `source_model + source_voice_id`，后端直接构造 `references[].speaker`，试听音频不进入场景请求；其它供应商命中共享 OSS 时提交 `audio_url`，无云存储降级为 Blob 时提交 `audio_data_base64`。非原生 speaker 的 Base64、URL 和缓存身份三条路径最终都经过 10MB、30 秒、可解码、削波和异常静音检查，并统一转为 Seed Audio 的 `audio_data`。
  - 三个角色槽位分别维护模型、音色目录、加载、播放、错误和绑定状态，互不覆盖；角色到 `@音频N` 的顺序仍由后端计划构建器确定，不由前端拼 Prompt。
  - 首次页面联调出现 `/scene-audio/test-preview` HTTP 422，根因曾是 Windows 同时存在两组 8000 监听。后续确认 Docker 重启策略会让 `localhost/[::1]` 指向容器，而开发终端中的 Uvicorn 监听 IPv4；Vite 开发代理现统一复用 `http://127.0.0.1:8000`，API、workflow 和 WebSocket 均进入开发终端对应的本机后端。
  - reference Prompt 已停止重复年龄感、口音、音高、沙哑度、磁性等静态音色描述，只保留确定性的 `角色名 -> @音频N` 映射和当前情绪表演；Prompt 哈希因此变化，旧场景缓存不会复用。浏览器评审存储现升级到 v3，评审身份由 `case + variant + sample_index` 组成，旧 v2 记录不计入三次复测基线。
  - Seed-TTS 2.0 原生 speaker 已完成真实请求验证：`zh_male_taocheng_uranus_bigtts` 作为 `references[].speaker` 生成“旧宅中的线索”得到 `17.928s / 286892 bytes`，“雨声里的回忆”得到 `33.168s / 530732 bytes`，两次均 `reference_type=speaker / generation_status=passed`；相同 Prompt 和 speaker 再次读取为 `cached=true`。
  - 统一中性试听文本已为上述音色真实生成并上传 OSS：首次 `cache_hit=false / storage=oss`，第二次 `cache_hit=true`。该试听只供选择确认，不进入原生 speaker 的 Seed Audio 请求。
  - 独立测试结果按 `model + prompt_hash + reference_hashes + audio_config + sample_index` 分别落盘，`r1/r2/r3` 不再覆盖；`sample_id` 同时绑定槽位签名与实际音频 SHA-256，强制重生成得到不同音频时不会错误继承旧评审。第 1 次复测仍会尝试读取升级前旧缓存，避免无意义重新计费。
  - 普通“生成样本”只复用当前复测序号的缓存，刷新图标会明确提示再次调用产生供应商费用。响应记录供应商 request ID、真实音频时长、生成时延、技术质量结果和按 `original_duration × ¥1/分钟` 计算的公开后付费费用；浏览器响应不暴露服务器绝对文件路径，评审记录只写独立本地测试存储，不写 `ChapterAudio`。
  - 页面现固定展示每条路径的第 1/2/3 次复测，总进度按 30 份评审计算；评审维度已拆分为台词完整、剧情可懂、角色可区分、音色一致、情绪表演、音效时序、配乐适配、混音清晰和可用于生产。未生成当前样本、未给综合评分或仍有待评维度时不能保存为完成评审。
  - 2026-07-25 用户确认 30 个槽位均已完成综合评分和全部九项评审。由于评审记录当前只保存在浏览器 `localStorage`，本轮先记录用户明确给出的定性结论，不能伪造未导出的逐槽位均分、通过率或胜率：跨供应商 reference 成品与原试听存在轻微音色差异，但同一 reference 的不同生成批次基本保持相似；只使用文字音色描述时，只要角色描述词完全固定，不同批次的声音相似度也较好；在场景间主观响度得到控制的前提下，整体效果具备正式生成可用性。
  - 生产路由据此收敛为：豆包原生 `speaker` 继续作为最高稳定性身份输入；主角、旁白和长期重复角色优先使用原生 `speaker` 或固定 reference，并明确产品文案不得承诺逐样本精确复刻；次要角色、一次性人物和群体声允许使用固定描述音色。无论采用 reference 还是描述音色，同一角色的声音身份块必须版本化并锁定，场景 Prompt 只改变情绪、语速、距离和动作，不得重新改写年龄、口音、音高、沙哑度等身份词。
  - 当前 `SceneAudioAssembler` 在所有场景拼接后对整章执行两遍 EBU R128，目标为 `I=-16 LUFS / TP=-1.5 dBTP / LRA=11 LU`。它能统一章节最终平台响度，但会保留场景源文件之间原有的相对响度差，不能单独保证片段切换时主观响度一致。正式灰度前新增受限的场景级响度校准：先测量各场景 LUFS，以章节对话场景中位数为基准做小范围增益修正并设置最大增减幅度，再执行现有整章两遍 loudnorm；低语、远场、回忆、爆发和纯环境段必须保留剧情动态，禁止把每个场景机械压到完全相同 LUFS。校准应在 PCM 装配阶段完成，避免场景逐个二次有损编码。
  - 场景级响度校准现已落地：`FFmpegLoudnessNormalizer.measure()` 只测量不渲染；`SceneAudioAssembler` 只让包含审定台词且测量成功的场景参与中位数，最大增益调整为 `±3dB`，正增益受 `-1.5 dBTP` 真峰值余量约束，低于 `0.25dB` 的微调忽略，纯环境段不作为基准；测量失败或可测对话场景不足两个时跳过校准并保留原有整章两遍 loudnorm。校准报告写入 `loudness_report.scene_balancing`，不改变字幕时间轴和最终单次编码路径。Seed 场景装配及章节注入回归 `146 passed / 1 skipped`，最终评审/导出回归 `26 passed`；真实用户授权资产的误报/漏报与听感阈值仍需标定。
  - 2026-07-24 首次评审联调出现“生成后空白页”：根因不是路由跳转，而是 `5173` 已加载新版 Vite 源码，`8000` 却仍由 2026-07-21 启动且无热重载的 Docker `novel_backend` 提供旧响应；旧响应缺少 `billing/sample_id/sample_index`，React 读取 `preview.billing.actual_cost_yuan` 时发生运行时异常。前端现通过 `normalizeSeedSceneTestPreviewResponse` 对旧响应补齐安全默认值，版本错配时不再整页崩溃；Docker 后端已单独重启，健康检查和 OpenAPI 均确认三个字段来自当前代码。PostgreSQL、Redis、前端和数据卷未重启。
  - `multi_character_pressure / described_voices / r2` 在真实评审联调中等待豆包接口 `300 秒` 后返回 `The read operation timed out`，没有成功 manifest 或可复用音频。该错误属于供应商网络读取超时，不能证明供应商未受理或未计费；测试单元保持 `max_retries=0`，因此没有自动重复请求。前端现将这类错误转换为中文风险提示，要求先确认账单/供应商状态，再通过刷新按钮显式重试。
  - 用户随后显式重试同一 `r2` 时，Seed 创建阶段已经返回临时签名音频地址；后端在 `2026-07-24 15:31:55` 对该地址收到 HTTP 200，但连接在声明的 `286508 bytes` 中只接收 `79617 bytes` 后被对端关闭，最终报 `peer closed connection without sending complete message body`，因此没有成功音频和 manifest。这不是 Prompt、Seed 创建超时或前端响应体错误，而是**已生成成品的临时 URL 下载中断**。`SceneRenderService` 现将临时 URL 下载设为独立恢复层：连接中断、读取超时、408/425/429 和可重试 5xx 最多额外重试同一地址 2 次，默认退避 `0.25s/0.5s`；该过程不重新调用 Seed、不增加生成次数，新增的业务重试日志只记录下载尝试序号和错误类型，不主动记录 URL。连续 3 次下载失败后返回稳定错误码 `audio_download_failed:*`，并标记为不可触发 Seed 自动重试；前端提示本次生成可能已计费，只允许用户稍后显式决定是否重新生成。当前这次已失败请求没有持久化临时 URL，不能通过普通缓存自动恢复；再次点击生成会创建新的 Seed 请求。伪 URL 回归已确认“首次中断后恢复”和“下载耗尽也只调用一次 Seed”，相关后端合并测试为 `52 passed`，前端错误提示为 `4 passed`；修复过程没有调用真实 API。历史 `httpx` INFO 访问日志曾记录完整签名 URL，本次没有删除或改写历史日志；正式生产前应统一对 HTTP 客户端日志中的 query 参数做脱敏，同时保留域名、路径、状态码和时延。
  - 经用户确认，Seed Audio 客户端读取超时已由 `300 秒` 延长到 `600 秒`：Docker Compose 显式传入 `VOLCENGINE_OPEN_SPEECH_TIMEOUT=${VOLCENGINE_OPEN_SPEECH_TIMEOUT:-600}`，前端独立测试请求同步延长到 `660 秒`，为后端序列化和网络返回保留 60 秒余量；测试单元继续禁止自动重试。`novel_backend` 已单独强制重建并确认容器内变量为 `600`，健康检查与 OpenAPI 正常；本次配置变更没有调用 Seed API。
  - 独立测试缓存曾把音频保存为当前环境绝对路径，并要求读取路径位于当前 `output_root`，导致 Windows 的 `C:\...\backend\data\seed_scene_tests\...` 与 Docker 的 `/app/data/seed_scene_tests/...` 互相失效，存在同一样本被重新调用和重复计费的风险。现已使用 manifest schema 3 持久化 `renders/...` 相对路径，并兼容映射 schema 1/2 旧路径；现存 12 份真实清单只读核验中，5 份 Docker 路径和 7 份 Windows 路径均能映射到当前真实文件。新格式、两种旧路径复用和路径穿越拒绝回归均已覆盖，后端独立单元为 `18 passed`；修复验证没有调用 Seed API。
  - 五类场景当前预计时长合计为 `148 秒`；两条路径各重复 3 次的静态预计总时长为 `888 秒（14.8 分钟）`，按公开后付费约 `¥14.80`。这只是调用前估算，最终必须按每次供应商返回的 `original_duration` 汇总；30 次均触及 120 秒硬上限时理论上限为 `¥60`。本轮升级没有调用真实 Seed API，也没有新增费用。
  - 历史首个真实样本 `multi_character_pressure / described_voices` 已映射为 A 路径第 1 次复测：`19.032s / 304556 bytes`，`X-Tt-Logid=20260720235856F569987EDB45DA34D5C2`；字幕完整包含 5 句台词，覆盖率 1.0，无漏句、增句、乱序、削波或异常静音，旧 manifest 可通过 `original_duration=19.0s` 恢复公开价费用 `¥0.3167`。但旧绝对路径在 Docker 中失效后，2026-07-24 又产生一份同槽位 `r1`：`X-Tt-Logid=2026072422194419E5EF2A151396F93996`、`original_duration=17.5s`、公开价约 `¥0.2917`；因此不能再把当天读取描述为“没有新增调用”。路径兼容修复后，当前容器已只读确认该 legacy manifest 为 `cache_readable=true / audio_exists=true`，后续不应再仅因 Windows/Docker 切换重复调用。
- [x] 阶段 1A：Seed-TTS 2.0 正式改编 Prompt 修复。
  - 已使用统一模型 ID 规范化替代 `"plus" in model_name` 粗略判断。
  - Seed-TTS 2.0 已获得独立的 Query-Response / `context_texts`、短强表演音频标签边界和微表演指导。
  - 剧本改编继续输出供应商中立的 `ScriptSegment` 字段，不允许 LLM 直接输出 `style_control_method`、`style_tags`、`inline_audio_tags`、`context_texts` 或 `use_tag_parser`。
  - 非 Qwen、非 CosyVoice、非 Seed-TTS 模型使用通用提示，不再错误显示为 Qwen。
  - TDD：新增 `test_transform_prompt_uses_seed_tts_delivery_contract`；修复前按预期失败，定向测试 `1 passed`，相关提示策略回归 `13 passed`。
- [x] 阶段 1B：Seed Audio 适配器契约扩展。
  - 支持 `seed-audio-1.0` 与实验性注册的 `seed-audio-1.0-multilingual`，请求模型不再固定；多语种模型仍需阶段 0 真实调用验证后才可进入生产路由。
  - 默认合并 `mp3 / 48000Hz / pitch_rate=0 / speech_rate=0 / loudness_rate=0 / enable_subtitle=true`，并保留调用方显式配置；资产中心和场景渲染器现在复用同一份默认配置并统一传递空 watermark。
  - 请求前校验 Prompt 最长 3000 字符、references 最多 3 条，以及每条 `speaker/audio_data/audio_url` 严格三选一。
  - 响应兼容官方顶层 `audio/url/subtitle` 与可能的 `data` 嵌套结构，统一解析 URL、Base64 音频、字幕、时长和请求标识；请求发送 UUID `X-Api-Request-Id` 并保留响应 `X-Tt-Logid`。
  - 验证错误不可重试；连接超时、429、408/504 和 5xx 以结构化 `error_code / retryable / retry_after / status_code / provider_code` 返回，重试执行留给场景服务。
  - 供应商将 Prompt/reference 内容校验包装为 HTTP 500 时，适配器按 `TTSInvalidText / ReadableTextRatioTooLow` 识别为不可重试的 `invalid_request`，避免重复计费风险。
  - TDD：适配器测试全量 `16 passed`；模型目录同时区分“官方支持格式/采样率”与“项目已验证组合”。
- [x] 阶段 1C：现有试听片段参考资产物化。
  - 新增 `PreviewReferenceAsset / PreviewReferenceMaterializer`，只负责非原生 speaker 的已有试听结果或共享 OSS 试听缓存，不在 reference 解析或物化过程中触发 TTS；Seed-TTS 2.0 在该服务之前直接解析为 `speaker`。
  - 新增正式角色试听默认缓存身份构造，复用现有 `_build_preview_cache_key`，并验证其与试听路由、warmup 生成的键一致；Qwen 音色别名仍先规范化为真实 speaker。
  - Base64 Data URL 会去除 MIME 前缀并严格解码；URL 下载后不直接透传给 Seed Audio，统一转换为已校验的 `audio_data`。
  - 已实现 10 MB、30 秒、空音频、不可解码、明显削波、异常静音检查，SHA-256 稳定寻址和原子落盘；技术分析结果已按音频 SHA-256 持久化缓存跨运行复用（`SceneAudioAnalysisCache`）；单人声、背景音乐/混响自动检测及授权资产表仍需后续完成。
  - TDD：新增 `test_audiobook_seed_scene_preview_reference_asset.py`；参考资产与试听缓存契约定向回归 `19 passed`。
- [x] 阶段 2A：`SceneAudioEvent` 与确定性 Prompt 编译器。
  - 新增供应商中立的 `SceneAudioEvent`、`SceneVoiceProfile`、`ScenePromptCompileResult`，事件类型和时间锚点在构造时校验。
  - `ScenePromptCompiler` 可将正式 `ScriptSegment[]` 确定性转换为音乐、语音、非语言人声、音效、环境和停顿事件，不调用 LLM。
  - 当前场景角色按首次发声顺序绑定 `@音频N`；未出场角色不会进入 Prompt；超过 3 条 references 直接拒绝。
  - 有 reference 的角色不再附带静态音色描述，只声明“声音身份以参考为准”；年龄、口音和声线描述仅用于没有 reference 的临时角色，逐句事件继续控制当前情绪和表演。
  - 台词只从 `ScriptSegment.text` 复制；喘息、吞咽、哭腔等进入 `vocalization`，动作音效不进入台词引号。
  - 支持 `before/during/after/throughout/until_text` 的自然语言渲染；超过字符预算返回 `requires_split`，保留完整 Prompt 和全部台词供规划器拆分。
  - TDD：新增 `test_audiobook_seed_scene_prompt.py`，`5 passed`。
- [x] 阶段 2B：`ScenePlanner` 与 `VoiceReferenceResolver`。
  - `ScenePlanner` 复用现有有声书时长估算器，按 45-75 秒目标、90 秒软上限、105 秒硬上限、最终 Prompt 字符预算和最多 3 条 references 贪心切分。
  - 每次扩展候选场景都会运行真实 Prompt 编译，不以原文字符数替代最终 Prompt 校验；同一 `ScriptSegment.text` 永不在内部切断。
  - 计划包含稳定场景 ID、原片段索引、预计时长、完整预期台词、Prompt 哈希和 reference 哈希；单片段自身超限时标记 `legacy_stems`，不删减内容。
  - `VoiceReferenceResolver` 仅将 Seed-TTS 2.0 音色转换为 `speaker`；其它供应商 `voice_id` 不透传。存在当前试听 URL/Base64 时直接形成待物化描述；项目只保存 `tts_model + voice_id` 时形成内部 `preview_cache` 身份，既占用规划期 reference 名额，又由 Pipeline 用同一默认缓存键命中 OSS。Renderer 会拒绝任何未物化 `preview_cache`，确保内部占位永不泄漏到供应商 API。
  - 当前解析器已经完成试听结果字段桥接，`PreviewReferenceMaterializer` 也已完成试听缓存读取、校验和落盘；场景主流程仍需在阶段 3 调用物化器，并把返回的 `audio_data` reference 注入场景计划。
  - 当前 resolver 消费运行态 voice mapping；生产级授权字段和通用声音身份资产表仍是后续数据层工作，本轮没有迁移数据库，也没有把 Base64 写入项目 JSON。
  - planner 已补入第一版确定性语义边界：达到目标最小时长后识别显式 `instruct_scene` 变化、音乐风格变化，以及新说话人与情绪阶段联合变化；短场景不会仅因软边界被继续切碎。
  - 当前仍缺少独立时间/地点/故事节拍字段、禁止切点关系和最近最佳边界回溯，不能把第一版规则描述成完整语义评分器。
  - TDD：`test_audiobook_seed_scene_planner.py` 当前 `14 passed`，覆盖时长、Prompt、reference、场景、音乐、说话人/情绪联合边界、短场景保护、物化后重编译和失败场景语义拆分。
- [x] 阶段 2C：字幕/ASR 与音频技术质量闸门领域核心。
  - `SceneAudioQualityGate` 优先解析供应商字幕，字幕缺失时接受已有 ASR 转写结果；两者都缺失时明确返回 `needs_asr`，不默认音频正确。
  - 对台词统一消除标点、大小写和空格差异后，分别计算覆盖率、漏句、额外可辨识文本和顺序；已声明的“啊/嗯/喘息”等仅从额外文本中豁免。
  - 门槛保持 `coverage >= 0.99`、漏句 0、额外文本 0、顺序正确；恢复动作固定为 ASR → 同场景重试一次 → 拆分一次 → `legacy_stems`，不存在无限重试。
  - `SceneAudioTechnicalAnalyzer` 实际解码场景音频文件，计算时长、采样率、声道、削波样本比例和长静音比例；损坏或空文件返回结构化失败。
  - 真实 reference 产物包含 `68.1841%` 的剧情停顿、极低电平雨声和约 5.37 秒收尾留白，旧 `65%` 阈值将其误判为异常静音。技术闸门现仅在静音比例超过 `90%` 时失败：`75%` 的戏剧停顿可通过，`100%` 全静音仍被拦截；台词完整性继续由字幕/ASR 独立保证。
  - TDD：质量闸门与策略 `12 passed`，真实 WAV 技术分析 `5 passed`。ASR provider 注入、vocalization 豁免透传、`needs_asr` 不重复 Seed 和质量策略哈希已在阶段 3I 完成。
- [x] 阶段 3A：独立 `SceneRenderService` 单场景渲染核心。
  - 新增显式调用的 `SceneRenderService`：向适配器传递计划中的 Prompt、references 和字幕配置，支持适配器 URL/Base64 输出，结果立即原子落盘并计算稳定路径。
  - 接入字幕/ASR 质量闸门；失败最多重试一次，随后返回 `legacy_stems`，成功计划按 Prompt/reference 哈希复用检查点。
  - 该服务已由共享 `SceneRenderMixin` 接入章节两个生成入口；默认模式仍未改变，只有显式 `seed_scene` 调用。真实 reference 与无 reference 调用均已完成供应商生成、字幕返回、URL 下载、原子落盘和技术分析。
  - 通用 renderer 检查点已纳入 `schema_version + renderer_version + model + audio_config + scene_id + prompt_hash + reference_hashes`；缺字段的旧检查点、模型变化或合并后的采样配置变化都会重新生成。
  - TDD：`test_audiobook_seed_scene_renderer.py` 当前 `7 passed`，覆盖单场景成功、有限重试回退、严格检查点复用、模型/配置失效、旧检查点失效和不可重试错误。
- [x] 阶段 3B：`ChapterScenePipeline` 领域编排核心。
  - 串联 `VoiceReferenceResolver → ScenePlanner → PreviewReferenceMaterializer → 最终计划重编译 → SceneRenderService`，已授权用户私有/公共池 reference 在最终 Prompt/哈希前变为已校验 `audio_data`，原生 Seed speaker 保持 ID 直传；其它供应商官方试听直接拒绝。
  - 同一参考源在单章运行内复用物化结果；场景检查点按最终 scene ID 独立传递，某一场景 reference 失败或渲染回退不会阻断后续场景。若 checkpoint 已存在 `_split_01/_split_02` 子场景，重启直接恢复拆分拓扑，不再重复调用父场景。
  - 内容质量失败只允许拆分一次；子场景结果保留父场景 ID、父失败原因和父尝试次数，不递归调用。
  - TDD：新增 `test_audiobook_seed_chapter_scene_pipeline.py`，`9 passed`。
- [x] 阶段 3C：`SceneAudioAssembler` 基础装配核心。
  - 按实际解码时长装配 Seed 与上层提供的 legacy 回退音频，场景边界不交叉淡化，并输出场景时间轴、来源和带场景偏移的定时字幕条目。
  - 支持 mp3/wav/m4b 最终原子导出；两遍 FFmpeg `loudnorm`、单次有损编码和响度报告已接入。定时字幕条目已桥接现有字幕文件生成器和生产保存链路；阶段 3J 已补齐无时间戳字幕的 ASR 时间轴数据通路，真实时间戳型供应商契约仍需灰度验证。
  - TDD：`test_audiobook_seed_scene_assembler.py` 当前 `8 passed`，覆盖真实 WAV 装配、长短边界、Seed 毫秒时间戳、字幕偏移、回退音频、两遍命令、PCM 中间产物与异常测量拒绝。
- [x] 阶段 3D：显式 `seed_scene` 双入口薄接入。
  - 新增共享 `SceneRenderMixin`，`generate_chapter_audio()` 与 `generate_chapter_audio_from_script()` 都在剧本质量闸门、章节节奏和角色音色确定后、旧 TTS 开始前调用同一 `_try_generate_seed_scene_chapter()`；`legacy_stems` 与当前未启用的 `auto` 返回 `None`，完整保留旧流程。
  - 项目音频配置新增严格枚举 `audio_engine_mode`；前端“叙事与音频”卡片新增“分轨合成 / 场景生成”分段控件，项目加载恢复、生成前保存和后台运行态读取已经贯通。默认值固定为 `legacy_stems`。
  - Mixin 为失败场景只选择其 `source_segment_indices` 调用现有 TTS 与 `AudioMixer`；随后按实际片段时间轴筛选、重定位并裁剪该场景有源片段锚点的 SFX/BGM，先音效后配乐生成完整局部回退文件，再交给 assembler。成功 Seed 场景和无法确定归属的全章素材不会被重复叠加。
  - 成功章节继续复用现有输出路径、任务完成、字幕文件入口和下载保存；Seed 定时字幕直接桥接，缺少定时字幕的场景使用场景实际起止与完整审定文本作为保守字幕。
  - 场景检查点已进入后台 run checkpoint；每个场景完成后通过主事件循环线程立即提交，并按 `scene_id` 增量合并。通过的 Seed 场景、终态失败决定、既有拆分拓扑和完整 fallback artifact 均可恢复；同循环 WebSocket 任务会在章节流程内等待和回收。
  - TDD：新增数据库增量合并、渲染线程回调切换、累积快照转发和双入口透传覆盖；相关运行时、Mixin 与临时片段回归 `61 passed`。
  - TDD：局部回退新增全章时间线筛选、实际时间重定位、持续时间裁剪和 SFX/BGM 顺序覆盖；场景 Mixin 当前 `9 passed`。
  - 真实 API：默认跳过的 `test_audiobook_seed_scene_real_api.py` 已显式运行，短旁白场景从真实 Seed Audio 生成，经字幕质量闸门、检查点、落盘和 WAV 装配，`1 passed in 27.99s`。
- [x] 阶段 3E：Seed Audio 按秒用量与积分链路。
  - renderer v2 对每次成功供应商响应累计 `original_duration` 和请求标识，同时立即追加到 run 级 `provider_attempts.jsonl`；重试、父场景失败和拆分子场景均纳入按 request ID 去重的章节汇总。
  - `seed_scene` 预检按预计朗读时长与统一 Seed 费率解析器计算，三个生成/恢复入口均使用同一计费上下文，冻结金额直接采用预检结果。
  - 章节产物记录 `pricing_status`、`pricing_source`、`price_per_minute_yuan`、`price_per_second_yuan`、`billable_duration_s`、`provider_request_count` 和 `actual_cost_yuan`，并复用现有项目结算与失败释放。
  - 用户价固定按公开后付费 ¥1/分钟；旧每分钟/每秒覆盖变量不再改变用户冻结与结算。实际采购套餐仅进入供应商成本与毛利；线性折扣使用现有配置，含额度/超额价的套餐待采购档案接入。
  - 独立不可变的场景计费账本表仍待运营审计决策；当前 provider attempt ledger 和检查点已具备后续补账所需的请求 ID 与时长证据。
- [x] 阶段 3F：场景级实时进度闭环。
  - 后端场景开始和每个检查点完成后向专用有声书房间推送 `scene_rendering`，不包含 Prompt、reference 或密钥；场景持久化回调同步把章节 run 阶段更新为 `scene_rendering`。
  - 前端 WebSocket service 已支持 `join_audiobook` / `leave_audiobook`、项目切换、断线重入和独立取消订阅；有声书页面仅在存在焦点任务时订阅。
  - `0-100` 事件进度在单一适配器中归一化为页面 `0-1` 阶段进度；收到场景证据后动态用“场景生成”替换“TTS 合成”，旧 `legacy_stems` 页面不变。Socket 失败继续由 SSE/轮询兜底。
  - 2026-07-21 联调曾出现 API 成功入队、旧 Celery worker 随即报 `cannot import name 'get_audio_engine_mode'`。根因是 Uvicorn 已热重载当前源码，而从更早时间启动的 worker 仍缓存旧模块，并非 Seed Audio 或 Redis 失败。开发启动脚本现会先关闭旧 worker，再用 `audiobook@%h` / `dreamweaver@%h` 唯一节点名启动；任务代码变更后必须重启 worker。
- [x] 阶段 3G：剧本审定与场景渲染两阶段交互闭环。
  - 首次点击固定创建 `script_only` 任务；`seed_scene` 在这一阶段参与分析、改编、审稿和渲染就绪度设计，但不调用 Seed Audio。正式音频调用点是用户批准剧本后触发的 `/projects/{id}/generate-audio-from-scripts`，后台读取项目 `audio_config.audio_engine_mode`，在旧逐句 TTS 前优先进入 `_try_generate_seed_scene_chapter()`。
  - 配置页主操作改为“生成本章场景剧本”，流程状态按当前阶段显示“生成场景剧本 / 审阅场景剧本”或“生成场景音频 / 音频完成”，避免把剧本准备误解为已经执行 Seed Audio。
  - 剧本编辑器只负责保存和批准，不再从编辑器内部绕过完成页直接创建音频任务；批准后刷新项目摘要，由剧本完成页统一触发第二阶段，保证计费预检、引擎标识和任务状态只有一个明确入口。
  - 剧本完成态已从音频完成态拆开：只展示剧本章节、片段、自动评审、批准状态，以及审阅、批准和生成场景音频入口；播放器、导出、下载、收藏、音频评分和 Prompt/Audio 验收只在真实音频完成态出现。
  - 历史项目或刷新页面时，不再用“存在 `ChapterAudio` 数据行”等同于“存在可播放音频”；只有非空 `audio_path` 才进入音频完成态，纯剧本项目会恢复到剧本审阅页。
  - 项目详情摘要补充 `segment_count / dialogue_count / narration_count / character_count / generation_time / tts_cost`，剧本页无需逐章额外请求即可显示与当前阶段有关的统计。
  - TDD：前端全量回归 `155 files / 773 tests passed`；项目摘要、运行时模式、章节场景流水线和 Scene Mixin 聚焦回归 `30 passed`。
- [x] 阶段 3H：剧本模式定向生成与评审。
  - `background_jobs_scripts` 在调用 `prepare_chapter_script()` 前读取并应用项目 `audio_engine_mode`；模式同步进入 `AudiobookScriptAgent` 和 `AudioQualityReviewer`，不再只在第二阶段音频任务中生效。
  - `ScriptSegment[]` 继续作为唯一台词事实源，不生成两份不同台词。分流发生在分析、渲染指导、审稿、就绪度和执行策略：`legacy_stems` 强调独立 TTS 单元、可匹配素材、时间锚点和混音参数；`seed_scene` 强调连续声学空间、音乐生命周期、动作/对白相对时序、非语言人声和场景边界。
  - `seed_scene` Prompt 只把 `seed-audio-1.0` 定义为主生成模型；用户选择的逐句 TTS 只用于试听参考音色和局部回退，避免同时向 LLM 注入 Qwen/CosyVoice 主模型合同。
  - LLM 审稿新增模式合同；确定性 `render_readiness` 对 Seed 检查场景上下文、事件相对时序和音乐生命周期，对分轨模式检查音效可执行参数。该诊断进入 `audio_balance`，当前不修改既有总分公式，避免历史项目被新规则突然阻断。
  - `script_only` 场景剧本准备阶段不再调用本地 `SoundEffectDesigner` / `MusicComposer` 生成素材或分轨时间线，只保留剧本声音事件计数；正式音频阶段仍准备分轨时间线，保证 Seed 失败场景的局部 `legacy_stems` 回退保留 SFX/BGM。
  - `ScenePromptCompiler` 新增场景状态事件、相同场景/配乐去重、音乐停止/切换语义，以及音效 `delay/fade/duration` 的自然语言编译；先于台词和持续环境事件会真实排在台词之前，不再出现序号与文字锚点矛盾。
  - TDD：本阶段模式贯穿、Prompt、审稿、就绪度、素材执行边界、Seed 编译器和局部回退聚焦回归 `201 passed`；全部有声书测试在工作区临时目录约束下为 `632 passed / 4 skipped / 1 deselected`。
- [x] 阶段 3I：生产链路一致性、成本与恢复修复。
  - [x] 将 `ScenePromptCompileResult.events` 中的 `vocalization` 文本写入 `SceneRenderPlan.expected_vocalizations`，并由 renderer 透传给质量闸门；端到端回归确认声明喘息不再误判。
  - [x] 复用同签名终态 `legacy_stems` 决定，并为完整局部回退建立带路径、大小、SHA-256 和计划签名的 `fallback_artifact`。
  - [x] 建立追加式 provider attempt JSONL ledger；供应商成功响应后立即持久化，以 request ID 跨实例幂等并作为章节费用优先事实源。
  - [x] 在章节 factory 显式注入现有 ASR provider；区分未配置、provider 失败和台词质量失败，ASR 缺失不再重复调用 Seed。
  - [x] 新增严格 `seed_audio_model` 项目配置，贯通生产 mixin、adapter、pipeline、checkpoint、provider ledger 和 billing summary；multilingual 真实调用仍作为上线前契约项。
  - [x] 最终评审改用源片段 `audio_presence`，不再同时读取全部场景音频 bytes；整章 bytes 因当前返回合同仍保留一份。
  - [x] ScenePlanner 使用增量 Prompt 成本和 reference 门控，接近预算才完整编译候选，最终计划仍执行完整编译。
  - [x] 集中质量阈值并生成 `quality_policy_hash`，写入 Seed checkpoint 和 fallback artifact；同循环进度任务在章节流程内统一等待和回收。
- [x] 阶段 3J：Seed/ASR 逐句时间轴规范化与恢复接线。
  - [x] 修复正式 Seed `start_time/end_time` 毫秒被按秒解释，以及同层整段 `text` 遮蔽 `sentences` 的字幕偏移错误；统一规范化为 `start_ms/end_ms`。
  - [x] 扩展 `PromptAudioAsrResult`，显式携带规范化 `subtitle_payload`；MiMo、阿里云和豆包适配器共享同一解析合同。
  - [x] 无时间戳供应商字幕只调用声明支持时间戳的 ASR；ASR 时间轴必须再次通过台词质量闸门，失败时保留已验证的供应商文本。
  - [x] Seed 临时音频 URL 只在当前 ASR 调用中透传，不进入 checkpoint；旧 passed checkpoint 可直接对既有落盘音频补时间轴，不重新调用 Seed。
  - [x] 真实 MiMo 探测确认 `mimo-v2.5-asr` 只有 transcript、没有 timed segments，已加入能力门控；`fun-asr-flash`（DashScope）时间戳型真实契约已于 2026-07-22 验证（本地 base64、SSE、`segments[]` 毫秒时间戳）；阿里云 `paraformer-v2` 与豆包 `volc.bigasr.auc` 的公网 URL 成功路径已于 2026-07-24 完成真实验证，异常/成本灰度仍待完成。
- [x] 阶段 3K：Seed Audio 正式基础费率。
  - [x] 根据后付费控制台确认用户公开价为 ¥1/分钟，代码、预检、实际汇总和模型目录使用同一秒价。
  - [x] 用户价不再接受采购费率覆盖；`pricing_source=volcengine_public_postpaid`，`pricing_basis=public_list_price`。
  - [x] 实际采购套餐不按任务用量自动跳档，只通过供应商折扣配置影响平台实际成本与毛利。
- [x] 阶段 3L：豆包系统/复刻音色 `speaker` 契约收敛。
  - [x] 复核《豆包语音_音色列表》与 Seed Audio HTTP 契约：`speaker` 可使用豆包语音合成 2.0 系统音色或声音复刻音色；`speaker`、`audio_data`、`audio_url` 严格三选一。
  - [x] 正式章节 resolver 与独立测试单元继续按规范化模型归属识别豆包 `speaker`，优先级高于已有试听 URL/Base64；仅用户自有设计/复刻音色和已审核公共池可物化为音频 reference。
  - [x] 修复 `SeedTTSVoiceManager` 将目录外复刻 ID 静默替换为默认 `vivi` 的问题；显式不透明 ID 现在贯穿 `voice_id`、`tts_speaker_id` 和最终 TTS 参数，由豆包账号侧校验。
- [x] 阶段 3M：公开价单源与章节结算正确性。
  - [x] 九个有声书 TTS 的公开价统一收敛到 `tts_model_ids.py`；运行时 `TTSEngine`、模型目录和积分预检不再维护第二套价格判断。
  - [x] MiMo 三个 TTS 明确标记为 `limited_time_free`，允许生成且预计费用、积分和冻结均为 0；未知价格仍不得伪装成免费。
  - [x] 角色级混用模型按主引擎和所有子引擎聚合字符、调用、缓存、失败及分模型成本；普通章节按生成前后快照差额结算，避免连续多章重复累计。
  - [x] Seed 场景总成本按 `Seed Audio original_duration + 本章局部回退 TTS` 计算，并保存三项成本组成；项目汇总优先读取结构化 `estimated_cost_yuan`，兼容 `¥/￥/$` 旧展示字符串。
- [x] MiniMax、StepAudio、豆包复刻固定费用已作为模型价格元数据登记；音色生命周期账本载体已落地（`voice_asset_billing_ledger` 表 + 仓储 + 幂等键 + 扣费凭证字段，TDD `7 passed`），以幂等键登记创建/试听/正式成功/首次使用事件，只登记不自动扣费；实际计一次的口径与失败是否计费仍待运营决策，凭证齐备后经 `mark_charge_settled` 落地，禁止每章重复收取。
  - [x] 新增后端复刻 ID 保真测试、resolver 三选一路由测试和前端绑定契约测试；静态系统音色目录不再承担复刻 ID 白名单职责。
- [x] 阶段 3N：用户公开价倍率锁定与经营成本分层。
  - [x] 有声书预检、正式冻结、最终结算、用户中心成本汇总和经营快照统一忽略通用 `user_price_rate`，有效倍率固定为 `1.0`；短剧与资产中心保持现有策略。
  - [x] 供应商折扣只进入 `supplier_discounted_cost_yuan`、平台毛利和毛利率，不再改变有声书 `user_billed_yuan`。
  - [x] MiniMax HD 公开价回归统一为 ¥3.5/万字符，冻结 10,000 字在 100 积分/元、10% 冻结缓冲下为 385 积分，最终结算仍为 350 积分。
  - [ ] 录入实际订阅档位、成交价、周期额度和超额价格；在资料补齐前供应商实际成本继续按公开后付费价保守估算。
- [x] 阶段 3O：MiniMax Speech 2.8 百炼音色复刻接入。
  - [x] HD/Turbo 共用严格模型白名单，按百炼 `input.action=voice_clone` 合同上传授权 mp3/wav、传递逐字稿并创建真实 `voice_id`；供应商试听支持 hex、Base64 和 URL 三种返回形式。
  - [x] 复刻元数据按 `owner_user_id` 隔离持久化，不保存临时 `audio_url` 或大段音频编码；当前用户的音色合并进 `/tts/voices`，可直接进入角色音色映射和正式 TTS。
  - [x] 自定义 `mmx_` 音色不再被静态系统音色白名单替换；正式合成失败时禁止静默回退到无关系统音色，避免角色声线悄然改变。
  - [x] 前端在真实创建请求前展示收费确认：HD 试听 ¥3.5/万字符、Turbo 试听 ¥2/万字符，首次正式使用另收 ¥9.9/音色；固定解锁费仍不自动冻结或结算，等待音色生命周期账本。
  - [x] 本系统“移除”只删除当前用户的本地登记，不声称删除百炼账号云端音色；供应商删除合同补齐前不提供伪云端删除能力。
- [x] 阶段 3P：用户参考音色隔离与公共音色池基础闭环。
  - [x] 数据库迁移 `add_user_voice_public_pool` 已执行：`voice_reference_assets` 增加 owner、授权人/依据、撤销人/原因和清理状态；新增 `voice_pool_publications`、`voice_pool_ratings`。
  - [x] 用户敏感资产 ID 纳入 `owner_user_id`；`user_recording/provider_preview/user_generated_voice` 缺少 owner、授权人、授权依据、版本或时间时 fail-closed。MiMo、StepAudio、MiniMax 和新建 CosyVoice 自定义音色均按当前用户登记/过滤；无法确认 owner 的历史 CosyVoice 条目默认隐藏。
  - [x] 设计/复刻音色标准参考试听使用 `voice-reference-preview-v1` 与固定约 8-12 秒文本。缓存未命中时第一次请求只返回公开后付费报价，`confirm_cost=true` 后才调用模型；成功音频上传 OSS 并登记幂等 preview 账本。
  - [x] 公共池采用主动发布、`pending_review -> published` 审核、所有者幂等撤回和低分自动下架；阈值为评分数至少 10、低分至少 8、低分比例至少 80%、平均分不高于 2.0。
  - [x] 私有设计/复刻创建时不强制填写公共分类，避免阻塞不打算公开的用户；主动公开时才必填公开名称、性别感、年龄感、主要风格、语言、1-5 个音色质感、1-5 个适用场景、权利依据、许可版本和确认时间。
  - [x] 原始复刻录音不能直接发布；客户端不再提交公共 URI，后端只从 `voice-reference-preview-v1` 标准衍生资产取得可信 OSS 地址。
  - [x] 项目创建与音频生成前分别校验私有 owner/撤销状态和公共 `published` 状态；其它供应商官方系统音色试听不再自动进入 Seed reference。前端场景模式已合并豆包原生、我的参考音色和公共池音色，并提供生成确认、发布与评分入口。
  - [x] 运营决策：公共音色当前免费共享，不按调用向贡献者分成；使用公共音色不增加音色授权费，但消费者仍按正常 Seed Audio 输出时长承担有声书生成费用。后续只通过显式活动配置排行奖励，不追溯自动奖励历史使用。
  - [x] 上线前全部历史设计/复刻测试音色已按确认 manifest 清理；数据库、本地索引/音频和供应商云端均已执行零残留验证，测试路由数据库隔离复核通过。
  - [ ] 正式开放剩余项已在 §12-14 完成实施级规划：管理员审核工作台、许可文本、举报申诉、真实用户原始录音与派生缓存硬删除、公共发现扩展、活动排行和滥用治理；OpenAPI、评分正确性和集中状态机已经完成。
- [ ] 阶段 3Q：公共音色池正式开放。
  - [x] Q0 技术阻断：`AutoMergeRequest` 已移入公共 settings schema；直接 `app.openapi()` 与组合 ASGI `/openapi.json` 回归通过；评分只允许 `published` 且禁止所有者自评；集中状态机、非法转换、重复审核和并发旧快照覆盖测试通过。
  - [ ] Q1 合规与治理：发布 `voice-pool-license-v1` 正式文案、管理员审核工作台、审核事件账本、举报/申诉与紧急暂停。
  - [x] Q2a 测试数据盘点：只读 dry-run 与精确 manifest 已落地，覆盖数据库、本地索引/音频、OSS 候选和 CosyVoice 云端 ID；全部操作受工作区路径、ID 白名单、SHA-256 和 manifest 指纹约束。
  - [x] Q2b 一次性测试数据清理：经独立危险操作确认后，已按 manifest 清除数据库、本地音频/索引和 CosyVoice 云端测试音色，并完成数据库、本地和供应商三层零残留验证；未开发历史 owner 认领功能。
  - [ ] Q2c 真实用户数据权利：接入面向正式用户的可恢复硬删除任务、OSS/本地缓存安全删除和供应商云端删除状态机。
  - [ ] Q3 发现与灰度：服务端分页、标签筛选、排序、聚合统计和受邀用户灰度；免费共享期先积累合格使用事实，不发积分。
  - [ ] Q4 活动引流：单独启用活动、排行快照、反作弊、审核冻结和幂等奖励；默认关闭，不与公共池基础可用性绑定。
- [ ] 阶段 3：章节主链路 `seed_scene` 集成。
  - 双入口、运行时模式、局部 fallback、字幕桥接、检查点、响度、场景进度、按秒计费、保存和下载骨架已经接通；默认逐段 TTS、音效、配乐和混音行为保持不变。
  - 阿里云/豆包时间戳成功路径、统一超时和单场景调用/金额预算已完成；尚需 ASR 临时 URL/限流/超时等异常分布、授权资产和整体灰度（`multilingual` 真实接口契约与 `fun-asr-flash` 时间戳契约也已验证）；这些完成前阶段 3 仍标记为实施中。
- [ ] 阶段 4：`auto` 路由与灰度。

当前核心验证命令：

```powershell
$env:TMP=(Resolve-Path ".test-tmp").Path
$env:TEMP=$env:TMP
& ".venv/Scripts/python.exe" -m pytest -q -p no:cacheprovider `
  "backend/tests/test_audiobook_seed_scene_audio_analysis.py" `
  "backend/tests/test_audiobook_seed_scene_planner.py" `
  "backend/tests/test_audiobook_seed_scene_preview_reference_asset.py" `
  "backend/tests/test_audiobook_seed_scene_prompt.py" `
  "backend/tests/test_audiobook_seed_scene_quality_gate.py" `
  "backend/tests/test_audiobook_seed_scene_renderer.py" `
  "backend/tests/test_audiobook_seed_scene_provider_attempt_ledger.py" `
  "backend/tests/test_audiobook_seed_scene_test_unit.py" `
  "backend/tests/test_audiobook_seed_chapter_scene_pipeline.py" `
  "backend/tests/test_audiobook_seed_scene_assembler.py" `
  "backend/tests/test_audiobook_seed_scene_engine_mixin.py" `
  "backend/tests/test_audiobook_runtime_truth.py" `
  "backend/tests/test_temp_segment_store.py" `
  "backend/tests/test_points_task_precheck.py" `
  "backend/tests/test_audiobook_task_support_billing.py" `
  "backend/tests/test_user_center_billing_events.py" `
  "backend/tests/test_audiobook_seed_scene_billing_wiring.py"

Set-Location "frontend"
npm.cmd test -- --run `
  "src/services/__tests__/websocket.test.ts" `
  "src/pages/audiobook/__tests__/audiobookSceneProgress.test.ts" `
  "src/pages/audiobook/__tests__/stageUtils.test.ts" `
  "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts" `
  "src/pages/audiobook/__tests__/projectSelectionLoader.test.ts" `
  "src/pages/audiobook/__tests__/setupStepSource.test.ts" `
  "src/pages/audiobook/__tests__/seedSceneReferenceUtils.test.ts" `
  "src/pages/audiobook/__tests__/seedSceneTestReviewUtils.test.ts" `
  "src/pages/audiobook/__tests__/ttsPromptTestUnitSource.test.ts"
npm.cmd run type-check
npm.cmd run lint
npm.cmd run build
```

最新验证结果（2026-07-24）：一次性测试音色清理后，`voice_reference_assets`、`voice_pool_publications`、`voice_pool_ratings`、`voice_asset_billing_ledger` 均为 0，清理 manifest 的数据库、本地、OSS、供应商和阻断计数均为 0；6 个 CosyVoice 云端 ID 经 `query_voice` 逐一确认不存在。清理、CosyVoice、TTS 目录和 MiMo/StepAudio 隔离相关合并回归为 `97 passed`，其中 MiMo/StepAudio 路由测试 `24 passed` 后再次确认开发 PostgreSQL 未产生测试记录。随后完成 P0 正确性修复：`AutoMergeRequest` 移入 `app.schemas.settings`，直接 `app.openapi()` 和经 Socket.IO 组合 `application` 请求 `/openapi.json` 均通过；评分仅接受 `published` 并禁止所有者自评；`voice_pool_state.py` 成为唯一状态转换事实源，审核采用条件更新阻止并发旧快照覆盖。ASR 默认从无时间戳 MiMo 调整为已验证的 `fun-asr-flash`，章节结果保留经过过滤的 provider/model/request ID/usage，明确丢弃 `raw_output`；ASR 失败只调用一次 Seed 和一次 ASR 后局部回退；豆包 ASR 复用项目已配置的 `VOLCENGINE_OPEN_SPEECH_API_KEY`，不混用火山方舟通用 Key。阿里云首次真实探测暴露异步结果 URL 未下载问题并已修复；豆包 HTTP 400 经官方合同定位为 Request ID/header/body/query 结构错误并已修复，两家使用同一公共 OSS 系统试听的公网 URL 成功路径均已验证。四条公开价格和单场景调用/成本/超时策略已接线，ASR 尝试按实际时长跨 Seed 重试聚合且 checkpoint 恢复不重置预算。OpenAPI、公共池、ASR provider/价格、探测脚本、renderer 与章节注入聚焦回归为 `87 passed`。本次三次复测升级另完成后端 Seed 测试单元与全应用 OpenAPI `16 passed`；空白页兼容修复后的前端独立测试入口、评审存储和响应规范化为 `12 passed`，`npm.cmd run type-check` 与 `npm.cmd run lint` 通过。随后缓存路径修复的后端独立单元为 `18 passed`，全应用 OpenAPI 为 `2 passed`；前端超时提示、响应规范化和评审存储聚焦回归为 `8 passed`，类型检查和 ESLint 再次通过。12 份现有清单的 5 份 Docker 路径和 7 份 Windows 路径均映射成功；容器内当前 `r1` legacy manifest 只读解析为 `cache_readable=true / audio_exists=true`。Docker 后端再次单独重启后 `/health` 返回 200，容器超时变量为 `600`，OpenAPI 保持 `sample_index/sample_id/billing` 三个字段，启动日志无异常；本次缓存路径修复、验证和重启没有调用真实 Seed API。三次复测联调期间已经发生新的 `r1` 调用和一次状态未知的 `r2` 超时，不能把整个联调阶段描述为“只复用历史样本”。公共列表仍以 `.all()` 全量读取并逐条查询评分摘要；ASR 临时 URL 有效期与异常分布仍待灰度。

2026-07-25 真实 ASR 补充样本：使用仓库已有的非用户合成旁白，通过幂等缓存键上传到项目 OSS 后，对同一稳定公网 MP3 各调用一次阿里云 `paraformer-v2` 与豆包 `volc.bigasr.auc`。阿里云在 `3.779s` 返回完整转写、单段 `9240-15320ms` 时间轴和 `15.336s` usage；豆包在 `3.129s` 返回等价转写、单段 `9710-14750ms` 时间轴和 `15.335s` usage。按公开后付费价估算分别为 `¥0.001227` 与 `¥0.009797`。同日使用约 `0.39s` 的公共领域非语音 OGG、每家 `45s` 查询预算各探测一次，两家均终止为 `asr_provider_timeout`，且没有自动重试或重新调用 Seed；该样本证明极短非语音输入可能占满候选 provider 轮询预算，不能把“无台词”假设为快速 `asr_empty_transcript`。超时任务是否产生供应商费用仍须以账单凭证为准，不从失败响应猜测。公共发现接口同期改为默认 `50`、最大 `100` 的稳定游标分页，并将当前页评分摘要改为单次 grouped aggregate，已消除 `.all()` 和逐条评分 N+1；后端公共池/OpenAPI `23 passed`，前端类型检查通过，工作台加载更多交互尚未接入。

下载中断专项验证（2026-07-24）：`SceneRenderService`、独立测试单元和全应用 OpenAPI 合并回归为 `54 passed`；前端超时/下载错误提示、旧响应规范化和评审存储为 `10 passed`，TypeScript 与 ESLint 通过，`git diff --check` 无空白错误。`novel_backend` 已单独重启，容器内只读确认默认 `max_download_retries=2 / download_retry_backoff_s=0.25`，`/health` 返回 200；PostgreSQL、Redis、前端和数据卷未重启。该修复与验证没有调用真实 Seed API，也没有自动重试失败的 `r2`。

此前基线继续有效：2026-07-23 公共池、参考资产、用户隔离、场景 resolver/物化和模型路由相关后端扩展回归为 `141 passed`；前端全量为 `156 files / 778 tests passed`，`npm.cmd run type-check`、`npm.cmd run lint` 和 `npm.cmd run build` 均通过。2026-07-22 的后端全量基线为全部 `test_audiobook_*.py` `683 passed / 4 skipped`、`backend/tests` `1534 passed / 5 skipped`，2026-07-24 未重复执行全量后端。Seed Audio 用户费率事实源为 `volcengine_public_postpaid`，固定 `¥1.0/分钟` 和 `¥0.0166666667/秒`；九个 TTS 的用户价来自 `tts_model_ids.py` 公开价目录。有声书在全局 `user_price_rate=0.8` 的回归场景下仍按 `1.0` 倍率完成预检、冻结和结算。真实凭证现已覆盖 `seed-audio-1.0-multilingual`、`fun-asr-flash`、阿里云 `paraformer-v2` 和豆包 `volc.bigasr.auc` 的成功接口契约；整体灰度和 ASR 异常分布仍待完成。当前虚拟环境未安装 `ruff`，未执行 Ruff。

---

## 9. 分阶段实施计划

### 阶段 0：真实接口契约与 A/B 基线

- 验证两个模型 ID、references 三种载荷、3 条上限、字幕结构、Base64/URL、格式、120 秒/3000 字符错误行为、鉴权、限流、计费字段和临时 URL 下载。
- 选择五类真实章节场景：用户样例对应的多人压迫动作、电话对话、三参考音色争吵、单人情绪独白，以及额外的纯旁白基线。
- 每类比较三条路径：现有链路、只把音效改为 Seed Audio 的过渡方案、Seed Audio 场景统一生成；每条路径独立生成 3 次，避免以一次偶然结果决策。
- Seed Audio 场景统一生成内部再区分三种声音身份：无 reference 的文字描述、Seed-TTS 2.0 原生 `speaker`、跨供应商 `audio_data`。三者不能混成一个“reference 样本”统计。
- 产出接口契约样本、盲评结果、台词完整率、P50/P95 时延、调用/重试/成本基线和是否继续的决策记录。

### 阶段 1：适配器与参考音色资产

- 先以测试驱动扩展 `DoubaoSeedAudio10Adapter`：模型选择、references 校验、字幕和 Base64/URL 响应、请求标识、可重试错误分类。
- 建立稳定参考音色资产接口，打通 Seed `speaker`、用户上传参考和其它 TTS 统一中性试听片段；PoC 运行时物化层已完成，生产级授权资产表尚未实现。
- 修复 `text_to_audio` 计费预估；真实调用仍只在显式集成测试中执行。

### 阶段 2：场景计划、提示词编译与质量闸门

- 实现 `ScenePlanner`、`VoiceReferenceResolver`、`ScenePromptCompiler`、签名和静态计划校验。
- 实现字幕/ASR 对齐、音频技术检查及“重试一次 → 拆分一次 → 回退”的有限状态机。
- 以用户示例提炼提示词规则和回归断言，但测试不得依赖 LLM 文本完全一致。
- 在正式章节接入前补齐语义切分优先级；第一版现有字段规则已经完成，正式时间/地点、故事节拍、禁止切点关系和边界回溯仍不能跳过，也不能直接把 `auto` 设为默认。

### 阶段 3：章节级 `seed_scene`

- [x] 实现并验证 `SceneRenderService` 单场景核心。
- [x] 扩展生产检查点签名，纳入 schema、renderer、模型和合并后的 `audio_config`；旧检查点严格失效。
- [x] 实现 `ChapterScenePipeline` 领域核心和拆分一次后单场景回退的有限状态机。
- [x] 实现 `SceneAudioAssembler` 基础核心、实际时长字幕偏移、边界留白和最终原子编码。
- [x] 为装配器接入两遍 FFmpeg `loudnorm`，使用 PCM 中间产物、单次有损编码、原子替换和可检查的测量报告。
- [x] 将定时字幕桥接到现有 SRT/VTT/ASS/Audacity Labels 产物链路。
- [x] 为无时间戳字幕接入规范化 ASR 逐句时间轴，并对时间轴单独执行台词一致性检查；`fun-asr-flash`、阿里云与豆包成功路径真实契约均已验证，异常和成本继续作为灰度项。
- [x] 在章节薄接入层为 `legacy_stems` 场景生成局部 TTS，并按实际片段时间轴筛选、重定位、裁剪 SFX/BGM 后回填 assembler。
- [x] 同时接入“完整生成”和“已有剧本生成音频”两个入口，并完成项目模式 API 与前端显式开关。
- [x] `script_only` 阶段按 `audio_engine_mode` 生成模式化分析、改编指导、审稿和渲染就绪度，同时保持共享台词事实源。
- [x] 完成场景尝试/回退原因、父子拆分关系、质量策略、章节 checkpoint、终态失败决定、完整 fallback artifact 和 provider attempt ledger 的生产恢复闭环。
- [x] 接入场景级 WebSocket 进度、前端专用房间订阅和动态“场景生成”阶段；总任务仍兼容复用 TTS 阶段。
- [x] 接入预计时长积分冻结、`original_duration` 实际用量、章节成本汇总、结算和失败释放。
- [x] 核实并配置生产用户基础费率：公开后付费 ¥1/分钟；实际采购套餐只更新供应商成本与毛利，不覆盖用户费率；复杂套餐待采购档案接入。
- [ ] 根据运营审计要求决定是否把 run 级 provider attempt JSONL 升级为数据库不可变账本表。
- [x] 运行两个新入口及 `legacy_stems` 自动化回归，覆盖 vocalization 豁免、ASR 注入、回退恢复、provider request 幂等、模型路由、质量策略失效和长章节评审内存；首轮仍仅对测试项目开放，默认仍为 `legacy_stems`。

阶段 3 完成定义：同一章节在两个入口得到一致的场景计划；`vocalization` 不被质量闸门误判；任一场景失败只回退该场景；进程中断后只重做签名变化、明确可重试错误或用户显式重生成；回退音频可复用且 provider attempt 不重复计入；模型、质量策略、章节字幕、音频、任务、积分和下载产物均可追踪；关闭实验模式后行为与现有链路一致。

### 阶段 4：`auto` 路由与灰度

- 启用按场景路由和自动回退，记录每种路由的质量、成本、时延和失败原因。
- 验收指标稳定后将新项目默认切到 `auto`；`legacy_stems` 始终保留为显式回退。
- 是否停用 Vidu/Mureka 另行决策，不能与 Seed 场景引擎上线绑定。

---

## 10. 测试计划

### 10.1 自动化测试

- **单元**：ScenePlanner 的时长/字符/reference/禁止切点和语义边界优先级；VoiceReferenceResolver 的 Seed 原生 speaker、跨供应商 ID 隔离与资产顺序；PreviewReferenceMaterializer 的缓存身份、Base64/URL、大小/时长、技术校验、哈希和原子落盘；ScenePromptCompiler 的台词逐字保留、顺序、`@音频N` 映射、reference 模式不重复静态音色、字符预算和停顿去重。
- **适配器契约**：扩展 `tests/test_doubao_audio_generation_adapter.py`，覆盖 speaker/audio_data/audio_url 互斥、最多 3 条、两个模型 ID、字幕、Base64/URL、请求元数据和错误分类。
- **质量闸门**：覆盖标点差异、同音字、漏句、增句、乱序、字幕缺失、ASR 回退、空音频、截断、削波和有限重试状态机。
- **集成**：mock 场景渲染器返回固定音频/字幕，验证任务阶段、场景进度、积分冻结/结算/释放、原子落盘、模型/配置变更使检查点失效、拆分一次、单场景回退和章节字幕偏移。
- **vocalization 端到端**：从 Prompt 编译事件生成计划豁免集合，经过 renderer 传给质量闸门；包含“啊/嗯/喘息/哽咽”的场景不被判为 `extra_lines`，未声明的完整台词仍失败。
- **恢复与成本**：回退场景重启复用 `fallback_ready` 产物；provider request ID 重放不重复写入成本 ledger；只有签名变化、用户显式重生成或冷却后的可重试错误重新调用 Seed。
- **ASR 与模型路由**：注入 mock ASR 后无字幕场景可完成闸门；未注入时返回明确 `needs_asr`；运行时选择的模型同时出现在 adapter 请求、检查点和 billing summary。
- **性能与资源**：Planner 长章节基准验证增量估算不会改变最终计划；最终评审不同时构造整章和所有场景的 bytes；质量策略 hash 变化会使旧 checkpoint 失效；进度 callback 异常不会产生未回收任务。
- **装配**：验证场景边界停顿、禁止对白重叠、字幕偏移、输出格式和只编码一次的主路径；真正 LUFS 处理使用可检查的工具输出测试。
- **回归**：`legacy_stems` 的完整生成、已有剧本生成、试听、字幕、导出、断点续作和前端进度行为不变。

真实网络测试必须显式标记，不进入默认单元测试；运行前展示预计调用次数和成本，并避免使用生产项目数据。Windows PowerShell 下禁止用默认文本管道把含中文的 here-string 传给 `python -`；应从 UTF-8 文件读取，或通过 Unicode 环境变量传递，并在请求前记录 Prompt 字符数和中文字符数。

### 10.2 人工盲评

固定五类场景，每类同时生成“描述音色 A”和“reference 音色 B”两条路径，每条路径各 3 个独立结果，总样本数为 `5 类 × 2 路径 × 3 次 = 30`。随机隐藏模型、路径与文件名，A/B 必须逐字共享同一台词，只改变声音身份输入方式。至少评价：

当前独立页面已经完成 30 个固定槽位和内容绑定样本 ID，但同一操作者在生成样本 B 前需要配置 reference，因此只能视为**半盲评工具**，不能把路径标签隐藏误报为严格盲评。正式基线必须采用以下任一方式：由配置者完成 30 份生成后交给另一评审者随机试听；或新增只读取既有样本、随机化顺序且不展示 Prompt/reference 配置的评审会话。完成其中一种之前，页面内评审可以用于逐项发现问题，但不能作为严格盲评胜率。

1. 台词是否完整、清楚、容易理解剧情。
2. 角色声音是否可区分且跨场景一致。
3. 情绪是否连续、强弱是否符合剧情。
4. 音效和动作是否同步、是否存在错误或多余声音。
5. 音乐/环境是否遮挡对白，空间关系是否自然。
6. 场景连接是否突兀，停顿是否合理。

声音身份必须单独记录，不与“角色可区分”混为一项：

1. **Seed 原生 speaker 一致性**：与同一 Seed-TTS 2.0 音色试听相比，音色、口音、年龄感和发声方式是否仍是同一个人。
2. **跨供应商 reference 相似度**：与 OSS 试听相比是否相似；该项当前是观测指标，不作为统一场景引擎继续实施的阻断条件。
3. **场景内稳定性**：同一角色在同一场景不同情绪下是否发生换人式漂移。
4. **跨场景稳定性**：同一声音身份在至少三个场景中是否保持可识别。

首期增加离线声纹观测，但不立即作为生产硬闸门：使用固定版本的 speaker embedding 模型，分别计算“reference 与成品”和“同角色跨场景成品之间”的余弦相似度，保存模型版本、音频片段范围与原始分数。豆包原生 `speaker` 与跨供应商音频 reference 必须分组统计；主角、旁白单独采用更严格的候选阈值。低相似结果进入人工评审，确认发生换人式漂移时将该角色或场景回退 `legacy_stems`。在样本分布和误判率稳定前，不得仅凭 embedding 自动删除成品或重复调用 Seed。

声纹指标只衡量声音身份，不替代情绪、剧情可懂度、台词完整性、音效、配乐、时延和费用评分。跨供应商 reference 相似度不足时不得继续叠加年龄、口音、音高、沙哑度等静态文字音色描述；这会重新定义声音并压过 reference。

评估音色相似度时，测试角色名、性别语义和所选 speaker 应匹配；若故意使用男性 speaker 绑定“女主”等冲突组合，必须单列为“文字语义对 speaker 的干扰实验”，不能计入正常音色得分。

2026-07-25 用户完成 30 个槽位的综合评分和九项评审后的定性结论如下：

1. **reference 路径**：生成音色与被参考音色存在轻微差异，不能把跨供应商 reference 当作精确声音复刻；但同一 reference 在不同批次生成的声音基本相似，说明它更适合作为稳定身份锚点。
2. **描述音色路径**：只要角色描述词保持完全不变，不同批次的声音相似度也较好，说明 Seed 对固定、简洁、稳定的身份描述具有可重复性；这不等于可以在每个场景自由改写描述词。
3. **生产选择**：豆包原生 `speaker` 优先级最高；主角、旁白和长期重复角色优先使用原生 `speaker` 或固定 reference；次要角色和一次性人物可以使用固定描述音色，以控制 reference 准备成本和角色数量。
4. **上线判断**：在场景之间保持可感知响度连续、对白不被音效/配乐遮挡的前提下，人工试听结论支持进入受控生产灰度；当前结论是“可用”，不是“跨供应商音色完全一致”或“无须回退”。
5. **数据边界**：页面评审目前只写浏览器 `localStorage`，用户已确认完成全部评审，但没有形成可供系统读取的逐槽位数值导出。因此本轮不把主观结论伪装成严格盲评胜率、均分置信区间或 embedding 阈值结论。

### 10.3 首期验收门槛

| 维度 | 首期门槛 |
|---|---|
| 台词完整性 | 关键台词缺失 `0`，未声明的额外可辨识台词 `0`，规范化覆盖率 `≥99%` |
| 产物可靠性 | 所有成功响应均在临时 URL 失效前落盘、校验并写检查点 |
| 失败恢复 | 网络错误有限重试；内容失败可拆分；最终可只回退当前场景 |
| 断点续作 | 未变化的成功场景复用率 `100%` |
| 主观质量 | 戏剧化场景平均分不低于 `4/5`，且相对 legacy 至少提升 `0.5/5` |
| 对白清晰度 | 盲评中“音乐/音效明显遮挡对白”的场景占比为 `0` |
| 原生 speaker 一致性 | 三次重复盲评平均不低于 `4/5`，且不得出现无法识别为同一声音身份的样本 |
| 跨供应商音色 | 记录相似度和漂移分布；阶段 0 暂不设生产硬门槛，主角低相似时路由到 `legacy_stems` |
| 场景间响度连续性 | 正式灰度前完成场景级 LUFS 测量和有界增益校准；校准前不得仅以整章 `-16 LUFS` 宣称片段响度一致 |
| 可观测性 | 每场景可追踪 Prompt、references、模型、尝试、质量、成本和回退原因 |

数值门槛是首期决策线，阶段 0 后可按真实字幕误差和盲评分布调整，但不得取消“关键台词零缺失”和“未声明额外台词为零”两条硬要求。

---

## 11. 风险与回退

| 风险 | 影响 | 缓解/回退 |
|---|---|---|
| 3000 字符/120s 限制导致场景过碎 | 连贯性下降、调用数增加 | 45-75s 目标；语义边界优先；模板压缩重复描述；保存前后状态 |
| 最多 3 条 references | 旁白加多人群戏无法全部绑定 | 旁白计入规划；拆场景；临时角色文字描述；无法治理时回退旧链路 |
| 黑盒混合结果漏词/增词 | 剧情错误且无法分轨修复 | 字幕/ASR 强制闸门；有限重试；拆分；单场景回退 |
| 固定静音比例误伤剧情停顿 | 有效的低声环境、长停顿或收尾留白被错误回退 | 接近全静音才作为技术失败；台词完整性由字幕/ASR 单独判定；保留 `silence_ratio` 观测 |
| 音乐或音效压住对白 | 可懂度下降 | Prompt 前景约束；人工盲评；失败场景回退；后续评估源分离检测 |
| 跨场景音色漂移 | 主角身份感被破坏 | 稳定声音身份资产；reference 哈希锁定；未绑定声音不承担主角 |
| 文字音色描述压过 audio reference | 选定音色与成品不像同一人 | reference 模式禁止重复静态音色词；只描述当前表演；低相似主角回退旧链路 |
| 角色名/性别语义与 speaker 冲突 | 错误判断原生 speaker 能力或生成错误性别 | 正式绑定校验角色与音色；冲突组合仅进入独立干扰实验 |
| 跨供应商参考音色授权不清 | 合规与下架风险 | 保存来源与授权范围；用户确认；无授权不生成跨模型参考 |
| 临时 URL 失效 | 音频丢失、续传失效 | 响应后立即原子落盘、校验并计算哈希 |
| 采购套餐变化但采购档案未更新 | 平台实际成本和毛利被高估或低估 | 用户继续按 ¥1/分钟公开价；线性折扣更新供应商折扣配置，复杂套餐更新额度、周期和超额价档案，并记录来源 |
| 当前 dBFS 被误当 LUFS | 平台响度不一致 | FFmpeg loudnorm/等价实现；pydub 仅降级 |
| 成本/时延波动 | 用户等待和预算不可控 | P50/P95 与实际账单观测；auto 路由；并发/重试上限 |
| 新阶段破坏前端进度 | 页面卡在未知状态 | 阶段标签与兼容映射测试；旧模式回归 |

整体回退开关：`audio_engine_mode=legacy_stems`。自动路由还必须支持场景级回退，不能只有整章级开关。

---

## 12. 剩余决策项

1. **模型路由**：普通中文默认 `seed-audio-1.0`；哪些场景触发 multilingual，时间轴提示的官方格式与账号权限是什么。2026-07-22 已完成 `seed-audio-1.0-multilingual` 真实接口契约验证（同步 `/api/v3/tts/create`，约 22s；同时返回临时签名 `url`（`x-expires` 标明有效期）与 base64 `audio`；字幕为 `subtitle.sentences[]`，每句含 `start_time`/`end_time`（毫秒）+ `text` + 逐字/逐词 `words[]`，中文逐字、英文按词切分正确）。**2026-07-22 运营决策：multilingual 变体暂不启用，项目仅开放 `seed-audio-1.0`。** 已在项目路由层收敛：`project_audio_config.py` 保留登记全集 `KNOWN_SEED_AUDIO_MODELS`，但开放集合 `SEED_AUDIO_MODELS` 只含 `seed-audio-1.0`——`set_seed_audio_model` 拒绝 multilingual、`get_seed_audio_model` 对历史配置回退默认；API `ProjectAudioConfig.seed_audio_model` 与前端 `api.ts`/`types.ts` 的联合类型同步收窄为仅 `seed-audio-1.0`；适配器能力层 `SUPPORTED_SEED_AUDIO_MODELS` 不变，multilingual 适配器保留代码但不可经项目配置触达，恢复时只需把 `SEED_AUDIO_MODEL_MULTILINGUAL` 并回 `SEED_AUDIO_MODELS` 及放开上述类型。至此路由默认口径闭环，剩余待定的仅是将来恢复 multilingual 时的触发条件与账号权限，届时仍需授权与灰度。
2. **参考音色资产载体**：已定并落地。专用表 `voice_reference_assets` 已通过迁移 `add_user_voice_public_pool` 扩展 owner、授权、撤销和清理字段，并新增 `voice_pool_publications/voice_pool_ratings`。Seed 系统/复刻继续使用 `speaker`；用户私有与公共池使用稳定资产身份，不把 Base64 长期写入 `Project.audio_config`。`ChapterScenePipeline` 只允许物化后端已校验的 `user_private/public_pool`，且仅把用户私有物化结果回写到同一条既有授权资产；不会再从其它供应商官方试听新建 `provider_preview`。未注入数据库会话或回写失败时不阻断本次渲染，但项目创建和正式生成前的使用闸门仍为 fail-closed。至此本项闭环。
3. **用户自有跨供应商参考资产质量**：统一中性试听文本已经确定；可解码、空内容、时长、大小、明显削波和异常静音已自动校验，分析结果缓存已落地（`SceneAudioAnalysisCache` 按音频 SHA-256 持久化技术分析，`PreviewReferenceMaterializer` 默认写入 `output_root/.analysis-cache`，跨运行复用避免重复解码）。2026-07-22 已补齐单人声/背景音乐·环境声/混响三项声学检测（`SceneAudioTechnicalAnalyzer` 基于帧级 RMS 与通道相关）：`single_voice`（立体声按左右声道皮尔逊相关判多声源，单声道假定单声源——同轨多说话人无法廉价判别，属已知局限）、`background_energy_ratio`/`background_music`（低分位能量地板占峰值比刻画持续背景铺底）、`reverb_tail_s`/`reverb`（语音结束后衰减到地板附近的中位时长刻画混响拖尾）；三项指标与判定布尔均随报告缓存并经 `to_quality_metadata()` 暴露给下游。判定阈值已进 `SceneAudioQualityPolicy`（`channel_correlation_min=0.2`、`background_energy_ratio_threshold=0.35`、`reverb_tail_s_threshold=0.12`，保守默认仅命中明显污染），正式阈值与是否纳入物化硬闸门由 §12-11 用真实资产标定后统一发布。资产授权与使用闸门已完成；剩余工作是用真实用户资产标定质量阈值和音色相似度分布。
4. **场景模式入口**：首轮只开放测试项目，还是在有声书页面提供显式实验开关；生产默认仍为 `legacy_stems`。
5. **真实计费口径**：供应商按哪个时长字段计费、失败调用是否计费、最低计费单位和积分换算比例。四个维度分别说明「现状实现 / 待决口径 / 建议默认 + 理由」。**2026-07-22 运营决策：四项建议默认已全部采纳并落地**——①②④ 确认现状（与现有实现一致，无需改码），③ 新增可配置最低计费单位（默认线性，行为不变）。真实账单到位后只需调默认值/环境变量，无需改动结算逻辑。

   - **① 按哪个时长字段计费**
     - 现状实现（`scene_billing.py`）：优先按去重后（provider_request_id 幂等）每次成功 provider attempt 的 `original_duration`（秒，毫秒级精度）累加为章节 `billable_duration_s`；无 attempt 记录时回退各场景检查点的 `billing_duration_s`。`actual_cost_yuan = billable_duration_s × price_per_second_yuan`（¥1/60）。
     - 待决口径：供应商真实账单以「合成音频输出时长（`original_duration`）」计费，还是以「输入字符/ token 数」或 API 返回的「独立计费时长字段」计费。
     - 建议默认：若真实账单/接口返回独立计费时长字段，则以该字段为准；否则以 `original_duration`（我方裁剪前的原始合成时长）为准——裁剪属我方后处理，供应商已渲染完整音频，用裁剪后时长计费会低估成本。

   - **② 失败调用是否计费**
     - 现状实现：仅「带 provider_request_id 且 `original_duration > 0`」的成功尝试计入；无 request_id、无产出的纯失败一律不计费；质量闸门失败但供应商已成功生成的重试，仍按各自 `original_duration` 分别累计（因为供应商确已产出音频）。
     - 待决口径：供应商是否对失败/中断调用收费（如超时后仍完成生成、部分产出、鉴权失败但已触发合成）。
     - 建议默认：仅对「返回 request_id 且产出音频」的尝试计费，纯失败不计费，与「去重-by-request-id + 供应商按成功产出收费」的现有设计一致；须以真实账单核实供应商是否对失败/中断调用收费，若收费则新增「失败尝试计费」分支。

   - **③ 最低计费单位**
     - 现状实现：无最低单位、无按调用取整——按总秒数线性计价，仅在末尾把金额 `round` 到 4 位小数（元）；一次 60 秒响应按 ¥1.00。
     - 待决口径：供应商是否按整秒向上取整、单次调用是否有最低计费秒数、是否有单次最低收费额。
     - 建议默认：口径确认前保持「线性按秒」（最保守、不高估）；确认后在每次 attempt 层加最低计费单位/向上取整规则（例如 `ceil` 到整秒或单次最低 N 秒），在 `build_seed_scene_billing_summary` 的按 attempt 累加处施加，而非章节汇总处，以正确处理多次短调用。
     - **落地（2026-07-22）**：`scene_billing.py` 新增可配置最低计费单位 `DEFAULT_SEED_AUDIO_BILLING_INCREMENT_S`（默认 `0.0` = 线性、行为不变），环境变量 `DOUBAO_SEED_AUDIO_BILLING_INCREMENT_S` 覆盖，无效/非正值回退线性。`resolve_seed_audio_billing_increment_s()` 解析，`_quantize_billable_duration()` 把**每次调用**时长 `ceil` 到增量的整数倍（正时长在启用增量时至少计一个单位，同时满足「向上取整到增量」与「单次最低一个单位」）；施加于按 attempt 累加处，无 attempt 时按检查点逐场景施加。摘要新增 `billing_increment_s` 字段供审计。真实账单确认最低单位后只改默认值/环境变量即可；若需「大于增量的单次最低秒数」这类独立地板，再作后续扩展。

   - **④ 积分换算比例**
     - 现状实现（见 §8）：用户有效 `user_price_rate` 固定 `1.0`（始终按公开后付费最高价 ¥1/分钟计），不受后台通用倍率影响；`points_per_yuan` 负责人民币↔积分的线性换算（沿用既有配置，量级参考 MiniMax HD 回退口径 100 积分/元）；`freeze_buffer_rate` 只增加临时冻结额度、不增加最终结算；预检按选中章节「预计朗读秒数」冻结积分，结算按 `original_duration` 实际用量扣减，失败释放冻结。
     - 待决口径：seed audio 的 `points_per_yuan` 具体取值、是否有最低积分收费、冻结用「预检估算」而结算用「实际用量」的差额处理是否需要额外缓冲。
     - 建议默认：复用既有 `points_per_yuan`（100 积分/元）保持与其它模型一致；预检按估算秒数冻结、结算按实际 `original_duration` 扣减多退少补；最低积分收费随维度③的最低计费单位联动。
6. **授权策略**：2026-07-23 已完成资产级确认、owner 隔离、使用前闸门、软撤销和公共发布许可快照。参考来源收敛为：豆包账号内 `system_voice/voice_clone`、当前用户 `user_recording/user_generated_voice`、已审核公共池；其它供应商官方系统音色的 `provider_preview` 不再作为生产 reference 来源。

   - **① 确认（授权采集）**
     - 已落地：用户敏感资产必须同时携带 `owner_user_id/authorized_by_user_id/authorization_scope/authorization_basis/authorization_version/authorized_at`，任一缺失即拒绝落库。公共发布再记录独立 `rights_basis/license_version/consent_at`；未主动发布不进入公共池。

   - **② 审计**
     - 已落地：资产表保留来源、owner、授权人与依据、SHA-256、存储 URI、授权/撤销时间和元数据快照；标准试听调用写入 `voice_asset_billing_ledger`。待运营确认是否需要逐章节 `used` 事件账本和合规导出。

   - **③ 删除 / 撤销**
     - 已落地：幂等软撤销 API、各自定义音色删除时的同步撤销、active lookup 与项目创建使用前闸门。公共撤回不追溯破坏历史有声书，但禁止未来选择；低分达到阈值自动转 `community_rejected`。待补的是 `user_recording` 原始文件和分析缓存硬删除任务，资产行仍需保留最小授权/撤销审计残留。
7. **旧音效/配乐链路去留**：在至少一个灰度周期的数据完成前不做下线决策。
8. **主角低相似度策略**：先按场景回退整段 `legacy_stems`，还是在未来增加“稳定 TTS 对白 + Seed 环境音乐”的混合渲染；阶段 3 不实现混合模式。
9. **provider attempt ledger 载体**：阶段 3I 已采用 run 目录追加式 JSONL，并满足跨实例 request ID 幂等；正式运营是否升级为数据库不可变账本表，取决于跨任务归档、查询、清理和财务审计要求。
10. **ASR provider 配置**：首发默认使用已经完成真实时间戳契约验证、支持本地 Base64 的 `fun-asr-flash`。阿里云 `paraformer-v2` 与豆包 `volc.bigasr.auc` 已使用临时公网 `audio_url` 完成成功路径真实验证；豆包 2.0 可通过 `VOLCENGINE_ASR_RESOURCE_ID=volc.seedasr.auc` 显式灰度，不在开通状态完成验证前静默切换默认资源。四条公开价、usage 时长成本、默认 `300s/2 次/¥0.20` 单场景预算及环境配置均已落地；ASR 失败只进入明确回退，不隐式重新调用 Seed。剩余候选灰度只处理限流、任务失败、静音、URL 失效和真实超时分布，不再重复验证已完成的成功合同或价格目录。
11. **质量策略版本**：削波、静音、覆盖率、vocalization 豁免和 ASR 失败的正式阈值，以及 `quality_policy_hash` 的发布和兼容策略。§12-3 新增的声学检测阈值（`channel_correlation_min`、`background_energy_ratio_threshold`、`reverb_tail_s_threshold`）同属本项：需使用真实用户明确授权的上传、设计与复刻资产建立正负样本，分别统计误报率和漏报率，再决定是否将 `single_voice`/`background_music`/`reverb` 纳入物化硬闸门。阈值、样本集版本和判定模式必须一起进入策略版本；未经校准的指标只记录观测，不得直接阻断正式资产。
12. **实际采购套餐档案**：等待补充各供应商实际订阅档位、成交价、计费周期、包含额度、超额单价和生效时间；资料未齐前供应商成本按公开后付费价保守估算。
13. **固定音色生命周期账本**：载体已落地（表 `voice_asset_billing_ledger` + 仓储，以幂等键登记供应商、模型、账号范围、`voice_id`、创建/试听/正式成功/首次使用事件，并预留供应商扣费凭证字段）。仍待运营决策：创建成功还是首次正式使用计一次固定费；供应商超时、明确失败、`ResourceNotExist`、重复创建、创建成功但试听失败、删除后重建分别是否收费；¥9.9、¥138 等公开固定费用如何冻结/结算；供应商扣费 ID、账单或回执如何回写并支持对账。金额必须沿用 §5 的已核实公开后付费事实源，不能根据 `voice_id` 或错误响应猜测收费；口径确定前只登记事件，固定费不自动冻结或结算。

14. **公共音色池正式开放边界**：2026-07-23 已完成产品、权限、数据、合规和活动奖励的实施级规划。基础表与发布/审核/评分/撤回 API 已存在；以下内容是正式开放前的完成定义，不代表当前代码已经全部实现。

   ### 14.1 免费共享与费用归属

   - **当前模式**：公共音色本身免费共享。贡献者不获得按次分成、现金收益或自动积分；消费者选择公共音色不支付额外“音色许可费”。
   - **生成费用不免费**：公共池只免除音色选择费用，豆包 Seed Audio 的场景生成仍按公开后付费最高价和实际输出时长正常结算。不得在 UI 中把“公共音色免费”表述为“有声书生成免费”。
   - **参考试听成本**：贡献者首次生成标准参考试听时，仍按来源 TTS 的公开价确认并承担该次生成成本；缓存命中后不重复生成。消费者复用公共衍生试听时不再次调用来源 TTS，因此不承担来源模型费用。
   - **不追溯奖励**：免费共享期间只记录合格使用事实。未来活动默认不追溯活动开始前的使用，除非活动规则在创建时明确包含历史窗口并单独完成预算确认。
   - **活动与基础功能解耦**：`VOICE_POOL_CAMPAIGNS_ENABLED` 默认关闭。关闭活动不会影响公共池的发布、发现、选择和评分。

   ### 14.2 `voice-pool-license-v1` 许可基线

   发布确认页必须以不可变版本保存许可快照，建议正式文案至少包含以下边界：

   1. 发布者确认其对声音来源拥有本人权利、有效授权或可公开使用的合成设计权利，并允许平台进行审核、标准化、存储和场景生成。
   2. 发布者授予平台及平台用户一项**非独占、免音色许可费、仅限平台服务内使用**的许可。用户生成作品的使用范围沿用主服务协议，不因公共音色额外收取授权费。
   3. 许可不转移声音或音色所有权；禁止下载后再次复刻、转售参考音频、建立外部音色库、冒充真实人物或暗示被模仿者背书。
   4. 公共 API 只返回可播放的短时签名地址；不得把长期 OSS 原始地址当作稳定公开下载地址。
   5. 发布者撤回后立即禁止新的选择和生成；撤回前已经成功完成的有声书产物不追溯销毁，除非确认侵权或法律要求另行处置。
   6. 平台可因侵权、冒充、违法内容、错误分类、低质或安全风险暂停/移除音色，并保留最小审核证据。
   7. 许可版本不可原地修改。升级到 `voice-pool-license-v2` 时，旧发布保持旧快照；需要扩大授权范围时必须由发布者重新同意。

   正式上线门槛：产品页、发布弹窗、数据库快照和服务协议中的版本/文案必须一致；法律审阅未完成前仅允许内部或受邀灰度，不开放匿名公共发布。

   ### 14.3 状态机与管理员审核

   采用显式有限状态机，禁止 route 直接写任意状态字符串：

   ```text
   pending_review -> published | rejected
   published      -> suspended | community_rejected | withdrawn | removed
   suspended      -> published | removed
   rejected       -> pending_review（修改标签或更换标准试听后重新提交）
   community_rejected / withdrawn / removed -> 终态；重新公开必须创建新 publication 版本
   ```

   - `withdrawn`：所有者主动撤回；保留私有资产，不等同于删除私有录音。
   - `community_rejected`：达到低分阈值自动下架；只下架，不物理删除。
   - `suspended`：举报或管理员紧急暂停；调查期间禁止发现、选择、评分和新生成。
   - `removed`：确认侵权或严重违规后的终态；触发公共衍生资产清理评估。
   - 评分只允许 `published`，发布者不得给自己的音色评分。当前仓储允许 `community_rejected` 继续评分，应在 Q0 收紧。
   - 除表中列出的转换外全部拒绝；route 和 repository 不得各自维护不同状态集合。重复请求必须携带幂等键或 `expected_updated_at`：同一命令重放返回既有结果且不重复写事件，不同管理员并发决策只能有一个成功，过期版本返回冲突。

   新增 `voice_pool_moderation_events` 作为追加式审核账本，至少记录 `publication_id/action/from_status/to_status/reason_code/note/actor_user_id/license_version/created_at`。状态表保存当前事实，事件表保存过程，二者在同一事务提交。

   管理 API 统一放入 `/api/v1/admin/voice-pool`，复用现有 `require_admin`：

   - `GET /publications`：按状态、权利依据、来源类型、标签、提交时间、评分和举报数分页。
   - `GET /publications/{id}`：标准试听、标签、权利快照、来源审计摘要、评分和举报摘要。
   - `POST /publications/{id}/decision`：通过/拒绝，携带 `expected_updated_at` 防止两名管理员覆盖彼此决定。
   - `POST /publications/{id}/suspend|restore|remove`：紧急治理动作，必须填写原因码。

   管理前端新增 `/admin/voice-pool`，沿用现有 AdminLayout：左侧密集审核队列，右侧试听与元数据详情；提供状态 tabs、过滤、通过、拒绝、暂停、恢复和移除，不在有声书业务页面混入管理员操作。

   审核清单固定为：音频可播放、单人声和无明显背景污染；公开名称/性别感/年龄感/风格/语言/标签与试听一致；权利依据完整；不包含可识别真人冒充、隐私或违法内容；不存在明显重复发布。每个拒绝必须选择稳定原因码，说明文字可选。

   ### 14.4 举报、申诉与滥用治理

   新增 `voice_pool_reports`，字段至少包含 `report_id/publication_id/reporter_user_id/reason_code/detail/status/handled_by_user_id/handled_at/created_at`。首版原因码：`rights_violation`、`impersonation`、`privacy`、`illegal_content`、`misleading_tags`、`spam_duplicate`、`poor_quality`、`other`。

   - 同一用户对同一 publication 同时最多一条未处理举报；接口按账号和 IP 限流，防止批量恶意举报。
   - 普通质量问题继续走评分阈值；举报数本身不直接自动定罪。3 个以上独立用户在 24 小时内举报只提升审核优先级，不自动删除。
   - `rights_violation/impersonation/privacy` 可由管理员一键 `suspended`，先阻断新使用再调查。
   - 所有者可对 `rejected/community_rejected/suspended` 提交一次当前版本申诉；申诉不能绕过 `removed`，终态恢复必须创建管理员复核事件。
   - 列表和日志不得暴露举报人身份、原始录音 URI、供应商私有 voice ID 或授权证据文件。

   ### 14.5 撤回、硬删除与保留策略

   三个操作必须分开，避免“撤回公共发布”误删用户私有资产：

   | 操作 | 立即效果 | 文件处理 | 历史作品 |
   |---|---|---|---|
   | 撤回公共发布 | 公共池不可发现、不可新选 | 保留用户私有源和标准试听 | 已完成作品保留 |
   | 撤销私有音色授权 | 私有/公共入口和运行时校验全部拒绝 | 创建硬删除任务 | 已完成作品保留；排队任务停止使用 |
   | 管理员确认侵权移除 | 公共发布终态 `removed` | 删除公共衍生试听并评估私有源合法保留 | 按法务结论处理，不自动批量删除成品 |

   复用现有 `cleanup_status/cleanup_requested_at/deleted_at/cleanup_error`，新增 Celery `voice_reference_cleanup` 任务：

   1. 事务内设置 `revoked_at + cleanup_status=requested`，立即阻断新使用。
   2. 任务只删除受控本地目录和受控 OSS 前缀中的对象；任何外部 URL 或路径越界都拒绝处理并记录错误。
   3. 删除原始上传录音、标准衍生试听、物化缓存和按 SHA-256 建立的分析缓存；删除前检查对象引用，避免误删仍由其它有效 publication 使用的衍生对象。
   4. 供应商云端音色仅在供应商提供正式删除 API 时删除；不支持时记录 `provider_cleanup_unsupported`，不得向用户声称已经删除云端音色。
   5. 成功后写 `cleanup_status=succeeded + deleted_at`，失败使用有界重试并进入管理员队列，不恢复授权。

   建议服务目标：活跃存储在请求后 24 小时内删除；备份通过对象生命周期在 30 天内过期；不含音频的最小授权、撤回、审核和清理证据保留 3 年。上线前由法律/隐私负责人确认这三个期限，配置化后不得由普通管理员随意修改。

   ### 14.6 上线前测试音色清理

   运营事实：当前系统内所有设计、复刻和历史无 owner 音色均为开发测试数据，没有需要迁移或认领的真实用户资产。因此取消历史 CosyVoice owner 认领工具，不新增认领表、API、证据上传或管理页面。

   - 清理完成前，历史无 `owner_user_id` 条目继续隐藏，禁止进入试听、角色选择、Seed reference 和公共发布。
   - 清理工具采用一次性管理脚本，不做长期在线接口。脚本必须先 `dry-run`，只输出数量、ID、来源模型、存储类型和将执行的动作，不输出原始录音内容或密钥。
   - dry-run 范围应覆盖：CosyVoice/MiMo/StepAudio/MiniMax 测试音色登记、`voice_reference_assets`、`voice_pool_publications`、`voice_pool_ratings`、相关 preview/固定费用测试账本、本地参考文件、OSS 标准试听/派生缓存和可识别的供应商云端测试音色。
   - 已落地只读工具：`python -m app.scripts.dry_run_voice_test_cleanup --json`（在 `backend/` 目录运行）。报告版本为 `voice-test-cleanup-dry-run-v1`，固定输出 `destructive=false`；数据库部分盘点自定义参考资产、公共发布、评分和音色账本并排除 `system_voice`，本地部分复用 MiMo/StepAudio/MiniMax/CosyVoice 的实际默认路径。
   - `--json` 报告中的音频存储只输出 `local/oss/http/unknown` 类型和布尔元数据，不输出 `storage_uri`、公共 URL、原始音频、Base64、授权文本或密钥；本地索引只输出截断后的非敏感 ID、模型、资产类型、owner 是否存在、文件计数和字节数。
   - 已落地精确确认清单：`python -m app.scripts.dry_run_voice_test_cleanup --manifest`。manifest 版本为 `voice-test-cleanup-manifest-v1`，固定输出 `destructive=false`、`execution_permitted=false` 和 `confirmation_required=true`；仅该模式输出受工作区根目录约束的完整本地路径、文件 SHA-256、数据库主键和已知自定义音色 ID，并生成覆盖全部动作的 `manifest_fingerprint`。脚本不存在 `--execute` 参数。
   - 2026-07-23 开发库 dry-run 快照：`voice_reference_assets=5`（均为 `user_generated_voice`，其中 StepAudio 4 条、MiMo 1 条）；公共发布、公共评分和音色生命周期账本均为 `0`。本地 MiMo 索引 4 条无 owner 测试记录（3 条 design、1 条 clone），受控本地音频 1 个、约 `996524` bytes；CosyVoice 历史名称映射 6 条无 owner 记录；StepAudio 索引为空；MiniMax 本地目录不存在。该快照仅用于核对脚本范围，不能替代执行前重新生成报告。
   - 2026-07-23 精确 manifest 快照：指纹 `vctc_fb6a4589d40a6cbae820f83f815cc9b8`；数据库删除候选为 `voice_reference_assets.id IN (1,2,3,4,5)`，公共发布、评分和音色账本均为 0；本地操作 8 项，其中清空 CosyVoice/MiMo 两个 JSON 索引、删除 6 个测试音频文件共 `996602` bytes，空的 StepAudio 索引不改写；OSS 候选 0；CosyVoice 云端已知自定义音色 6 个；人工复核 0；阻断项 0。该快照用于本次操作确认，实际执行前若重新生成的指纹不一致，必须停止并重新确认。
   - 2026-07-23 已按上述指纹完成一次性清理：CosyVoice 云端 6 个 ID 中 5 个由本次调用成功删除、1 个在清理时已返回 `BadRequest.ResourceNotExist`；终检对 6 个 ID 逐一调用 `query_voice`，全部明确返回不存在。数据库删除 `voice_reference_assets` 5 行，四张相关表终检均为 0；本地完成 8 项操作，6 个音频文件均不存在，CosyVoice 索引为 `{}`，MiMo 索引为 `{"assets":[]}`；OSS 无候选对象。云端与本地执行审计均为 `completed`。
   - 污染来源复核：上述 5 条数据库记录来自早期未覆盖 `get_db` 的 MiMo/StepAudio 路由测试。当前测试客户端已将 `get_db` 覆盖为非 `Session` 测试对象，登记入口因此不会连接开发 PostgreSQL；2026-07-23 重新运行两组测试 `24 passed`，随后四张相关表和 manifest 汇总仍全部为 0。执行审计保留在本机 `backend/data/voice_cleanup_audits/`，该目录已加入 `.gitignore`。
   - CosyVoice 云端删除白名单仅接受 `cosyvoice-v3.5-plus-` 与历史 `cosyvoice-v3-plus-` 两种已知自定义前缀。DashScope `VoiceEnrollmentService.delete_voice(voice_id)` 不要求模型参数，因此两个前缀共用同一 SDK 删除合同；`longanyang` 等官方系统音色和任意未知 ID 会在网络请求前拒绝。
   - 自动化回归覆盖：只读标志、官方系统音色排除、URI/音频内容不泄露、索引单文件与目录扫描、空索引跳过、工作区越界阻断、公共关系/账本清单、manifest 指纹和 CosyVoice 新旧自定义 ID 白名单；测试文件为 `backend/tests/test_voice_test_cleanup_dry_run.py`、`backend/tests/test_cosyvoice_clone_cleanup.py`。执行前必须在目标数据库、目标进程工作目录和目标 OSS 配置下重新生成报告。
   - 本次一次性执行已完成；后续任何真实用户硬删除仍属于数据库删除、文件删除和供应商云端操作，必须另行按危险操作格式列出精确数量、路径前缀、表范围和供应商动作，并取得用户明确确认。“当前没有真实用户”不能成为未来操作的永久授权。
   - 删除顺序：先暂停自定义音色创建并重新生成/校验 manifest 指纹；再按白名单删除供应商云端测试音色，任一失败即停止且不改本地映射；随后在数据库事务中按评分、发布、账本、参考资产顺序删除；再删除 manifest 精确列出的本地/OSS 音频，最后以原子写方式清空本地索引并执行零残留校验。任一步失败都停止后续高风险步骤，不做猜测性补删。
   - 不重置数据库自增序列，不删除已生成的测试有声书成品，不触碰官方系统音色；是否连同测试项目一起删除是独立操作，不与音色清理捆绑。
   - 清理后执行零残留校验：无 owner 自定义音色计数为 0、测试 publication/评分为 0、受控本地/OSS 前缀无孤立对象、正式创建入口产生的新资产均带完整 owner 与授权快照。
   - 上线后不保留“历史认领”兼容分支。真实用户只能通过当前带身份认证的设计/复刻入口创建资产，避免长期维护一个没有业务对象的迁移流程。

   ### 14.7 公共发现、统计与隐私

   - 公共列表改为服务端游标分页，默认 24 条、最大 50 条；支持性别感、年龄感、主要风格、语言、音色质感、适用场景和口音筛选。
   - 首版排序只提供“推荐、最新、评分、使用最多”。推荐采用可解释的角色标签匹配，不引入个性化模型。
   - 评分和使用统计改为 grouped aggregate 或日汇总表，消除当前逐 publication 查询评分摘要的 N+1。
   - 公共响应只暴露 publication 身份、公开标签、短时试听地址和聚合统计；不暴露 `owner_user_id`、私有 `asset_id`、原始录音、供应商私有映射和授权证据。
   - 记录合格使用事件时只保存内部 user ID、publication ID、run ID 和结果状态；排行榜对外只展示音色公开名称，不展示贡献者真实身份，除非贡献者主动设置公开昵称。

   合格使用事件定义为：有声书 run 成功完成，最终使用了该 publication，且该 `(run_id, publication_id)` 尚未计数。试听、下拉选择、失败任务、回退后未使用、所有者自用、管理员/测试账号和取消/退款任务均不计入排行。

   ### 14.8 后期排行奖励活动

   排行奖励是**显式、限时、预算封顶的运营活动**，不是永久收益分成。活动数据模型在真正启用前再新增，避免当前阶段提前维护未使用表：

   - `voice_pool_campaigns`：活动名称、时间窗、状态、规则版本、资格门槛、奖励档位、总预算、创建/审批人。
   - `voice_pool_campaign_snapshots`：截止时间、publication、合格独立用户数、合格完成章节数、贝叶斯评分、违规状态和最终名次。
   - `voice_pool_campaign_rewards`：获奖用户、publication、积分、幂等键、审核状态和发放凭证。

   首期排行建议采用透明字典序，避免不可解释加权分：

   1. 达到活动配置的最低独立使用用户数、最低评分数和最低平均分。
   2. 优先按 `qualified_unique_users` 降序。
   3. 再按 `qualified_completed_chapters` 降序。
   4. 再按带先验的贝叶斯评分降序，避免少量五星超过大量稳定评价。
   5. 同分时按首次达到成绩的时间升序。

   反作弊规则：排除所有者自用和管理员/测试账号；同一用户对同一 publication 每日最多贡献一次独立使用；只有完成且通过结算的 run 计数；异常账号簇、批量短文本和互刷评分进入人工复核。榜单结束后冻结 48 小时再发奖，处理举报和退款；严重作弊取消资格并保留审计。

   奖励不得复用任务扣费的 freeze/settle/release 事件。应建立专用正向积分事件 `VOICE_POOL_CAMPAIGN_REWARD`，幂等键为 `campaign_id:publication_id:reward_version`，与积分调整和奖励凭证在同一事务完成。每次活动创建时必须显式确认活动预算、名次档位、积分数、有效期、是否展示贡献者昵称和是否允许历史窗口；未确认不得进入 `active`。

   ### 14.9 OpenAPI 与接口合同阻断

   2026-07-24 修复前，`/openapi.json` 因 `settings_api/routes_project.py` 使用未在本模块定义的 `AutoMergeRequest` 前向引用而失败；该类实际定义在 `routes_templates.py`，模块导入顺序不能构成合法类型依赖。修复方案：

   1. 将 `AutoMergeRequest` 移入 `app/schemas/settings.py`，由 `routes_project.py` 显式导入；删除 route 模块之间的隐式类型依赖。
   2. 新增全应用测试，直接调用 FastAPI `app.openapi()`，断言 schema 可生成且包含公共池和 settings auto-merge 路由。
   3. 通过实际导出的 Socket.IO 组合 `application` 请求 `/openapi.json`，防止单模块测试通过但全路由装配或部署入口失败。

   2026-07-24 实测证据：在当前全应用路由装配下直接调用 `app.openapi()`，稳定抛出 `PydanticUserError`，核心信息为 `ForwardRef('AutoMergeRequest') is not fully defined`。代码复核确认 `backend/app/api/v1/settings_api/routes_project.py:90` 使用该类型，而类型仍定义在 `routes_templates.py`。因此不能用“相关业务 endpoint 可单独请求”替代全应用 OpenAPI 验收。

   完成结果：请求模型已移入 `app.schemas.settings` 并由 `routes_project.py` 显式导入；路由模块不再互相依赖类型定义。两条全应用回归均已通过，该 Q0 阻断已解除。未来新增管理员路由后继续扩展同一 schema 路径断言。

   ### 14.10 实施顺序与验收门槛

   | 顺序 | 实施包 | 完成标准 |
   |---|---|---|
   | 1 | Q0 OpenAPI 合同 | `app.openapi()` 与组合 ASGI `/openapi.json` 均成功；schema 包含 settings 与公共池路由，管理员路由在 P1 落地后加入同一断言 |
   | 2 | Q0 评分正确性 | 只有 `published` 可评分；所有者不能自评；重复评分、下架并发和权限测试通过 |
   | 3 | Q0 公共池状态机 | 转换表集中定义；非法转换拒绝；管理员并发决定、命令重放和审核事件幂等测试通过 |
   | 4 | S0 时间戳 ASR 灰度 | 首发默认 `fun-asr-flash`；阿里云/豆包以临时公网 `audio_url` 完成候选灰度；时间轴、URL 有效期、成本、超时、限流、最大重试和 Seed 不重复调用均有证据 |
   | 5 | S0 Seed 场景质量基线 | 五类场景的描述音色 A/reference 音色 B 各生成 3 次，共至少 30 个样本；盲评和自动指标达到 §10.3 与已确认阈值 |
   | 6 | Q1 管理审核与许可 | `voice-pool-license-v1` 完成审阅；管理员可分页审核、试听、拒绝、暂停、恢复、永久移除；所有动作有追加式事件 |
   | 7 | Q1 举报申诉 | 用户可举报、所有者可申诉、敏感举报可先暂停；权限、限流和并发状态转换回归通过 |
   | 8 | Q2 真实用户硬删除 | 撤销立即阻断；本地/OSS/供应商清理可恢复、可重试、可审计、路径受限；不误删历史作品或最小审计残留 |
   | 9 | Q3 公共发现与灰度 | 游标分页、标签筛选、排序和聚合统计无 N+1；受邀用户完成发布、审核、选择、撤回全链路 |
   | 10 | S1 长篇稳定性与阈值校准 | 角色跨场景音色一致性完成离线评估；ScenePlanner 语义边界和性能回归通过；真实授权资产完成质量策略误报/漏报标定 |
   | 11 | Q4 活动排行 | 活动默认关闭；合格使用可去重；榜单可复算；奖励幂等且预算不超限 |

   一次性开发测试音色清理已于 2026-07-23 完成，不再属于实施待办或上线阻断项。其 manifest、执行顺序、零残留结果和回归证据保留在 §14.6，仅作为历史审计与未来真实用户硬删除的安全基线。

   正式公开发现的最低门槛：许可文本完成法律审阅；管理员审核和紧急暂停可用；举报入口可用；撤销能立即阻断新使用；真实用户硬删除任务至少在预发布环境完成本地与 OSS 演练；OpenAPI、迁移、权限、并发审核和端到端场景生成测试全部通过。排行奖励不属于公共池上线阻断项，免费共享可先独立灰度。

   ### 14.11 2026-07-24 优化优先级与完成状态

   | 优先级 | 工作项 | 当前事实 | 完成定义 |
   |---|---|---|---|
   | P0（已完成） | 修复全应用 OpenAPI | 请求模型已移入公共 schema；直接 `app.openapi()` 与组合 ASGI `/openapi.json` 均通过 | 新增路由持续纳入全应用 schema 回归 |
   | P0（已完成） | 收紧公共池评分 | 仅 `published` 可评分，所有者自评返回 403，下架后不再新增评分 | 保持仓储与 route 回归，后续管理员/测试账号排除并入合格使用统计 |
   | P0（已完成） | 集中公共池状态机 | 唯一转换表已落地；审核、撤回和低分下架统一校验；并发旧快照不能覆盖首个审核决定 | P1 管理动作必须复用同一状态机并写审核事件，不得复制状态判断 |
   | P0（部分完成） | 时间戳型 ASR 真实灰度 | 首发默认、三家成功路径、安全审计、四条公开价、调用/金额预算、成本聚合和失败不重复 Seed 已完成；阿里云提交/轮询/结果下载与豆包提交/轮询现共享单一 `monotonic` 绝对截止时间，各 HTTP 步骤只使用剩余预算，相关 provider/renderer 回归 `54 passed` | 继续固化临时 URL 最小有效期和限流/静音/任务失败样本；绝对截止时间的真实非语音复测因本轮外部调用权限审批超时尚未取得新证据 |
   | P0（严格盲评工程通路已完成，等待多人复评数据） | 五类场景 A/B 三次重复评审 | `seed-scene-review-export-v1`、锁定盲评批次、匿名音频、只读页面、九项评审首次提交锁定和管理员解盲均已接通；已从现有 30 槽位缓存创建 `blind_e33c39a24b5a19e92f14e8b6`，未调用 Seed/ASR；多评审者汇总可统计去重人数、覆盖槽位、平均分和九项通过率，只有管理员汇总关联真实 variant | 邀请独立评审者完成该批次；数据形成后导出汇总结论，并继续完成声纹相似度与角色跨场景稳定性基线 |
   | P0（代码已完成，效果标定待完成） | 场景间响度连续性 | 场景级测量、中位数基准、有界增益、真峰值约束和整章 loudnorm 已接入；真实资产听感分布尚未标定 | 使用真实授权资产完成低语、爆发、纯环境和回退片段的 LUFS/真峰值误报漏报与听感回归；确认 `±3dB` 上限和 `0.25dB` 忽略阈值后再解除效果阻断 |
   | P0 | 角色音色一致性离线评估 | 质量闸门当前不判断声线漂移，跨供应商 reference 相似度不稳定 | 分别统计原生 `speaker` 与跨供应商 reference；计算 reference/成品、同角色跨场景 embedding 相似度；主角和旁白采用更严格候选阈值，低相似进入人工评审或回退 |
   | P1 | 公共池许可与管理员治理 | 有单条审核 API，缺少正式许可、待审列表、事件账本、举报、申诉和紧急治理闭环 | 完成 `voice-pool-license-v1`、分页工作台、审核事件、举报申诉、暂停/恢复/永久移除及权限审计 |
   | P1 | 真实用户硬删除 | 当前仅完成开发测试数据清理；尚无面向真实用户的可恢复删除任务 | 撤销即时生效；原始录音、衍生缓存、本地/OSS 和可删除云端资产按状态机清理；保留不含音频的最小审计证据 |
   | P1 | 公共发现性能与扩展 | 当前公共列表 `.all()`，并逐条查询评分摘要，存在无界读取和 N+1 | 服务端游标分页、标签筛选、排序和 grouped aggregate/日汇总落地；查询数不随条目数线性增长 |
   | P1 | ScenePlanner 语义切分 | 规划器已有增量门控，但长篇时间/地点、故事节拍、禁止切点和情绪连续性仍缺结构化依据 | 有限窗口最近最佳边界回溯落地；转场、问答/因果保护、情绪弧和超长章节性能回归通过 |
   | P1 | 真实资产质量阈值校准 | 当前削波、静音、背景、混响和单人声策略主要来自少量样本 | 使用真实用户明确授权资产统计误报率/漏报率；版本化样本与阈值，确认后再把指标升级为硬闸门 |
   | P2 | 固定音色费用结算与采购成本 | 生命周期账本已落地；实际采购套餐、固定费用触发和失败计费口径未定 | 明确创建/首次使用、供应商失败、`ResourceNotExist`、重复创建和删除重建；用户仍按公开最高后付费价，供应商成本按实际套餐和扣费凭证入账 |
   | P2 | provider attempt 数据库账本决策 | 当前追加式 JSONL 已支持请求去重和恢复 | 根据运营审计需求决定是否迁移为数据库不可变账本；未形成明确需求前保持现状，避免重复建设 |
   | P2 | `auto` 路由 | 后端枚举支持 `auto`，前端类型和加载器会将其降级为 `legacy_stems` | 按场景类型、角色/reference 数、精确编辑、成本和近期失败率定义可解释路由；再接通前端配置、持久化、观测和灰度开关 |
   | P3 | `multilingual` 正式开放 | 真实接口契约已验证，但中文首发阶段主动暂停 | 只有出现明确多语种业务需求并完成质量/成本样本后开放，不阻断中文场景生成 |
   | P3 | 公共池排行奖励 | 当前运营口径为免费共享，后续可用活动引流 | 有独立活动预算、快照、反作弊、审核冻结和幂等奖励后再启用；默认关闭 |

   本轮执行状态与下一实施顺序如下，前一项完成其回归门槛后再扩大后一项灰度：

   1. [x] 修复全应用 OpenAPI。
   2. [x] 修复评分状态和所有者自评。
   3. [x] 集中公共池状态机。
   4. [ ] `fun-asr-flash` 首发默认、失败不重复 Seed、阿里云/豆包公网 URL 成功路径、公开价和单场景预算均已完成；继续验证两家候选的临时 URL 有效期与异常分布。
   5. [ ] 30 槽位已完成单人综合评审；场景级响度校准代码已落地，下一步导出逐槽位数据、完成严格盲评/声纹离线统计，并用真实授权资产完成响度效果标定后再扩大生产灰度。
   6. 实施管理员治理与许可闭环。
   7. 实施真实用户硬删除和公共列表分页/聚合。

   后续需要用户或运营补充确认的口径如下；在获得明确输入前，代码不得猜测商业规则或伪造验收标准：

   1. **实际采购套餐档位与价格**：供应商、地域、套餐名、成交价、周期额度、超额单价、生效/失效时间；只用于供应商实际成本和毛利，不改变用户按公开最高后付费价计价的原则。
   2. **固定费用触发与失败计费**：声音设计/复刻的创建、解锁、首次合成分别在哪个成功事件结算；供应商超时、返回失败、创建成功但试听失败、重试和删除后重建是否计费。
   3. **`voice-pool-license-v1` 正式文案**：授权范围、免费共享期限、作品存续、撤回后已有作品、禁止内容、投诉处理、原始录音保护和平台治理权，需由法律/隐私负责人确认。
   4. **A/B 盲评验收阈值**：主观偏好胜率、台词零漏词/零增词要求、角色一致性最低分、技术质量通过率、最大场景回退率、P95 时延和单分钟成本上限。阈值确认前先完整记录原始样本与指标，不以临时观察结果宣称上线达标。

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
- 剧本模式指导：`backend/app/services/audiobook/script_render_mode.py`
- 当前试听缓存：`backend/app/services/audiobook/tts_preview_cache.py`
- 试听参考资产物化：`backend/app/services/audiobook/scene_engine/preview_reference_asset.py`
- 私有参考资产与撤销：`backend/app/services/audiobook/voice_reference_asset_repository.py`
- 公共音色池仓储/API：`backend/app/services/audiobook/voice_pool_repository.py`、`backend/app/api/v1/audiobook_api/routes_voice_pool.py`
- 公共音色池前端：`frontend/src/pages/audiobook/VoicePoolWorkbench.tsx`、`useAudiobookSceneVoicePool.ts`
- 测试音色清理 dry-run/manifest：`backend/app/scripts/dry_run_voice_test_cleanup.py`
- 测试音色清理回归：`backend/tests/test_voice_test_cleanup_dry_run.py`、`backend/tests/test_cosyvoice_clone_cleanup.py`
- 独立场景测试目录与计划：`backend/app/services/audiobook/seed_scene_test_unit.py`
- 独立场景测试渲染与缓存：`backend/app/services/audiobook/seed_scene_test_renderer.py`
- 独立场景测试 API：`backend/app/api/v1/audiobook_api/routes_seed_scene_test.py`
- 独立场景评审页面：`frontend/src/pages/SeedSceneTestPanel.tsx`、`frontend/src/pages/TtsPromptTestPage.tsx`
- 独立场景 reference 绑定：`frontend/src/pages/audiobook/seedSceneReferenceUtils.ts`
- 独立场景统一试听文本：`frontend/src/pages/audiobook/voicePreviewText.ts`
- 独立场景评审本地存储：`frontend/src/pages/audiobook/seedSceneTestReviewUtils.ts`
- 场景 ASR provider/真实合同：`backend/app/services/audiobook/prompt_audio_asr_provider.py`
- 场景 ASR 公开价与预算策略：`backend/app/services/audiobook/prompt_audio_asr_pricing.py`
- Seed 按秒用量：`backend/app/services/audiobook/scene_engine/scene_billing.py`
- Seed provider 尝试账本：`backend/app/services/audiobook/scene_engine/provider_attempt_ledger.py`
- Seed 版本化质量策略：`backend/app/services/audiobook/scene_engine/quality_policy.py`
- 计费预检与路由：`backend/app/services/points_task_precheck.py`、`backend/app/services/audiobook/task_support.py`
- 积分冻结/结算/释放：`backend/app/services/user_center_points_events.py`、`backend/app/services/audiobook/background_jobs_shared.py`
- 字幕产物：`backend/app/services/audiobook/background_jobs_shared.py`
- 两遍响度标准化：`backend/app/services/audiobook/scene_engine/loudness_normalizer.py`
- 场景进度后端：`backend/app/services/audiobook/engine_pkg/_scene_render_mixin.py`、`backend/app/websocket/manager.py`
- 场景进度前端：`frontend/src/services/websocket.ts`、`frontend/src/pages/audiobook/audiobookSceneProgress.ts`、`frontend/src/pages/audiobook/useAudiobookRealtimeProgress.ts`

---

## 附录 B：架构决策摘要

| 决策 | 选择 | 原因 |
|---|---|---|
| 主渲染粒度 | 场景级，不是整章 | 满足硬限制，控制重生成成本，保留情绪连续性 |
| 默认常规场景时长 | 45-75s | 100-120s 黑盒片段局部修改代价过高 |
| 剧本事实源 | `ScriptSegment[]` | 已具备台词、角色、表演、停顿、音效和音乐结构 |
| 提示词生成 | 确定性模板优先 | 防止 LLM 在生成前改写、漏掉或新增台词 |
| 角色音色 | 稳定声音身份资产 | 跨供应商 voice_id 不可直接互通，Base64 不适合长期配置 |
| Seed-TTS 2.0 音色 | 直接传 `references[].speaker` | 与 Seed Audio 同属豆包声音身份，不需要试听音频中转 |
| 跨供应商用户自有音色 | owner 隔离 + 标准衍生试听 + OSS + `audio_data` | 仅允许用户设计/复刻资产或已审核公共池；官方系统试听禁止自动转用 |
| 公共音色商业模式 | 当前免费共享，后续限时排行奖励 | 不引入按次分成；活动预算、规则和积分发放独立审计 |
| 公共音色标签时机 | 发布公共池时必填 | 私有音色创建保持低摩擦，公共发现仍有稳定分类 |
| 公共音色撤回 | 阻断新使用，不追溯已完成作品 | 平衡发布者撤回权、用户产物稳定性和审计要求 |
| reference Prompt | 不重复静态音色描述 | 避免文字年龄、口音和声线定义压过参考输入 |
| 质量策略 | 字幕/ASR 自动闸门 | 完整混合音频无法通过分轨后期修复漏词 |
| 回退粒度 | 单场景 | 避免一个失败场景导致整章重做 |
| 运行模式 | legacy_stems / seed_scene / auto | 支持灰度、对照、自动路由和总回退 |
| Seed 计费 | 预计秒数冻结、`original_duration` 结算 | 用户固定按公开后付费 ¥1/分钟；套餐只影响供应商成本与毛利；不混用 TTS 文字价格 |
| 场景进度 | 专用有声书房间 + 动态阶段卡片 | 不改变旧 TTS 展示，断线仍有 SSE/轮询兜底 |
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
9. Seed-TTS 2.0 系统/复刻音色必须直接使用 `speaker`；其试听音频不得转成 `audio_data` 代替原生身份。
10. 其它供应商 `voice_id` 不得写入 Seed Audio 的 `speaker`；只有当前用户未撤销的私有设计/复刻资产或 `published` 公共池资产可以解析为音频 reference，其它官方系统音色必须拒绝或改走旧链路。
11. 有 reference 的角色块不得重复年龄感、口音、音高、沙哑度、磁性等静态音色词。
12. 检查点签名必须包含 schema、renderer、模型、音频配置、Prompt 和 reference 身份；任一项变化都必须使对应场景失效。
13. Base64 reference 只允许存在于当前运行时请求，不得写入项目配置、检查点或长期日志。
14. `seed_scene` 的主模型合同不得与逐句 TTS 的 Qwen/CosyVoice 合同同时出现；逐句 TTS 只定义参考音色来源和局部回退。
15. 同一地点连续片段的场景状态和相同配乐只编译一次；真实转场、配乐变化或停止必须生成新的有序事件。
16. `vocalization` 事件必须进入 `expected_vocalizations` 并透传到质量闸门；未透传时不能声称非语言人声豁免已生效。
17. `fallback_ready` 检查点必须包含可校验的回退音频路径、哈希、时长和源片段签名；终态回退恢复不得自动再次调用 Seed。
18. provider request ID 只能在成本 ledger 中计入一次；内部积分幂等不能替代供应商外部调用幂等。
19. 生产模型、计费模型和 checkpoint 模型必须来自同一运行时配置，不能由 mixin、adapter 或摘要函数各自固定默认值。
20. 质量阈值和豁免策略必须集中、版本化并进入 checkpoint 签名；策略变化后旧音频必须重新评估或失效。
21. Seed-TTS 2.0 静态系统音色目录只用于展示、推荐和自动分配；账号级声音复刻 ID 不得因目录未收录而被替换或拒绝，最终合法性由供应商账号校验。
22. Seed 创建成功后的临时音频 URL 下载必须使用独立重试预算；下载重试只能访问同一成品地址，不得消耗 Seed 生成重试次数。下载预算耗尽后必须阻断自动重新生成并提示可能已计费。
