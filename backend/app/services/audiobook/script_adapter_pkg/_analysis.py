"""
章节分析 Mixin

包含 _analyze_chapter 方法
"""
import json
import re
import logging
from typing import Dict, Any, Optional, List

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
        
        model_name = (getattr(self, "tts_model", None) or "qwen3-tts-flash").strip()
        if "plus" in model_name:
            tts_block = "**当前TTS模型：CosyVoice v3-plus（精品模式）**\n- 适合：精品章节 / 情绪层次丰富场景\n- 特性：精细情感控制、停顿/重音/语调变化能力极强，音质最佳\n- 成本：相对更高，适合高光章节与关键桥段\n"
            instruct_block = (
                "**Instruct 情绪提示（CosyVoice 专用）**\n"
                "- cosyvoice-v3-plus 内置音色仅 2 种：longanyang（男）/ longanhuan（女），均支持 Instruct/SSML\n"
                "- 请在 performance_notes 中写清角色身份、场景张力、目标语气（如【愤怒/紧张/平静】），便于后续注入 instruction\n"
            )
        else:
            tts_block = "**当前TTS模型：Qwen3-TTS Flash（高性价比模式）**\n- 适合：长篇连载 / 日更章节\n- 特性：音色丰富、稳定性强、成本低，适合大体量文本\n- 限制：当前调用通道不支持 Instruct/SSML，且不暴露可控的情绪/语速/音调参数（仅使用 voice + language_type）\n"
            instruct_block = (
                "**Qwen3 备注提示**\n"
                "- 仍可在 performance_notes / emotion 写【紧张/平静/激动】等中文情绪（用于编剧节奏与后续扩展），但请不要假设会直接影响 TTS\n"
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
            from core.model_resolution import TaskType
            
            max_tokens_value = 8000
            logger.info(f"[章节分析] 请求 max_tokens: {max_tokens_value}")
            
            response = await self.llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                task_type=TaskType.AUDIOBOOK_SCRIPT,
                max_tokens=max_tokens_value,
                use_cache=False,
                response_format={"type": "json_object"},
            )
            
            logger.info(f"[章节分析] 实际返回: {len(response)} 字符")
            
            json_match = response.find("```json")
            if json_match != -1:
                json_end = response.find("```", json_match + 7)
                json_str = response[json_match + 7:json_end].strip()
            else:
                json_str = response.strip()
            
            json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
            json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
            json_str = re.sub(r',\s*([}\]])', r'', json_str)
            
            return json.loads(json_str)
        except Exception as e:
            logger.error(f"分析失败: {e}")
            raise RuntimeError(f"LLM章节分析失败: {e}")
