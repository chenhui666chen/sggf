# 朗读 TTS 提示词能力官方取证（证据表）

> 平台：耳畔星河（novel_writing_agent）
> 核实日期：2026-10-10 ｜ 取证方式：各供应商官方文档页 + 本地 `bailian-docs-llm-wiki`（`models/groups/*.json` 官方 samples、`raw/` 原文）交叉验证
> 性质：取证 + 实测记录。**不含任何代码改动**；G1–G7 门槛批次已产生真实付费调用（音频、manifest、ASR、两轮评分均留档，结论见 §9）。
> 配套：`docs/AUDIOBOOK_TTS_PROMPT_OPTIMIZATION_GUIDE.md`（现有优化系统 G1–G7）、`docs/QWEN_AUDIO_TTS_NEXT_PROMPT_GUIDE_20261010.md`（Next 已收口的写法结论）、`docs/MODEL_INTEGRATION_REFERENCE.md` §11（接入契约）
> 置信标注：high = 官方页原文/结构化 samples 直接支撑；medium = 官方页存在但与另一官方页冲突或需实跑确认；low = 官方未提供，仅我方推断。

---

## 0. 一页结论：每个模型"能写什么"

| 模型 | 官方风格控制通道 | 情绪控制形态 | 我方代码现状 | 最大空白 |
|---|---|---|---|---|
| qwen3-tts-instruct-flash | 自然语言 `instructions`（≤1600 Token，中英）+ `optimize_instructions` 开关 | 无枚举，纯自然语言 | 只发自然语言，预算自设 600；**未用 `optimize_instructions`** | 官方上限是我方的 2.7 倍；重写开关闲置 |
| qwen-audio-3.1-tts-flash | `input.instruction`（官方未标长度上限）＋ **正文内 `[excited]`/`[sad]` 类标签**（官方给了词表与示例但**未保证可与 instruction 叠加**；叠加形状已由 §20 q8 实测为合法且逐字干净） | 任意指令（系统音色与复刻音色均可） | 只用 instruction，预算保守 1200；**情感标签完全未用** | **已收口写法层（§22 人耳裁定）＋取值层（§23 B4 全量扫描）**：正文官方标签逐句 ＞ 动机式 instruction ＞ 三段式＝念稿；圆括号会被朗读出口；官方 23 控制类＋7 富语言类**逐个实测全部不发音**（30/30 `leak=0`），但**作用域止于句界、必须逐句下标签**（段首一枚只有 1.21× vs 逐句 1.56×），且时长粗排必须用**发声量**而非总时长。剩余空白＝SSML `<break>`/`<phoneme>` 未试、q8 叠加未定序、第一档七对近义取值的名实待第二轮耳裁、生产装配仍走 instruction 单通道（改动待批准）；**取值层人耳已签字（§23.5–§23.7：强 18／弱 10／无 1，白名单定成"情绪 13＋事件 6＋物理效果 4＋暂缓 7"四档，粗排轴补上绝对响度）** |
| cosyvoice-v3.5-plus | WS `parameters.instruction` / HTTP `input.instruction`，**≤100 加权字符（汉字算 2）**，超限报 428 | 任意指令（复刻音色） | 计量口径已正确（汉字 2 单位） | 只能写约 55 个汉字 → 提示词必须极简，这是设计约束而非 bug |
| minimax-speech-2.8-hd / turbo | `voice_setting.emotion` 枚举 7 档（2.8 不支持 `whisper`）＋括号语气词 `(laughs)`＋`pronunciation_dict`＋`language_boost`＋`voice_modify`＋`timbre_weights`；MiniMax 官方另有 `<#x#>` 定时停顿（**百炼页未列出**） | 枚举 + 括号标签，**无自然语言 prompt** | 只发 `speed/vol`，`pitch` 写死 0，**`emotion` 从不传** | 整条情绪通道闲置；`<#x#>` 能否透传未验证 |
| mimo-v2.5-tts（基座） | 台词必须放 `assistant`，风格放 `user`（官方明文）；句首风格标签 `(风格)`／全角／方括号均可，句中任意位置可插标签；官方支持**复合情绪**与段落→句→词→字粒度指令 | 自然语言 + 标签，支持自定义风格、唱歌 | director（`角色/场景/指导` 三段）+ audio_tags 前缀 | 复合情绪与字粒度重音未按官方口径写；唱歌未用 |
| mimo-voicedesign | `user` 消息即音色描述（性别年龄/质感/情绪语气/语速节奏） | 描述式 | 有"固定声音设定（不可改变）"前缀 | 标签在该模式下是否生效官方未明（low） |
| mimo-voiceclone | `audio.voice` = `data:{MIME};base64,`（≤10MB，mp3/wav）＋同基座的指令与标签 | 同基座 | 走 base64 音色 | 参考音频时长要求官方未提供 |
| stepaudio-3-tts | **顶层 `instruction`（≤500 字符）**＋正文内半角圆括号 `（冷笑）…`（括号内容默认不发音）＋`speed 0.5~2`/`volume 0.1~2.0`＋`pronunciation_map.tone` | 自然语言；`voice_label{emotion/style/language}` 枚举**只服务 step-tts-2/mini，传 3-tts 会报错** | instruction 预算原写死 **200**（`_aliyun_mixin.py:36`），**2026-10-11 已按官方上调为 500** | 预算曾自砍 60%（已修复）；官方导演句式示例（"语气极其愤怒，压迫感强，语速偏快"）未成模板 |
| seed-tts-2.0-expressive | `req_params.additions.context_texts`（**只有第一个值有效**，不计费）＋ **Cot 标签 `<cot text=急促难耐>…</cot>`**（`additions.use_tag_parser=true`，单句内生效，含标签 <64 字符）＋ `audio_params.emotion` + `emotion_scale`（1~5，默认 4，仅部分音色） | 指令式句子 + Cot 标签 + 独立情绪参数 | 标签写成 `[标签，标签]` 方括号前缀（非官方形式）；`emotion/emotion_scale` **从不传** | Cot 语法未用；情绪参数未用；`model=expressive` 与 `context_texts` 是否互斥需实测 |

> **实测校正（§9）**：上表"最大空白"里的几条已有结论——`<#x#>` 停顿与 `emotion` 在百炼通道可用；stepaudio 上限是 500 而非 200；豆包 Cot 生效且不发音，**`[标签]` 方括号前缀在"不带 `use_tag_parser`"的形状下会被朗读出口**（生产形状另说，见 §13）；`model=expressive` 与 `context_texts` 不互斥；qwen3-tts 的 `parameters.instructions` 不被拒但关键词式情绪未产出表演。
>
> **写法层实测校正（§11 B1、§12 B2，2026-10-10 同日完成）**：①**正文内圆括号标签是干净的停顿通道**——MiMo b1e 与 stepaudio s3 各自 3/3 未被朗读且显著拉长产出；豆包侧 `[方括号]` 前缀在不带 `use_tag_parser` 时 3/3 被朗读出口（**生产的精确形状尚未实测，见 §13**）。②**情绪提示词的效力排序（仅 MiMo 有人耳真值）**：官方【角色】【场景】【指导】三段式 ≈ 动机前置式 ＞ 物理量式 ≈ 正文标签 ＞ 关键词式（关键词式仍略胜于念稿基线）。③**同一套写法搬到 qwen3-tts-flash / 豆包 `context_texts` 后，时长层面全部无信号**，`optimize_instructions=True` 同样无信号——写法红利是**模型特异**的，不能跨模型移植。④**时长判据是非对称的**：放大＝采纳的充分证据，不放大≠未采纳；各基线自身三轮极差可达 1.28×。⑤豆包单向 HTTP 兜底**能出音频**，此前失败是请求头多带 `X-Api-App-Key` 所致（§12.2）。
>
> **写法层首个结论（§11 B1，MiMo，人耳已裁定）**：**【角色】+【场景】+【指导】三段式与"动机前置＋物理量"两种写法效果最好**，正文内圆括号标签的停顿自然且不发音；单个抽象情绪词（`克制悲伤`）只带来可听但很弱的增量，不能当主控制手段。上表 mimo 基座一行的"最大空白"里，复合情绪／字粒度重音仍未测，但**首要缺口已经换了性质**：不是语法不支持，而是我方装配的指令信息量太低。
>
> **3.1 形状实测（§20 B3，2026-10-11）**：**全角圆括号舞台提示在 3.1 上会被朗读出口**（q5/q6 两轮一致），所以上面①那条"圆括号是干净通道"只对 MiMo／stepaudio 成立，**不能当作跨模型规则**；而**官方半角方括号控制类标签 `[sad]` 在 3.1 上被解析、不发音，并把发声量拉长 56%（字数不变）＝表演放慢**，与 instruction 叠加同样干净。3.1 本轮 6/8 写法三轮 md5 逐字节相同、极差 1.000，供应商抖动远小于 §12 观测到的 1.28× 量级。**人耳盲听（§22）改写了这条的落点**：耳裁 `[sad]` 标签写法最强、动机式 instruction 次之、三段式与念稿基线并列最弱——时长放大排序与耳裁同向，而**主评 doubao 把最强那条听成了"无哭腔"**（首个假阴性样本，方向与 qwen3.8 的假阳性相反）。**取值层已闭合（§23 B4，2026-10-13）**：官方 23 控制类＋7 富语言类**逐个实测均不发音**（30/30 `leak=0`，含带空格的英文多词标签），按发声量排 `[like dracula]` 1.91× ／ `[very slowly]` 1.88× 最强、`[very fast]` 0.79× 反向可用；`[sad]` 段首一枚只有 1.21× 而逐句 1.56× ⇒ **作用域止于句界，生产必须逐句下标签**；`[mischievously]` 1.01×／`[empathetic]` 0.99×／`[snorts]` 1.09× 客观层无信号，只能由耳朵定档。**耳朵已经定完（§23.5–§23.7）**：强 18／弱 10／无 1，客观无信号那三条全部落弱档（两轴可自动淘汰得到验证），但 `[shouting]` 发声量倒数第四却判强（Δ响度 +2.16 dB 全场最高）证明**粗排必须"发声量＋绝对响度"两轴一起看**，而 `[like dracula]` 1.91×、`[very slowly]` 1.88× 双双判弱证明"只放慢不加力"耳朵不给分；`[whispers]`/`[asmr]` 把音量压低 9–10 dB 实现干净却判无/弱 ⇒ **"变轻"是独立用途，不能按强度淘汰**。

---

## 1. qwen3-tts-instruct-flash
- **字段**：`instructions`（string，可选）、`optimize_instructions`（boolean，默认 false，对 instructions 做语义增强重写；instructions 为空时不生效）。官方非实时文档把两者列在 **`input` 属性**下；本项目发在 `parameters`（`_aliyun_mixin.py:2232-2242`）。→ 位置差异必须实测确认（是否被静默忽略），不能凭 200 就当生效。
- **上限**：`instructions` **不超过 1,600 Token**，仅支持中文和英文，仅 Instruct-Flash 系列。档案 `instruction_budget=600`（`tts_model_ids.py:128`）**无官方依据**；官方 600 是"非千问-TTS 模型 **text** 上限 600 字符"，与千问-TTS text 512 Token 同段，极易误抄。
- **韵律**：该请求体不含 volume/rate/pitch；`language_type` 枚举 `Auto/Chinese/English/German/Italian/Portuguese/Spanish/Japanese/Korean/French`。SSML 支持清单**未列入本模型**；`<#>`、phoneme/拼音、`hot_fix` 均**未找到官方依据**（low）。
- **官方示例原文**（逐字）：
  ```python
  instructions='The speaking speed is fast and there is a distinct upward inflection, which is suitable for introducing fashionable products.'
  optimize_instructions=True
  voice="Cherry"; text="Dear listeners, hello everyone. Welcome to the evening news."
  # 中文注释示例：instructions='语速较快，带有明显的上扬语调，适合介绍时尚产品。'
  ```
- **实测（G1，2026-10-10）**：`instructions` 发在 `parameters` **未被拒**，HTTP 200 且时长随指令分化（无指令 3360 / "克制悲伤" 4000 / "明快雀跃" 3680 ms），ASR 逐字一致、没有读出指令文本；但在 `optimize_instructions=False` 下，关键词式情绪**没有产出可听表演**（用户听辨："语气无低落感、句尾没下沉，等于没实现"）。→ 位置问题已解决，效果问题留给 §10 B1。
- 来源：本地 `raw/_short/qwen-tts-api-88cc336b17a3a583.md:219-275`、`models/groups/qwen3-tts-instruct-flash.json` samples；`https://help.aliyun.com/zh/model-studio/non-realtime-tts-user-guide` — high

## 2. qwen-audio-3.1-tts-flash

- **字段**：非实时 HTTP `input.instruction`（string，可选），官方原文「设置指令，用于控制方言、情感或角色等合成效果」；SDK/WS 走 `SpeechSynthesizer(..., instruction=...)`。**官方未标 instruction 长度上限**（"最大输入长度：—"），我们的 1200 是本地保守值（`tts_model_ids.py:139`）。
- **情绪**：官方指令控制章节列 `qwen-audio-3.1-tts-flash、qwen-audio-3.0-tts-plus、qwen-audio-3.0-tts-flash`，「系统音色和声音复刻音色：均可输入任意指令」。**另有第二条通道**：「情感与富语言标签」直接写进 `text`，仅这三档模型支持。**「可与 instruction 叠加」是我方早先的转述，官方该章节并未给出叠加保证（2026-10-11 复核原文）**，故叠加效果列为 B3 q8 的实测项（**§20 已实测：叠加形状合法、逐字干净**）。官方示例原文：
  ```text
  [excited]今天的天气真不错！[laughing]我们一起出去玩吧！
  ```
- **标签词表（2026-10-11 从官方《非实时语音合成》用户指南取全；本地 `bailian-docs-llm-wiki` 镜像只到「细粒度标签控制能力」这句话，未收录词表本身）**：
  - 控制类 23 个：`[sad]` `[amazed]` `[deep and loud shouting]` `[trembling]` `[angry]` `[excited]` `[sarcastic]` `[curious]` `[like dracula]` `[bored]` `[tired]` `[scornful]` `[shouting]` `[asmr]` `[panicked]` `[mischievously]` `[empathetic]` `[whispers]` `[reluctantly]` `[crying]` `[serious]` `[very slowly]` `[very fast]`
  - 富语言类 7 个：`[gasp]` `[sighing]` `[clears throat]` `[giggles]` `[laughing]` `[cough]` `[snorts]`
  - 官方作用域原文：控制类作用于标签之后的文本，「直到遇到下一个控制类标签或句子被自动切分」；富语言类在当前位置插入拟声效果、不干扰前后文风格。止于句界还是整段官方未明说 → B3 的 q7/q8 **逐句下标签**，两种解释下都覆盖全文。
- **韵律**：`volume` 0–100（默认 50）、`rate` 0.5–2.0（SDK 名 `speech_rate`）、`pitch` 0.5–2.0、`seed` 0–65535、`language_hints`（16 值，仅首个生效）。`enable_ssml=true` 时本模型在 SSML 支持清单内：`<break time="2s"/>`（s∈[1,10]、ms∈[50,10000]，连续累加上限 10 秒）、`<phoneme alphabet="py" ph="dian3 dang4 hang2">典当行</phoneme>`、`<sub alias="网络协议标准">W3C</sub>`；非 SSML 兜底 `hot_fix`：`{"pronunciation":[{"天气":"tian1 qi4"}],"replace":[{"今天":"金天"}]}`。`<#>` 未找到官方依据。方言走指令，例 `请用河南话表达`。
- **缺口**：**未找到** qwen-audio-3.1-tts-flash 带 instruction 的官方逐字示例（samples 均为无 instruction 调用）。
- **实测（G7，2026-10-10）**：`[excited]` 写在 `input.text` 中**不会被朗读出口**（ASR 转写干净，4560 ms vs 纯 instruction 4320 ms）；但本轮把它和"悲伤克制"指令对立下达，无法据此判断标签是否改变表演——**该条测试设计失效，需按官方示例同向重做**。
- 来源：`raw/_short/qwen-audio-tts-http-api-6a5232db21a53ba2.md:189-195`、`https://help.aliyun.com/zh/model-studio/ssml-latex-user-guide` — high（"未找到"亦为事实）

## 3. cosyvoice-v3.5-plus

- **字段与上限**：WS `parameters.instruction` / HTTP `input.instruction`。官方原文：「指令文本长度限制：**不超过 100 字符**。汉字（含简/繁、日文汉字、韩文汉字）按 **2 个字符**计算，其他字符（标点、字母、数字、日韩假名/谚文）按 1 个字符计算」；超限报 `428`（`[tts:]Engine return error code: 428`）。
- **代码事实（纠正一次子代理误判）**：本项目**已按加权口径**计量——`_aliyun_mixin.py:980-991` 与 `tts_prompt_strategy.py:153-170` 均 `ord(char)>127 → 2 单位`，因此中文实际上限约 **55 个汉字**。这是硬设计约束：CosyVoice 的提示词必须走"极短指令 + 关键词"路线，不能照抄千问/米默的长导演描述。
- **模型差异**：v3.5-plus/flash「声音复刻/设计音色：可输入任意指令」；「系统音色：v3.5 不支持系统音色」。指令语言支持中/英/法/德/日/韩/俄/葡/泰/印尼/越。韵律：`volume` 0–100、`rate/pitch` 0.5–2.0、`bit_rate` 6–510、`seed`、`word_timestamp_enabled`（含 v3.5-plus 复刻音色）、SSML（仅北京地域＋复刻音色）、`enable_markdown_filter`。
- **官方示例原文**（带 instruction 的 curl 属 **cosyvoice-v3-flash**）：
  ```json
  {"instruction": "请用河南话表达。", "text": "叫你去买盐，你买回来一袋面，这不是弄啥嘞吗！", "voice": "longanhuan_v3"}
  ```
  v3.5-plus 的官方 samples 只演示声音复刻（`synthesizer.call("How is the weather today?")`），**不带 instruction** → v3.5-plus 带 instruction 的逐字示例：未找到。
- **可复用的官方声音描述维度示例**（未绑定模型，逐字）：`标准播音风格：吐字清晰精准，字正腔圆`；`温柔知性的女性，30 岁左右，语调平和，适合有声书朗读`；`沉稳的中年男性，语速缓慢，音色低沉有磁性，适合朗读新闻或纪录片解说`。

## 4. minimax-speech-2.8-hd / turbo（经百炼通道）

- **通道**：本项目用 `DASHSCOPE_API_KEY` 经百炼 multimodal-generation 调 `MiniMax/speech-2.8-hd|turbo`（`_minimax_mixin.py:236`）。因此**能力面以百炼文档为准**，MiniMax 官方文档只作上限参考。
- **百炼官方页字段**（`input.voice_setting`）：`emotion` ∈ `happy/sad/angry/fearful/disgusted/surprised/calm/whisper`，**2.8-hd/turbo 不支持 `whisper`**；`speed` [0.5,2.0] 默认 1.0；`vol` (0,10] 默认 1.0；`pitch` [-12,12] 整数默认 0；`text_normalization`、`latex_read`（需 `$$…$$`）。另有 `pronunciation_dict.tone`（`"处理/(chu3)(li3)"`）、`language_boost`（`auto` 或 40 语种含 `Chinese,Yue`）、`timbre_weights`（≤4 音色，weight 1–100）、`voice_modify`（pitch/intensity/timbre [-100,100] + `sound_effects`：`spacious_echo/auditorium_echo/lofi_telephone/robotic`）。
- **语气词**：百炼示例正文直接用括号 `(laughs)`；MiniMax 官方称 2.8 系支持约 19–20 个括号语气词（`(laughs)(chuckle)(sighs)(gasps)(breath)…`）。**`<#x#>` 停顿标签仅 MiniMax 官方文档有（0.01–99.99 秒，≤2 位小数，不可连用），百炼页未列出 → 是否透传必须实测**（medium）。
- **无自然语言风格 prompt**：官方 T2A 没有角色/情绪自由文本字段，风格只能靠枚举＋括号标签＋参数（voice-design、music 才有 prompt，非 T2A）。
- **官方示例原文**（逐字，百炼页非流式）：
  ```json
  {"model": "MiniMax/speech-2.8-hd",
   "input": {"text": "今天是不是很开心呀(laughs)，当然了！",
     "voice_setting": {"voice_id": "male-qn-qingse", "speed": 1, "vol": 1, "pitch": 0, "emotion": "happy"},
     "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
     "pronunciation_dict": {"tone": ["处理/(chu3)(li3)", "危险/dangerous"]},
     "subtitle_enable": false}}
  ```
- **代码事实**：`_aliyun_mixin.py:1170-1189` 仅发 `voice_setting.speed/vol`，`pitch` 恒为 0；`tts_style_control.py:585-632` 走 basic 并输出降级告警"MiniMax basic 模式不支持自然语言/标签风格控制"。`_minimax_mixin.py` 里的 emotion 枚举（`_constants.py:119-121`）与 `MINIMAX_INTERJECTIONS`（`:124-129`）**不在 aliyun 路由链上**，属未用旁路。
- **实测（G2，2026-10-10）**：`input.voice_setting.emotion` 经百炼通道**被接受**（calm 5000 / sad 5793 ms，均 HTTP 200、转写干净）；`<#1.5#>` 连用两处 → 8249 ms 且转写中不出现"1.5"或标签字符，**定时停顿确实生效**。档案 `style_control_modes:["basic"]` 与该模型的降级告警不成立。
- 来源：`https://help.aliyun.com/zh/model-studio/minimax-synchronous-speech-synthesis-api`、`https://platform.minimaxi.com/docs/api-reference/speech-t2a-http`、`.../guides/speech-t2a-websocket` — high

## 5. mimo-v2.5-tts 三变体

- **请求形态**：OpenAI 兼容 `POST https://api.xiaomimimo.com/v1/chat/completions`。**台词文本放 `assistant` 消息 content（官方明文"不可放 user"）**；风格指令/音色描述放 `user`。`audio` 对象含 `format`(wav/mp3/pcm16)、`voice`、`optimize_text_preview`。
- **标签语法**：句首风格标签 `(风格)`，半角 `()`、全角 `（）`、`[]` 均可；**多风格在同一括号内并列，分隔符不限**；**支持自定义风格**；唱歌须写 `唱歌/sing/singing`（仅基座）。句中可在任意位置插入标签，官方样例用全角括号：`（紧张，深呼吸）（长叹一口气）（苦笑）（咳嗽）`；**未要求成对闭合**。官方风格表分类：基础情绪／复合情绪／整体语调／音色定位／人设腔调／方言／角色扮演／唱歌。"micro tags"一词官方未出现。
- **模式核对（重要）**：官方只有两条通道——自然语言控制（含"导演模式"，都是 `user` 消息）与标签控制（`assistant` 消息）。**导演模式不是独立 API，是自然语言的进阶写法**，按【角色】【场景】【指导】三段描述。我方档案 `director/audio_tags/natural_language` 三分法不冲突，但须记住 director ⊂ 自然语言。
- **复合情绪官方原文**：「支持"压抑的愤怒""带着哽咽的笑意""温柔但疲惫""狂躁中的狂气中的温柔"等复合情绪，而非只能选单一情绪」；粒度官方为「段落级→句子级→词级（重音）→字粒度」，均通过自然语言指令下达（词级控制成立）。
- **voicedesign**：`user` 消息即音色描述（维度：性别年龄／质感／情绪语气／语速节奏，情绪可写入），建议 1–4 句、避免矛盾特征与后期效果词；不支持 `audio.voice`、不支持唱歌。**档案 `voice_design_instruction_mode: voice_description_first` 官方查无此说法**（low）；该模式下风格标签是否生效官方未明。
- **voiceclone**：`audio.voice` 必填 `data:{MIME};base64,<纯 Base64>`，仅 mp3/wav，Base64 ≤10MB；支持 `user` 自然语言指令与音频标签；不支持唱歌／预置音色／音色设计。参考音频时长要求官方未提供。
- **规格**：上下文 8K、最大输出 8K token，RPM 100／TPM 10M；方言：东北／四川／河南／粤语；预置音色中英 9 款；仅基座低延迟真流式（需 pcm16），voicedesign/voiceclone 完成后一次性流式返回；计费限时免费（`price_per_10k=0.0`，`limited_time_free`）。
- **风险提示**：官方文档横幅称 `mimo-v2.5`／`v2.5-pro`（**文本**模型）2026-10-14 起自动转发 V2.6、10-21 下线；TTS 系列未见下线公告（medium）。开跑前需再确认一次。
- **实测（G6，2026-10-10）**：`messages` 按官方拆分（`user`=风格、`assistant`=台词）可用；单情绪词"愤怒"**未产出可听愤怒**（用户听辨："声音温婉平缓、重音弱"），"压抑的愤怒"未经听辨确认。两条 1280 / 1120 ms，转写均干净，风格词没有被朗读。
- **实测（B1 写法批次，2026-10-10，见 §11）**：同一台词下，`克制悲伤` 这类**单个抽象情绪词的产出与"不做额外表演"基线无法区分**（3.52s vs 4.05s，三轮极差 0.48s），与 G6a 的人耳裁定相互印证；三段式／动机式／物理量式／正文标签都显著改变了产出（1.34–2.12× 时长），且 `（深呼吸）（停顿）` **3/3 轮均未被朗读出口**。
- 来源：`https://mimo.mi.com/docs/zh-CN/api/audio/tts`、`.../quick-start/usage-guide/audio/speech-synthesis-v2.5`、`.../quick-start/summary/model`（2026-10-08 更新） — high

## 6. stepaudio-3-tts

- **instruction**：请求体**顶层** `instruction`（自然语言，非枚举）。官方原文：「仅在使用 `stepaudio-2.5-tts`、`stepaudio-3-tts` 时生效；2.5 最大 200 个字符，**3-tts 最大支持 500 个字符**」。WS 侧同名字段在 `tts.create` 的 `data.instruction`。**档案与代码写 200 是上一代限制**（`_aliyun_mixin.py:38`）。
- **正文内标签**：半角圆括号 `()`，官方原文「括号 `()` 内的内容将作为指令处理，**默认不发音**；如需发音，请勿使用括号包裹」。→ 不存在 `input.parentheses` 字段，指令直接写在 `input`/`data.text` 文本里（我们代码用 `build_stepaudio_inline_prefix` 拼前缀，位置正确）。
- **不支持**：`voice_label{language/emotion/style}` 枚举**传 3-tts 会报错**，且三字段互斥不可组合（只服务 `step-tts-2`/`step-tts-mini`）；无 pitch／音调参数；"复合情绪""micro tags""词级韵律控制"**均无官方依据**（官方仅有词级时间戳与 `pronunciation_map` 词级发音修正）。
- **其他参数**：`speed` 0.5–2（默认 1.0）、`volume` 0.1–2.0（默认 1.0）、`sample_rate` 8000/16000/22050/24000/48000（默认 24000）、`response_format` wav/mp3/flac/opus/pcm、`text_normalization` standard/enhanced、`markdown_filter`、`return_url`、`stream_format` sse/audio；`input` 上限 **1000 字符**；流式支持 HTTP SSE 与 `wss://api.stepfun.com/v1/realtime/audio`；多音字 `pronunciation_map.tone` 示例 `["阿胶/e1胶","扁舟/偏舟","LOL/laugh out loudly"]`。
- **官方示例原文**（逐字；注意均标在 2.5-tts 标签页，官方**未给 3-tts 专属示例**）：
  ```text
  instruction="语气极其愤怒，压迫感强，语速偏快"
  input="（冷笑）你以为我们阶跃星辰北京公司的技术是开玩笑的吗！"
  WS tts.create: instruction="语气冰冷，压迫感强，语速偏慢"
  WS 文本事件: text="（拍桌子）你以为我们阶跃星辰北京公司的技术是开玩笑的吗！"
  {"model":"stepaudio-2.5-tts","input":"2025 年第 4 季度营收同比增长 18.6%，约合 12.3 亿元。","voice":"cixingnansheng","text_normalization":"enhanced"}
  ```
- **实测（G3，2026-10-10）**：244 字 `instruction` → HTTP 200 并正常出音频（3024 / 2928 ms，同文本对照只差 96 ms），**官方 500 字上限为真**，代码里的 `_truncate_stepaudio_instruction` 200 自限可直接上调。
- 来源：`https://platform.stepfun.com/docs/zh/api-reference/audio/create-audio`、`.../audio/ws-audio`、`.../guides/models/stepaudio-3-tts`、`.../guides/developer/tts` — high

## 7. seed-tts-2.0-expressive（豆包，火山方舟）

- **模型位**：`req_params.model` 取 `seed-tts-2.0-standard`（默认）/ `seed-tts-2.0-expressive`。官方原文：「表现力增强版本…支持语音指令 QA 和语音标签 Cot 能力，**存在效果抽卡的情况**」。鉴权头 `X-Api-Resource-Id: seed-tts-2.0`（或复刻 `seed-icl-2.0`）。
- **语音指令**：`req_params.additions.context_texts`（string 数组），官方定义「语音合成的辅助信息，用于模型对话式合成」，且「**当前字符串列表只第一个值有效**」「该字段文本不参与计费」。最佳实践页给的是 Query-Response 片段（`["我才不难过呢，那个人太渣了。"]`）与指令式句子（`["用最悲伤的语气演绎下面这句话："]`）。
- **⚠️ 冲突必须实测**：现行 HTTP/WS 文档写「（model）仅当 speaker 为**复刻音色**时需指定此参数，**且指定后不支持使用语音指令 context_texts**」，与历史文档/RTC 文档"expressive 支持 QA"矛盾（medium）。这直接决定 B 组能否同时用 `model=expressive` ＋ `context_texts`。
- **Cot 标签**：`additions.use_tag_parser=true`（默认 false），正文在 `req_params.text`。官方原文与示例：「支持单组和多组 cot 标签：`<cot text=急促难耐>工作占据了生活的绝大部分</cot>，只有去做自己认为伟大的工作，才能获得满足感。<cot text=语速缓慢>不管生活再苦再累，都绝不放弃寻找</cot>`」；限制：「单句的 text 字符长度最好小于 64（cot 标签也计算在内）」「cot 能力生效范围是**单句**」「仅适用于豆包声音复刻大模型 2.0 的表现力增强版本」。RTC 侧另给双大括号形式 `{{"additions":{"context_texts":["自然语言描述"]} }}`，并注明「末尾 `}}` 前必须留一个空格」「标签须置于所作用句子前面，作用于所在子句及之后直到新标签」「首句建议纯文本以优化首帧」。
- **独立情绪参数**：`req_params.audio_params.emotion`（如 `"angry"`）＋ `emotion_scale` **1–5（默认 4）**；「仅部分音色支持，不同音色支持范围不同」。中文多情感音色枚举：生气／冷漠／恐惧／开心／厌恶／中性／悲伤／沮丧；英文：neutral/happy/angry/sad/excited/chat/ASMR/warm/affectionate/authoritative。
- **韵律**：`audio_params.speech_rate` [-50,100]（100=2.0 倍）、`audio_params.loudness_rate` [-50,100]、`additions.post_process.pitch` [-12,12]；停顿 `additions.silence_duration` 0–30000ms（仅句尾）；注音 `additions.pronunciation_dict.tone`（`"北京/(bei3)(jing1)"`，≤5000 词条、原词 ≤9 字符、与 SSML 互斥）；`additions.max_length_to_filter_parenthesis`（默认 0 不过滤）——**说明括号在豆包是"过滤对象"而不是控制语法**。
- **SSML**：`req_params.ssml`（与 text 二选一、优先级更高），`<break time>`（仅 time）、`<phoneme alphabet="py">`、`<say-as>`、`<sub>`、`<soundEvent>`、`<speak>` 属性 `bgm`/`backgroundMusicVolume`/`effect`；限制：双向流不支持、仅中文普通话音色、含标签合成 ≤150 字符、`_saturn_bigtts` 结尾音色不支持；历史文档称 **TTS 2.0 与 ICL 2.0 音色"暂不支持" SSML**。
- **其他**：文本长度上限官方**未给明确数字**（仅有错误码 `40402003 TTSExceededTextLimit`）；格式 mp3/pcm/ogg_opus/wav，采样率 8000–48000，`bit_rate` 64000–160000；语种 `additions.explicit_language`（zh-cn/en/ja/ko/es-mx/id/pt-br + 30 语扩展）、`explicit_dialect`（历史文档仅 `zh_female_vv_uranus_bigtts` 支持东北/陕西/四川）；Vivi 2.0 等音色标「方言：粤语、上海、河南、北京、天津、四川、陕西、东北」「支持能力：指令遵循」；`enable_subtitle` 仅中英。
- **官方示例原文**（现行 HTTP 页 cURL）：
  ```bash
  curl -N -X POST 'https://openspeech.bytedance.com/api/v3/tts/unidirectional' \
    -H 'X-Api-Key: your_api_key' -H 'X-Api-Resource-Id: seed-tts-2.0' \
    -H 'Content-Type: application/json' -H 'Connection: keep-alive' \
    -d '{"req_params":{"text":"你好，这是一个语音测试","speaker":"zh_female_vv_uranus_bigtts",
         "audio_params":{"format":"mp3","sample_rate":24000}}}'
  ```
  历史 V3 示例（含 model 位）：`{"req_params":{"speaker":"YOUR_VOICE_ID","model":"seed-tts-2.0-expressive"},"additions":{"use_tag_parser":true}}`
- **代码事实**：`emotion`/`emotion_scale` 从不发送（`_aliyun_mixin.py:1472-1477` 只发 format/采样率/bit_rate/`speech_rate:0`/`loudness_rate`）；标签走 `[标签，标签]` 方括号前缀（`tts_style_control.py:559`），**与官方 Cot 语法不一致**；档案写的 `req_params.use_tag_parser` 路径也不准确（实际在 `req_params.additions.use_tag_parser`，代码 `_aliyun_mixin.py:161-167` 是对的）。
- **实测（G4/G5，2026-10-10）**：`req_params.model=seed-tts-2.0-expressive` 与 `additions.context_texts` 同时下达**不报 400**、正常出音频（无指令 3072 / 带指令 2832 ms，转写一致）→ 该 speaker 与该通道上"互斥"警告不成立，文档冲突按"可共存"处理；`context_texts` 的情绪引导本身未兑现（用户听辨："整体轻快平淡，没实现"）。`<cot text=焦急难耐>…</cot>`（带引号与不带引号均可）被**解析且静默**：1464 ms，转写中无标签词，并快于无标签基线 1632 ms；而**不带 `use_tag_parser`** 的 `[标签，标签]` 方括号前缀被 ASR 转写成实际字词，**确实被朗读出口**（注意：生产实际发的是"前缀＋`use_tag_parser=true`"这一组合，尚未实测，见 §13）。此外本批 5 次单向流式 HTTP 尝试全部没取到音频（2 次只有字幕帧、3 次因探针侧 `additions` 发成对象被 55000000 拒绝），而同样请求走 WS 6/6 出音频；**HTTP 能否出音频已于同日 §12.2 定性：能，根因是请求头多带 `X-Api-App-Key`**。
- 来源：`https://docs.volcengine.com/docs/DoubaoVoice/unidirectional-streaming-text-to-speech-http`、`https://www.volcengine.com/docs/6561/1598757`、`.../DoubaoVoice/DoubaoTextToSpeech20CapabilityIntroduction`、`.../DoubaoVoice/SoundReplication20BestPractices`、`https://docs.volcengine.com/docs/6348/2139328`、`https://www.volcengine.com/docs/6561/1330194` — high（冲突项标 medium；G4/G5 部分已实测，见上条）

---

## 8. 档案纠错清单（需回写 `MODEL_INTEGRATION_REFERENCE.md` / `tts_model_ids.py`，待批准；括号标注 G1–G7 实测状态）

> **回写状态（2026-10-10 晚）**：本节 1–8 条的**文档部分**已回写进 `docs/MODEL_INTEGRATION_REFERENCE.md` 新增 §11.9（逐条标 `[文档]`／`[字段]`）、§11.10（评审采信分工），并就地更正了 4 处旧表述：§11.4.1 的 `X-Api-App-Key`、§11.4.3 的方括号标签形状限定、§11.4.4 的 `context_texts` 实测补充、§11.6 排查清单里 qwen3-tts 的 404 提示；§14 维护建议已加路由。**所有 `[字段]` 项（stepaudio 200→500 与三个能力位、minimax `basic`、qwen3 budget、mimo `voice_design_instruction_mode`、切 qwen3-tts 默认）一个都没动**，因为改能力位即改生产出站行为，须逐条批准。

1. stepaudio-3-tts：instruction 上限 200 → **500**（✅ G3 已实测：244 字 HTTP 200；✅ 2026-10-11 预算已落地为 500）；`voice_label` 情绪枚举对 3-tts **会报错**；删除"复合情绪/micro tags/词级韵律控制"等无官方依据的描述。
2. qwen3-tts-instruct-flash：`instruction_budget=600` 无官方依据，官方为 **1600 Token**；补 `optimize_instructions` 能力位；确认 `instructions` 究竟进 `input` 还是 `parameters`（✅ G1 已实测：发在 `parameters` 不被拒、影响时长，但关键词式情绪未产出表演，见 §9）。
3. minimax-2.8：档案 `style_control_modes:["basic"]` 与"不支持风格控制"的降级告警**不成立**（✅ G2 已实测：`emotion` 枚举被接受且时长分化，`<#x#>` 停顿确实生效），官方有 `emotion` 7 档＋括号语气词＋注音＋`voice_modify`。
4. seed-tts-2.0-expressive：补 `audio_params.emotion`/`emotion_scale`、Cot 标签语法与 64 字符限制、`context_texts` 只首值有效且不 metered；`use_tag_parser` 路径写进 `additions`。（✅ G4/G5 已实测：`model=expressive` 与 `context_texts` 可共存、Cot 被解析且不发音；另见 §9.4 两条生产缺陷）
5. mimo：`voice_design_instruction_mode` 属自造说法，官方无；导演模式应标注为自然语言的进阶写法；补"台词必须在 assistant"的契约说明。（G6 只测了情绪粒度，未覆盖本条）
6. cosyvoice-v3.5-plus：档案 100 一致，但需注明**加权字符**口径（≈55 汉字）。
7. 新增（G5 实测）：**不带 `use_tag_parser` 的** `[标签，标签]` 前缀会被豆包朗读出口，档案与告警文案须改为标注"该形状产生台词污染，官方语法是 `<cot text=…>` + `use_tag_parser=true`"。（✅ B2 §12.1 d4 三轮复现；⚠️ 生产实际形状＝前缀＋`use_tag_parser=true`，**该组合未测**，回写时必须带这个限定，见 §13）
8. 新增（2026-10-10 晚，B2 期间发现）：`qwen3-tts-instruct-flash` 今日 15:00 同 key 同端点还返回 200，**17:40 起持续 404 `Model not exist`**，但上架目录 `models/groups/qwen3-tts-instruct-flash.json` 仍列有该模型（0.8 元/万字符）。该 ID 同时是生产默认，硬编码在 `app/schemas/audiobook.py:16,28,130,365`、`app/api/v1/projects.py:492,535,632`、`app/services/asset_studio_model_catalog.py:55,90`、`app/api/v1/audiobook_api/routes_segment_regen.py:98`、`app/api/v1/asset_studio_api/_constants.py:64` 等处 → **一旦下架，qwen3 链路会全线失败**。探针已改用同价位在架的 `qwen3-tts-flash`（§12.1 A 组）；是否把生产默认切到 `qwen3-tts-flash` 属配置改动，待裁定。

## 9. G1–G7 实测结论（2026-10-10 门槛批次，已完成真实调用）

三层证据分开记：**客观层**（HTTP 状态码 + ffprobe 时长 + ASR 逐字转写，不依赖耳朵与评分器）→ **评分层**（锚定与盲评两轮）→ **人耳层**（用户听辨裁定，为最终真值）。凡只靠评分层支撑的结论一律标"未确认"。

| 门槛 | 客观证据 | 评分层（锚定 主评/复核 → 盲评 主评/复核） | 人耳裁定 | 结论 |
|---|---|---|---|---|
| G1 qwen3-tts `parameters.instructions` | HTTP 200，三条 3360/4000/3680 ms（sad 最长）；ASR 逐字一致、无指令泄漏 | 5/5、2/2、1/1 → 盲评 5/–、5/4、5/2 | g1b「语气无低落感、句尾没下沉，等于没实现」 | **参数位未被拒、时长有响应，但关键词式情绪指令没有产出表演**；须换官方"场景＋人物状态＋发声方式＋台词处理"句式复测 |
| G2 MiniMax 百炼通道 `emotion` + `<#x#>` | `emotion` calm 5000 vs sad 5793 ms，均 200、转写干净；`<#1.5#>`×2 → 8249 ms 且转写无"1.5"无标签词 | calm 4/5 → 4/3；sad 5/4 → –（schema_invalid）/2 | 未听辨 | **`<#x#>` 定时停顿在百炼通道确实透传并生效（客观确立）**；`emotion` 枚举确立"被接受、时长分化"，情绪效果待听辨；档案 `basic` 降级不成立 |
| G3 stepaudio-3-tts 长 instruction | 244 字 instruction → HTTP 200，3024/2928 ms | 不进评分（纯客观） | — | **官方 500 字上限为真，我方自设 200 无依据** |
| G4 豆包 `model=expressive` + `context_texts` | 无 400，两版 3072/2832 ms，转写一致 | 主评 5 / 复核 1 → 盲评 4/2 | g4b「整体轻快平淡，没实现」 | **文档"互斥"警告在该 speaker 与该通道上不成立（可共存）；`context_texts` 的情绪引导不成立** |
| G5 豆包标签语法 | 探针侧 `[焦急，语速快]` 前缀（**未带 `use_tag_parser`**）被 ASR 转写成「焦急语速快」＝**被朗读**；`<cot text=…>`（带/不带引号）均 1464 ms、转写干净，快于无标签对照 1632 ms | cot 4/3 → 4/2；无标签对照 5/5 → 4/3 | — | **Cot 被解析、不发音、改变时长（客观确立），但相对对照没有可听的"焦急"增益证据**；**方括号前缀在缺 `use_tag_parser` 时确被朗读**；生产的"前缀＋parser"组合未测，见 §13 |
| G6 MiMo 复合情绪 | 单情绪词 1280 ms、复合情绪 1120 ms，转写干净 | 5/1、5/4 → 盲评 5/3、5/2 | g6a「声音温婉平缓、重音弱」 | **单个情绪词不生效**；复合情绪未确认（盲评双方都偏"平淡"） |
| G7 qwen-audio-3.1 `[excited]` | 4320/4560 ms，两条转写均干净 → 标签**没有被朗读** | g7a 5/5 → 4/2；g7b 3/2 → 4/4 | — | **标签不被读出口（客观确立）**；"标签是否改变表演"这条**测试设计失效**（指令要求悲伤、标签要求兴奋，互相矛盾），须按官方示例同向重做 |

### 9.1 评分层可靠性：盲评复测的结论比门槛本身更重要

同一批 13 条音频、同一评分合同，把提示词里的"本轮下达的表演要求"去掉重跑 26 次（2 次 `schema_invalid`，主评复核各 1，失败率 7.7%）。结果：

- **盲评没有修好主评。** 三条已有人耳真值的样本上，qwen3.8-omni-flash 的盲评证据仍然与耳朵相反：g1b 仍称"明显哭腔与颤抖、句尾下坠"，g4b 仍称"委屈质问、声音有轻微颤抖"，g6a 仍称"语气急促带质问感、情绪鲜明"，置信度 0.82–0.95，分数反而比锚定更高。
- **更硬的证据是横向对照。** 同文本、同音色的 g1a（无任何指令）/ g1b（悲伤）/ g1c（明快雀跃）三条，主评盲评**全部给 5 分**并都描述成"哭腔、颤抖、压抑"——包括那条根本没下过指令的基线。它的"可听细节"不随音频变化，属**细节级幻觉**，不只是把指令复述成听感。
- **复核（豆包）在这批上更接近耳朵**（g4b/g6b/g7a 盲评 2 分并描述"平直／表现力弱"），但同样不是逐条可靠：g1b 盲评给 4 且称"句尾音调下沉"（耳朵说没下沉）；g2b 描述"无奈低落、句尾下沉"却只给 2 分，**分数与自身描述矛盾**；g6a 称"句尾带轻微笑意"。
- **方法学警示：两轮分数不可直接比较。** 锚定的 `emotion_match` 定义是"是否实现指令"，盲评的定义是"情绪表达的鲜明程度"，量纲不同；跨轮可比的只有**证据文本**。因此盲评的正确用法是"拿到一份不含指令线索的听感描述，由人对照指令判定"，而不是把两轮分数做差。
- 两模型在 `fidelity` 与 `contamination` 上 13/13 全给 5，与 ASR 客观结论一致（本批未送进评分的 g5a 恰是 ASR 抓到污染的那条），说明它在**可验证维度**上稳定，在**情绪维度**上不可信。

**建议（待你裁定后再落地，属评审流程而非生产配置）**：情绪维度不以 qwen3.8-omni-flash 为主评，改由豆包 Seed 2.1 Lite 承担、人耳作最终真值；qwen3.8 只用于污染/保真类可验证维度。凡"评分器说好"都不得单独作为提示词有效的结论。

### 9.2 本轮实际用量与成本（刊例推算，不等于账单实扣）

| 轮次 | 主评 qwen3.8-omni-flash（0.8/2.7 元·百万 token） | 复核 doubao-seed-2-1-lite |
|---|---|---|
| 锚定 13 次 | 5,873 in / 11,445 out（其中 reasoning 7,588）≈0.036 元，走 100 万 token 免费额度 | 6,104 in / 2,972 out ≈0.09 元 |
| 盲评 13 次 | 6,439 in / 9,217 out（其中 reasoning 5,259）≈0.030 元 | 6,767 in / 3,117 out ≈0.10 元 |

另：生成 18 条 ≈0.1 元（其中 5 次豆包 HTTP 空转无音频 ≈0.02 元已浪费）、ASR 6 份 ≈0.006 元。G1–G7 全流程合计 ≈0.26–0.35 元。

### 9.3 证据留存位置（第二阶段复用，勿删）

- ~~`backend/data/tts_debug/gate_probe_g1_g7/`：18 条音频、`manifest.json`（完整出站 payload + http_status + request_id + usage + duration_ms）、`asr/*.json`、`scores.json`（锚定）、`scores_blind.json` + `blind_sheet.md`（盲评）、`raw/`（5 次豆包 HTTP 无音频的原始响应）。~~
  **2026-10-11 复核：该目录已不存在**（`backend/data/tts_debug/` 只剩 2026-06-25 的 `seed_tts_99_voice_validation_*` 四个文件）。上面这些逐条产物**无法再复核**，本文记录的 G1–G7 时长、HTTP 状态、盲评分数一律按"一次性观测快照"读取，不再当作可追溯原始数据。
- 探测脚本 `backend/app/scripts/probe_tts_capability_gates.py`、`probe_tts_gate_scoring.py`（后者含 `--mode blind`）：**2026-10-11 裁定改为长期留存，不再"第二阶段结束后删除"**。原计划（本节旧文本）是让脚本与证据目录同批清理；证据目录已丢失后，脚本成了门槛结论的唯一复现入口——删掉就再也无法重跑 G1–G7，而 §11.9/§11.10/§11.13 和 `config/models.yaml` 的 stepaudio / seed 档案都引用这些结论。两脚本默认干跑、必须显式 `--confirm-paid` 才发真实请求，留存不产生被动费用。复现口径只到"重新跑一遍拿新数据"，不声称能还原 2026-10-10 那批旧响应。

### 9.4 生产侧缺陷与本次更正

1. **已修复（2026-10-10，附测试）**：`_parse_seed_tts_audio_response` 在"响应全是 JSON 帧但没有任何音频"时，会走到 `if response.content: return bytes(response.content)`，把 NDJSON **文本原样当音频返回**——坏字节会被当成合成成功并写进缓存。现在该分支只在正文确实不是 JSON 帧（可能是缺 content-type 的二进制音频）时才返回原始字节；纯帧响应抛出 `ValueError("Seed-TTS response missing audio data (...)")`，并把供应商错误帧的 `code/message` 冒泡出来。新增三条测试：无音频帧必须报错、错误码 55000000 必须冒泡、非 JSON 二进制仍按音频返回。效果：`_synthesize_seed_tts` 的 WS→HTTP 兜底不再静默产出坏音频，而是清晰失败。
2. **撤回一条我先前的错误结论**：`additions` 发成对象（触发 `55000000 json: cannot unmarshal object into ... req_params.additions of type string`）是**探测脚本手工构造的 payload** 造成的，**生产代码没有这个问题**——`_build_seed_tts_additions` 早已 `json.dumps` 成字符串，WS 路径同样如此，`test_seed_tts_http_call_uses_volcengine_v3_endpoint` 也按字符串断言。该端点要求 `additions` 为 JSON 字符串，这条作为协议事实保留。
3. **已定性（2026-10-10 晚，§12.2 的 15 次单向 HTTP 对照）**：单向流式 HTTP **能拿到音频**。G1–G7 那 5 次空手不是通道缺陷，而是**请求头多带了 `X-Api-App-Key`**——按官方 cURL 逐字构造（只发 `X-Api-Key`/`X-Api-Resource-Id`/`Content-Type`）的 h1/h2 两轮复现出音频，把生产 body 换上官方头（m2）也出音频，把官方 body 换上生产头（m1）就没音频；15 次里"带 App-Key 头 0/4 出音频、不带 11/11 出音频"。修复动作很小：`_call_seed_tts_http` 去掉该头即可（**尚未改动，需批准**）。另注：现有 HTTP 单测的假响应是 `{"audio": base64}` 单对象，与实测到的 NDJSON 帧格式不一致，这条通路的"已验证"程度低于 WS。
4. **未改动（属提示词写法，交由 B 组实测后再落地）**：`<cot text=…>` + `additions.use_tag_parser=true` 是官方语法，实测被解析且不发音；`[标签，标签]` 方括号前缀**在"不带 `use_tag_parser`"的形状下**会被朗读出口（G5 g5a ＋ B2 d4 三轮，共 4 次 ASR 逐字读出标签词，时长 1.40–1.66× 几乎正好对应多读的字）。
   → **2026-10-10 晚复盘生产代码后的自我更正（详见 §13）**：`tts_style_control.py:815-843` 与 `_aliyun_mixin.py:1459-1499` 显示，生产在发 `[标签，标签]` 前缀的**同时**也发 `use_tag_parser=true`，而这个精确组合**从未被实测过**。所以"生产成品里情绪标签被念出来"目前是**推断，不是结论**；d4 的时长放大也不构成"生产的污染代价"。判定它只需 1–2 次生产形状复现（探针已备好 `--batch seed_tag_parser`，待批准）。

## 10. 候选写法矩阵（B 组设计依据；mimo 基座 / stepaudio / 豆包三行已真实测试，其余未测）

| 模型 | B1（最低风险） | B2（官方特性） | B3（叠加） |
|---|---|---|---|
| qwen3-tts-instruct-flash | ✅ **已测（§12.1 B2，因原 ID 404 改在 `qwen3-tts-flash` 上跑）**：三段式/动机式/关键词式时长全部落在噪声带内，`optimize_instructions` 亦无时长信号 | ✅ 已测：`optimize_instructions=True` 不改变产出 | 未测 |
| qwen-audio-3.1-tts-flash | instruction 场景化 | **已实测（§20）**：`--batch qwen31_writing` 的 q7/q8（同向 `[sad]` 逐句）干净且放慢，圆括号 q5/q6 被朗读出口 | instruction ＋ SSML `<break time>` 控停顿（仍未排） |
| cosyvoice-v3.5-plus | ≤55 汉字的"关键词式"指令（`克制悲伤，语速偏慢，句尾下沉`） | 官方声音描述维度句式 | 短指令 ＋ 标点停顿（SSML 需复刻音色＋北京地域） |
| minimax-2.8 | `emotion` 枚举按情绪映射 | `emotion` ＋ 括号语气词 `(sighs)(breath)` | `emotion` ＋ `pronunciation_dict` ＋ `speed` |
| mimo 基座 | ✅ **已测（§11 B1）**：三段式最省力地被采纳，关键词式≈基线 | ✅ 部分已测：正文圆括号标签 3/3 不发音（b1e）；复合情绪／句中细粒度标签待测 | 字级重音指令 |
| mimo voicedesign | 4 维度音色描述（含情绪语气） | 1–4 句精简版对照 | — |
| stepaudio-3-tts | ✅ 部分已测（§12.1 B 组）：500 字预算内的导演句式/动机式/关键词式**时长均无信号** | ✅ **已测：正文圆括号标签三轮 1.20–1.61× 全部高于基线且不被朗读**（唯一有信号的通道） | 分段多标签连续下达（未测） |
| seed-tts-2.0-expressive | ✅ 已测（§12.1 C 组）：`context_texts` 三段式/动机式时长均无信号，与 G4 的"没实现"一致 | ✅ **已测：Cot 标签 3/3 被解析且不发音**；`[标签]` 前缀 3/3 被朗读出口 | Cot ＋ `emotion`/`emotion_scale`（未测） |

> 以上每一项都只是**待验证假设**。只有"同文本、同音色、同音频参数，仅提示词不同"的 A/B 生成经人耳确认后才算结论。
>
> G1–G7 只回答了"这条通道存不存在、会不会被静默忽略"，**没有任何一条构成"某种写法更优"的证据**，B 组仍需重新生成与听辨。另按 §9.1 的盲评结论，第二阶段必须换成：**客观层先行（ffprobe 时长 + ASR 转写）→ 盲评描述（不把指令交给评分模型）→ 人耳对照判定**；评分器分数不得单独作为"提示词有效"的结论。

## 11. B1 已完成：MiMo 写法对照（免费批次，3 轮 × 6 条 = 18 次真实调用）

按 §10 的"free-first"原则，第一个写法 A/B 选在**限时免费**的 `mimo-v2.5-tts` 基座上跑，未产生刊例费用。

- 通道：`POST https://api.xiaomimimo.com/v1/chat/completions`，`audio.format=mp3`，音色/参数全一致；**唯一变量是 `user` 消息里的风格指令**（b1e 额外在 `assistant` 正文插入标签）。
- 台词：`我没事。我真的没事，你们都不用管我。`；6 种写法 = 关键词式 / 物理量式 / 官方【角色】【场景】【指导】三段式 / 动机前置式 / 正文内标签 / 最小基线（"用普通自然的语气朗读，不做额外表演"）。
- 18/18 HTTP 200，均出音频；三轮重复专用于观测供应商抖动（官方"表现力增强版本存在效果抽卡"同样适用于该链路）。

| 编号 | 写法 | 三轮时长(s) | 均值 | vs 基线 | r1 ASR |
|---|---|---|---|---|---|
| b1a_keyword | 关键词式（`克制悲伤`） | 3.68 / 3.68 / 3.20 | 3.52 | **0.87×** | 与台词一致 |
| b1b_physical | 物理量式（音量/语速/句尾/气息） | 5.92 / 5.12 / 5.92 | 5.65 | 1.39× | 一致（"没事儿"） |
| b1c_director | 官方三段式 | 8.64 / 8.32 / 8.80 | 8.59 | **2.12×** | 一致 |
| b1d_motivation | 动机前置式（先给角色动机再给物理量） | 6.40 / 5.12 / 6.24 | 5.92 | 1.46× | 一致 |
| b1e_labels | 正文内圆括号标签 | 6.24 / 4.80 / 5.28 | 5.44 | 1.34× | 一致，**标签未出口** |
| b1f_control | 最小基线 | 3.84 / 4.00 / 4.32 | 4.05 | 1.00× | 一致 |

**客观层结论（已证实的部分）**：

1. **关键词式在时长上几乎不改变产出**：0.87× 与念稿基线同量级，三轮极差 0.48s。但**这条已被人耳层部分推翻**（见下方裁定）——用户听出 b1a 确实比 b1f 好一点，只是远不如其他写法。方法论更正：**时长放大是"指令被采纳"的充分证据，但不是"未被采纳"的证据**；写法可以在不改变总时长的前提下改变音质/句尾处理，客观层只能筛掉"完全没反应"，不能筛掉"反应小"。
2. **写法信息量与产出偏移单调相关**：三段式 2.12× > 动机前置 1.46× > 物理量 1.39× > 正文标签 1.34× > 关键词 0.87×。时长放大只证明"指令被采纳并放慢/加停顿"，**不证明好听**。
3. **正文内 `（深呼吸）（停顿）` 三轮 3/3 都没被朗读出口**，与官方"括号内为指令、默认不发音"一致；标签与 `user` 风格消息可并存（b1e 两条通道同时下达）。这条正面反衬豆包侧：方括号 `[标签，标签]` 前缀在缺 `use_tag_parser` 时被 ASR 逐字读出（§9.4 第 4 项、§13），MiMo 的圆括号语法是干净的。
4. **保真度总体干净，长指令有轻微抽卡**：抽检 10 条转写均无指令回显；唯一偏差是 r2 的三段式出现"嗯，没事…"（多插语气词、首字弱化）。样本量 n=1，只够标记为"存在但罕见"的风险，需在 B2 扩大轮次确认是否与指令长度相关。

**人耳层裁定（2026-10-10，用户听辨 18 条）**：

- **b1c 官方三段式与 b1d 动机前置式效果最好**；b1c 被确认为"像表演"，不是刻意拖慢——即 2.12× 的时长放大是有效表演而非虚假信号。
- **b1e 的停顿自然**：正文内标签通道可用。
- **b1a 与 b1f 有差别，b1a 好一些但不如其他几个**：抽象情绪单词**并非完全不被消费**，只是产出增量远小于带物理量/动机/场景的写法。
- 由此得到的 MiMo 首选写法：**把情绪翻译成可执行的物理量＋给出角色为什么这样说**（三段式＝角色/场景/指导，动机前置式＝先因后果），二者并列最优；关键词式只能当弱加分，不能当主控制手段；正文圆括号标签可用来精确安排停顿且不污染文本。

**成本**：MiMo 18 次生成按刊例 `price_per_10k=0.0`（限时免费）计 0 元，manifest 逐条留了 `usage`（如 b1a：136 in / 25 out）以便政策变动后核算；ASR 抽检 10 份 ≈0.01 元。除此之外本轮未发出任何付费调用。

**由裁定引出的下一步（尚未执行）**：

1. **免费可继续的收尾**（MiMo，0 元）：b1a 与 b1f 的"好一些"是否稳定需要更多轮次；三段式 vs 动机前置式在**同一情绪的多个台词**上谁更稳；三段式精简版（砍掉【场景】只留【角色】＋【指导】）能否保住效果、省下半数预算；字级重音（§10 mimo B3）与句中复合情绪标签（B2 剩余项）。
2. **付费模型的 B1**：把已被人耳确认的两种写法搬到 qwen3-tts / qwen-audio-3.1 / 豆包 /（StepAudio 需 `STEP_API_KEY`，当前缺失）。每次都要先给确切次数与刊例估算再取批准——量级参考：G1–G7 的 18 条生成实测 ≈0.1 元。
3. 本批**不再调用 qwen3.8-omni-flash 做情绪主评**（§9.1 已证实其会编造情绪证据）；如需机器描述只跑豆包盲评（6 次 ≈0.05 元，需批准）。

→ 第 2 项已于同日完成，见 **§12**；第 3 项在 §12 的 B2 批次里被彻底执行（B2 未调用任何评分模型）。

## 12. B2 已完成：付费模型写法对照 ＋ 豆包单向 HTTP 通道定性（2026-10-10 晚，用户授权"不用担心费用"）

### 12.1 写法对照：3 轮 × 15 条 = 45 次真实调用，45/45 出音频

把 §11 人耳确认的 MiMo 冠军写法（三段式 / 动机前置式 / 关键词式 / 念稿基线）逐字搬到三个付费模型上，**同台词、同音色、同音频参数，唯一变量是提示词**；每条重复 3 轮以测供应商抖动。本轮**不调用任何评分模型**（§9.1 已证实主评会编造情绪证据），只做客观层，人耳裁定见 `backend/data/tts_debug/b2_paid_writing/listening_sheet.md`（**2026-10-11 复核：听辨从未执行，该批次目录已随产物清理删除；要听必须先按 `--batch b2_paid` 重新生成**，逐条口径见 §12.3 收口说明）。

| 组 | 模型/通道 | 变量位置 | 三轮时长 vs 基线 | ASR（r1 全量转写） |
|---|---|---|---|---|
| A | qwen3-tts-flash（DashScope） | `parameters.instructions` | q1 三段式 0.93/0.89/1.00×；q2 三段式＋`optimize_instructions=True` 1.00/1.07/1.13×；q3 动机式 0.95/0.86/1.05×；q4 关键词 1.05/0.89/1.08×；基线 q5 自身极差 1.13× | 5/5 逐字一致，**零指令泄漏** |
| B | stepaudio-3-tts（`api.stepfun.com/v1/audio/speech`） | 顶层 `instruction` | s1/s2/s4 全部 0.86–1.28×，落在噪声带（基线 s5 自身极差 1.28×） | 一致；s1「我没事儿」属口径差异 |
| B | 同上 | **正文圆括号标签** ＋ 三段式 | **s3 三轮 1.61/1.30/1.20×，全部高于基线**（三轮极差 1.71，不稳） | 标签**未出口**；首句听成「啊，没事」＝唯一一次首字改写 |
| C | seed-tts-2.0-expressive（WS 双向） | `additions.context_texts` | d1 三段式 1.17/1.06/1.04×；d2 动机式 1.07/0.96/0.94×（无信号） | 一致，无回显 |
| C | 同上 | 官方 **Cot 标签** ＋ `use_tag_parser=true` | d3 1.07/1.00/1.00× | **3/3 标签未被朗读** |
| C | 同上 | `[标签，标签]` 前缀、**不带** `use_tag_parser`（≠生产形状，见 §13） | d4 **1.66/1.40/1.52×** | **3/3 把"克制悲伤，语速偏慢"念出口** |

客观层四条结论（细节见听辨表）：

1. **噪声底比预想大**：三条基线自身三轮极差 1.11–1.28×。所以只有"稳定放大"才算采纳信号，落在 ±15% 内一律记"无信号"，**不得记为"指令未被采纳"**——§11 的人耳裁定已证明这条判据会假阴性（b1a 时长 0.87× 却仍被听出优于基线）。
2. **qwen3-tts-flash 本轮没有任何写法显示出时长信号**，`optimize_instructions=True` 也没有。与 G1 时 `qwen3-tts-instruct-flash` 出现 3360/4000/3680ms 分化形成对照——**换模型 ID 后情绪通道像被关掉了**，须在人耳层之后决定是否值得用 instruct-flash 复测（若该 ID 真已下架则无法复测）。
3. **正文内圆括号标签在第二个模型上再次验证为干净通道**（stepaudio s3 不被朗读、且显著拉长产出），与 MiMo b1e 一致；这条比顶层自然语言 instruction 更容易被"看见"。
4. **豆包 d4 证实的是"缺 parser 的形状"，不是生产**：`[标签，标签]` 前缀在 `additions` 为空时 3/3 被朗读，多出的时长几乎正好对应多读的字；d3 官方 Cot 语法 3/3 干净。但**生产同时发前缀和 `use_tag_parser=true`**，该组合的表现仍未实测——见 §13 的更正与最小判定实验。

### 12.2 豆包单向流式 HTTP：能出音频，根因是我方多带了一个请求头

按官方 cURL 逐字构造的最小请求（`POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`，只发 `X-Api-Key` / `X-Api-Resource-Id: seed-tts-2.0` / `Content-Type`），**稳定拿到音频**；随后逐个把生产 payload 的字段加回去做控制变量，15 次探测：

| 变量组合 | 用例 | 结果 |
|---|---|---|
| 官方 body ＋ 官方头 | h1（官方 speaker `zh_female_vv_uranus_bigtts`）、h2（生产 speaker）、i1（＋`req_params.model`）、j1–j4（＋`text_type`/`with_timestamp`/`speech_rate`+`loudness_rate`/`user.uid`）、k1–k3（多字段叠加） | **11/11 出音频**（3.6–4.4s） |
| 生产 body ＋ 官方头 | m2 | **出音频 4.272s** |
| 任意 body ＋ 含 `X-Api-App-Key` 的生产头 | h3、i2、k4、**m1（官方 body＋生产头）** | **0/4 出音频**：HTTP 200，响应只有字幕帧（`code:0` 带整句文本、`data:null`）＋ `code:20000000 OK` |

- 错误归因链值得留档：先怀疑 `req_params.model`（i1 证伪）→ 再怀疑 `text_type`/`with_timestamp`/rates/`user`（j1–j4、k1–k3 全部证伪）→ 最后靠 m1/m2 对照才定位到**请求头**。**教训：控制变量必须同时覆盖 headers，只控 body 会归因错。**
- 机制未查明，不编造：带 App-Key 时服务端只回文本帧、不回音频帧，可能是该头把会话路由到"仅字幕"，也可能与 resource-id 组合冲突。对结论不影响：**去掉 `X-Api-App-Key` 就能让 HTTP 兜底真正拿到音频**。
- 修复范围很小、本轮未动：`_call_seed_tts_http` 请求头去掉 `X-Api-App-Key`，WS 路径保持不变（WS 用同一套头一直正常出音频，说明该头只在 HTTP 端有害）。**属生产代码改动，待批准。**
- 更正 §9.4 第 3 项："HTTP 能否出音频仍未定性" → **已定性：可以出音频，是我方请求头问题**。

### 12.3 用量、成本与证据位置

- qwen3-tts-flash 15 次：`usage.characters` **恒为 33**（等于台词长度，**说明 instruction 不进该计费字段**），按目录价 0.8 元/万字符 ≈ **0.04 元**。
- stepaudio-3-tts 15 次：响应无 usage，按字符量 ≈330 字符、本仓库既有档案单价 2.5 元/万字符 ≈ **0.08 元**（该单价来自 `TTS_PROMPT_OPTIMIZATION_AND_OMNI_SCORING_PLAN_20261010.md:167`，非本轮独立核实）。
- 豆包 WS 15 次：无 usage，≈300 字符、档案单价 3.0 元/万字符 ≈ **0.09 元**；`context_texts` 官方标注不计费。
- 豆包 HTTP 探测 15 次：4 次 200 但无音频（浪费），11 次出音频。
- ASR 客观转写 15 份（q/s 10 ＋ d 5）。**本轮未调用任何评分模型，0 次评分支出。**
- 以上均为**刊例推算，不等于账单实扣**。
- 证据：`backend/data/tts_debug/b2_paid_writing{,_r2,_r3}/`（45 条音频 + manifest 全量出站 payload/status/request_id/usage/duration_ms + `listening_sheet.md`）、`backend/data/tts_debug/seed_http_shape/`（11 个音频 + 4 份 `raw/*.txt` 无音频响应原文 + manifest）、`b2_duration_summary.json`。

**2026-10-11 收口说明（本节及 §12.1/§12.2 全部逐条数字的读取口径）**：上述批次目录与 `b2_duration_summary.json` 已全部删除，`backend/data/tts_debug/` 现在只剩 2026-06-25 的 `seed_tts_99_voice_validation_*` 四个文件。因此本节的 45 条时长倍数、ASR 逐字结果、`usage.characters` 恒为 33 等一律按**一次性观测快照**读取，不可再复核；要重新取证需 `python -m app.scripts.probe_tts_capability_gates --batch b2_paid`（45 次合成 ≈0.2 元 ＋ 15 次 ASR，执行前需批准）。与 §9.3 的 G 批同款处置。

### 12.4 需要用户拍板的三件事

1. **听辨 B2 的 15 条**（重点：q1 vs q2 是否有差别、s3 的停顿与"啊，没事"、d1/d2/d3 相对 d5 是否更克制、d4 是否真听到了标签被念出来）→ 决定哪种写法进生产。（2026-10-11：音频已删除，本项前置条件是重跑批次，见 §12.3 收口说明）
2. **是否批准 `_call_seed_tts_http` 去掉 `X-Api-App-Key`**（本轮新发现，不在既有授权措辞内；改动＝1 个请求头 + 1 条测试）。
3. **`qwen3-tts-instruct-flash` 已从端点消失但仍是生产默认**（§8 第 8 项）：切默认到 `qwen3-tts-flash`，还是先向上游确认该 ID 状态？注意 §12.1 显示 `qwen3-tts-flash` 对情绪指令**无时长响应**，切过去可能同时丢掉情绪控制面。

## 13. 自我更正：豆包"生产污染"结论越界了（2026-10-10 晚，复盘生产代码后）

### 13.1 错在哪

今天多处写过"**生产在用的 `[标签，标签]` 前缀会被朗读出口，是成品级污染**"。复盘代码后发现这句话把两件事合并了：

| | 探针发过的形状 | 证据 |
|---|---|---|
| g5a（G 批） | `text="[焦急，语速快]你怎么还不走？"`，**`additions` 缺省** | ASR 读出标签词 → 被朗读 ✅ 已证 |
| d4（B2 批，3 轮） | `text="[克制悲伤，语速偏慢]我没事。…"`，**`additions` 缺省** | 3/3 ASR 读出标签词 → 被朗读 ✅ 已证 |
| **生产真实形状** | `text="[标签，标签]…"` **＋ `additions={"use_tag_parser":true}`** | **当晚已实测：同样被朗读 → 见 §16** ✅ |
生产代码事实（可作为复核锚点）：`tts_style_control.py:815-827` 只在 `style_control_method` 命中 `audio_tags/tags/label/labels/voice_labels` 时构建 `_build_inline_tag_strategy(..., placement="text_prefix", use_tag_parser=True)`，`_render_doubao_voice_label_prefix()`（同文件 557-559 行）渲染成 `[a，b]`；`_aliyun_mixin.py:1459-1499` 把 `use_tag_parser` 从 `provider_fields` 取出，与 `context_texts` 一起交给 `_build_seed_tts_additions()` 写进 `additions`；WS 路径 `_aliyun_mixin.py:1709-1720` 同样如此。也就是说**探针测的是"忘了开 parser"的形状，而生产是"开了 parser"的形状**。

由此需要撤回的结论：**"豆包通道存在成品级标签污染"目前是推断，不是实测结论**；d4 的 1.40–1.66× 时长也不能记作生产的代价。保留的结论：Cot 语法（`<cot text=…>`＋parser）被解析且不发音（g5b/g5c/d3 共 5 次）；缺 parser 的方括号前缀被朗读（g5a/d4 共 4 次）。

### 13.2 判定它只需 1–2 次调用（待批准）

最小实验：同台词同音色，发 **n1 ＝ 生产精确形状**（`[克制悲伤，语速偏慢]` 前缀 ＋ `additions={"use_tag_parser":true}`，`context_texts` 留空以隔离变量），再加 1 次重复测稳定性；随后对音频做 ASR。

- 若 ASR 读出标签词 → 污染在生产里真实存在，修复动作是把 `_render_doubao_voice_label_prefix` 改成官方 `<cot text=…>` 包裹（改动很小，可 TDD 落地）。
- 若 ASR 干净 → 生产没有污染，今天关于"必须立刻换语法"的判断作废，豆包侧保留 Cot 只作为"可选写法"。
- 两种结果都不回答"哪种更好听"，那仍属 §12.4 第 1 项的人耳裁定。

探针已就位：`python -m app.scripts.probe_tts_capability_gates --batch seed_tag_parser`（默认干跑，加 `--confirm-paid` 才发出）。

**→ 本实验已于同日执行（用户批准，2 次真实调用）。判定结果见 §16：`use_tag_parser=true` 不能让方括号前缀免被朗读，§13.1 撤回的那条结论恢复为实测结论。**

### 13.3 方法学回写（与本节同源的教训）

**对照实验必须复刻"生产实际发出的完整形状"，包括开关字段与请求头。** 本轮踩了两次同一种坑：§12.2 里 15 次 HTTP 探测只控 body 不控 headers，导致先错误归因给 `req_params.model`；本节里只控 body 与标签文本、不控 `use_tag_parser`，导致把"探针形状"当成"生产形状"。写探针时应先 `_snapshot_*`/payload builder 读一遍生产实际出站内容，再据此构造 payload（本轮 §13 的 n1 就是这么做的）。

## 14. 阻断项：探针 manifest 把豆包 API Key 写成明文（2026-10-10 晚，code-review 子代理发现，已自证）

`probe_tts_capability_gates.py:475-482` 的 `_redact()` 只掩 `authorization` / `x-api-key` / `api-key` 三个头名，而 `_seed_headers()`（`:157-167`）在没配 `VOLCENGINE_TTS_APP_KEY` 时**把 API Key 兜底填进 `X-Api-App-Key`**（`:159-161`），该头不在掩码名单里 → 出站头被原样写进 manifest。

扫描结果（只统计不打印密钥值）：`VOLCENGINE_TTS_API_KEY` 明文出现在 **5 个 manifest、共 25 处**——
`data/tts_debug/b2_paid_writing{,_r2,_r3}/manifest.json`（各 5）、`gate_probe_g1_g7/manifest.json`（6）、`seed_http_shape/manifest.json`（4）。
其余 4 个密钥名（DashScope/MiMo 等）与全部音频、`raw/*.txt` 响应原文均未泄漏。入库状态核实：这 5 个 manifest **目前未被 git 跟踪、也没提交过**（`git ls-files` 无命中），但 `backend/data/tts_debug` **不在 .gitignore 内**（`git check-ignore` 返回非命中），且同目录下已有 3 个 `seed_tts_99_voice_validation*.json` 在版本库里 → **任何人跑一次 `git add -A` 就会把密钥写进历史**。所以修复要在下一次提交前做完。

建议修复（两项都待批准，本轮未动）：

1. **代码 1 行**：`_redact()` 改成按"头名含 key/token/authorization 即掩码"，而不是枚举三个名字——枚举式白名单正是这次漏 `X-Api-App-Key` 的原因（与 §13.3 同源：只控已知项、不控新增项）。
2. **数据擦洗**：对上述 5 个 manifest 做定点字符串替换（密钥值 → `***`），共 25 处，不动其他字段；替换后重跑一遍扫描脚本验证计数归零。
3. 可选：既然 §12.2 已证 `X-Api-App-Key` 是单向 HTTP 拿不到音频的根因，探针的 `_seed_headers()` 本就该默认**不发**这个头，需要它时由单独的形状实验显式打开。

**2026-10-11 复核（本节读法与仍然生效的守卫）**：上面点名的 5 个 manifest 连同所在批次目录已全部删除，密钥明文的物理载体不存在了，因此"25 处命中""复扫残留 0"这类逐条计数按**一次性观测快照**读取，无法再复核。仍然生效的是代码侧守卫：`_redact()` 已改为按头名关键字（key/token/authorization/secret/signature）掩码（§17.1）。**仍未闭合的同源缺口**：`backend/data/tts_debug/` 至今不在 `.gitignore` 内（`git check-ignore` 非命中），该目录下 4 个 `seed_tts_99_voice_validation*.json` 是已跟踪文件——下一次探针批次往这里写 manifest 时，`git add -A` 依旧会把出站头收进历史；`.gitignore:159` 刚为 `backend/data/scene_audio_artifacts/` 补过同类规则。**2026-10-11 已补：`.gitignore:164` 加入 `backend/data/tts_debug/`（commit 321fce0），新写入的 manifest 不再进 `git status`；但目录下那 4 个已跟踪的 `seed_tts_99_voice_validation*.json` 不受忽略规则影响，仍在索引里，要移出需单独 `git rm --cached`。**

## 15. 仍待用户拍板的事项（汇总）

- **B2 的 15 条音频尚无人耳听辨**（§12.4 第 1 项）——这是"哪种写法更好听"的唯一真值来源。**2026-10-11 状态变更**：原听辨表 `backend/data/tts_debug/b2_paid_writing/listening_sheet.md` 与音频已随产物清理删除，本项从"去听"变成"**先重生成再听**"（`--batch b2_paid`，45 次合成 ≈0.2 元 ＋ 15 次 ASR，需批准）；未重生成前，§12.1 的 B2 结论只能停在客观层。
- **`_render_doubao_voice_label_prefix`（`tts_style_control.py`）改成官方 `<cot text=…>` 包裹**：§16 已确证 `[a，b]` 前缀在生产形状下仍被朗读，Cot 是实测干净的替代语法。**2026-10-11 复核：改动已在工作区落地**（渲染 `<cot text="…">`、逐句补 `</cot>`、按官方 64 字符上限逐标签装填并剔除引号尖括号、`tag_syntax="doubao_cot"`、`use_tag_parser` 改由前缀是否存在驱动），`tests/test_audiobook_tts_provider_payloads.py` 有对应断言，该文件＋评分契约文件 **124 passed**；**但尚未提交**（`git show HEAD:` 里 `<cot` 命中 0 处），所以本项从"待批准"变成"**待用户决定是否提交**"。详见 §19。
- **`qwen3-tts-instruct-flash` 404 后生产默认怎么切**：用户新提议"是否全面切到 `qwen-audio-3.1-tts-flash`（音色更多、价格更便宜）"，调研进行中；注意 §12.1 A 组显示 `qwen3-tts-flash` 对情绪指令无时长响应。
- **§11.9 列出的 `[字段]` 项**（stepaudio 三个能力位、minimax `basic`、qwen3 budget 600、mimo `voice_design_instruction_mode`）。其中 **stepaudio instruction 预算 200→500 已于 2026-10-11 落地**，落点与实测副作用见 `docs/MODEL_INTEGRATION_REFERENCE.md` §11.9 第 1 条。
- （可选）再发 2 次 n1 把供应商抖动钉死，≈0.01 元。

已闭环、本轮不再待批：密钥泄漏修复与 5 个 manifest 擦洗（§17.1）、`_call_seed_tts_http` 去掉 `X-Api-App-Key`（§17.2）、`seed_tag_parser` 判定实验（§16）。

## 18. 「qwen3 是否全面切到 qwen-audio-3.1-tts-flash」调研结论（同日，只读取证，未改任何配置）

用户提议的依据是"3.1 音色更多、价格更便宜"。两条都成立，但**都不足以支撑"全面切"**，且切换有一个静默失败的坑。逐条核实：

- **音色**：档案 `config/models.yaml:699 total_count: 24`（qwen3 走 `QWEN3_TTS_INSTRUCT_SUPPORTED_VOICES` 白名单过滤，`voice_catalog.py:11,122`）对 `:1146 total_count: 68`（3.1，`shared/qwen_audio_3_1_tts_voices.json`）→ 68 vs 24，"更多"成立。
- **价格**：qwen3 是 `pricing_basis: public_list_price` 的 0.8 元/万字符；3.1 的 0.4 是 **`derived_from_token_price` 我方折算值**（实测带宽 0.285–0.42，`MODEL_INTEGRATION_REFERENCE.md` §11.7.5）。"便宜一半"名义成立、**口径不成立**，且这个折算值换模型版本就作废。
- **情绪控制面：3.1-flash 从未做过写法实测**。§10 候选矩阵（`:213`）里 3.1 一栏全是待测项；B1/B2 都没跑它；唯一相关的 G7 只确立"`[excited]` 类标签不被朗读"，而"标签是否改变表演"那条**测试设计失效、需同向重做**。反过来说，`qwen3-tts-flash` 无时长信号不等于 3.1 更差——**现在没有证据支持任一侧**。
- **切换的最大风险是静默改路由 + 音色整体失效**：`_AUDIOBOOK_TTS_MODEL_ALIASES`（`tts_model_ids.py:521-527`）把所有 `qwen3-tts*` 写法折叠到 `DEFAULT_AUDIOBOOK_TTS_MODEL`，归一化里还有 `startswith("qwen3-tts") → default`（`:593` 附近）。**改 DEFAULT 不等于只改新默认，而是把历史 qwen3 配置一并静默改路由到 3.1**；两边音色 ID 不相交（3.1 全带 `_v3.1`），解析不到音色时 `voice_manager.py:1151` 只 `logger.warning` 后 **`continue` 跳过该角色**，前端 legacy 映射又只在 `model === 'qwen3-tts-instruct-flash'` 字面命中 → 成品可能整本塌成一条声线且**不报错、测试也不会变红**。全仓没有 qwen3→3.1 音色对照表。
- 其它连带：切后 `_is_qwen_tts_model()`（`_tts_mixin.py:181`）为 False，600 字校验与 360 字分块、`_fit_qwen_instruction_payload_to_limit` 全部退出（正文上限 600→10000）；3.1 走 `output.audio.url` 下载，多一次 GET 和一类失败面；试听缓存 key 含 model → 全量失效重生成。计费链是本地 `len(text) × price_per_10k`，不读 provider usage，所以派生价结构上仍适用，但单点折算系数会随文本长度/语种漂。
- 上游侧**没有任何下线公告**：`MODEL_LIFECYCLE_MANAGEMENT_GUIDE_20260731.md` 无该 ID，退役登记测试未收录，档案仍 `status: active`（`config/models.yaml:509`）→ 404 目前只是端点事件，不能当作已下架。

推荐分两步，而不是一次全面切：

1. **止血（小改动、零音色风险）**：把 `qwen3-tts-flash` 注册成**独立模型 ID**（常量 + 能力矩阵 + `AUDIOBOOK_TTS_RUNTIME_MODEL_IDS` + CATALOG + 前端选项），音色继续用 qwen3 那份表，然后由用户点名用它跑章节；`DEFAULT` 暂时不动或只指向它。
2. **要切 3.1，先补两件事**：①一轮 3.1-flash 情绪写法实测（1 台词 × 4 写法＋基线 × 3 轮 ≈ **15 次合成 + 15 次 ASR ≈ 0.03–0.05 元**，另需重做 G7 标签同向对照 +6 次 ≈0.01 元，15 条必须人耳听辨）；②一份 qwen3→3.1 音色对照表 + 迁移兜底（纯文档与单测成本，0 次付费调用）。两件事完成前不动 `tts_model_ids.py:10`。

**2026-10-11 收口：本节是"切换前"的分析，实际执行走的是"直接全面切"。与当前代码逐条对账：**

- 折叠形状已收敛：`_AUDIOBOOK_TTS_MODEL_ALIASES` 里不再有 qwen3 逐条键，历史拼写统一由 `tts_model_ids.py:558` 的前缀分支（`startswith("qwen3-tts"/"qwen3_tts") → QWEN_AUDIO_31_TTS_FLASH_MODEL`）承接；前端镜像规则在 `frontend/src/pages/audiobook/ttsModels.ts:128`，两边都有反向断言（`backend/tests/test_audiobook_tts_model_ids.py:1069-1120`、`ttsModels.test.ts:23-24`）。"改 DEFAULT 会静默改路由"这条仍然成立，只是现在**结果确定**（一律落到 3.1）。
- "前端 legacy 映射只在 `model === 'qwen3-tts-instruct-flash'` 字面命中"已修（`ttsModels.ts:80` 起改为前缀折叠）。
- "全仓没有 qwen3→3.1 音色对照表"已补：`voice_manager.py:64-88` 的 `LEGACY_PRESET_ALIASES` 把 23 条旧声线名全部指向 `_v3.1` 现役音色，反派快路径与末位降级也换成现役名（`:577`、`:579`、`:640`）；接口层不再持有音色名（`routes_segment_regen.py:244` 下发空 speaker，MiniMax 保留常量 `:97`，cosyvoice 显式 400）。**当时唯一没消掉的是"解析不到音色只 `logger.warning` 后 `continue` 跳过该角色"**（旧 `voice_manager.py:1158`，行号已漂移）**已于 2026-10-11 收口**：`apply_project_voice_mapping()` / `load_from_db()` 解析不到用户显式指定的音色时不再 `continue`，改抛 `VoiceMappingResolutionError`（继承 `ValueError`）拒单，接口层 400、后台任务打 `status=failed`；"静默塌成一条声线且不报错"这条缺口不复存在，判据与调用点清单见 `docs/MODEL_INTEGRATION_REFERENCE.md` §11.7.9 末段。
- 数据与配置侧已归零：`config/models.yaml` 无 qwen3-tts 条目、无 `status: deprecated`；`shared/` 下 qwen3 两份音色档案已删；`scripts/rewrite_legacy_model_ids.py` 干跑报"数据库中没有旧模型 ID 引用"；`.env`、`.env.example`、`backend/.env`、`backend/.env.example` 里**没有任何 `QWEN3_TTS_*` 变量**（门禁的 env 盲区这次不存在）。
- 退役台账收录情况：`tests/test_model_retirement_registry.py:52` 已登记 `qwen3-tts-instruct-flash → qwen-audio-3.1-tts-flash`，所以 `audit_model_references.py --all-retired` 会扫它；但 `qwen3-tts-flash`／裸 `qwen3-tts` **不在登记表**，且该文件 `:464`、`:470` 明确断言 `qwen3-tts-flash` 属"上游线名豁免"——这类拼写在门禁里永远绿灯，靠的是上面那条前缀折叠分支兜底，不是靠扫描。
- 本节推荐的两件事里**只有②完成**；①（3.1 情绪写法实测 B3）仍未执行，任务 #37 开着。换言之"全面切 3.1"是在**情绪控制面从未实测**的前提下上线的，这正是 §12.1 A 组警告过的缺口。


## 16. §13.2 判定实验结果：生产形状确证被朗读（同日执行，2 次付费调用已批准）

同台词、同音色（`ICL_uranus_zh_female_keainvsheng_tob`）、同 `model=seed-tts-2.0-expressive`、同 WS 通道：

| key | 形状 | `additions` | 时长 ms | ASR 逐字 |
|---|---|---|---|---|
| **n1**（本轮） | 前缀＋parser（只开 parser，隔离单一变量） | `{"use_tag_parser":true}` | **6024** | 「克制悲伤，语速偏慢，我没事，我真的没事，你们都不用管我。」 |
| **n2**（本轮） | 生产完整形状＝前缀＋parser＋`context_texts` | `{"context_texts":[…],"use_tag_parser":true}` | **5856** | 同上，标签词仍被念出 |
| d4（3 轮，缺 parser 对照） | 只有前缀 | 缺省 | 6024 / 5664 / 5880 | 同上（3/3 读出标签） |
| d3（3 轮）Cot 语法 | `<cot text=…>` | `{"use_tag_parser":true}` | 3864 / 4032 / 3864 | 干净 |
| d5（3 轮）念稿基线 | 无标签 | 缺省 | 3624 / 4032 / 3864 | 干净 |

判定：

- **`use_tag_parser=true` 并不能让方括号前缀免于被朗读。** n1 与 d4 的时长**精确到毫秒相同（6024 = 6024）**，ASR 逐字一致 → parser 对这个形状不起"剥离标签"的作用，"漏读是因为没开 parser"这个假设被否证。
- **音色混杂变量已排除**：同一个 speaker 下 Cot 语法 3 轮全部干净、时长与基线同量级（g5b/g5c 也是 1464 ms，对照 g5d 1632 ms），说明该音色**会解析标签、只是不认 `[a，b]` 这种前缀**。
- 因此 §13.1 里撤回的"生产成品级标签污染"**恢复为实测结论**，但范围要按代码事实限定清楚：只有 `style_control_method ∈ {audio_tags, tags, label, labels, voice_labels}` 的片段会走 `[a，b]` 前缀（`tts_style_control.py:815-827`），且 `:843` 是"只要前缀存在就 `use_tag_parser=true`"。不是全量章节，是显式标签模式的片段。
- **生产代码里没有任何 `<cot text=…>` 渲染路径**（`tts_style_control.py` 全文 grep 无 `<cot`），所以修复动作是把 `_render_doubao_voice_label_prefix` 改成官方 Cot 包裹——已被 6 次实测证明"解析、不发音、能改变时长"。属生产改动，**待批准**。**2026-10-11 复核：本条前半句已失效**，Cot 渲染路径已在工作区落地并通过测试（未提交），状态以 §15 对应条与 §19 为准；本节保留原措辞只作为当晚取证时点的事实。
- 样本量坦白：n1/n2 各 1 次，供应商抖动未测；但 d4 同形状已 3 轮复现、且 n1 与 d4 时长逐毫秒相同，可信度高。若要把抖动也钉死，再发 2 次 n1 即可（≈0.01 元）。
- 成本：豆包 WS 2 次（刊例推算 ≈0.01 元，非账单实扣）＋ ASR 2 次（qwen3-asr-flash）。证据：`backend/data/tts_debug/seed_tag_parser_shape/`（2 条 mp3 + manifest + 2 份 `asr_*.txt`；manifest 里所有鉴权头已被掩码成 `***`）。**2026-10-11 复核：该目录已随产物清理删除，"n1 与 d4 逐毫秒相同（6024 = 6024）"按一次性观测快照读取，不可再复核；要复核需 `--batch seed_tag_parser` 重发 2 次（≈0.01 元）。**

## 17. 本轮已落地的两处修复（用户批准）

1. **探针密钥泄漏（§14）已修**：`_redact()` 从"枚举三个头名"改为"头名含 key/token/authorization/secret/signature 即掩码"（`probe_tts_capability_gates.py:475`）；5 个 manifest 里 25 处 `X-Api-App-Key` 明文已定点替换为 `***`，替换前确认过**所有命中都在 `$[*].headers.X-Api-App-Key` 且整值等于密钥**（无嵌入在更长字符串里的情况），替换后 JSON 可解析、条目计数不变。复扫全 `data/tts_debug` 目录（含音频与 `raw/*.txt`，按字节匹配 4 个不同密钥值）→ **残留 0**。擦洗过程中产生的 `.bak_pre_scrub` 备份含明文，已删除并验证不存在。
2. **`_call_seed_tts_http` 已去掉 `X-Api-App-Key`**（`_aliyun_mixin.py:1855-1874`，同时删掉只为该头存在的 `app_key` 变量与 `VOLCENGINE_TTS_APP_KEY`/`DOUBAO_TTS_APP_KEY` 读取）。按 TDD 走：先改测试期望（红：`Left contains 1 more item: {'X-Api-App-Key': ...}`）→ 再改代码（绿）。回归 `tests/test_audiobook_tts_provider_payloads.py + test_audiobook_tts_model_ids.py + test_audiobook_audio_score_contract.py` → **167 passed**。

遗留：`prompt_audio_asr_provider.py:485` 的 ASR 通道仍发 `X-Api-App-Key`——那是另一个端点（Volcengine ASR），本轮没有实测证据说明它有害，**未动**。

## 19. 2026-10-11 交接复核：B3 扩条、评分层参数化、豆包 Cot 状态

- **证据现状**：`backend/data/tts_debug/` 只剩 2026-06-25 的 4 个 `seed_tts_99_voice_validation_*.json`（版本库跟踪文件），§9.3/§12.3/§16 的"批次目录已删除"与磁盘一致。
- **3.1 生产形状复核**（按 §13.3 的规矩，先读生产 builder 再谈探针）：`_aliyun_mixin.py:2071-2083` 只发 `{"model","input":{text,voice,instruction?}}`，请求头仅 `Authorization` / `Content-Type`，3.1 正文不经 `prepare_text_for_style_control`；B3 干跑的 8 条 payload 与之一字一致。音色 `yeqinghe_v3.1` 即生产别名 `female_young_gentle`（`voice_manager.py:78`）。
- **B3 从 6 写法扩到 8**：新增 q7（仅正文 `[sad]`，逐句）与 q8（三段式 instruction ＋ `[sad]`）。原因是原 q5/q6 用的是全角圆括号舞台提示（MiMo/stepaudio 的写法），只能回答"3.1 会不会把圆括号念出来"；3.1 官方文档化的正文通道是**半角方括号标签**，而"标签是否改变表演"这条 G7 失效测试必须同向重做，`[excited]` 与悲伤指令对立下达答不了这个问题。完整词表与官方作用域原文见 §2。
- **叠加口径降级**：官方《非实时语音合成》用户指南给了标签词表与逐句示例，但**没有给出"可与 instruction 叠加"的保证**；§0/§2 原先的转述已改为"官方未保证、由 q8 实测"。本地 `bailian-docs-llm-wiki` 镜像只到 HTTP API 原文的 `instruction` 一句和模型页"细粒度标签控制能力"这句话，词表本身不在镜像里。
- **评分层阻断已解（零付费）**：`probe_tts_gate_scoring.py` 的 `PROBE_DIR/MANIFEST/OUT_*` 改由 `--probe-dir` / `--manifest` 决定（相对路径按仓库根解析，默认 B3 目录），待评清单逐行读自 manifest，`--key` 可只抽审计锚、`--line` 只用于给缺字段的旧批次补台词。探测脚本相应新增可选 `spoken_text` 字段并写进 manifest：**正文带标签的写法必须显式给出干净台词**，否则 fidelity 会把标签当成漏字。g1–g7 的 13 条硬编码 TARGETS 已删（该批音频永久丢失，§9.3），`HUMAN_RULING` 三条人耳真值锚保留用于侦测评分器漂移。
- **豆包 Cot**：状态见 §15 与 §16 的 2026-10-11 更正——工作区已落地、`tests/test_audiobook_tts_provider_payloads.py` 等 **124 passed**、**尚未提交**。
- **B3 成本重算**（刊例/派生推算，不等于账单实扣；3.1 的 0.4 元/万字是 `derived_from_token_price`，带宽 0.285–0.42，`config/models.yaml:549-555`）：8 写法 × 3 轮 = **24 次合成 ≈0.07–0.15 元 ＋ 24 次 ASR ≈0.02–0.04 元**；若再按评审层协议送双模型盲评，8 条 × 2 个模型 ≈0.08–0.1 元/轮。**（2026-10-11 实际执行口径见 §20：合成 24 次全 200；因 6/8 写法三轮逐字节相同，ASR 去重到 10 次 ≈0.01 元；盲评候选缩到 6 条 ≈0.06–0.08 元/轮，尚未发。）**

---

## 20. B3 实测结果：qwen-audio-3.1-tts-flash 的 8 种提示词形状（2026-10-11 付费批次）

批次与成本：8 写法 × 3 轮 = **24 次合成**（HTTP 24/24 = 200）＋ **10 次 ASR**（`qwen_audio_asr_flash`，本地 wav 直转，不上传公网）。ASR 从原估 24 次压到 10 次，因为 6/8 写法三轮 md5 逐字节相同，去重后只需 8 份，q6/q8 各有第 2 个哈希再各加 1 份。按刊例推算：合成 ≈0.07–0.15 元、ASR ≈0.01 元（**推算值，非账单实扣**）。证据：`backend/data/tts_debug/b3_qwen31_writing{,_r2,_r3}/`（24 个 wav + 3 份 manifest + 10 份 `asr/*.json`；manifest 鉴权头已掩码为 `***`，整目录由 `.gitignore:164` 忽略）。

### 20.1 客观层总表

基线 = q4（不传 instruction、正文无标签），15 字台词逐字与 B1/B2 同。

| key | 形状 | 三轮时长 ms | vs 基线 | 三轮 md5 | ASR 逐字（similarity） | 判定 |
|---|---|---|---|---|---|---|
| q1 | 三段式 instruction | 4560 / 4560 / 4560 | 1.08× | 1 个 | 1.000，干净 | 待定（送评） |
| q2 | 动机前置 instruction | 5120 ×3 | 1.21× | 1 个 | 1.000，干净 | 待定（送评） |
| q3 | 关键词式 instruction | 4080 ×3 | **0.96×** | 1 个 | 1.000，干净 | 待定；无人耳外的采纳证据 |
| q4 | 念稿基线 | 4240 ×3 | 1.00× | 1 个 | 1.000 | 参照 |
| q5 | 仅正文全角圆括号舞台提示 | 7920 ×3 | 1.87× | 1 个 | **0.682**，转写含"很轻的，几乎耳语"×2 | **判负：标签被朗读出口** |
| q6 | 三段式 instruction＋圆括号 | 7440 / 8080 / 8080 | 1.75–1.91× | 2 个 | 两份 0.682，同上 | **判负：同上** |
| q7 | 仅正文官方 `[sad]`，逐句 | 6880 ×3 | **1.62×** | 1 个 | 1.000，`[sad]` 未出现在转写 | **标签被解析、不发音** |
| q8 | 三段式 instruction＋`[sad]` | 6000 / 6160 / 6160 | 1.42–1.45× | 2 个 | 两份 1.000，干净 | **叠加形状合法、不互相冲突** |

### 20.2 判定

1. **全角圆括号舞台提示在 3.1 上会被朗读出口**（q5/q6，2 个不同哈希的音频转写一致）。这与 §16 豆包 `[方括号]` 前缀被朗读是同一类红线，但**结论必须逐模型记**：§11/§12 已证明 MiMo 的 `(风格)` 与 stepaudio 的 `（冷笑）` 是干净通道，写法红利不可跨模型移植，反过来"某个括号形状干净"也不能移植。
2. **3.1 官方半角方括号控制类标签是可用通道**：q7 逐字干净、时长 1.62×，且下方 20.3 的能量分析显示发声量增长来自放慢而非多念字 → 按"放大＝采纳的充分证据"这条非对称判据，`[sad]` 单独就能改变表演。这正是 §9 G7 当年设计失效、没能回答的问题。
3. **instruction ＋ 正文标签叠加合法且干净**（q8），官方未保证可叠加这条空白就此关闭。但 q8 的 1.42× **小于** q7 的 1.62×，说明两通道不是简单相加；**时长倍数不能用来排序情绪质量**，q7 与 q8 谁的情绪更到位只能靠评审层＋人耳。
4. **本轮 3.1 几乎没有供应商抖动**：6/8 写法三轮 md5 逐字节相同、极差 1.000，连基线也是 4240 ×3。这与 §12 里"基线自身极差可达 1.28×"的另一批观测不同量级 ⇒ 在该音色（`yeqinghe_v3.1`）＋该短句形状下，时长信号可直接采信，不需要为抖动追加轮次。这条只对 3.1 成立，不外推。
5. **instruction 三种写法在本轮只有 q2 给出可听证据之外的信号**：动机前置 1.21× ＞ 三段式 1.08× ＞ 关键词式 0.96×（低于基线）。关键词式在 MiMo 上"略胜于念稿"，在 3.1 上连时长方向都不成立——但按非对称判据，0.96× 只说明"没有放大的证据"，不能定罪。

### 20.3 发声能量分析（本地零成本，用于钉 q5 的复读与 `[sad]` 的放慢）

口径：`wave` + numpy，20 ms 帧 RMS，阈值"帧 RMS > 峰值 − 35 dB"记为发声帧，连续 ≥3 帧合为一段，段间隔 ≥120 ms 记为停顿。一次性分析，脚本未留存，按此口径可复现。

| key | 发声总时长 | 段落（ms） | ≥120 ms 停顿 |
|---|---|---|---|
| q4 基线 | 2840 | 6 段，末段止于 4000 | 820→+260、1140→+160、2300→+600 |
| q5 | 5080 | 13 段 | **60–1080 与 1560–2580 两段各 ≈1020 ms**，随后 2580→+960 |
| q7 | 4440 | 7 段 | 1440→+800、4320→+500 |
| q8 | 4080 | 7 段 | 1620→+620、3660→+420 |

- q5：转写里"很轻的，几乎耳语"出现 2 次，能量上确有**两段等长（≈1020 ms）的前置发声块**，而 `（停一下）` 所在位置是 960 ms **纯静音**（无发声帧）。所以"复读"发生在 TTS 侧、不是 ASR 的整句重复幻觉（幻觉判据本来也该触发折叠：15 字台词在尾部区段实际发声 3120 ms，与基线 2840 ms 同量级，装得下两遍 7 字提示）。
- q7/q8：发声块 4440/4080 ms vs 基线 2840 ms，而**字数与基线逐字相同**（similarity 1.000）⇒ 增量全部来自放慢与停顿加长，不是多念字。这是"标签被采纳为表演而非被朗读"的正面证据。
- ASR 把"很轻**地**"转成"很轻**的**"是既有同音归一（`voice_profile_tagging._HOMOPHONE_TABLE`），不算失真；similarity 已归一后才得 0.682，因此 0.682 只反映"多出来的内容"，不掺标点/同音噪声。

### 20.4 未判定项与下一步（须另批确认）

- **情绪质量排序**：q5/q6 已客观判负、不送评；候选 q1/q2/q3/q4/q7/q8 六条已于 2026-10-11 按 §7 分工送 `doubao-seed-2-1-lite`（emotion_match / prosody_pause / overall_naturalness）＋ `qwen3.8-omni-flash`（fidelity / contamination），`--mode blind`，12/12 成功。**结果与读法见 §21**。
- **人耳按 §7 的三种情况介入**：q3（0.96×，无时长放大证据）与 q4（基线参照）属第②类；q7 vs q8 若与评分器跨模型分歧属第①类；另固定抽 1–2 条作评分器漂移审计锚（第③类，不参与选冠军）。**盲评已发，压缩后的 4 条送听清单见 §21.3**；3.1 只有在这些项走完并得到用户耳朵裁定后才算收口。
- SSML `<break>` / `<phoneme>` 在 3.1 支持清单内但本轮未排（§10），仍是空白。

---

## 21. B3 盲评结果（2026-10-11，qwen-audio-3.1-tts-flash 评审层）

发出：`python -m app.scripts.probe_tts_gate_scoring --key q1,q2,q3,q4,q7,q8 --confirm-paid`（`--mode blind` 为默认）。**6 条 × 2 模型 = 12 次调用，12/12 `reviewed`，无 skipped**。q5/q6 已按 §20 客观层判负，不送评。产物：`backend/data/tts_debug/b3_qwen31_writing/{scores_blind.json,blind_sheet.md}`。

用量与成本（按 `usage` 实数，不是次数估算）：

| 评分模型 | 次 | prompt / audio / completion tokens | 成本口径 |
|---|---|---|---|
| doubao-seed-2-1-lite | 6 | 3216 / 198 / 1452 | 按档案分价（非音频输入 0.80、音频输入 12.00、输出 2.70 元/百万 token）推算 ≈**0.0087 元** |
| qwen3.8-omni-flash | 6 | 3071 / 215 / 4373（含 reasoning 2821） | **档案无分价数字可推**：`config/models.yaml` 里只有 `qwen3.5-omni-flash` 的卡，其 `pricing_info` 带 `verification_required: true` 且无数值；评分层用的 `qwen3.8-omni-flash` 这个 ID **在本仓档案里没有卡** |

> §20.4 里我给的"≈0.06–0.08 元/轮"是按旧批次粗估，**不作数**；doubao 侧实测比粗估低一个量级，omni 侧只能标注为"档案缺口、无法推算"。

### 21.1 主评（doubao-seed-2-1-lite）的证据列读法

盲评下 `emotion_match` 的语义是**情绪鲜明度**，不是"是否贴合本轮指令"（指令没给模型看）。所以六条的 emotion 分数挤在 2–4，**排序只能读证据文本＋人耳，不能读分值**。按证据要点判"是否达成克制悲伤（低落、音高偏低、句尾下沉、有哭腔或气息颤抖）"：

| key | 形状 | 时长 vs 基线 | doubao emotion/prosody/nat | 盲评听到的要点 | 达成度 |
|---|---|---|---|---|---|
| q2 | 动机前置 | 1.21× | 4 / 4 / 4 | 委屈低落、音高偏低、句尾下沉**且带哭腔** | **全要素** |
| q1 | 三段式 | 1.08× | 4 / 4 / 4 | 句尾下沉，但"略带傲娇甜感"、**无明显哭腔** | 部分 |
| q7 | 仅 `[sad]` 逐句 | **1.62×** | 3 / 4 / 4 | 些许低落、句尾下沉，但**音高平稳、无哭腔** | 只做到放慢 |
| q8 | 三段式＋`[sad]` | 1.42× | **2 / 3 / 4** | 低落但最平缓，无哭腔 | 最弱 |
| q3 | 关键词式 | 0.96× | 4 / 4 / 4 | "故作轻松"、句尾**上扬**、无哭腔 | 未实现 |
| q4 | 念稿基线 | 1.00× | 4 / 4 / 4 | 轻快、"没事"结尾**上扬带笑意** | 未实现（参照） |

三条结论：

1. **时长放大 ≠ 情绪质量**。q7 的 1.62× 是全场第二大放大，主评却只给 emotion 3，并明确"音高平稳、无哭腔"；q2 只有 1.21× 却是唯一全要素。§9 的非对称判据仍然成立（放大＝指令被采纳进韵律的充分证据），但它**不能用来排表演好坏**——这条以前只是逻辑推论，本轮第一次有同批次数据支撑。
   **2026-10-12 更正：本条推翻了。** 它拿来做对比的"doubao 情绪排序"本身在人耳裁定下是错的（见 §22）：耳裁 q7 最强、q2 次之，与时长放大排序同向。真正被证伪的是主评在这一批上的判别力，不是时长判据。
2. **`[sad]` 单独用＝"放慢"而不是"悲伤"**：能量剖面（§20.3）显示增量全在发声时长与停顿，主评显示质地没变。要在 3.1 上要哭腔，得靠 instruction 侧的动机描写，标签负责的是节奏与收尾。
   **2026-10-12 更正：后半句推翻了。** "质地没变"来自主评的证据文本，耳朵判它漏检——q7 恰是四条里悲伤感最强的一条（§22）。前半句（增量全在发声时长与停顿）是客观测量，仍然成立。
3. **叠加没有相加**（q8 1.42× < q7 1.62×，且 emotion 2 是全场最低）。形状合法、逐字干净（合法性问题已闭合），但"instruction ＋ 正文标签"目前不产生 1＋1 效果，反而最平。

### 21.2 参考评的偏差再证实，而且比 §9.1 更严

`qwen3.8-omni-flash` 给 **q4 无指令基线**打了 emotion 5／naturalness 5，证据是"声音颤抖带哭腔，句尾下沉哽咽"；q1/q2/q3/q7/q8 全部 5 分。而基线在客观层是 4240 ms、主评听来"轻快、上扬带笑意"。

- 关键点：本轮是 **blind 模式，表演要求没有进 prompt**。它仍然补出了哭腔 ⇒ 泄漏通道不是"指令复述"，而是**台词原文本身**（"我没事。我真的没事，你们都不用管我。"语义就偏悲伤，模型按语义先验生成听感）。
- 因此 `--mode blind` 只消除了"复述指令"这一条偏差路径，**不消除"按台词脑补情绪"**。qwen3.8 的 emotion/prosody/naturalness 列在任何模式下都不采信，这条从"怀疑"升级为"两条模式都实测过"。
- 它的可交付维度仍然可用且与客观层交叉一致：**fidelity 5／contamination 5，6/6**，与 §20 的 ASR 逐字 similarity=1.000（q1–q4、q7、q8）完全吻合。

### 21.3 待你耳朵裁定的最小集（按 §7 三类情况压缩后 4 条）

| 听 | 文件 | 为什么必须人耳 |
|---|---|---|
| q2 | `b3_qwen31_writing/q2_qwen31_motivation.wav` | 主评冠军候选，需确认"哭腔"是否真存在、还是评分器替台词补的 |
| q1 | `q1_qwen31_director.wav` | 与 q2 同分（4）但证据弱一档，**选冠军必须二选一** |
| q7 | `q7_qwen31_sad_tag_only.wav` | ①跨模型分歧（主评 3／"无哭腔" vs 参考评 5／"哭腔"）＋ 放大最大，是"放慢算不算表演"的争议本体 |
| q4 | `q4_qwen31_baseline.wav` | ②无时长放大 ＋ ③审计锚（同时是三类，用来侦测主评与参考评谁在漂） |

不送听：q3（0.96× 无放大证据、主评证据显示句尾上扬，方向已明确劣于基线之上的一档之外）、q8（叠加的合法性问题已被 ASR 闭合，情绪上主评给全场最低，不构成冠军候选）。

`blind_sheet.md` 里六条都留了"人耳裁定：尚未听辨"的空位，裁哪几条就回填哪几条。

试听页：`backend/data/tts_debug/b3_qwen31_writing/listen_human_ruling.html`（浏览器直接打开，四条带播放器；顺序已打乱为 A=q7／B=q4／C=q2／D=q1，编号对照与主评要点写在页面末尾的折叠区，听完再展开，避免先入为主）。该目录整体被 `.gitignore:164` 忽略，页面与音频都不入库。

---

## 22. 人耳裁定与 3.1 收口结论（2026-10-12）

用户对 §21.3 的 4 条做了打乱顺序盲听（A=q7／B=q4／C=q2／D=q1），原话：**"a 最强，c 差一些，bd 这次最没有感情"**。

| 排名 | key | 形状 | 时长 vs 基线 | 人耳 | 主评 doubao | 参考评 qwen3.8 |
|---|---|---|---|---|---|---|
| 1 | q7 | 仅正文官方 `[sad]`，逐句 | 1.62× | **最强** | emotion 3／"音高平稳、无哭腔" | 5／"颤抖带哭腔" |
| 2 | q2 | 动机前置 instruction | 1.21× | 实现，差一些 | 4／"委屈低落、句尾下沉带哭腔" | 5 |
| 3＝3 | q1 | 三段式 instruction | 1.08× | **与基线并列，最没感情** | 4／"略带傲娇甜感、无明显哭腔" | 5 |
| 3＝3 | q4 | 念稿基线 | 1.00× | 同上（符合预期） | 4／"轻快、句尾上扬带笑意" | 5／"哭腔哽咽" |

### 22.1 三个可复用的结论

1. **3.1 的冠军形状是正文官方控制类标签，不是 instruction**。三段式【角色】【场景】【指导】——B1 里 MiMo 的人耳最优写法——搬到 3.1 后与念稿基线并列，耳朵听不出增量。这与 §12 的"写法红利模型特异"完全一致：MiMo 的最强写法在 3.1 上是最弱档之一，而 3.1 自己最强的通道（正文标签）在 MiMo 上并不是首选。
2. **时长放大排序与耳裁排序在本批同向**（1.62 ＞ 1.21 ＞ 1.08 ≈ 1.00）。这升级了 §9 非对称判据在 3.1 上的地位：不止"放大＝采纳"，在该引擎＋该短句形状下放大倍数还能**粗排**表演强度。但要按分辨率诚实限定：q1 与 q4 人耳并列、时长差 8%，说明 **10% 量级以内的差异不可用于排序**，只有跨 20% 以上的差距（q7 vs q2/q1）才与耳朵一致。样本只有 4 条，这条是"可用作低成本预筛"，不是"可替代耳朵"。
3. **主评模型第一次出现假阴性，方向与 qwen3.8 相反**。doubao 在本批把证据描述对了三条（基线"轻快上扬"、q1"无哭腔"、q3"句尾上扬"），却把耳裁最强的 q7 说成"音高平稳、无哭腔"，并用同一个 4 分把 q1、q3、q4 与 q2 并列。合起来是两条不同的失效路径：
   - `qwen3.8-omni-flash`＝**假阳性**（§21.2：无指令基线也报"哭腔"，且盲评不透露指令仍挡不住，泄漏源是台词原文）；
   - `doubao-seed-2-1-lite`＝**假阴性／分辨率不足**（在正文标签通道上听不出表演，且 blind 模式的 emotion 分值只表"鲜明度"，不能当"是否实现"用）。
   据此 §7 的"doubao 是情绪唯一采信方"要加限定：**它可作为"有没有情绪"的粗筛，不能作为"哪种写法更强"的排序依据**；写法对照的排序必须让耳朵上，评分层只负责把明显污染的、明显无变化的筛掉。

### 22.2 qwen-audio-3.1-tts-flash 收口（写法层）

- **可用**：正文半角方括号控制类标签，逐句下达（`[sad]我没事。[sad]我真的没事…`）。不发音、显著放慢、耳裁最强。与 `input.instruction` 叠加形状合法干净（q8，未定序，见下）。
- **次选**：`instruction` 写动机＋物理量（q2 式），耳裁有效但弱于标签。
- **无效**：三段式【角色】【场景】【指导】（q1，与基线并列）、关键词式抽象情绪词（q3，0.96× 无放大证据、主评证据显示句尾上扬）。
- **红线**：全角圆括号舞台提示会被朗读出口，且复读一遍（q5/q6 判负）；`（停一下）` 虽实现成 960 ms 静音，但整条形状已被污染，不可用。正式停顿控制应走 SSML `<break time>`——3.1 在官方支持清单内，**本轮仍未测**。
- **抖动**：6/8 写法三轮 md5 逐字节相同、极差 1.000，单轮结论可信度高于 §12 观测到的 1.28× 量级引擎。
- **唯一未闭合项**：q8（instruction＋标签叠加）未送听，是六条里唯一没有耳裁定序的候选。补听 1 条本地音频即可闭合，零付费：`backend/data/tts_debug/b3_qwen31_writing/q8_qwen31_director_plus_sad_tag.wav`。

### 22.3 生产含义（2026-10-12 已立项，未开工）

现状是 3.1 只把情绪写进 `input.instruction`（`_aliyun_mixin.py:2057-2132`，正文不经 `prepare_text_for_style_control`，§19 复核），而本轮耳裁证明**该通道的最强写法弱于正文标签**。把情绪落成可听表演需要一次装配改动，方向是把官方控制类标签按句装配进 `input.text`、instruction 退居动机与物理量描述。落地面至少要动这几处事实源，缺一不可：

1. 3.1 正文装配函数（新增逐句标签渲染，参照已落地的豆包 `_wrap_doubao_cot_sentences` 幂等写法）；
2. 标签词表与取值白名单（§2 的 23＋7 个官方取值，越界取值无官方保证）；
3. 逐句标签对**计费字符数**的影响——3.1 按 `characters` 计费且 `usage.characters` 恒等于正文长度，标签会进正文长度；
4. 与 instruction 预算（1200）的分工，避免同一句情绪在两处重复下达。

**2026-10-12 已立项**：完整改造面、标签白名单口径（第一阶段只放行实测过的 `sad`）、成本/时长两个相反口径、风险清单与 6 个实施切片见 `docs/AUDIOBOOK_QWEN31_BODY_TAG_ASSEMBLY_PLAN_20261012.md`。其中两条既有问题被单列而不混入本立项：① `config/models.yaml:486` 写 `instruction_max_chars: 4000`，代码与前端都是 1200，跨源一致性守卫未覆盖这一对；② `style_control_method` 无正式枚举定义、生产无赋值点、且在客户端快照里被黑名单剥离（`segment_synthesis_contract.py:87,118`）——**只做装配函数等于功能不存在**，开关链路是本立项最容易被低估的成本。

---

## 23. B4 实测：3.1 官方标签取值全量扫描（2026-10-13，30 次合成 + 30 份 ASR + 本地能量剖面）

§22 只实测过官方词表里的一个取值（`[sad]`），白名单因此被压成"第一阶段只放行 `sad`"。本批次把剩下的取值一次性扫完：**22 个未测控制类 + 7 个富语言类 + 1 条作用域对照**，共 30 条，30/30 HTTP 200。台词、音色（`yeqinghe_v3.1`）、音频参数与 B3 逐字相同，只换标签本身，因此全部与 q4 念稿基线（total 4240 ms、发声量 2900 ms）直接可比。控制类沿用 q7 的逐句形状 `[tag]我没事。[tag]我真的没事…`；富语言类只在第一个句界后插一枚（它是事件不是作用域，逐句会连发三次、无法判读落点）；`x01` 把 `[sad]` 从逐句改成**仅段首一枚**，用来闭合官方那句"作用于其后所有文本，直到遇到下一个控制类标签"。

只跑一轮，依据是 §20.2④ 的零抖动实测。**但 x01 与 q7 是不同输入（标签数量不同），零抖动结论不能搬过来替它们背书**，两者的差异解释见 §23.2③。

### 23.1 总表（按发声量倍数降序）

判据两列分开列：`total×` 是产物总时长／基线，`voiced×` 是**发声段总长**／基线发声量（能量口径同 §20.3：20 ms 帧 RMS、阈值峰值 −35 dB、连续 ≥3 帧成段、间隔 ≥120 ms 记停顿）。`占比` ＝ 发声量／总时长，用来区分"放慢"与"堆停顿"两种机制。`sim` 是 ASR 逐字相似度（门槛 0.90），`leak` 是转写里是否出现完整标签词组。

| key | 标签 | total× | 发声量 ms | voiced× | 占比 | 段数 | sim | leak |
|---|---|---|---|---|---|---|---|---|
| t08 | `[like dracula]` | 1.736 | 5540 | **1.910** | 0.753 | 4 | 1.000 | 0 |
| t21 | `[very slowly]` | 1.717 | 5440 | **1.876** | 0.747 | 4 | 1.000 | 0 |
| t10 | `[tired]` | 1.642 | 5080 | **1.752** | 0.730 | 5 | 0.909 | 0 |
| t06 | `[sarcastic]` | 1.528 | 4740 | **1.634** | 0.732 | 3 | 1.000 | 0 |
| t19 | `[crying]` | 1.585 | 4640 | **1.600** | 0.691 | 4 | 1.000 | 0 |
| t01 | `[amazed]` | 1.377 | 4380 | **1.510** | 0.750 | 4 | 1.000 | 0 |
| t09 | `[bored]` | 1.396 | 4240 | **1.462** | 0.716 | 3 | 0.968 | 0 |
| p04 | `[giggles]` | 1.321 | 4160 | **1.434** | 0.743 | 6 | 1.000 | 0 |
| t04 | `[angry]` | 1.302 | 4140 | **1.428** | 0.750 | 4 | 1.000 | 0 |
| t02 | `[deep and loud shouting]` | 1.245 | 4120 | **1.421** | 0.780 | 3 | 0.968 | 0 |
| p01 | `[gasp]` | 1.283 | 4060 | **1.400** | 0.746 | 5 | 0.938 | 0 |
| t05 | `[excited]` | 1.075 | 3980 | **1.372** | **0.873** | 2 | 1.000 | 0 |
| t03 | `[trembling]` | 1.321 | 3880 | **1.338** | 0.693 | 3 | 1.000 | 0 |
| t18 | `[reluctantly]` | 1.377 | 3880 | **1.338** | 0.664 | 3 | 1.000 | 0 |
| t14 | `[panicked]` | 1.208 | 3860 | **1.331** | 0.754 | 2 | 1.000 | 0 |
| t11 | `[scornful]` | 1.151 | 3800 | **1.310** | 0.779 | 3 | 1.000 | 0 |
| p02 | `[sighing]` | 1.245 | 3720 | **1.283** | 0.705 | 4 | 0.968 | 0 |
| p06 | `[cough]` | 1.264 | 3720 | **1.283** | 0.694 | 4 | 0.968 | 0 |
| t13 | `[asmr]` | 1.321 | 3720 | **1.283** | **0.664** | 3 | 1.000 | 0 |
| p03 | `[clears throat]` | 1.208 | 3700 | **1.276** | 0.723 | 5 | 1.000 | 0 |
| p05 | `[laughing]` | 1.151 | 3680 | **1.269** | 0.754 | 5 | 0.938 | 0 |
| t07 | `[curious]` | 1.094 | 3580 | **1.234** | 0.772 | 4 | 1.000 | 0 |
| x01 | `[sad]` **仅段首一枚** | 1.132 | 3500 | **1.207** | 0.729 | 3 | 1.000 | 0 |
| t17 | `[whispers]` | 1.132 | 3240 | **1.117** | 0.675 | 3 | 1.000 | 0 |
| t20 | `[serious]` | 1.094 | 3220 | **1.110** | 0.694 | 3 | 1.000 | 0 |
| p07 | `[snorts]` | 1.019 | 3160 | **1.090** | 0.732 | **3** | 1.000 | 0 |
| t12 | `[shouting]` | 1.038 | 3100 | **1.069** | 0.705 | 3 | 0.968 | 0 |
| t15 | `[mischievously]` | 0.943 | 2940 | **1.014** | 0.735 | 3 | 1.000 | 0 |
| t16 | `[empathetic]` | 0.887 | 2880 | **0.993** | 0.766 | 3 | 1.000 | 0 |
| t22 | `[very fast]` | 0.811 | 2280 | **0.786** | 0.663 | 3 | 1.000 | 0 |
| 参照 | q7 `[sad]` 逐句（B3） | 1.623 | 4520 | **1.559** | 0.657 | 5 | 1.000 | 0 |
| 参照 | q4 念稿基线（B3） | 1.000 | 2900 | 1.000 | 0.684 | 4 | 1.000 | 0 |

### 23.2 六条判定

1. **官方词表整体是 3.1 的干净通道，30/30 无一朗读出口**。`leak` 全 0、`sim` 全部 ≥0.909。这闭合了 §22 遗留的二义性：t08 `[like dracula]` 是全场时长最高的一条，"它把两个英文词念出来了"与"它把表演放慢了"两种解释都能产生这个倍数——转写证明是后者。**带空格的多词英文标签（`deep and loud shouting`／`like dracula`／`very slowly`／`very fast`）同样不发音**，这条不能从"短标签干净"外推，本来必须逐条实测。§20.2① 的圆括号教训不外推到官方方括号词表。
2. **`sim` 低于 1.0 的 8 条没有一条是漏字**，两种成因都能解释：0.968 那几条是"没事"被读成"**没事儿**"（儿化），t10/p01/p02/p06 是句首或句界多出"**啊**"这类语气发声。后者其实是指令被实现的正面证据（疲惫的人先叹一口气），所以本批的 `sim` 只当"有没有念出标签文字"的门槛用，**不当扣分项**。
3. **作用域止于句界：生产必须逐句下标签**。同一句台词、只差标签数量，段首一枚（x01）发声量 1.207×，逐句两枚（q7）1.559×，**差 29%**。官方文档那句"作用于其后所有文本，直到遇到下一个控制类标签或因句子较长被自动切分"在短句上的实际行为是后者——第二句没被第一枚标签覆盖。这条推翻了"每个片段写一枚标签就够"的省钱设想；两个输入不同，不能拿零抖动当免检理由，如需再钉可按 `--tag r2` 复跑一次。
4. **粗排必须用发声量，不能用总时长**——本批抓到两个反例：t05 `[excited]` 的 total 只有 1.075×（排第 12 名附近）但发声量 1.372×，占比 0.873 是全场最高、只有 2 个发声段，它的机制是**压缩停顿**；t13 `[asmr]` 的 total 1.321× 看着比 t05 强，发声量却只有 1.283×、占比 0.664 全场最低档，机制是**堆停顿**。§22.1 说的"时长放大可粗排"因此要加一条限定：**按 `total` 排会把"停顿多"排在"表演强"前面**，两种机制在耳朵上是完全不同的东西。
5. **富语言类确实在指定位置插入了独立发声段**。7 条的第一句都是 620 ms，句界之后的段结构是：p01 `[gasp]` 多出 660 ms 单段；p02 `[sighing]` 多出 500 ms；p03 `[clears throat]` 多出 240＋160 两段；p04 `[giggles]` 多出 300＋340 两段，且把第二句切成 1420／60／1420；p05 `[laughing]` 多出 440＋280 两段，ASR 在同一位置写出"**呵呵**"；p06 `[cough]` 多出 540 ms。基线的段结构是 [740, 60, 1000, 1100]，句界处**没有** 240–660 ms 这个量级的段，所以这些是事件不是放慢。唯一例外是 p07 `[snorts]`：3 段、无额外发声块、发声量仅 1.090×——本批唯一疑似未采纳，按非对称判据不许自动判负，交耳朵。
6. **`[very fast]` 是全场唯一有方向性预期的取值，行为符合预期**：发声量 0.786×、`sim` 1.000、占比 0.663（加速没有顺手堆停顿）。语速通道可用，有声书里"抢话／急促"场景有低成本手段；与之配对的 `[very slowly]` 是 1.876×，两端都有实测锚点。

### 23.3 对生产立项的直接输入（`AUDIOBOOK_QWEN31_BODY_TAG_ASSEMBLY_PLAN_20261012.md`）

- **白名单不必只放 `sad`**：官方 23 个控制类的"不发音"这一档已逐取值闭合，第一阶段可以放行全表。但"不发音"≠"名不副实也能用"——t15 `[mischievously]` 1.014×、t16 `[empathetic]` 0.993× 在客观层无信号，p07 `[snorts]` 疑似未落地，这三个要等耳朵签字才能定档。
- **切片 2 的渲染器形状定了**：逐句下标签（§23.2③），不是"每片段一枚"。相应地切片 4 的计费增量＝标签字符数 × 句数，`[deep and loud shouting]` 这种长标签在长段落里会显著推高 `characters`。
- **切片 6 的灰度验收指标改用发声量**（§23.2④），否则会系统性奖励"停顿多"的写法。

### 23.4 仍未闭合

① 29 个取值的"表演是否名实相符"只能由耳朵给（§22.1：doubao 只能粗筛、qwen3.8 会编造），下一步是 30 条匿名打乱的耳裁；② q8（instruction＋标签叠加）从 §22 起就欠一条耳裁定序，本地音频现成；③ SSML `<break>`／`<phoneme>` 在 3.1 上仍未测（§22.2 红线那条的正式替代方案）；④ 官方词表之外的取值（如 `[whisper]` 单数、中文标签）无保证，本批不覆盖。

### 23.5 人耳裁定（2026-10-13，32 条 tag-blind 强度盲评）与白名单定档

形式按用户 2026-10-13 的长期要求改为**内置浏览器页内点选**：`backend/data/tts_debug/b4_qwen31_tag_scan/listen_tag_scan.html`，每行「强／弱／无」radio ＋ 可选备注，答案存 localStorage，页尾导出制表符文本。本轮只问强度、不露标签名（名字会把耳朵带过去，§21 的评分模型就是栽在同一件事上）。32 条＝ 30 实验条 ＋ q7（`[sad]` 逐句，§22 耳裁冠军）＋ q4（念稿基线），FNV-1a 固定种子打乱。

**三档口径**：强＝一听就不是念稿；弱＝有差别但要留意才听得出；无＝和念稿听不出区别。
**结果分布**：强 18／弱 10／无 1（另 x01 强）。两条对照：**q7＝强**（与 §22 一致，标尺立住）、**q4 基线＝弱**（不是"无"）。

| key | 标签 | 耳裁 | voiced× | Δ响度 dB | key | 标签 | 耳裁 | voiced× | Δ响度 dB |
|---|---|---|---|---|---|---|---|---|---|
| t01 | `[amazed]` | 强 | 1.510 | +0.76 | t08 | `[like dracula]` | 弱 | **1.910** | +0.36 |
| t02 | `[deep and loud shouting]` | 强 | 1.421 | **+2.44** | t13 | `[asmr]` | 弱 | 1.283 | **−10.83** |
| t03 | `[trembling]` | 强 | 1.338 | −0.49 | t15 | `[mischievously]` | 弱 | 1.014 | −0.35 |
| t04 | `[angry]` | 强 | 1.428 | +0.59 | t16 | `[empathetic]` | 弱 | 0.993 | −0.09 |
| t05 | `[excited]` | 强 | 1.372 | +0.12 | t18 | `[reluctantly]` | 弱 | 1.338 | +0.51 |
| t06 | `[sarcastic]` | 强 | 1.634 | +1.53 | t20 | `[serious]` | 弱 | 1.110 | +0.35 |
| t09 | `[bored]` | 强 | 1.462 | −0.89 | t21 | `[very slowly]` | 弱 | **1.876** | +1.21 |
| t10 | `[tired]` | 强 | 1.752 | −2.48 | t22 | `[very fast]` | 弱 | 0.786 | +1.96 |
| t11 | `[scornful]` | 强 | 1.310 | −0.57 | p07 | `[snorts]` | 弱 | 1.090 | −0.20 |
| t12 | `[shouting]` | 强 | **1.069** | **+2.16** | t17 | `[whispers]` | **无** | 1.117 | **−9.46** |
| t14 | `[panicked]` | 强 | 1.331 | +0.91 | 参照 | q7 `[sad]` 逐句 | 强 | 1.559 | +0.15 |
| t19 | `[crying]` | 强 | 1.600 | −0.28 | 参照 | x01 `[sad]` 段首一枚 | 强 | 1.207 | −1.30 |
| p01 | `[gasp]` | 强 | 1.400 | −0.51 | 参照 | q4 念稿基线 | 弱 | 1.000 | 0.00 |
| p02 | `[sighing]` | 强 | 1.283 | −1.36 | | | | | |
| p03 | `[clears throat]` | 强 | 1.276 | +0.16 | | | | | |
| p04 | `[giggles]` | 强 | 1.434 | +0.44 | | | | | |
| p05 | `[laughing]` | 强 | 1.269 | −0.74 | | | | | |
| p06 | `[cough]` | 强 | 1.283 | +0.20 | | | | | |

`Δ响度` 是本节新补的客观轴：**帧 RMS 相对满量程（dBFS）、取发声段均值、与 q4 基线做差**。§23.1 的能量剖面阈值是按每条自身峰值 −35 dB 定的，逐条归一，"整体更响/更轻"这条通道在原表里**完全不可见**。该轴已落进留存脚本 `backend/app/scripts/probe_tts_audio_energy.py`（新增 `voiced_rms_dbfs` 字段，`--baseline` 时打印 ΔdB 列），B3／B4 两批的 `energy/*.json` 已按新口径重跑补齐，下一批不必再手推。

### 23.6 五条判定（耳裁 × 两轴客观层）

1. **三档实际退化成两档，定档只能按"强／非强"二值用**。基线 q4 落在"弱"而非"无"，而弱档 10 条里有 4 条（t15 1.014、t16 0.993、p07 1.090、t22 0.786）发声量在或低于基线——"弱"的可操作含义就是"与念稿同级"。耳朵本轮可靠分辨的只有"强"这一档。
2. **客观粗排必须同时看发声量与绝对响度，单轴会同时产生假阳和假阴**。两个互补反例：t12 `[shouting]` 发声量 1.069（全场倒数第四）却判强，靠的是 Δ响度 +2.16 dB＝全场最高，是"更响"不是"更长"；t08 `[like dracula]` 1.910、t21 `[very slowly]` 1.876 是全场放慢最狠的两条，Δ响度只有 +0.36/+1.21，双双判弱。合起来是一条干净的方向性结论：**放慢而不加力＝耳朵不给分；不加长而加响＝耳朵给分**。§23.2④ 只说了"别用总时长"，这条把剩下的那个轴也补齐了。
3. **"弱／无"绝不等于"未采纳"，该非对称性在耳朵方向上同样成立**。t17 `[whispers]` Δ−9.46 dB、t13 `[asmr]` Δ−10.83 dB，是全场唯一两条大幅压低音量的写法，实现得极其干净，耳朵却给"无／弱"。不是词表失效，而是"整体变轻"在人的听感里不计入表演强度。对有声书的直接含义：**轻音量是一条独立需求（悄悄话、贴麦气声），这两条按用途保留、不按强度淘汰**；副作用是成品人声会低 9–10 dB，混音/响度归一层是否兜底**未测**。
4. **两轴在"淘汰"方向上与耳朵一致，在"加冕"方向上一致性破裂**：客观层无信号的三条（t15／t16／p07）全部落弱档，富语言类有独立发声段的六条全部判强。所以 §22.1 的"时长可粗排"精确化为：**发声量＋响度两轴可用于自动淘汰，不可用于选冠军**（t08／t21 就是会排在冠军前面的假阳）。
5. **x01（段首一枚）与 q7（逐句）耳裁同档都强**，但发声量差 29%、响度差 1.3 dB。§23.2③ 的"必须逐句"依据因此从"不逐句就听不出"降为"**表演量级更低**"：生产仍按逐句装配（q7 是两轮耳裁冠军形状，且花钱换量级），但逐句不再是硬红线，预算紧张或长句可用段首一枚。

### 23.7 白名单定档（切片 1 的输入，`AUDIOBOOK_QWEN31_BODY_TAG_ASSEMBLY_PLAN_20261012.md` §3.2）

| 档位 | 放行取值 | 依据 | 用法约束 |
|---|---|---|---|
| **第一档·情绪**（13） | `sad`（§22＋本轮双轮耳裁）, `amazed`, `angry`, `crying`, `excited`, `panicked`, `sarcastic`, `scornful`, `trembling`, `tired`, `bored`, `shouting`, `deep and loud shouting` | 耳裁强＋客观两轴至少一轴有信号 | 逐句下标签，进情绪映射主表 |
| **第二档·事件**（6） | `gasp`, `sighing`, `clears throat`, `giggles`, `laughing`, `cough` | 耳裁强＋客观确有独立发声段 | 只在句界/段首插一枚，**不逐句**（逐句会连发三次） |
| **第三档·物理效果**（4） | `very fast`, `very slowly`, `whispers`, `asmr` | 客观方向性明确（0.79×／1.88×／−9.5 dB／−10.8 dB），耳朵不计入情绪强度 | 按节奏或音量需求**显式调用**，不进情绪表 |
| **暂缓**（7） | `curious`, `like dracula`, `mischievously`, `empathetic`, `reluctantly`, `serious`, `snorts` | 耳裁弱且无专用用途 | 不放行 |

**本轮未闭合的两点，交给第二轮页内点选**（形式同上，本地零成本，页面 `backend/data/tts_debug/b4_qwen31_tag_scan/listen_b4_namecheck.html`）：① 耳裁只给了强度、没给名字，第一档里七对近义取值（`bored`/`tired`、`sarcastic`/`scornful`、`trembling`/`crying`、`excited`/`amazed`、`shouting`/`deep and loud shouting`、`angry`/`panicked`、`giggles`/`laughing`）可能被听成同一个东西；若确实分不出，映射层要把它们**合并成同桶并只放行一个**，否则情绪名实不符。第二轮把名字放进问题、把映射藏起来（每对只标甲／乙，问"更『无聊』的是哪一条"）：两个名字各自命中一条＝能分且名实相符，指向同一条＝该并桶。② q8（instruction＋标签叠加）仍欠耳裁定序，与上一点同批复听；它的客观锚点已随绝对响度轴补测落盘（`energy/q8_qwen31_director_plus_sad_tag.json`：发声量 4260 ms＝**1.469×**、Δ响度 −0.09 dB、仅 3 个发声段），按发声量排在 q7（1.559×）之后、q2（1.110×）之前，耳朵只需判"叠加是否强于纯标签"。



---

_创建：2026-10-10；同日完成 G1–G7 门槛批次并回写 §0/§1/§2/§4/§5/§6/§7/§8/§9/§10，同日完成 **§11 B1 MiMo 写法批次（免费，3 轮 18 条）**、**§12 B2 付费写法批次（3 轮 45 条）＋ 豆包单向 HTTP 定性（15 次）**、**§13 生产形状自我更正 → §16 判定实验（污染确证）**、**§14 探针密钥泄漏 → §17 已修**。§8 的文档部分已回写进 `MODEL_INTEGRATION_REFERENCE.md` §11.9/§11.10。本文件为取证与实验设计输入；档案字段上调、情绪参数透传等生产改动仍须另行批准，真实付费调用逐批单独确认。**2026-10-11：交接复核、B3 扩到 8 写法、评分层参数化与豆包 Cot 落地状态记录在 §19；B3 已发并出客观层结论（24 次合成 + 10 次 ASR + 本地能量分析）在 §20，盲评 12 次结果在 §21，**人耳裁定与 3.1 写法层收口在 §22（§21.1 的两条结论被耳裁推翻，已就地标注更正）**。**2026-10-13：B4 一次扫完 3.1 官方标签取值（30 次合成 + 30 份 ASR + 本地能量剖面）在 §23——全表逐取值不发音、作用域止于句界故必须逐句下标签、时长粗排改用发声量而非总时长；同日本人耳裁定 32 条（§23.5）并补测绝对响度轴，得出"发声量＋响度两轴才能粗排、且只用于淘汰"、"变轻≠未采纳"、白名单四档定档在 §23.6–§23.7。**_
