"""
剧本转化 Mixin

包含 _transform_to_script 和 _transform_paragraph 方法
"""
import logging
import re
from typing import List, Dict, Any, Optional, Callable

from app.services.audiobook.llm_client import call_audiobook_llm_async
from app.services.audiobook.llm_json import (
    LLMJsonParseError,
    clean_llm_json_text,
    parse_llm_json_array,
)

from ._dataclasses import ScriptSegment
from ._segment_validation import build_script_segments

logger = logging.getLogger(__name__)

TRANSFORM_BATCH_TARGET_CHARS = 850
TRANSFORM_BATCH_HARD_CHARS = 1200
TRANSFORM_RETRY_CHUNK_TARGET_CHARS = 650
TRANSFORM_RETRY_CHUNK_HARD_CHARS = 850
TRANSFORM_OUTPUT_TOKEN_MIN = 1800
TRANSFORM_OUTPUT_TOKEN_MAX = 9000
TRANSFORM_CONTINUITY_SEGMENTS = 4
TRANSFORM_CONTINUITY_MAX_CHARS = 520


class TransformMixin:
    """剧本转化方法"""
    
    async def _transform_to_script(
        self,
        content: str,
        character_list: List[str],
        analysis: Dict[str, Any],
        audio_adaptation_brief: str = "",
        progress_callback: Optional[Callable[[int, int], None]] = None,
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> List[ScriptSegment]:
        """
        剧本转化：听觉化改写
        
        核心改编策略：
        1. 心理活动 → 独白/音效暗示
        2. 环境描写 → 音效标注
        3. 复杂描述 → 简化为听觉友好的语言
        4. 对话优化 → 删除拗口词汇
        """
        
        # 分段处理：仅丢弃空行，短句/短对白必须保留，避免改编前丢失原文。
        paragraphs = [p.strip() for p in content.splitlines() if p.strip()]
        
        # 合并短段落，但限制单次 LLM 转化请求体量，避免 JSON 模式大输出长时间无响应。
        merged_paragraphs = self._build_transform_batches(paragraphs)
        
        total_paras = len(merged_paragraphs)
        logger.info(f"📝 合并后 {total_paras} 个批次（原 {len(paragraphs)} 段），总长度: {len(content)} 字")
        
        all_segments = []
        continuity_context = ""
        
        for idx, para in enumerate(merged_paragraphs, 1):
            logger.info(f"   ⏳ [{idx}/{total_paras}] 处理段落 ({len(para)}字)...")
            
            try:
                segments = await self._transform_paragraph(
                    para,
                    character_list,
                    analysis,
                    audio_adaptation_brief=audio_adaptation_brief,
                    character_profiles=character_profiles,
                    continuity_context=continuity_context,
                )
                all_segments.extend(segments)
                continuity_context = self._build_transform_continuity_context(all_segments)
                logger.info(f"   ✅ [{idx}/{total_paras}] 完成，生成 {len(segments)} 个片段")
            except Exception as e:
                logger.error(f"   ❌ [{idx}/{total_paras}] 失败: {e}")
                # 继续处理下一段，不中断整个流程
                pass

            if progress_callback:
                progress_callback(idx, total_paras)
        
        logger.info(f"✅ 全部段落处理完成，总计 {len(all_segments)} 个剧本片段")
        
        # 🆕 根据用户偏好：不在这里强制合并短片段，而是尽量在编剧阶段控制片段长度
        logger.info(f"📝 保持原始剧本片段数量：{len(all_segments)}（不做短片段自动合并）")
        
        # 可选：如启用语义验证，仅用于日志提示，不再强制修改结构
        if self.strategy and getattr(self.strategy, 'semantic_validation', False):
            all_segments = self._validate_semantic_integrity(all_segments)
        
        return all_segments

    def _build_transform_batches(self, paragraphs: List[str]) -> List[str]:
        """把原文段落组装成适合单次有声剧本转化的小批次。"""
        merged_paragraphs: List[str] = []
        current_batch: List[str] = []
        current_length = 0

        for para in paragraphs:
            for part in self._split_long_paragraph_for_transform(para):
                part_length = len(part)
                separator_length = 1 if current_batch else 0
                would_exceed_target = (
                    current_batch
                    and current_length + separator_length + part_length > TRANSFORM_BATCH_TARGET_CHARS
                )

                if would_exceed_target:
                    merged_paragraphs.append("\n".join(current_batch))
                    current_batch = [part]
                    current_length = part_length
                else:
                    current_batch.append(part)
                    current_length += separator_length + part_length

        if current_batch:
            merged_paragraphs.append("\n".join(current_batch))

        return merged_paragraphs

    def _split_long_paragraph_for_transform(self, paragraph: str) -> List[str]:
        """按句子边界拆分过长段落，避免单段超过安全上限。"""
        text = str(paragraph or "").strip()
        if not text:
            return []
        if len(text) <= TRANSFORM_BATCH_HARD_CHARS:
            return [text]

        sentence_units = [
            unit.strip()
            for unit in re.findall(r"[^。！？!?；;]+[。！？!?；;]?", text)
            if unit.strip()
        ] or [text]

        chunks: List[str] = []
        current: List[str] = []
        current_length = 0

        def flush_current() -> None:
            nonlocal current, current_length
            if current:
                chunks.append("".join(current).strip())
                current = []
                current_length = 0

        for unit in sentence_units:
            if len(unit) > TRANSFORM_BATCH_HARD_CHARS:
                flush_current()
                for start in range(0, len(unit), TRANSFORM_BATCH_HARD_CHARS):
                    chunk = unit[start:start + TRANSFORM_BATCH_HARD_CHARS].strip()
                    if chunk:
                        chunks.append(chunk)
                continue

            if current and current_length + len(unit) > TRANSFORM_BATCH_HARD_CHARS:
                flush_current()

            current.append(unit)
            current_length += len(unit)

        flush_current()
        return chunks

    def _split_paragraph_for_parse_retry(self, paragraph: str) -> List[str]:
        """JSON 解析失败后使用更小的句子批次重试，降低单次输出复杂度。"""
        text = str(paragraph or "").strip()
        if not text:
            return []

        source_lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(source_lines) > 1:
            chunks: List[str] = []
            for line in source_lines:
                if len(line) <= TRANSFORM_RETRY_CHUNK_HARD_CHARS:
                    chunks.append(line)
                    continue
                for start in range(0, len(line), TRANSFORM_RETRY_CHUNK_HARD_CHARS):
                    chunk = line[start:start + TRANSFORM_RETRY_CHUNK_HARD_CHARS].strip()
                    if chunk:
                        chunks.append(chunk)
            return chunks

        sentence_units = [
            unit.strip()
            for unit in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
            if unit.strip()
        ] or [text]

        chunks: List[str] = []
        current: List[str] = []
        current_length = 0

        def flush_current() -> None:
            nonlocal current, current_length
            if current:
                chunks.append("".join(current).strip())
                current = []
                current_length = 0

        for unit in sentence_units:
            if len(unit) > TRANSFORM_RETRY_CHUNK_HARD_CHARS:
                flush_current()
                for start in range(0, len(unit), TRANSFORM_RETRY_CHUNK_HARD_CHARS):
                    chunk = unit[start:start + TRANSFORM_RETRY_CHUNK_HARD_CHARS].strip()
                    if chunk:
                        chunks.append(chunk)
                continue

            if current and current_length + len(unit) > TRANSFORM_RETRY_CHUNK_TARGET_CHARS:
                flush_current()

            current.append(unit)
            current_length += len(unit)

        flush_current()
        return chunks

    def _estimate_transform_max_tokens(self, paragraph: str) -> int:
        """根据输入长度估算 JSON 输出预算，避免固定 32000 导致慢请求。"""
        paragraph_length = len(str(paragraph or ""))
        estimated = int(paragraph_length * 2.8) + 1000
        return max(TRANSFORM_OUTPUT_TOKEN_MIN, min(TRANSFORM_OUTPUT_TOKEN_MAX, estimated))

    def _estimate_transform_timeout(self, max_tokens: int) -> int:
        """给段落改编请求设置显式超时，和动态输出预算保持一致。"""
        estimated = int(max_tokens / 80) + 60
        return max(90, min(180, estimated))

    def _build_transform_continuity_context(self, segments: List[ScriptSegment]) -> str:
        """提取上一批结尾状态，给下一批保持剧情、角色和情绪连续性。"""
        recent_segments = [segment for segment in segments if str(getattr(segment, "text", "")).strip()]
        recent_segments = recent_segments[-TRANSFORM_CONTINUITY_SEGMENTS:]
        if not recent_segments:
            return ""

        lines: List[str] = []
        for segment in recent_segments:
            text = str(getattr(segment, "text", "") or "").strip()
            if not text:
                continue
            speaker = str(getattr(segment, "speaker", "") or "旁白").strip() or "旁白"
            emotion = str(getattr(segment, "emotion", "") or "neutral").strip() or "neutral"
            segment_type = str(getattr(segment, "type", "") or "narration").strip() or "narration"
            text = re.sub(r"\s+", " ", text)
            if len(text) > 80:
                text = text[:80].rstrip() + "..."
            lines.append(f"- {speaker}/{segment_type}/{emotion}: {text}")

        context = "\n".join(lines)
        if len(context) > TRANSFORM_CONTINUITY_MAX_CHARS:
            context = context[-TRANSFORM_CONTINUITY_MAX_CHARS:].lstrip()
        return context
    
    async def _transform_paragraph(
        self,
        paragraph: str,
        character_list: List[str],
        analysis: Dict[str, Any],
        audio_adaptation_brief: str = "",
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        continuity_context: str = "",
        allow_parse_retry: bool = True,
    ) -> List[ScriptSegment]:
        """转化单个段落
        
        Args:
            character_profiles: 🆕 完整角色档案（用于对话归属和角色身份识别）
        """
        
        model_name = (getattr(self, "tts_model", None) or "qwen3-tts-instruct-flash").strip()
        if "plus" in model_name:
            tts_block = """**当前TTS模型：CosyVoice v3.5-plus（精品模式）**\n- 适合：精品章节 / 情绪层次丰富场景\n- 特性：精细情感控制、instruction 演绎能力强，但必须使用复刻/设计音色\n"""
            instruct_block = (
                "**Instruct 提示（cosyvoice-v3.5-plus）**\n"
                "- 无系统音色，请默认上游已选择复刻/设计 voice_id\n"
                "- 请输出结构化指令字段：instruct_emotion / instruct_scene / instruct_role / instruct_identity\n"
                "- instruct_emotion 取值：neutral、fearful、angry、sad、surprised、happy、disgusted\n"
                "- 请优先输出通用自然语言约束，不要依赖固定内置音色枚举\n"
            )
        else:
            tts_block = """**当前TTS模型：Qwen3-TTS Instruct Flash（默认模式）**\n- 适合：长篇连载 / 日更章节 / 成本敏感但需要一定表现力的内容\n- 特性：49 音色、稳定性强、成本低，并支持通过自然语言 instructions 控制语气与演绎\n- 限制：当前链路重点是 instructions，不要输出 SSML 语法\n"""
            instruct_block = """**Qwen3 Instruct 提示**\n- 请输出结构化指令字段：instruct_emotion / instruct_scene / instruct_role / instruct_identity\n- performance_notes 会一并映射到 Qwen instructions，请写成可直接执行的演绎说明\n- qwen3-tts-instruct-flash 不依赖 SSML，请直接描述情绪、场景、身份与语气目标\n"""

        six_step_block = """**有声剧本 6 步听觉化重构流程（请严格遵守）**
1. 心理活动 → 改写为可听见的独白或用音效/环境暗示呈现，避免长篇抽象描写。
2. 环境描写 → 提炼为可感知的音效标签（如“雨声渐密”“地铁驶过”），填入 sound_effects。
3. 动作与场景切换 → 用短句 + 停顿 + 过渡性音效，避免连续大段说明。
4. 对话优化 → 口语化，必要时拆分过长句子，允许适度长句，去掉拗口表达，保证朗读顺畅。
5. 节奏控制 → 根据情节紧张度调整句长，并通过 pause_before/pause_after 控制呼吸感。
6. 音乐与情绪 → 为情绪明显的片段给出 music_cue（如“低频紧张弦乐”），避免整章铺满BGM。
   - 音效密度建议控制在每分钟 2-6 个，仅保留关键动作/场景的音效。
   - 配乐覆盖建议 15%-40%，低密度时仅保留开头/结尾/高潮等关键位置。
   - 原文中的 [pause:xs]、[break]、%P% 是结构停顿提示，不要当成文字朗读；请转成 pause_before/pause_after，或保留在相邻 text 末尾交给渲染层识别。
"""

        adaptation_block = (
            f"**跨模态改编提示**:\n{audio_adaptation_brief}\n\n"
            if audio_adaptation_brief
            else ""
        )
        continuity_block = (
            "**上一批结尾状态**（仅用于保持承接关系，不要复述这些内容）：\n"
            f"{continuity_context}\n\n"
            if continuity_context
            else ""
        )
        
        character_block = ""
        if character_profiles:
            character_block = "**角色参考**（用于对话归属和角色身份识别）：\n"
            for char in character_profiles:
                char_desc = f"- {char['name']}"
                if char.get('role_position'):
                    char_desc += f"（{char['role_position']}）"
                if char.get('relations'):
                    char_desc += f"，{char['relations']}"
                character_block += char_desc + "\n"

        prompt = f"""你是专业的有声书剧本改编师，负责将网络小说改编成适合音频化播放的有声剧本。

{tts_block}

{instruct_block}

{six_step_block}

**🎯 片段划分与语义完整性（硬性要求）**
        
下面的规则是硬性要求。请把小说段落改成“可播讲单元”，而不是把原文整段搬进一个 narration：
        
1【推荐做法：语义完整优先】
   - 尽量让每个片段在语义上自洽：包含完整的动作/情绪/场景信息，而不是被机械拆成几字一段。
   - 旁白片段建议 45-120 字；强动作、强情绪、转场、回忆切入处必须拆段。
   - 单个 narration 不要超过 140 字；单个 dialogue/monologue 不要超过 120 字。确有长句时，按动作拍点、情绪转折、因果推进拆成多个片段。
   - 每个片段只承载一个主要听觉任务：动作爆发、伤害结果、角色反应、逃离推进、回忆切入，不要全部塞进同一段。
        
2【短片段的合理场景】
   - ✅ 简短而自然的对白/感叹（如"好。""这不可能！"，"你说什么？"）可以作为独立片段存在；
   - ✅ 强烈情绪的短句（惊讶/愤怒/紧张等）适合单独成段，用来制造节奏和冲击力；
   - ❗ 建议避免：完全脱离上下文、让人不知所云的碎片（如单独出现的"就一晚。"而看不到前后铺垫）。
        
3【长叙事的有声化拆分】
   - 连续动作描写：按“发动 → 受击 → 后果 → 反应”拆分。
   - 逃亡/追逐/战斗：每个片段保留一个清晰动作，使用 pause_after 制造呼吸点。
   - 回忆切入：单独成段，给出更慢、更低的 performance_notes，并可添加轻微转场音效。
   - 有明显音效的动作（倒地、骨裂、风声、脚步、墓前静默）应单独标注 sound_effects，不要只写在 text 里。

4【对话与旁白关系】
   - 直接引语必须拆成 dialogue：凡是原文中出现 “...”、「...」、『...』 或 角色说/道/问/喊/低声 后面的台词，都必须单独输出为 dialogue 片段。
   - speaker 必须写真实角色名：原文明确说话人时使用该角色名；上下文连续且说话人明确时沿用最近角色；只有叙述性文字才使用 speaker=旁白。
   - 不要把角色台词归到旁白；不要把带引号的台词和旁白合成一个 narration。可拆成“旁白动作/心理” + “dialogue 台词”两个片段。
   - 对于本来就自然很短的应答（"行。""好。"），可以放心保留为独立片段，不必强行合并。

5【旁白情绪层次】
   - 旁白也必须有情绪层次，不要整章都使用 neutral。根据场景张力选择 tense、fearful、mysterious、sad、solemn 等更准确的 emotion。
   - 旁白的 performance_notes 必须具体可执行：说明语速、声线、重读位置、停顿目标；例如“低沉克制但有压迫感，关键意象处放慢并加重，句尾留悬念停顿”。
   - 旁白要丰富但不抢角色台词：保持讲述者身份，不替角色喊台词，不把角色对白写进 narration。
        
总之：**请优先保证片段听起来像有声小说分镜，而不是长段朗读；语义完整和播讲呼吸必须同时满足。**
        
**已知角色**: {', '.join(character_list) if character_list else '无'}
{character_block}
**情感基调**: {analysis.get('emotional_tone', 'neutral')}
**建议情感**: {', '.join(analysis.get('recommended_emotions', ['natural']))}
**节奏模式**: {analysis.get('rhythm_pattern', '中等')}
{adaptation_block}
{continuity_block}

**原文段落**:
{paragraph}

**输出格式**：
请以**纯净的JSON对象格式**输出剧本片段（不要包含任何注释或说明文字），顶层必须是 `segments` 数组：

**字段合约**：
- 优先使用 `sound_effects` / `music_cue` 的精品字段；只有无法判断参数时才使用 `sound_effects_simple` / `music_cue_simple`。
- JSON 内不要写 `//`、`/* */` 或解释性文字。
- 不要同时为同一个听觉事件重复填写精品字段和 simple 字段。
- 每个片段对象中每个 key 只能出现一次，禁止重复输出 `performance_notes`、`sound_effects`、`music_cue` 等字段。
- `type=dialogue` 时 `speaker` 必须是角色名，禁止使用旁白；不确定说话人时才退回 narration。
- `type=narration` 时 `speaker` 必须为旁白，且 text 中不得包含角色引号台词。
- `sound_effects` 每个片段最多 2 个；没有关键音效时使用空数组。
- `music_cue` 只在开场、转场、高潮、强情绪片段出现；普通片段使用 null 或省略，不要整段铺满 BGM。
- 如果使用 `sound_effects`，则 `sound_effects_simple` 必须为 []；如果使用 `music_cue`，则 `music_cue_simple` 必须为空字符串。

```json
{{
  "segments": [
    {{
      "type": "narration|dialogue|monologue",
      "text": "实际要朗读的文本",
      "speaker": "角色名或旁白",
      "emotion": "neutral|happy|sad|angry|calm|tense|excited|tender|solemn",
      "instruct_emotion": "neutral|fearful|angry|sad|surprised|happy|disgusted",
      "instruct_scene": "紧张逃亡场景",
      "instruct_role": "沉稳有压迫感的有声书旁白",
      "instruct_identity": "故事讲述者",
      "voice_params": {{
        "rate": 1.0,
        "pitch": 1.0,
        "pause_before": 0.2,
        "pause_after": 0.3
      }},
      "performance_notes": "低声、短促，句尾留出紧张停顿",
      "sound_effects": [
        {{
          "name": "脚步声",
          "layer": "action",
          "volume": 0.3,
          "timing": "trigger",
          "position_3d": "left_to_right",
          "duration": 2.0,
          "fade_out": 0.5
        }}
      ],
      "music_cue": {{
        "style": "悬疑低频弦乐",
        "volume": 0.2,
        "fade_in": 2.0,
        "fade_out": 2.0,
        "emotion_follow": true
      }},
      "sound_effects_simple": [],
      "music_cue_simple": "",
      "original_text": "对应的原文",
      "adaptation_reason": "按动作拍点拆分，并用停顿营造压迫感"
    }}
  ]
}}
```

**🎵 音效/配乐标注指南**：

1. **音效分层原则**：
   - bottom（底音）：持续的环境音，如"雨声""风声""火光燃烧噪噪声"，音量0.08-0.15
   - action（动作）：触发式音效，如"脚步声""开门声""剑刃碰撞"，音量0.3-0.5
   - atmosphere（氛围）：情绪加强，如"诡异回声""雷声""人群噪声"，音量0.2-0.4

2. **3D位置使用**：
   - 角色移动：使用 left_to_right 或 right_to_left
   - 静态场景：center（主角视角）、left/right（配角）、back（远处）

3. **配乐音量控制**：
   - 日常场景：0.15-0.2
   - 情绪高涨：0.3-0.4
   - 高潮场景：0.4-0.5（关键处留白，突出台词）

*重要提醒**：
- 只输出 JSON 对象，顶层格式为 {{"segments": [...]}}，不要添加任何 // 注释或 /* 注释 */
- 不要在JSON中添加解释性文字
- emotion字段必须使用推荐情感之一，不要自行发明
- instruct_emotion 可用于 qwen3-tts-instruct-flash / cosyvoice-v3.5-plus；CosyVoice 请使用 neutral、fearful、angry、sad、surprised、happy、disgusted
- instruct_scene / instruct_role / instruct_identity 可用于 qwen3-tts-instruct-flash / cosyvoice-v3.5-plus；CosyVoice 请输出通用自然语言约束，不要依赖固定系统音色枚举
- voice_params必须包含rate和pitch参数，根据情感调整
- pause_before/after单位为秒，范围：0.1-2.0
- 优先使用happy/sad/tense等有强烈情感的标签，避免过多使用neutral
- performance_notes要具体可执行，帮助TTS调节韵律和语气；在 qwen3-tts-instruct-flash 中它会直接参与 instructions 构建
- adaptation_reason说明为什么这样设置句式和停顿，以服务听觉节奏

🔥 **极重要：text字段内容规范**
- text字段必须是**实际要朗读的台词/旁白内容**，不要写对朗读方式的描述
- ❌ 错误示例："旁白将温柔地讲述接下来的情节"（这是剧本指导语，不是台词）
- ❌ 错误示例："旁白怎样怎样选择"（这是对角色的描述，不是台词）
- ✅ 正确示例："夜幕降临，城市的灯光逐渐亮起"（这是实际的旁白台词）
- ✅ 正确示例："你真的要这样做吗？"（这是实际的对话台词）
- 如果需要说明朗读方式，请使用performance_notes字段，不要写在text中
"""
        
        try:
            
            # 使用有声书专用 LLM 配置，避免模型路由落到已下线模型。
            # 输出预算按段落长度估算，避免小段落也请求 32000 tokens 导致超时。
            max_tokens_value = self._estimate_transform_max_tokens(paragraph)
            timeout_value = self._estimate_transform_timeout(max_tokens_value)
            logger.info(
                f"🔧 [段落转化] 请求 max_tokens: {max_tokens_value}, "
                f"timeout: {timeout_value}s, 段落长度: {len(paragraph)} 字"
            )
            
            response = await call_audiobook_llm_async(
                self.llm_client,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens_value,
                timeout=timeout_value,
                max_retries=2,
                use_cache=False,
                response_format={"type": "json_object"},  # 启用 deepseek JSON 模式
            )
            
            logger.info(f"📊 [段落转化] 实际返回: {len(response)} 字符 (长度阈值检查: {'large' if len(response) > 40000 else 'normal'})")
            
            # 提取JSON
            json_str = clean_llm_json_text(response)
            
            # 清理JSON字符串（移除注释和多余逗号）
            # 移除单行注释 // ...
            # 移除多行注释 /* ... */
            # 移除数组/对象末尾的多余逗号
            
            # 记录清理后的JSON（用于调试）
            if len(json_str) > 500:
                logger.debug(f"清理后的JSON（前500字符）: {json_str[:500]}")
            else:
                logger.debug(f"清理后的JSON: {json_str}")
            
            try:
                segments_data = parse_llm_json_array(response)
            except LLMJsonParseError as json_err:
                error_context = self._format_json_error_context(json_str, json_err)
                logger.error(f"JSON解析失败: {json_err}; {error_context}")
                logger.error(f"JSON解析失败，原始响应前1000字符: {response[:1000]}")
                logger.error(f"清理后JSON前1000字符: {json_str[:1000]}")
                if allow_parse_retry:
                    retried_segments = await self._retry_transform_paragraph_in_smaller_chunks(
                        paragraph,
                        character_list,
                        analysis,
                        audio_adaptation_brief=audio_adaptation_brief,
                        character_profiles=character_profiles,
                        continuity_context=continuity_context,
                    )
                    if retried_segments:
                        return retried_segments
                raise RuntimeError(f"LLM返回的JSON格式错误: {json_err}") from json_err
            
            # 修复：将中文字段名转换为英文（LLM 偶尔会返回中文字段）
            field_mapping = {
                '类型': 'type',
                '文本': 'text',
                '说话人': 'speaker',
                '情绪': 'emotion',
                '情感值': 'instruct_emotion',
                '指令情感': 'instruct_emotion',
                '场景': 'instruct_scene',
                '指令场景': 'instruct_scene',
                '指令角色': 'instruct_role',
                '角色指令': 'instruct_role',
                '身份': 'instruct_identity',
                '指令身份': 'instruct_identity',
                '动作': 'action',
                '音效': 'sound_effects',
                '音乐': 'music_cue',
                '改编理由': 'adaptation_reason',
                'adaptation_理由': 'adaptation_reason',  # 混合情况
            }
            
            # 清理字段名
            cleaned_segments = []
            has_mapped_fields = False
            for seg in segments_data:
                if not isinstance(seg, dict):
                    cleaned_segments.append(seg)
                    continue

                cleaned_seg = {}
                for key, value in seg.items():
                    # 如果是中文字段名，转换为英文
                    english_key = field_mapping.get(key, key)
                    has_mapped_fields = has_mapped_fields or english_key != key
                    cleaned_seg[english_key] = value
                cleaned_segments.append(cleaned_seg)
            
            # 记录字段映射情况（调试）
            if has_mapped_fields:
                logger.warning("⚠️ LLM返回了中文字段名，已自动转换为英文")
            
            # 转换为ScriptSegment对象
            script_segments = build_script_segments(cleaned_segments, fallback_text=paragraph)
            if not script_segments:
                raise RuntimeError("LLM returned no valid script segments")
            return script_segments
            
        except Exception as e:
            logger.error(f"段落转化失败: {e}")
            return build_script_segments([], fallback_text=paragraph)

    def _format_json_error_context(self, json_text: str, json_err: Exception, radius: int = 320) -> str:
        """生成解析失败位置附近的上下文，便于定位模型输出污染点。"""
        message = str(json_err)
        match = re.search(r"\(char\s+(\d+)\)", message)
        if not match:
            return f"json_len={len(json_text)}"
        pos = int(match.group(1))
        start = max(0, pos - radius)
        end = min(len(json_text), pos + radius)
        snippet = json_text[start:end].replace("\n", "\\n")
        return f"json_len={len(json_text)} error_char={pos} context={snippet}"

    async def _retry_transform_paragraph_in_smaller_chunks(
        self,
        paragraph: str,
        character_list: List[str],
        analysis: Dict[str, Any],
        *,
        audio_adaptation_brief: str = "",
        character_profiles: Optional[List[Dict[str, Any]]] = None,
        continuity_context: str = "",
    ) -> List[ScriptSegment]:
        """解析失败后把原批次拆小重试，尽量保留 LLM 改编质量。"""
        chunks = self._split_paragraph_for_parse_retry(paragraph)
        if len(chunks) <= 1:
            return []

        logger.warning(
            "段落转化 JSON 解析失败，开始拆小重试: 原长度=%s chunks=%s",
            len(str(paragraph or "")),
            len(chunks),
        )

        recovered: List[ScriptSegment] = []
        retry_context = continuity_context
        for idx, chunk in enumerate(chunks, 1):
            try:
                chunk_segments = await self._transform_paragraph(
                    chunk,
                    character_list,
                    analysis,
                    audio_adaptation_brief=audio_adaptation_brief,
                    character_profiles=character_profiles,
                    continuity_context=retry_context,
                    allow_parse_retry=False,
                )
                recovered.extend(chunk_segments)
                retry_context = self._build_transform_continuity_context(recovered)
                logger.info(
                    "段落转化拆小重试完成: %s/%s 片段=%s",
                    idx,
                    len(chunks),
                    len(chunk_segments),
                )
            except Exception as exc:
                logger.warning("段落转化拆小重试失败: %s/%s error=%s", idx, len(chunks), exc)

        return recovered
