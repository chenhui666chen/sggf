"""
有声剧本编剧Agent - 专业的小说到有声剧本改编

核心功能：
1. 前期分析：理解原著核心、评估改编难度
2. 剧本转化：听觉化改写、声音元素标注
3. 声音设计：角色声音规划、音效音乐建议
4. 输出结构化剧本：包含表演提示、音效标注

模型选择：deepseek-reasoner（需要创意+逻辑推理）
"""
import re
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field
import json

logger = logging.getLogger(__name__)


# 🆕 音效精细化控制数据结构
@dataclass
class SoundEffect:
    """
    音效详细配置（符合《多人精品有声小说改编全指南》标准）
    
    示例：
        SoundEffect(
            name="脚步声",
            layer="action",
            volume=0.3,
            timing="trigger",
            position_3d="left_to_right",
            duration=2.0,
            fade_out=0.5
        )
    """
    name: str  # 音效名称，如"脚步声""雨声""剑刃碰撞"
    layer: str = "action"  # 层级：bottom(底音) | action(动作) | atmosphere(氛围)
    volume: float = 0.3  # 音量：0.0-1.0，人声为1.0基准
    timing: str = "trigger"  # 触发方式：continuous(持续) | trigger(触发式)
    position_3d: Optional[str] = None  # 3D位置：left | right | center | back | left_to_right | right_to_left
    duration: Optional[float] = None  # 持续时长（秒），None表示自然结束
    fade_in: float = 0.0  # 淡入时长（秒）
    fade_out: float = 0.0  # 淡出时长（秒）
    delay: float = 0.0  # 延迟触发（秒），相对于片段开始


@dataclass
class MusicCue:
    """
    配乐详细配置
    
    示例：
        MusicCue(
            style="悬疑低频弦乐",
            volume=0.2,
            fade_in=2.0,
            fade_out=3.0,
            duration=15.0
        )
    """
    style: str  # 音乐风格，如"悬疑低频弦乐""古风琴笝""激昂鼓点"
    volume: float = 0.2  # 音量：0.0-1.0，建议0.15-0.4范围
    fade_in: float = 2.0  # 淡入时长（秒）
    fade_out: float = 2.0  # 淡出时长（秒）
    duration: Optional[float] = None  # 持续时长（秒），None表示持续到片段结束
    start_time: float = 0.0  # 开始时间（秒），相对于片段开始
    emotion_follow: bool = True  # 是否跟随情绪波动调整音量


@dataclass
class ChapterOpening:
    """
    章节片头配置（30秒）
    
    示例：
        ChapterOpening(
            logo_sound="玉石碰撞2秒.mp3",
            intro_text="战神将军萧衍，温柔寻亲女苏清颜...",
            intro_music=MusicCue(style="古风悬疑", volume=0.2, fade_in=2.0)
        )
    """
    logo_sound: Optional[str] = None  # LOGO音效文件名，2-3秒
    intro_text: str = ""  # 简介文本（20-30字），介绍核心人设/主题
    intro_narrator: str = "旁白"  # 简介朗读者
    intro_music: Optional[MusicCue] = None  # 片头配乐
    duration: float = 30.0  # 片头总时长（秒）


@dataclass
class ChapterClosing:
    """
    章节片尾配置（1分钟）
    
    示例：
        ChapterClosing(
            recap_text="本章回顾：萧衍中箭倒地...",
            hook_text="下章预告：背叛与救赎，萧衍能否活下来？",
            call_to_action="点赞订阅，评论区留言'萧衍挡住'"
        )
    """
    recap_text: str = ""  # 本章回顾（30-50字）
    hook_text: str = ""  # 下章预告/悬念钩子（30-60字）
    call_to_action: str = ""  # 互动引导（20-40字）
    outro_narrator: str = "旁白"  # 片尾朗读者
    outro_music: Optional[MusicCue] = None  # 片尾配乐
    duration: float = 60.0  # 片尾总时长（秒）


@dataclass
class ChapterStructure:
    """
    章节完整结构（符合《多人精品有声小说改编全指南》标准）
    
    结构：
        - 片头（30秒）：LOGO音 + 人设简介 + 配乐渐强
        - 正文（15-24分钟）：剧本片段列表
        - 片尾（1分钟）：回顾 + 钩子 + 互动引导
    
    示例：
        ChapterStructure(
            chapter_title="第8章 古墓惊魂",
            opening=ChapterOpening(...),
            body_segments=[...],
            closing=ChapterClosing(...)
        )
    """
    chapter_title: str  # 章节标题
    chapter_number: int = 1  # 章节序号
    opening: Optional[ChapterOpening] = None  # 片头（30秒）
    body_segments: List['ScriptSegment'] = field(default_factory=list)  # 正文（15-24分钟）
    closing: Optional[ChapterClosing] = None  # 片尾（1分钟）
    
    # 元数据
    genre: str = "科幻"  # 小说类型
    total_duration_estimate: float = 0.0  # 预估总时长（秒）
    climax_timestamps: List[float] = field(default_factory=list)  # 高潮点时间戳
    
    def get_total_segments(self) -> int:
        """获取总片段数（包括片头/片尾）"""
        count = len(self.body_segments)
        if self.opening:
            count += 1  # 片头算为1个片段
        if self.closing:
            count += 1  # 片尾算为1个片段
        return count
    
    def estimate_duration(self, words_per_minute: float = 210.0) -> float:
        """
        预估章节总时长
        
        Args:
            words_per_minute: 每分钟字数（默认210字/分钟）
        
        Returns:
            预估时长（秒）
        """
        total_words = sum(len(seg.text) for seg in self.body_segments)
        body_duration = (total_words / words_per_minute) * 60
        
        opening_duration = self.opening.duration if self.opening else 0
        closing_duration = self.closing.duration if self.closing else 0
        
        self.total_duration_estimate = opening_duration + body_duration + closing_duration
        return self.total_duration_estimate


@dataclass
class ScriptSegment:
    """剧本片段（改编后的结构化输出）"""
    type: str  # "narration"旁白 | "dialogue"对话 | "monologue"独白
    text: str  # 改编后的文本
    speaker: str  # 角色名或"旁白"
    emotion: str  # 情绪标签
    
    # 声音表演提示
    performance_notes: str = ""  # 如"颤抖着低语""突然提高音量"
    pause_before: float = 0.0  # 前停顿（秒）
    pause_after: float = 0.0  # 后停顿（秒）
    
    # v3-plus音声参数控制
    voice_params: Optional[Dict[str, float]] = None  # {"rate": 1.0, "pitch": 1.0, "pause_before": 0.2, "pause_after": 0.3}
    
    # 🆕 音效音乐精细化标注（新版）
    sound_effects: List[SoundEffect] = field(default_factory=list)  # 音效对象列表
    music_cue: Optional[MusicCue] = None  # 配乐对象
    
    # 🔄 兼容旧版：简单字符串标注（如果LLM返回简单格式）
    sound_effects_simple: List[str] = field(default_factory=list)  # 如["推门声", "脚步声"]
    music_cue_simple: str = ""  # 如"悬疑感的低频弦乐"
    
    # 原文信息
    original_text: str = ""  # 原始文本（用于对比）
    adaptation_reason: str = ""  # 改编原因说明
    
    def __post_init__(self):
        # 兼容处理：如果LLM返回的是旧版格式，自动转换
        if self.voice_params is None:
            self.voice_params = {
                "rate": 1.0,
                "pitch": 1.0,
                "pause_before": self.pause_before,
                "pause_after": self.pause_after
            }
        
        # 如果sound_effects_simple有内容但sound_effects为空，转换为新格式
        if self.sound_effects_simple and not self.sound_effects:
            self.sound_effects = [
                SoundEffect(name=name, layer="action", volume=0.3)
                for name in self.sound_effects_simple
            ]
        
        # 如果music_cue_simple有内容但music_cue为None，转换为新格式
        if self.music_cue_simple and self.music_cue is None:
            self.music_cue = MusicCue(style=self.music_cue_simple, volume=0.2)


class AudiobookScriptAgent:
    """
    有声剧本编剧Agent
    
    基于专业编剧工作流程，将小说文本改编为适合音频化的剧本
    """
    
    def __init__(self, llm_client=None, tts_model: str = "qwen3-tts-flash", strategy: Optional[Any] = None):
        """
        Args:
            llm_client: LLM客户端（必需，支持OptimizedLLMClient或自定义）
            tts_model: 当前使用的TTS模型（如 qwen3-tts-flash / cosyvoice-v3-plus）
            strategy: AudioDirector的AdaptationStrategy（包含语义完整性约束）
        """
        if llm_client is None:
            raise ValueError("AudiobookScriptAgent必须提供llm_client参数")
        self.llm_client = llm_client
        self.tts_model = tts_model
        self.strategy = strategy  # 🆕 保存导演策略
    
    async def adapt_chapter(
        self,
        chapter_content: str,
        character_list: Optional[List[str]] = None,
        chapter_title: str = "",
        genre: str = "科幻",
        chapter_number: int = 1,
        enable_chapter_structure: bool = True  # 🆕 是否启用章节结构化
    ) -> List[ScriptSegment]:
        """
        将章节改编为有声剧本
        
        Args:
            chapter_content: 原始章节文本
            character_list: 角色列表
            chapter_title: 章节标题
            genre: 小说类型
            chapter_number: 章节序号
            enable_chapter_structure: 是否生成完整章节结构（片头/片尾）
        
        Returns:
            如果enable_chapter_structure=False: 返回剧本片段列表
            如果enable_chapter_structure=True: 返回ChapterStructure对象
        """
        logger.info(f"🎬 开始改编章节: {chapter_title}")
        logger.info(f"   原文长度: {len(chapter_content)} 字符")
        
        # 1. 前期分析
        analysis = await self._analyze_chapter(
            chapter_content, 
            chapter_title, 
            genre
        )
        logger.info(f"   ✅ 分析完成: {analysis.get('theme', 'N/A')}")
        
        # 2. 剧本转化
        script_segments = await self._transform_to_script(
            chapter_content,
            character_list or [],
            analysis
        )
        logger.info(f"   ✅ 转化完成: {len(script_segments)} 个片段")
        
        # 🆕 3. 章节结构化（新增）
        if enable_chapter_structure:
            chapter_structure = self._build_chapter_structure(
                chapter_title=chapter_title,
                chapter_number=chapter_number,
                genre=genre,
                body_segments=script_segments,
                analysis=analysis,
                character_list=character_list or []
            )
            logger.info(f"   ✅ 结构化完成: 片头{'✓' if chapter_structure.opening else '✗'} + {len(script_segments)}片段 + 片尾{'✓' if chapter_structure.closing else '✗'}")
            logger.info(f"   🕒 预估时长: {chapter_structure.estimate_duration() / 60:.1f} 分钟")
            return chapter_structure
        
        return script_segments
    
    async def _analyze_chapter(
        self,
        content: str,
        title: str,
        genre: str
    ) -> Dict[str, Any]:
        """
        前期分析：理解原著核心
        
        Returns:
            {
                "theme": "主题",
                "emotional_tone": "情感基调",
                "highlight_scenes": ["高光场景1", "高光场景2"],
                "adaptation_challenges": ["挑战1", "挑战2"]
            }
        """
        
        model_name = (getattr(self, "tts_model", None) or "qwen3-tts-flash").strip()
        if "plus" in model_name:
            tts_block = """**当前TTS模型：CosyVoice v3-plus（精品模式）**\n- 适合：精品章节 / 情绪层次丰富场景\n- 特性：精细情感控制、停顿/重音/语调变化能力极强，音质最佳\n- 成本：相对更高，适合高光章节与关键桥段\n"""
            instruct_block = (
                "**Instruct 情绪提示（CosyVoice 专用）**\n"
                "- cosyvoice-v3-plus 内置音色仅 2 种：longanyang（男）/ longanhuan（女），均支持 Instruct/SSML\n"
                "- 请在 performance_notes 中写清角色身份、场景张力、目标语气（如【愤怒/紧张/平静】），便于后续注入 instruction\n"
            )
        else:
            tts_block = """**当前TTS模型：Qwen3-TTS Flash（高性价比模式）**\n- 适合：长篇连载 / 日更章节\n- 特性：音色丰富、稳定性强、成本低，适合大体量文本\n- 限制：当前调用通道不支持 Instruct/SSML，且不暴露可控的情绪/语速/音调参数（仅使用 voice + language_type）\n"""
            instruct_block = (
                "**Qwen3 备注提示**\n"
                "- 仍可在 performance_notes / emotion 写【紧张/平静/激动】等中文情绪（用于编剧节奏与后续扩展），但请不要假设会直接影响 TTS\n"
            )

        # 智能采样：章节开头 + 中段 + 结尾，兼顾全局又控制长度
        def _build_analysis_sample(text: str, max_len: int = 6000) -> str:
            if not text:
                return ""
            if len(text) <= max_len:
                return text
            part = max_len // 3
            # 开头
            head = text[:part]
            # 中段尽量居中，但避免与开头区域重叠
            mid_start = max(len(text) // 2 - part // 2, part)
            mid = text[mid_start:mid_start + part]
            # 结尾
            tail = text[-part:]
            return head + "\n...\n" + mid + "\n...\n" + tail

        sample_content = _build_analysis_sample(content, max_len=6000)

        prompt = f"""你是专业的有声书剧本改编师，负责将网络小说改编成适合音频化播放的有声剧本。

{tts_block}

{instruct_block}

**章节标题**: {title}
**小说类型**: {genre}

**章节内容节选**（智能采样：开头+中段+结尾，最多6000字）：
{sample_content}

**分析目标**：基于当前TTS模型能力，挖掘文本中的情感细节和节奏变化，为后续“6步听觉化重构”和参数控制提供依据。

请以**纯净的JSON格式**输出分析结果（不要包含注释）：
```json
{{
    "theme": "章节主题（一句话概括）",
    "emotional_tone": "整体情感基调（calm/tense/exciting/sad/mysterious）",
    "emotion_transitions": ["关键情感转折点"],
    "rhythm_pattern": "节奏模式（快速/中等/慢速/变化丰富）",
    "highlight_scenes": ["适合音频化的高光场景"],
    "adaptation_challenges": ["需要特殊处理的难点"],
    "recommended_emotions": ["建议使用的主要情感标签"],
    "voice_control_strategy": {{
        "pace_changes": "语速变化策略",
        "pitch_variations": "音调变化建议",
        "pause_points": "关键停顿位置"
    }}
}}
```"""
        
        try:
            from app.services.model_optimizer import TaskType
            
            # 使用AUDIOBOOK_SCRIPT任务类型（自动选择deepseek-reasoner）
            # 分析阶段输出相对短，但也给足余量
            max_tokens_value = 8000
            logger.info(f"🔧 [章节分析] 请求 max_tokens: {max_tokens_value}")
            
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type=TaskType.AUDIOBOOK_SCRIPT,
                max_tokens=max_tokens_value,
                use_cache=False,
                response_format={"type": "json_object"},  # 启用 deepseek JSON 模式
            )
            
            logger.info(f"📊 [章节分析] 实际返回: {len(response)} 字符")
            
            # 提取JSON
            json_match = response.find("```json")
            if json_match != -1:
                json_end = response.find("```", json_match + 7)
                json_str = response[json_match + 7:json_end].strip()
            else:
                json_str = response.strip()
            
            # 清理JSON字符串
            import re
            json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
            json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
            
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"分析失败: {e}")
            raise RuntimeError(f"LLM章节分析失败: {e}")
    
    async def _transform_to_script(
        self,
        content: str,
        character_list: List[str],
        analysis: Dict[str, Any]
    ) -> List[ScriptSegment]:
        """
        剧本转化：听觉化改写
        
        核心改编策略：
        1. 心理活动 → 独白/音效暗示
        2. 环境描写 → 音效标注
        3. 复杂描述 → 简化为听觉友好的语言
        4. 对话优化 → 删除拗口词汇
        """
        
        # 分段处理（每次处理500-1000字）
        paragraphs = content.split('\n')
        # 过滤空段落
        paragraphs = [p for p in paragraphs if p.strip() and len(p) >= 10]
        
        # 合并短段落，减少LLM调用次数
        merged_paragraphs = []
        current_batch = []
        current_length = 0
        
        for para in paragraphs:
            if current_length + len(para) > 6000:  # 智能分批：每批次最多6000字，保持较大上下文窗口
                if current_batch:
                    merged_paragraphs.append('\n'.join(current_batch))
                current_batch = [para]
                current_length = len(para)
            else:
                current_batch.append(para)
                current_length += len(para)
        
        if current_batch:
            merged_paragraphs.append('\n'.join(current_batch))
        
        total_paras = len(merged_paragraphs)
        logger.info(f"📝 合并后 {total_paras} 个批次（原 {len(paragraphs)} 段），总长度: {len(content)} 字")
        
        all_segments = []
        
        for idx, para in enumerate(merged_paragraphs, 1):
            logger.info(f"   ⏳ [{idx}/{total_paras}] 处理段落 ({len(para)}字)...")
            
            try:
                segments = await self._transform_paragraph(
                    para,
                    character_list,
                    analysis
                )
                all_segments.extend(segments)
                logger.info(f"   ✅ [{idx}/{total_paras}] 完成，生成 {len(segments)} 个片段")
            except Exception as e:
                logger.error(f"   ❌ [{idx}/{total_paras}] 失败: {e}")
                # 继续处理下一段，不中断整个流程
                continue
        
        logger.info(f"✅ 全部段落处理完成，总计 {len(all_segments)} 个剧本片段")
        
        # 🆕 根据用户偏好：不在这里强制合并短片段，而是尽量在编剧阶段控制片段长度
        logger.info(f"📝 保持原始剧本片段数量：{len(all_segments)}（不做短片段自动合并）")
        
        # 可选：如启用语义验证，仅用于日志提示，不再强制修改结构
        if self.strategy and getattr(self.strategy, 'semantic_validation', False):
            all_segments = self._validate_semantic_integrity(all_segments)
        
        return all_segments
    
    async def _transform_paragraph(
        self,
        paragraph: str,
        character_list: List[str],
        analysis: Dict[str, Any]
    ) -> List[ScriptSegment]:
        """转化单个段落"""
        
        model_name = (getattr(self, "tts_model", None) or "qwen3-tts-flash").strip()
        if "plus" in model_name:
            tts_block = """**当前TTS模型：CosyVoice v3-plus（精品模式）**\n- 适合：精品章节 / 情绪层次丰富场景\n- 特性：精细情感控制、停顿/重音/语调变化能力极强，音质最佳\n"""
            instruct_block = """**Instruct 提示（cosyvoice-v3-plus）**\n- 内置音色仅 2 种：longanyang（男）/ longanhuan（女），均支持 Instruct/SSML\n- 请在 performance_notes 中写清语气/情绪（如【愤怒/紧张/平静】），便于后续注入 instruction\n"""
        else:
            tts_block = """**当前TTS模型：Qwen3-TTS Flash（高性价比模式）**\n- 适合：长篇连载 / 日更章节\n- 特性：音色丰富、稳定性强、成本低，适合大体量文本\n- 限制：当前调用通道不支持 Instruct/SSML，且不暴露可控的情绪/语速/音调参数（仅使用 voice + language_type）\n"""
            instruct_block = """**Qwen3 提示**\n- 可以输出 emotion/performance_notes 作为编剧标注与后续扩展，但不要把它当作可控的 TTS 参数\n"""

        six_step_block = """**有声剧本 6 步听觉化重构流程（请严格遵守）**\n1. 心理活动 → 改写为可听见的独白或用音效/环境暗示呈现，避免长篇抽象描写。\n2. 环境描写 → 提炼为可感知的音效标签（如“雨声渐密”“地铁驶过”），填入 sound_effects。\n3. 动作与场景切换 → 用短句 + 停顿 + 过渡性音效，避免连续大段说明。\n4. 对话优化 → 口语化，拆分过长句子，去掉拗口表达，保证朗读顺畅。\n5. 节奏控制 → 根据情节紧张度调整句长，并通过 pause_before/pause_after 控制呼吸感。\n6. 音乐与情绪 → 为情绪明显的片段给出 music_cue（如“低频紧张弦乐”），避免整章铺满BGM。\n"""

        prompt = f"""你是专业的有声书剧本改编师，负责将网络小说改编成适合音频化播放的有声剧本。

{tts_block}

{instruct_block}

{six_step_block}

**🎯 片段划分与语义完整性（建议）**
        
下面的规则是"优先参考"而不是硬性约束，你可以在保证听感流畅和语义清晰的前提下灵活使用短片段：
        
1【推荐做法：语义完整优先】
   - 尽量让每个片段在语义上自洽：包含完整的动作/情绪/场景信息，而不是被机械拆成几字一段。
        
2【短片段的合理场景】
   - ✅ 简短而自然的对白/感叹（如“好。”“这不可能！”，“你说什么？”）可以作为独立片段存在；
   - ✅ 强烈情绪的短句（惊讶/愤怒/紧张等）适合单独成段，用来制造节奏和冲击力；
   - ❗ 建议避免：完全脱离上下文、让人不知所云的碎片（如单独出现的“就一晚。”而看不到前后铺垫）。
        
3【对话与旁白关系】
   - 对话前后的旁白，可以适当合在一起，形成“动作/心理 + 台词”的完整单位；
   - 对于本来就自然很短的应答（“行。”“好。”），可以放心保留为独立片段，不必强行合并。
        
总之：**请优先保证片段本身听起来自然、有完整语气和意义，不必一味追求统一长度，也不需要强行合并所有短句。**
        
**已知角色**: {', '.join(character_list) if character_list else '无'}
**情感基调**: {analysis.get('emotional_tone', 'neutral')}
**建议情感**: {', '.join(analysis.get('recommended_emotions', ['natural']))}
**节奏模式**: {analysis.get('rhythm_pattern', '中等')}

**原文段落**:
{paragraph}

**输出格式**：
请以**纯净的JSON数组格式**输出剧本片段（不要包含任何注释或说明文字）：

**格式选择**：
1. **精品模式**（推荐）：详细配置音效/配乐参数（音量、层级、3D位置、淡入淡出）
2. **简洁模式**：只标注音效/配乐名称（系统会自动使用默认参数）

```json
[
    {{
        "type": "narration|dialogue|monologue",
        "text": "改编后的文本（简洁、听觉友好）",
        "speaker": "角色名或旁白",
        "emotion": "neutral|happy|sad|angry|calm|tense|excited|tender|solemn",
        "voice_params": {{
            "rate": 1.0,
            "pitch": 1.0,
            "pause_before": 0.2,
            "pause_after": 0.3
        }},
        "performance_notes": "语气提示，如：以故事机的身份温柔讲述 / 激动地高声说 / 低声急促地提醒",
        
        // 🆕 音效配置（二选一）
        // 方式1：精品模式（推荐）
        "sound_effects": [
            {{
                "name": "脚步声",
                "layer": "action",  // bottom(底音) | action(动作) | atmosphere(氛围)
                "volume": 0.3,  // 0.0-1.0，人声为1.0基准
                "timing": "trigger",  // continuous(持续) | trigger(触发式)
                "position_3d": "left_to_right",  // left | right | center | back | left_to_right | right_to_left
                "duration": 2.0,  // 持续时长（秒）
                "fade_out": 0.5  // 淡出时长（秒）
            }}
        ],
        // 方式2：简洁模式（兼容）
        "sound_effects_simple": ["脚步声", "雨声"],
        
        // 🆕 配乐配置（二选一）
        // 方式1：精品模式（推荐）
        "music_cue": {{
            "style": "悬疑低频弦乐",
            "volume": 0.2,  // 0.0-1.0，建议0.15-0.4范围
            "fade_in": 2.0,  // 淡入时长（秒）
            "fade_out": 2.0,  // 淡出时长（秒）
            "emotion_follow": true  // 是否跟随情绪波动调整音量
        }},
        // 方式2：简洁模式（兼容）
        "music_cue_simple": "悬疑低频弦乐",
        
        "original_text": "对应的原文",
        "adaptation_reason": "改编原因说明（如：使用较短句子 + 长停顿营造压迫感）"
    }}
]
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
- 只输出JSON数组，不要添加任何//注释或/*注释*/
- 不要在JSON中添加解释性文字
- emotion字段必须使用推荐情感之一，不要自行发明
- voice_params必须包含rate和pitch参数，根据情感调整
- pause_before/after单位为秒，范围：0.1-2.0
- 优先使用happy/sad/tense等有强烈情感的标签，避免过多使用neutral
- performance_notes要具体可执行，帮助TTS调节韵律和语气（可点明是"故事机"语气或"童声"语气等）
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
            from app.services.model_optimizer import TaskType
            
            # 使用AUDIOBOOK_SCRIPT任务类型（自动选择deepseek-reasoner）
            # 剧本转化可能输出很长的JSON数组，需要设置足够大的max_tokens
            max_tokens_value = 32000
            logger.info(f"🔧 [段落转化] 请求 max_tokens: {max_tokens_value}, 段落长度: {len(paragraph)} 字")
            
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type=TaskType.AUDIOBOOK_SCRIPT,
                max_tokens=max_tokens_value,
                use_cache=False,
                response_format={"type": "json_object"},  # 启用 deepseek JSON 模式
            )
            
            logger.info(f"📊 [段落转化] 实际返回: {len(response)} 字符 (JSON截断检测: {'TRUNCATED' if len(response) > 40000 else 'OK'})")
            
            # 提取JSON
            json_match = response.find("```json")
            if json_match != -1:
                json_end = response.find("```", json_match + 7)
                json_str = response[json_match + 7:json_end].strip()
            else:
                json_str = response.strip()
            
            # 清理JSON字符串（移除注释和多余逗号）
            import re
            # 移除单行注释 // ...
            json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
            # 移除多行注释 /* ... */
            json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
            # 移除数组/对象末尾的多余逗号
            json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
            
            # 记录清理后的JSON（用于调试）
            if len(json_str) > 500:
                logger.debug(f"清理后的JSON（前500字符）: {json_str[:500]}")
            else:
                logger.debug(f"清理后的JSON: {json_str}")
            
            try:
                segments_data = json.loads(json_str)
            except json.JSONDecodeError as json_err:
                logger.error(f"JSON解析失败，原始响应: {response[:1000]}")
                logger.error(f"清理后JSON: {json_str[:1000]}")
                # 尝试自动截断到最后一个完整对象来修复 JSON（避免因为尾部被截断导致整个数组不可用）
                try:
                    first_bracket = json_str.find("[")
                    last_brace = json_str.rfind("}")
                    if first_bracket != -1 and last_brace != -1 and last_brace > first_bracket:
                        salvage_str = json_str[first_bracket:last_brace + 1]
                        salvage_str = salvage_str.rstrip()
                        if salvage_str.endswith(","):
                            salvage_str = salvage_str[:-1]
                        salvage_str = salvage_str + "]"
                        logger.warning("⚠️ 尝试通过截断到最后一个完整对象来修复JSON...")
                        segments_data = json.loads(salvage_str)
                        logger.info(f"✅ JSON修复成功，保留片段数: {len(segments_data)}")
                    else:
                        raise json_err
                except Exception:
                    # 修复失败，再抛出原始错误
                    raise RuntimeError(f"LLM返回的JSON格式错误: {json_err}")
            
            # 修复：将中文字段名转换为英文（deepseek-reasoner可能返回中文字段）
            field_mapping = {
                '类型': 'type',
                '文本': 'text',
                '说话人': 'speaker',
                '情绪': 'emotion',
                '动作': 'action',
                '音效': 'sound_effects',
                '音乐': 'music_cue',
                '改编理由': 'adaptation_reason',
                'adaptation_理由': 'adaptation_reason',  # 混合情况
            }
            
            # 清理字段名
            cleaned_segments = []
            for seg in segments_data:
                cleaned_seg = {}
                for key, value in seg.items():
                    # 如果是中文字段名，转换为英文
                    english_key = field_mapping.get(key, key)
                    cleaned_seg[english_key] = value
                cleaned_segments.append(cleaned_seg)
            
            # 记录字段映射情况（调试）
            if any(key in field_mapping for seg in segments_data for key in seg.keys()):
                logger.warning("⚠️ LLM返回了中文字段名，已自动转换为英文")
            
            # 转换为ScriptSegment对象
            return [ScriptSegment(**seg) for seg in cleaned_segments]
            
        except Exception as e:
            logger.error(f"段落转化失败: {e}")
            raise RuntimeError(f"LLM剧本转化失败: {e}")
    
    def get_statistics(self, segments: List[ScriptSegment]) -> Dict[str, Any]:
        """获取剧本统计"""
        return {
            "total_segments": len(segments),
            "dialogue_count": sum(1 for s in segments if s.type == "dialogue"),
            "narration_count": sum(1 for s in segments if s.type == "narration"),
            "monologue_count": sum(1 for s in segments if s.type == "monologue"),
            "unique_speakers": len(set(s.speaker for s in segments)),
            "emotion_distribution": self._count_emotions(segments),
            "sound_effects_count": sum(len(s.sound_effects) for s in segments),
            "music_cues_count": sum(1 for s in segments if s.music_cue)
        }
    
    def _count_emotions(self, segments: List[ScriptSegment]) -> Dict[str, int]:
        """统计情感分布"""
        emotions = {}
        for seg in segments:
            emotions[seg.emotion] = emotions.get(seg.emotion, 0) + 1
        return emotions
    
    def _merge_short_segments(self, segments: List[ScriptSegment], min_length: int = 10) -> List[ScriptSegment]:
        """
        合并过短片段，确保语义完整性
        
        策略：
        1. 短对话（<10字）合并到前后的旁白或同角色对话
        2. 短旁白（<15字）合并到相邻旁白
        3. 保持情感一致性
        4. 对部分“自然短句”（如“好。”“行。”）允许保留，不强制合并
        
        Args:
            segments: 原始片段列表
            min_length: 最小片段长度（字数）
        
        Returns:
            合并后的片段列表
        """
        if not segments:
            return segments
        
        merged = []
        i = 0
        
        while i < len(segments):
            current = segments[i]
            current_len = len(current.text)

            # 对部分自然短句（如“好。”“行。”）允许保留，不强制合并
            if current_len < min_length and self._is_natural_short_utterance(current, min_length):
                merged.append(current)
                i += 1
                continue
            
            # 如果当前片段太短，尝试合并
            if current_len < min_length and i + 1 < len(segments):
                next_seg = segments[i + 1]
                
                # 🆕 策略 0：说话人切换时不合并（保持对话节奏）
                # 例如：张三：“行。” 李四：“好。” → 不合并，保持对话的独立性
                if current.type == "dialogue" and next_seg.type == "dialogue":
                    if current.speaker != next_seg.speaker:
                        # 不同说话人，不合并，直接保留短对话
                        merged.append(current)
                        i += 1
                        continue
                
                # 策略 1：短对话 + 后续旁白/同角色 → 合并
                if current.type == "dialogue":
                    # 如果下一个是旁白或同一角色，合并
                    if next_seg.type == "narration" or next_seg.speaker == current.speaker:
                        # 优化：对话 + 旁白时，保持对话的独立性，不使用逗号连接
                        if next_seg.type == "narration":
                            merged_text = f'"{current.text}"，{next_seg.text}'
                        else:
                            merged_text = f"{current.text}{next_seg.text}"
                        
                        merged_segment = ScriptSegment(
                            type=next_seg.type,  # 使用后续片段的类型
                            text=merged_text,
                            speaker=next_seg.speaker,
                            emotion=next_seg.emotion,
                            performance_notes=f"{current.performance_notes}; {next_seg.performance_notes}".strip("; "),
                            pause_before=current.pause_before,
                            pause_after=next_seg.pause_after,
                            sound_effects=(current.sound_effects or []) + (next_seg.sound_effects or []),
                            music_cue=next_seg.music_cue or current.music_cue,
                            original_text=f"{current.original_text} {next_seg.original_text}",
                            adaptation_reason=f"合并短对话({current_len}字)与后续片段，保持语义完整"
                        )
                        merged.append(merged_segment)
                        i += 2  # 跳过下一个
                        continue
                
                # 策略 2：短旁白 + 后续旁白 → 合并
                elif current.type == "narration" and next_seg.type == "narration":
                    merged_text = f"{current.text}{next_seg.text}"
                    merged_segment = ScriptSegment(
                        type="narration",
                        text=merged_text,
                        speaker="旁白",
                        emotion=next_seg.emotion,  # 使用后续的情感
                        performance_notes=f"{current.performance_notes} + {next_seg.performance_notes}".strip(),
                        pause_before=current.pause_before,
                        pause_after=next_seg.pause_after,
                        sound_effects=(current.sound_effects or []) + (next_seg.sound_effects or []),
                        music_cue=next_seg.music_cue or current.music_cue,
                        original_text=f"{current.original_text} {next_seg.original_text}",
                        adaptation_reason=f"合并短旁白: {current.adaptation_reason}"
                    )
                    merged.append(merged_segment)
                    i += 2
                    continue
            
            # 如果无法合并，直接添加
            merged.append(current)
            i += 1
        
        logger.info(f"🔧 片段合并统计: {len(segments)} → {len(merged)} (减少 {len(segments) - len(merged)} 个短片段)")
        return merged
    
    def _validate_semantic_integrity(self, segments: List[ScriptSegment]) -> List[ScriptSegment]:
        """
        语义完整性验证：检查并报告过短片段
        
        Args:
            segments: 片段列表
        
        Returns:
            验证后的片段列表（如果有问题会警告）
        """
        min_length = 15  # 默认阈值
        if self.strategy and hasattr(self.strategy, 'min_segment_length'):
            min_length = self.strategy.min_segment_length
        
        short_segments = []
        natural_short_segments = []
        for idx, seg in enumerate(segments):
            seg_len = len(seg.text)
            if seg_len < min_length:
                if self._is_natural_short_utterance(seg, min_length):
                    natural_short_segments.append({
                        "index": idx,
                        "text": seg.text,
                        "length": seg_len,
                        "type": seg.type,
                        "speaker": seg.speaker
                    })
                else:
                    short_segments.append({
                        "index": idx,
                        "text": seg.text,
                        "length": seg_len,
                        "type": seg.type,
                        "speaker": seg.speaker
                    })
        
        if natural_short_segments:
            logger.info(f"ℹ️ 检测到 {len(natural_short_segments)} 个自然短句（对白/独白），已从语义错误统计中排除")
        
        if short_segments:
            logger.warning(f"⚠️ 语义完整性验证失败：发现 {len(short_segments)} 个过短片段 (<{min_length}字)：")
            for item in short_segments[:5]:  # 只显示前5个
                logger.warning(f"   [{item['index']}] {item['type']} - {item['speaker']}: \"{item['text']}\" ({item['length']}字)")
            if len(short_segments) > 5:
                logger.warning(f"   ... 还有 {len(short_segments) - 5} 个过短片段未显示")
            logger.warning("💡 建议：调整LLM Prompt或增强合并逻辑")
        else:
            logger.info(f"✅ 语义完整性验证通过：所有片段均 ≥{min_length}字，或属于自然短句")
        
        return segments
    
    def _is_natural_short_utterance(self, seg: ScriptSegment, min_length: int) -> bool:
        """
        判断一个短片段是否属于“自然短句”，例如：
        - 简短而完整的对白/独白（如“好。”“行。”）
        - 带完整终止标点且长度虽短但语义完整
        - 🆕 强烈情绪的短句（惊讶/愤怒/紧张）
        这类片段允许在长度上略低于 min_length，而不视为语义错误。
        """
        text = (seg.text or "").strip()
        if not text:
            return False

        length = len(text)
        if length >= min_length:
            return False

        # 仅对白/独白考虑自然短句，旁白过短仍优先合并
        if seg.type not in ("dialogue", "monologue"):
            return False

        # 含有明显截断标记，一律视为非自然短句
        if "…" in text or "..." in text:
            return False

        # 🔧 常见的简短回答/感叹白名单（扩展版）
        whitelist = {
            # 简短回答
            "嗯", "哦", "好", "好吧", "好啊", "行", "可以", "不行", "不", "是",
            # 情绪表达
            "别闹", "闭嘴", "滚", "快走", "走", "别说了", "住口", "够了",
            # 疑问/惊讶
            "什么", "啊", "嗯？", "哈？", "真的？", "是吗",
            # 🆕 常见短句（带标点）
            "等等。", "等一下。", "停。", "不对。", "有意思。", "明白了。",
            "这不可能。", "你说什么？", "怎么回事？", "为什么？",
        }
        if text in whitelist:
            return True
        
        # 🆕 新增：强烈情绪判断（感叹号结尾、强情绪标签）
        strong_emotions = ["angry", "tense", "excited", "shocked", "fearful"]
        if seg.emotion in strong_emotions and text.endswith(("!", "！", "?", "？")):
            # 强烈情绪 + 感叹/疑问标点，允许较短的片段（8字以上）
            if length >= 8:
                return True

        # 以终止性标点结尾且长度>=3（从2提高到3，避免单字句），一般可以视为完整短句
        if text[-1] in ("。", "！", "?", "？", "!") and length >= 3:
            return True

        return False
    
    def _build_chapter_structure(
        self,
        chapter_title: str,
        chapter_number: int,
        genre: str,
        body_segments: List[ScriptSegment],
        analysis: Dict[str, Any],
        character_list: List[str]
    ) -> ChapterStructure:
        """
        构建完整的章节结构（片头 + 正文 + 片尾）
        
        Args:
            chapter_title: 章节标题
            chapter_number: 章节序号
            genre: 小说类型
            body_segments: 正文片段列表
            analysis: LLM分析结果
            character_list: 角色列表
        
        Returns:
            ChapterStructure对象
        """
        logger.info("🎬 开始构建章节结构...")
        
        # 1. 生成片头
        opening = self._generate_chapter_opening(
            chapter_title=chapter_title,
            chapter_number=chapter_number,
            genre=genre,
            analysis=analysis,
            character_list=character_list
        )
        
        # 2. 生成片尾（包含智能钩子）
        closing = self._generate_chapter_closing(
            chapter_title=chapter_title,
            chapter_number=chapter_number,
            genre=genre,
            body_segments=body_segments,
            analysis=analysis
        )
        
        # 3. 组装章节结构
        structure = ChapterStructure(
            chapter_title=chapter_title,
            chapter_number=chapter_number,
            opening=opening,
            body_segments=body_segments,
            closing=closing,
            genre=genre
        )
        
        # 4. 计算预估时长
        structure.estimate_duration()
        
        return structure
    
    def _generate_chapter_opening(
        self,
        chapter_title: str,
        chapter_number: int,
        genre: str,
        analysis: Dict[str, Any],
        character_list: List[str]
    ) -> ChapterOpening:
        """
        生成章节片头
        
        片头结构：
        - LOGO音效（2秒）
        - 人设简介/主题引入（20-30字）
        - 配乐渐强（8秒）
        
        Returns:
            ChapterOpening对象
        """
        # 根据类型选择LOGO音效
        logo_sound_map = {
            "科幻": "sci-fi-logo.mp3",
            "奇幻": "fantasy-chime.mp3",
            "悬疑": "mystery-bell.mp3",
            "言情": "romance-piano.mp3",
            "古言": "ancient-jade.mp3",
            "武侠": "sword-strike.mp3"
        }
        logo_sound = logo_sound_map.get(genre, "default-logo.mp3")
        
        # 生成简介文本
        theme = analysis.get('theme', '')
        emotional_tone = analysis.get('emotional_tone', 'calm')
        
        # 根据类型和主题生成简介（移除chapter_title，避免说出"chapter"）
        if character_list:
            main_chars = ', '.join(character_list[:3])  # 只取前3个主要角色
            intro_text = f"{main_chars}的故事继续展开。{theme}，第{chapter_number}集，现在开播！"
        else:
            intro_text = f"{theme}，第{chapter_number}集，现在开播！"
        
        # 选择片头配乐风格
        music_style_map = {
            "科幻": "科幻电子音乐",
            "奇幻": "史诗弦乐",
            "悬疑": "悬疑低频弦乐",
            "言情": "轻快钢琴曲",
            "古言": "古风琴笝",
            "武侠": "激昂鼓点+笝声"
        }
        music_style = music_style_map.get(genre, "轻快背景音乐")
        
        intro_music = MusicCue(
            style=music_style,
            volume=0.2,
            fade_in=2.0,
            fade_out=0.0,  # 片头不淡出，直接进入正文
            duration=28.0  # 持续到片头结束
        )
        
        return ChapterOpening(
            logo_sound=logo_sound,
            intro_text=intro_text,
            intro_narrator="旁白",
            intro_music=intro_music,
            duration=30.0
        )
    
    def _generate_chapter_closing(
        self,
        chapter_title: str,
        chapter_number: int,
        genre: str,
        body_segments: List[ScriptSegment],
        analysis: Dict[str, Any]
    ) -> ChapterClosing:
        """
        生成章节片尾（包含智能钩子生成）
        
        片尾结构：
        - 配乐过渡（10秒）
        - 本章回顾（30-50字）
        - 下章预告/钩子（30-60字）
        - 互动引导（20秒）
        
        Returns:
            ChapterClosing对象
        """
        # 1. 生成本章回顾（基于主题）
        theme = analysis.get('theme', '')
        recap_text = f"本章：{theme}"
        
        # 2. 🆕 生成智能钩子（基于最后几个片段的情绪高涨）
        hook_text = self._generate_smart_hook(
            body_segments=body_segments,
            genre=genre,
            chapter_number=chapter_number
        )
        
        # 3. 生成互动引导
        call_to_action_templates = [
            "喜欢本章记得点赞、订阅，评论区留言你的看法！",
            "点赞订阅，评论区说出你的猜测，下章不见不散！",
            "热烈讨论中，评论区等你来留言，别忘了点赞订阅哦！"
        ]
        call_to_action = call_to_action_templates[chapter_number % len(call_to_action_templates)]
        
        # 4. 片尾配乐（与片头风格一致）
        music_style_map = {
            "科幻": "科幻电子音乐",
            "奇幻": "史诗弦乐",
            "悬疑": "悬疑低频弦乐",
            "言情": "轻快钢琴曲",
            "古言": "古风琴笝",
            "武侠": "激昂鼓点+笝声"
        }
        music_style = music_style_map.get(genre, "轻快背景音乐")
        
        outro_music = MusicCue(
            style=music_style,
            volume=0.2,
            fade_in=0.0,  # 从正文继续，不需淡入
            fade_out=3.0,  # 片尾缓慢淡出
            duration=60.0
        )
        
        return ChapterClosing(
            recap_text=recap_text,
            hook_text=hook_text,
            call_to_action=call_to_action,
            outro_narrator="旁白",
            outro_music=outro_music,
            duration=60.0
        )
    
    def _generate_smart_hook(
        self,
        body_segments: List[ScriptSegment],
        genre: str,
        chapter_number: int
    ) -> str:
        """
        🆕 智能钩子生成（基于最后几个片段的情绪高涨）
        
        策略：
        1. 分析最后3-5个片段的情绪
        2. 检测情绪高涨点（angry/tense/excited）
        3. 提取关键内容生成悬念
        4. 根据类型匹配钩子模板
        
        Args:
            body_segments: 正文片段列表
            genre: 小说类型
            chapter_number: 章节序号
        
        Returns:
            钩子文本（30-60字）
        """
        if not body_segments:
            return f"下一章，更多精彩即将展开！"
        
        # 1. 分析最后3-5个片段
        last_segments = body_segments[-5:] if len(body_segments) >= 5 else body_segments
        
        # 2. 检测情绪高涨点
        high_emotion_segments = [
            seg for seg in last_segments
            if seg.emotion in ["angry", "tense", "excited", "sad"]
        ]
        
        # 3. 生成钩子
        if high_emotion_segments:
            # 有情绪高涨 -> 基于情绪生成悬念钩子
            last_high = high_emotion_segments[-1]
            emotion = last_high.emotion
            speaker = last_high.speaker
            
            # 根据情绪类型生成钩子
            if emotion == "angry":
                hook_templates = [
                    f"{speaker}的怒火已经被点燃，下一章，他将做出什么惊人之举？",
                    f"愤怒的{speaker}，会做出什么决定？下章揭晓！"
                ]
            elif emotion == "tense":
                hook_templates = [
                    f"危机将至，{speaker}能否逃过一劫？下章揭晓！",
                    f"紧张的局面下，{speaker}将如何选择？下一章见分晓！"
                ]
            elif emotion == "excited":
                hook_templates = [
                    f"{speaker}的计划即将实施，下一章，惊喜还是惊吓？",
                    f"激动人心的时刻即将到来，{speaker}的命运将如何？"
                ]
            elif emotion == "sad":
                hook_templates = [
                    f"{speaker}的心碎了，但故事还在继续。下一章，希望还在吗？",
                    f"悲伤的{speaker}，能否走出阴影？下章见分晓！"
                ]
            else:
                hook_templates = [f"下一章，{speaker}的故事继续展开！"]
            
            hook = hook_templates[chapter_number % len(hook_templates)]
        else:
            # 没有明显情绪高涨 -> 使用通用钩子
            last_seg = body_segments[-1]
            
            # 根据类型生成通用钩子
            genre_hooks = {
                "科幻": f"下一章，更多未知的科技奇迹即将揭晓！",
                "奇幻": f"下一章，魔法世界的秘密即将揭开！",
                "悬疑": f"下一章，真相即将浮出水面！",
                "言情": f"下一章，他们的感情将如何发展？",
                "古言": f"下一章，命运的齿轮继续转动！",
                "武侠": f"下一章，江湖风云再起！"
            }
            hook = genre_hooks.get(genre, f"下一章，精彩继续！")
        
        logger.info(f"🎯 生成智能钩子: {hook}")
        return hook
