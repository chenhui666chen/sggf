"""
章节结构 Mixin

包含 _build_chapter_structure, _generate_chapter_opening, _generate_chapter_closing, _generate_smart_hook 方法
"""
import logging
from typing import List, Dict, Any

from ._dataclasses import (
    ChapterStructure, ChapterOpening, ChapterClosing, 
    MusicCue, ScriptSegment
)

logger = logging.getLogger(__name__)


class StructureMixin:
    """章节结构方法"""
    
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
        logger.info("开始构建章节结构...")
        
        opening = self._generate_chapter_opening(
            chapter_title=chapter_title,
            chapter_number=chapter_number,
            genre=genre,
            analysis=analysis,
            character_list=character_list
        )
        
        closing = self._generate_chapter_closing(
            chapter_title=chapter_title,
            chapter_number=chapter_number,
            genre=genre,
            body_segments=body_segments,
            analysis=analysis
        )
        
        structure = ChapterStructure(
            chapter_title=chapter_title,
            chapter_number=chapter_number,
            opening=opening,
            body_segments=body_segments,
            closing=closing,
            genre=genre
        )
        
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
        logo_sound_map = {
            "科幻": "sci-fi-logo.mp3",
            "奇幻": "fantasy-chime.mp3",
            "悬疑": "mystery-bell.mp3",
            "言情": "romance-piano.mp3",
            "古言": "ancient-jade.mp3",
            "武侠": "sword-strike.mp3"
        }
        logo_sound = logo_sound_map.get(genre, "default-logo.mp3")
        
        theme = analysis.get('theme', '')
        
        if character_list:
            main_chars = ', '.join(character_list[:3])
            intro_text = f"{main_chars}的故事继续展开。{theme}，第{chapter_number}集，现在开播！"
        else:
            intro_text = f"{theme}，第{chapter_number}集，现在开播！"
        
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
            fade_out=0.0,
            duration=28.0
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
        theme = analysis.get('theme', '')
        recap_text = f"本章：{theme}"
        
        hook_text = self._generate_smart_hook(
            body_segments=body_segments,
            genre=genre,
            chapter_number=chapter_number
        )
        
        call_to_action_templates = [
            "喜欢本章记得点赞、订阅，评论区留言你的看法！",
            "点赞订阅，评论区说出你的猜测，下章不见不散！",
            "热烈讨论中，评论区等你来留言，别忘了点赞订阅哦！"
        ]
        call_to_action = call_to_action_templates[chapter_number % len(call_to_action_templates)]
        
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
            fade_in=0.0,
            fade_out=3.0,
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
        智能钩子生成（基于最后几个片段的情绪高涨）
        
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
        
        last_segments = body_segments[-5:] if len(body_segments) >= 5 else body_segments
        
        high_emotion_segments = [
            seg for seg in last_segments
            if seg.emotion in ["angry", "tense", "excited", "sad"]
        ]
        
        if high_emotion_segments:
            last_high = high_emotion_segments[-1]
            emotion = last_high.emotion
            speaker = last_high.speaker
            
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
            last_seg = body_segments[-1]
            
            genre_hooks = {
                "科幻": f"下一章，更多未知的科技奇迹即将揭晓！",
                "奇幻": f"下一章，魔法世界的秘密即将揭开！",
                "悬疑": f"下一章，真相即将浮出水面！",
                "言情": f"下一章，他们的感情将如何发展？",
                "古言": f"下一章，命运的齿轮继续转动！",
                "武侠": f"下一章，江湖风云再起！"
            }
            hook = genre_hooks.get(genre, f"下一章，精彩继续！")
        
        logger.info(f"生成智能钩子: {hook}")
        return hook
