"""
AudioQualityReviewer - 音频质量评审官Agent

核心职责：
1. 评审有声剧本的听觉体验质量
2. 检查对话自然度和信息密度
3. 评估音效/音乐的平衡性
4. 识别节奏和时长问题
"""

import logging
import re
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class QualityIssue:
    """质量问题"""
    location: str  # 位置标识（如chapter1_para5）
    severity: str  # critical/major/minor
    category: str  # script/audio/pacing
    description: str
    suggestion: str


@dataclass
class AudioQualityReport:
    """音频质量报告"""
    # 剧本质量
    script_quality: Dict[str, Any]
    
    # 音频平衡
    audio_balance: Dict[str, Any]
    
    # 节奏评估
    pacing: Dict[str, Any]
    
    # 问题列表
    issues: List[QualityIssue]
    
    # 总评
    overall_grade: str  # A+/A/A-/B+/B/B-/C+/C/C-/D/F
    overall_score: float  # 0-100
    
    # 修订建议
    revision_suggestions: List[str]


class AudioQualityReviewer:
    """
    音频质量评审官Agent
    
    评审有声剧本的各个维度质量
    """
    
    def __init__(self, llm_client=None):
        """
        Args:
            llm_client: LLM客户端（可选，用于智能评审）
        """
        self.llm_client = llm_client
        self.quality_standards = self._init_quality_standards()
    
    def _init_quality_standards(self) -> Dict[str, Any]:
        """初始化质量标准（更贴近有声小说实战节奏）"""
        return {
            # 句子与段落：朗读友好（对话 15-35 字为宜，极少超过 40 字）
            "max_sentence_length": 40,   # 单句建议不超过 40 字
            "max_paragraph_length": 120,  # 单段建议不超过 120 字（LLM 已经做了分段）

            # 时长：按 10 字/秒估算，建议单集在 10-35 分钟之间
            "max_episode_duration": 35 * 60,  # 最大单集时长（秒）
            "min_episode_duration": 10 * 60,  # 最小单集时长

            # 音效密度：推荐每分钟 2-6 个音效，高于 8 视为明显过多
            "min_sound_effects_per_minute": 2,
            "max_sound_effects_per_minute": 6,
            "hard_max_sound_effects_per_minute": 8,

            # 音乐覆盖率：推荐 15%-40%，超过 60% 视为几乎全程铺乐
            "music_coverage_target_min": 0.15,
            "music_coverage_target_max": 0.40,
            "max_music_coverage": 0.60,
        }
    
    def review_script(
        self,
        script_segments: List[Dict[str, Any]],
        novel_genre: str = ""
    ) -> AudioQualityReport:
        """
        评审有声剧本
        
        Args:
            script_segments: 剧本片段列表
                [
                    {
                        "type": "dialogue|narration|monologue",
                        "text": "文本内容",
                        "speaker": "角色名",
                        "emotion": "情绪",
                        "performance_notes": "表演提示",
                        "sound_effects": ["音效1"],
                        "music_cue": "音乐提示"
                    }
                ]
            novel_genre: 小说类型（如“都市”“玄幻”“悬疑”等），用于选择细分质量配置
        
        Returns:
            质量报告
        """
        logger.info(f"🔍 评审有声剧本: {len(script_segments)} 个片段...")

        # 根据小说类型应用细分质量标准
        genre = (novel_genre or "").strip().lower()
        standards = dict(self.quality_standards)
        if genre:
            standards = self._apply_genre_overrides(standards, genre)
        self.quality_standards = standards
        logger.info(f"   使用质量标准: {self.quality_standards}")
        
        issues = []
        
        # 1. 剧本质量评审
        script_quality = self._review_script_quality(script_segments, issues)
        
        # 2. 音频平衡评审
        audio_balance = self._review_audio_balance(script_segments, issues)
        
        # 3. 节奏评审
        pacing = self._review_pacing(script_segments, issues)
        
        # 4. 计算总评
        overall_score, overall_grade = self._calculate_overall_score(
            script_quality,
            audio_balance,
            pacing
        )
        
        # 5. 生成修订建议
        revision_suggestions = self._generate_suggestions(issues)
        
        report = AudioQualityReport(
            script_quality=script_quality,
            audio_balance=audio_balance,
            pacing=pacing,
            issues=issues,
            overall_grade=overall_grade,
            overall_score=overall_score,
            revision_suggestions=revision_suggestions
        )
        
        logger.info(f"   ✅ 评审完成: {overall_grade} ({overall_score:.1f}分)")
        logger.info(f"   发现 {len(issues)} 个问题")
        
        return report
    
    def _review_script_quality(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue]
    ) -> Dict[str, Any]:
        """评审剧本质量"""
        naturalness_score = 10.0
        clarity_score = 10.0
        engagement_score = 10.0
        
        for i, seg in enumerate(segments):
            text = seg.get("text", "")
            location = f"segment_{i}"
            
            # 检查句子长度
            sentences = re.split(r'[。！？]', text)
            for j, sentence in enumerate(sentences):
                if len(sentence) > self.quality_standards["max_sentence_length"]:
                    issues.append(QualityIssue(
                        location=f"{location}_sentence_{j}",
                        severity="major",
                        category="script",
                        description=f"句子过长（{len(sentence)}字）",
                        suggestion="建议拆分为多个短句"
                    ))
                    naturalness_score -= 0.5
            
            # 检查拗口词汇
            awkward_words = self._detect_awkward_words(text)
            if awkward_words:
                issues.append(QualityIssue(
                    location=location,
                    severity="minor",
                    category="script",
                    description=f"发现拗口词汇: {', '.join(awkward_words)}",
                    suggestion="建议替换为口语化表达"
                ))
                naturalness_score -= 0.3
            
            # 检查信息密度
            if len(text) > 100 and text.count("，") < 2:
                clarity_score -= 0.2
        
        return {
            "naturalness_score": max(0, min(10, naturalness_score)),
            "clarity_score": max(0, min(10, clarity_score)),
            "engagement_score": max(0, min(10, engagement_score)),
            "total_segments": len(segments),
            "average_segment_length": sum(len(s.get("text", "")) for s in segments) / len(segments) if segments else 0
        }
    
    def _detect_awkward_words(self, text: str) -> List[str]:
        """检测可能拗口、不适合朗读的词汇

        说明：
        - 这里先用一套简单的启发式规则，后续可以接 LLM 做更智能的评审
        - 目标是发现：书面化过重、成串叠词、生僻词堆叠等情况
        """
        candidates = [
            "之乎者也",
            "不禁感叹",
            "不由得感叹",
            "不禁赞叹",
            "不由得说道",
            "不禁说道",
            "蓦然回首",
            "恍若隔世",
            "不胜唏嘘",
        ]

        awkward = []
        for w in candidates:
            if w in text:
                awkward.append(w)

        # 规则2：连续三个以上相同的字（容易念错 / 听感别扭）
        repeat_pattern = re.compile(r"(.)\1{2,}")
        for m in repeat_pattern.finditer(text):
            awkward.append(m.group(0))

        # 去重
        return list(dict.fromkeys(awkward))
    
    def _apply_genre_overrides(self, standards: Dict[str, Any], genre: str) -> Dict[str, Any]:
        """根据小说类型对质量标准做细分调整。

        说明：
        - 都市/言情/校园：允许略高的背景音乐覆盖率，音效保持中等。
        - 玄幻/仙侠/热血/冒险：允许更高的音效密度和略高的音乐覆盖率。
        - 悬疑/推理/惊悚/恐怖：整体更克制，强调静音和环境音，背景音乐覆盖率下调。
        - 其他类型：使用默认标准。
        """
        g = genre

        # 都市、言情、校园 等相对温和题材
        if ("都市" in g) or ("言情" in g) or ("校园" in g) or ("日常" in g):
            standards["min_sound_effects_per_minute"] = 1
            standards["max_sound_effects_per_minute"] = 5
            standards["hard_max_sound_effects_per_minute"] = 7
            standards["music_coverage_target_min"] = 0.20
            standards["music_coverage_target_max"] = 0.50
            standards["max_music_coverage"] = 0.70

        # 玄幻、仙侠、热血、冒险 等偏戏剧化题材
        elif ("玄幻" in g) or ("仙侠" in g) or ("奇幻" in g) or ("热血" in g) or ("冒险" in g):
            standards["min_sound_effects_per_minute"] = 3
            standards["max_sound_effects_per_minute"] = 8
            standards["hard_max_sound_effects_per_minute"] = 10
            standards["music_coverage_target_min"] = 0.20
            standards["music_coverage_target_max"] = 0.50
            standards["max_music_coverage"] = 0.70

        # 悬疑、推理、惊悚、恐怖 等需要静音张力的题材
        elif ("悬疑" in g) or ("推理" in g) or ("惊悚" in g) or ("恐怖" in g):
            standards["min_sound_effects_per_minute"] = 1
            standards["max_sound_effects_per_minute"] = 4
            standards["hard_max_sound_effects_per_minute"] = 6
            standards["music_coverage_target_min"] = 0.05
            standards["music_coverage_target_max"] = 0.25
            standards["max_music_coverage"] = 0.40

        # 其他类型（包括科幻等）保持默认
        return standards
    
    def _review_audio_balance(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue]
    ) -> Dict[str, Any]:
        """评审音频平衡"""
        total_effects = 0
        total_music_cues = 0
        
        for seg in segments:
            # 防御性检查：确保 sound_effects 是列表类型
            sound_effects = seg.get("sound_effects", [])
            if sound_effects is None:
                sound_effects = []
            total_effects += len(sound_effects)
            
            if seg.get("music_cue"):
                total_music_cues += 1
        
        # 估算时长（粗略）
        total_text_length = sum(len(s.get("text", "")) for s in segments)
        estimated_duration_minutes = total_text_length / 10 / 60  # 假设10字/秒
        
        # 音效密度
        effects_per_minute = total_effects / estimated_duration_minutes if estimated_duration_minutes > 0 else 0

        target_min_effects = self.quality_standards.get("min_sound_effects_per_minute", 2)
        target_max_effects = self.quality_standards.get("max_sound_effects_per_minute", 6)
        hard_max_effects = self.quality_standards.get("hard_max_sound_effects_per_minute", target_max_effects + 2)

        sound_effect_rating = "适中"
        if effects_per_minute > hard_max_effects:
            sound_effect_rating = "严重偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description=f"音效密度严重过高（约 {effects_per_minute:.1f}/分钟）",
                suggestion="仅保留关键情节所需音效，删除背景性或重复音效"
            ))
        elif effects_per_minute > target_max_effects:
            sound_effect_rating = "偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description=f"音效偏多（约 {effects_per_minute:.1f}/分钟）",
                suggestion="合并相近音效触发点，避免每一句都叠加音效"
            ))
        elif 0 < effects_per_minute < target_min_effects:
            sound_effect_rating = "偏少"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description="音效略少，部分环境描写可以转化为音效",
                suggestion="为重要环境或动作场景补充少量高质量音效"
            ))
        elif effects_per_minute == 0 and total_text_length > 800:
            sound_effect_rating = "明显不足"
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description="长篇文本完全没有音效标注",
                suggestion="为关键环境/动作场景设计基础音效，例如雨声、脚步声、环境氛围音"
            ))
        else:
            sound_effect_rating = "适中"

        # 音乐密度
        music_rating = "适中"
        music_coverage = total_music_cues / len(segments) if segments else 0
        target_min_music = self.quality_standards.get("music_coverage_target_min", 0.15)
        target_max_music = self.quality_standards.get("music_coverage_target_max", 0.40)
        max_music_coverage = self.quality_standards.get("max_music_coverage", 0.60)

        if music_coverage > max_music_coverage:
            music_rating = "严重偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description=f"背景音乐覆盖率过高（约 {music_coverage*100:.0f}% 片段有BGM）",
                suggestion="保留开头/结尾/高潮等关键位置的配乐，减少连续长时间背景音乐"
            ))
        elif music_coverage > target_max_music:
            music_rating = "偏多"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description=f"背景音乐略多（约 {music_coverage*100:.0f}% 片段有BGM）",
                suggestion="适当减少非关键段落的配乐，给对话和旁白留出空间"
            ))
        elif 0 < music_coverage < target_min_music:
            music_rating = "偏少"
            issues.append(QualityIssue(
                location="overall",
                severity="minor",
                category="audio",
                description="背景音乐略少",
                suggestion="在情绪起伏较大的片段增加少量配乐，增强氛围"
            ))
        elif music_coverage == 0 and total_text_length > 800:
            music_rating = "明显不足"
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description="长篇章节没有任何背景音乐提示",
                suggestion="为章节开头/结尾或关键转折点增加简短背景音乐"
            ))

        # 角色音色区分度
        speakers = set(s.get("speaker") for s in segments if s.get("type") == "dialogue")
        voice_differentiation = "清晰" if len(speakers) <= 5 else "可能混淆"
        
        if len(speakers) > 5:
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="audio",
                description=f"角色过多（{len(speakers)}个）",
                suggestion="建议确保角色音色差异明显"
            ))
        
        return {
            "sound_effects": sound_effect_rating,
            "music": music_rating,
            "voice_differentiation": voice_differentiation,
            "total_effects": total_effects,
            "total_music_cues": total_music_cues,
            "effects_per_minute": effects_per_minute
        }
    
    def _review_pacing(
        self,
        segments: List[Dict[str, Any]],
        issues: List[QualityIssue]
    ) -> Dict[str, Any]:
        """评审节奏"""
        # 估算时长（粗略，按10字/秒）
        total_text_length = sum(len(s.get("text", "")) for s in segments)
        estimated_duration = total_text_length / 10  # 10字/秒
        estimated_duration_minutes = estimated_duration / 60
        
        pacing_issues = []
        
        # 检查时长
        if estimated_duration > self.quality_standards["max_episode_duration"]:
            pacing_issues.append(f"时长过长（{estimated_duration_minutes:.1f}分钟）")
            issues.append(QualityIssue(
                location="overall",
                severity="major",
                category="pacing",
                description=f"单集时长过长（{estimated_duration_minutes:.1f}分钟）",
                suggestion=f"建议控制在{self.quality_standards['max_episode_duration']/60}分钟以内"
            ))
        elif estimated_duration < self.quality_standards["min_episode_duration"]:
            pacing_issues.append(f"时长过短（{estimated_duration_minutes:.1f}分钟）")
        
        # 检查节奏变化
        segment_lengths = [len(s.get("text", "")) for s in segments]
        avg_length = sum(segment_lengths) / len(segment_lengths) if segment_lengths else 0
        
        # 如果连续多个片段都很长，可能节奏拖沓
        slow_segments = []
        for i, length in enumerate(segment_lengths):
            if length > avg_length * 1.5:
                slow_segments.append(i)
        
        if len(slow_segments) > len(segments) * 0.3:
            pacing_issues.append("部分片段节奏拖沓")
            issues.append(QualityIssue(
                location="segments_" + ",".join(map(str, slow_segments[:3])),
                severity="minor",
                category="pacing",
                description="部分片段过长，节奏拖沓",
                suggestion="建议加快节奏或增加停顿"
            ))
        
        return {
            "estimated_duration": f"{estimated_duration_minutes:.1f}分钟",
            "pacing_issues": pacing_issues,
            "average_segment_duration": f"{avg_length/10:.1f}秒",
            "total_segments": len(segments)
        }
    
    def _calculate_overall_score(
        self,
        script_quality: Dict[str, Any],
        audio_balance: Dict[str, Any],
        pacing: Dict[str, Any]
    ) -> tuple:
        """计算总评分"""
        # 剧本质量权重50%
        script_score = (
            script_quality["naturalness_score"] * 0.4 +
            script_quality["clarity_score"] * 0.3 +
            script_quality["engagement_score"] * 0.3
        ) * 5  # 转换为50分制
        
        # 音频平衡权重30%
        audio_score = 30.0  # 默认满分
        if audio_balance["sound_effects"] == "偏多" or audio_balance["sound_effects"] == "偏少":
            audio_score -= 5
        if audio_balance["music"] == "偏多" or audio_balance["music"] == "偏少":
            audio_score -= 5
        if audio_balance["voice_differentiation"] == "可能混淆":
            audio_score -= 10
        
        # 节奏权重20%
        pacing_score = 20.0  # 默认满分
        if pacing["pacing_issues"]:
            pacing_score -= len(pacing["pacing_issues"]) * 5
        
        total_score = max(0, script_score + audio_score + pacing_score)
        
        # 转换为等级
        if total_score >= 95:
            grade = "A+"
        elif total_score >= 90:
            grade = "A"
        elif total_score >= 85:
            grade = "A-"
        elif total_score >= 80:
            grade = "B+"
        elif total_score >= 75:
            grade = "B"
        elif total_score >= 70:
            grade = "B-"
        elif total_score >= 65:
            grade = "C+"
        elif total_score >= 60:
            grade = "C"
        elif total_score >= 55:
            grade = "C-"
        elif total_score >= 50:
            grade = "D"
        else:
            grade = "F"
        
        return total_score, grade
    
    def _generate_suggestions(
        self,
        issues: List[QualityIssue]
    ) -> List[str]:
        """生成修订建议"""
        suggestions = []
        
        # 按严重程度分组
        critical_issues = [i for i in issues if i.severity == "critical"]
        major_issues = [i for i in issues if i.severity == "major"]
        
        if critical_issues:
            suggestions.append(f"【紧急】修复 {len(critical_issues)} 个严重问题")
        
        if major_issues:
            suggestions.append(f"【重要】优化 {len(major_issues)} 个主要问题")
        
        # 按类别生成建议
        script_issues = [i for i in issues if i.category == "script"]
        if script_issues:
            suggestions.append("优化剧本：简化长句、替换拗口词汇")
        
        audio_issues = [i for i in issues if i.category == "audio"]
        if audio_issues:
            suggestions.append("调整音频平衡：优化音效和音乐密度")
        
        pacing_issues = [i for i in issues if i.category == "pacing"]
        if pacing_issues:
            suggestions.append("调整节奏：控制时长和段落长度")
        
        if not suggestions:
            suggestions.append("质量优秀，无需修订")
        
        return suggestions
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "quality_standards": self.quality_standards
        }
