"""
章节分析 Mixin

包含 _analyze_chapter 方法
"""
import logging
from typing import Dict, Any, Optional, List

from app.services.audiobook.llm_client import call_audiobook_llm_async
from app.services.audiobook.llm_json import parse_llm_json_object

logger = logging.getLogger(__name__)


class AnalysisMixin:
    """章节分析方法"""
    
    async def _analyze_chapter(
        self,
        content: str,
        title: str,
        genre: str,
        audio_adaptation_brief: str = "",
        character_profiles: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        前期分析：理解原著核心
        
        Args:
            character_profiles: 完整角色档案（包含性别、年龄、角色定位、关系网络等）
        
        Returns:
            {
                "theme": "主题",
                "emotional_tone": "情感基调",
                "highlight_scenes": ["高光场景1", "高光场景2"],
                "adaptation_challenges": ["挑战1", "挑战2"]
            }
        """
        
        model_name = (getattr(self, "tts_model", None) or "qwen3-tts-instruct-flash").strip()
        if "plus" in model_name:
            tts_block = "**当前TTS模型：CosyVoice v3.5-plus（精品模式）**\n- 适合：精品章节 / 情绪层次丰富场景\n- 特性：精细情感控制、instruction 演绎能力强，但必须使用复刻/设计音色\n- 成本：相对更高，适合高光章节与关键桥段\n"
            instruct_block = (
                "**Instruct 情绪提示（CosyVoice 专用）**\n"
                "- cosyvoice-v3.5-plus 无系统音色，请默认假设上游已经选定复刻/设计 voice_id\n"
                "- 请在 performance_notes 中写清角色身份、场景张力、目标语气（如【愤怒/紧张/平静】），便于后续注入 instruction\n"
            )
        else:
            tts_block = "**当前TTS模型：Qwen3-TTS Instruct Flash（默认模式）**\n- 适合：长篇连载 / 日更章节 / 需要低成本但仍要一定表现力的内容\n- 特性：49 音色、稳定性强、成本低，并支持通过 instructions / optimize_instructions 做自然语言演绎控制\n- 限制：当前链路重点是 instructions，不要输出 SSML 语法\n"
            instruct_block = (
                "**Qwen3 Instruct 提示**\n"
                "- 请把情绪、场景、身份、角色语气尽量结构化写到 instruct_emotion / instruct_scene / instruct_role / instruct_identity 中\n"
                "- performance_notes 会一并映射到 Qwen instructions，请写成可直接执行的演绎要求\n"
            )

        def _build_analysis_sample(text: str, max_len: int = 6000) -> str:
            if not text:
                return ""
            if len(text) <= max_len:
                return text
            part = max_len // 3
            head = text[:part]
            mid_start = max(len(text) // 2 - part // 2, part)
            mid = text[mid_start:mid_start + part]
            tail = text[-part:]
            return head + "\n...\n" + mid + "\n...\n" + tail

        sample_content = _build_analysis_sample(content, max_len=6000)
        adaptation_block = (
            f"\n**跨模态改编提示（来自章节结构化摘要）**：\n{audio_adaptation_brief}\n"
            if audio_adaptation_brief
            else ""
        )
        
        character_block = ""
        if character_profiles:
            character_block = "\n**角色档案**（来自小说创作阶段的角色管理系统）：\n"
            for char in character_profiles:
                char_desc = f"- **{char['name']}**"
                if char.get('gender'):
                    char_desc += f"，{char['gender']}"
                if char.get('age'):
                    char_desc += f"，{char['age']}岁"
                if char.get('role'):
                    char_desc += f"，{char['role']}"
                if char.get('role_position'):
                    char_desc += f"，{char['role_position']}"
                if char.get('importance_level'):
                    char_desc += f"，{char['importance_level']}"
                if char.get('faction'):
                    char_desc += f"，{char['faction']}势力"
                if char.get('relations'):
                    char_desc += f"\n  关系：{char['relations']}"
                if char.get('summary'):
                    char_desc += f"\n  简介：{char['summary']}"
                character_block += char_desc + "\n"

        prompt = f"""你是专业的有声书剧本改编师，负责将网络小说改编成适合音频化播放的有声剧本。

{tts_block}

{instruct_block}

{character_block}

**章节标题**: {title}
**小说类型**: {genre}
{adaptation_block}

**章节内容节选**（智能采样：开头+中段+结尾，最多6000字）：
{sample_content}

**分析目标**：基于当前TTS模型能力，挖掘文本中的情感细节和节奏变化，为后续"6步听觉化重构"和参数控制提供依据。

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
            max_tokens_value = 8000
            logger.info(f"[章节分析] 请求 max_tokens: {max_tokens_value}")
            
            response = await call_audiobook_llm_async(
                self.llm_client,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens_value,
                use_cache=False,
                response_format={"type": "json_object"},
            )
            
            logger.info(f"[章节分析] 实际返回: {len(response)} 字符")
            
            return parse_llm_json_object(response)
        except Exception as e:
            logger.error(f"分析失败: {e}")
            raise RuntimeError(f"LLM章节分析失败: {e}")
