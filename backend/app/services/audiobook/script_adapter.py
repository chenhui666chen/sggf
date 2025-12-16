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
from dataclasses import dataclass, asdict
import json

logger = logging.getLogger(__name__)


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
    
    # 音效音乐标注
    sound_effects: List[str] = None  # 音效列表，如["推门声", "脚步声"]
    music_cue: str = ""  # 音乐提示，如"悬疑感的低频弦乐"
    
    # 原文信息
    original_text: str = ""  # 原始文本（用于对比）
    adaptation_reason: str = ""  # 改编原因说明
    
    def __post_init__(self):
        if self.sound_effects is None:
            self.sound_effects = []


class AudiobookScriptAgent:
    """
    有声剧本编剧Agent
    
    基于专业编剧工作流程，将小说文本改编为适合音频化的剧本
    """
    
    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM客户端（必需，支持OptimizedLLMClient或自定义）
        """
        if llm_client is None:
            raise ValueError("AudiobookScriptAgent必须提供llm_client参数")
        self.llm_client = llm_client
    
    async def adapt_chapter(
        self,
        chapter_content: str,
        character_list: Optional[List[str]] = None,
        chapter_title: str = "",
        genre: str = "科幻"
    ) -> List[ScriptSegment]:
        """
        将章节改编为有声剧本
        
        Args:
            chapter_content: 原始章节文本
            character_list: 角色列表
            chapter_title: 章节标题
            genre: 小说类型
        
        Returns:
            剧本片段列表
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
        
        prompt = f"""你是一位专业的有声小说编剧，擅长为现代TTS语音合成技术改编文本。

**当前使用的TTS模型能力**：
- Qwen3-TTS：49种音色，8种原生情感（happy/sad/angry/nervous/calm/gentle/serious/natural）
- CosyVoice3：零样本音色克隆，多方言支持
- 首包延迟<300ms，自然度MOS 4.53

**章节标题**: {title}
**小说类型**: {genre}

**章节内容**（前800字）:
{content[:800]}

**分析目标**：为后续的语音合成提供关键指导，确保充分利用TTS模型的情感表达能力。

请以**纯净的JSON格式**输出分析结果（不要包含注释）：
```json
{{
    "theme": "章节主题（一句话概括）",
    "emotional_tone": "整体情感基调（calm/tense/exciting/sad/mysterious）",
    "highlight_scenes": ["适合音频化的高光场景描述"],
    "adaptation_challenges": ["需要特殊处理的难点，如心理描写、多时间线等"],
    "recommended_emotions": ["建议使用的主要情感标签（基于TTS支持的情感）"]
}}
```"""
        
        try:
            from app.services.model_optimizer import TaskType
            
            # 使用AUDIOBOOK_SCRIPT任务类型（自动选择deepseek-reasoner）
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type=TaskType.AUDIOBOOK_SCRIPT,
                use_cache=False
            )
            
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
            if current_length + len(para) > 6000:  # 智能分批：每批次最多6000字（原3000字，提升2倍效率）
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
        return all_segments
    
    async def _transform_paragraph(
        self,
        paragraph: str,
        character_list: List[str],
        analysis: Dict[str, Any]
    ) -> List[ScriptSegment]:
        """转化单个段落"""
        
        prompt = f"""你是专业的有声小说编剧，为高品质TTS语音合成改编文本。

**TTS模型能力说明**：
本项目使用Qwen3-TTS（主）+ CosyVoice3（备）双引擎：
- **49种音色**：支持多角色差异化
- **8种原生情感**: happy/sad/angry/nervous/calm/gentle/serious/natural
- **首包延迟<300ms**：实时响应
- **MOS 4.53**：接近真人的自然度
- **方言支持**：可选择普通话/四川话/粤语等

**改编要求** - 核心原则：充分发挥TTS情感表达能力
1. **识别对话、旁白、心理活动**
2. **情感标注**：每个片段必须匹配8种原生情感之一
3. **心理活动外化**：转为独白（monologue）或音效暗示
4. **环境描写音频化**：标注音效（如“雨声渐密”）
5. **表演提示**：标注语气、停顿等（利用TTS的prosody控制）
6. **节奏优化**：保留原文情感波动，确保听觉自然性

**已知角色**: {', '.join(character_list) if character_list else '无'}
**情感基调**: {analysis.get('emotional_tone', 'neutral')}
**建议情感**: {', '.join(analysis.get('recommended_emotions', ['natural']))}

**原文段落**:
{paragraph}

**输出格式**：
请以**纯净的JSON数组格式**输出剧本片段（不要包含任何注释或说明文字）：
```json
[
    {{
        "type": "narration|dialogue|monologue",
        "text": "改编后的文本（简洁、听觉友好）",
        "speaker": "角色名或旁白",
        "emotion": "happy|sad|angry|nervous|calm|gentle|serious|natural",
        "performance_notes": "语气提示，如：颤抖着低语 / 略带咽哽 / 激动地高声说",
        "pause_before": 0.5,
        "pause_after": 0.3,
        "sound_effects": ["音效1", "音效2"],
        "music_cue": "音乐提示",
        "original_text": "对应的原文",
        "adaptation_reason": "改编原因说明（如：利用TTS的nervous情感强化紧张气氛）"
    }}
]
```

**重要提醒**：
- 只输出JSON数组，不要添加任何//注释或/*注释*/
- 不要在JSON中添加解释性文字
- emotion字段必须使用8种原生情感之一，不要自行发明
- 优先使用happy/sad/nervous等有强烈情感的标签，避免过多使用neutral
- performance_notes要具体可执行，帮助TTS调节韵律和语气"""
        
        try:
            from app.services.model_optimizer import TaskType
            
            # 使用AUDIOBOOK_SCRIPT任务类型（自动选择deepseek-reasoner）
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type=TaskType.AUDIOBOOK_SCRIPT,
                use_cache=False
            )
            
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
