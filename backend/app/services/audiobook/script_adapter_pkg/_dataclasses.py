"""
有声剧本数据结构定义

包含音效、配乐、章节结构等数据类
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


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

    # cosyvoice-v3.5-plus Instruct 结构化字段（用于指令模板拼装）
    instruct_emotion: str = ""  # neutral/fearful/angry/sad/surprised/happy/disgusted
    instruct_scene: str = ""  # 场景，如“闲聊互动”
    instruct_role: str = ""  # 角色，如“一个旁白”
    instruct_identity: str = ""  # 身份，如“故事机”
    
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
        if self.instruct_emotion is None:
            self.instruct_emotion = ""
        if self.instruct_scene is None:
            self.instruct_scene = ""
        if self.instruct_role is None:
            self.instruct_role = ""
        if self.instruct_identity is None:
            self.instruct_identity = ""
        
        # 如果sound_effects_simple有内容但sound_effects为空，转换为新格式
        if self.sound_effects_simple and not self.sound_effects:
            self.sound_effects = [
                SoundEffect(name=name, layer="action", volume=0.3)
                for name in self.sound_effects_simple
            ]
        
        # 如果music_cue_simple有内容但music_cue为None，转换为新格式
        if self.music_cue_simple and self.music_cue is None:
            self.music_cue = MusicCue(style=self.music_cue_simple, volume=0.2)
